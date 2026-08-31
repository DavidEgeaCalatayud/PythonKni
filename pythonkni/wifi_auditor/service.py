from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import threading
import unicodedata
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from pythonkni.core.tasks import WorkerCancelled

from .models import AccessPoint, AuditFinding, AuditReport

NETSH_TIMEOUT_SECONDS = 12.0
REPORT_SCHEMA_VERSION = 1
LIMITATIONS = (
    "El inventario usa la enumeración WiFi disponible en Windows y no activa modo monitor.",
    "El informe evalúa configuración visible; no intenta obtener ni validar credenciales.",
    "No se realiza sondeo WPS activo; WPS solo puede revisarse con información pasiva disponible.",
    "Las inconsistencias de SSID son indicadores para revisión manual, no una atribución de rogue AP.",
)


def _check_cancel(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise WorkerCancelled()


def _run_netsh(args: list[str]) -> str:
    completed = subprocess.run(
        ["netsh", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
        timeout=NETSH_TIMEOUT_SECONDS,
    )
    return completed.stdout


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(c for c in normalized if not unicodedata.combining(c)).strip().lower()


def _number(value: str) -> int | None:
    digits = "".join(c for c in value if c.isdigit())
    return int(digits) if digits else None


def _band(channel: int | None, explicit: str = "") -> str:
    if explicit.strip():
        return explicit.strip()
    if channel is None:
        return "Unknown"
    if channel <= 14:
        return "2.4 GHz"
    if channel <= 177:
        return "5 GHz"
    return "6 GHz / other"


def parse_networks(output: str) -> list[AccessPoint]:
    points: list[AccessPoint] = []
    ssid = "<hidden>"
    auth = "Unknown"
    encryption = "Unknown"
    network_type = ""
    current: dict[str, object] | None = None

    def flush() -> None:
        nonlocal current
        if current is None:
            return
        channel = current.get("channel")
        points.append(
            AccessPoint(
                ssid=str(current.get("ssid") or "<hidden>"),
                bssid=str(current.get("bssid") or "").lower(),
                authentication=str(current.get("authentication") or "Unknown"),
                encryption=str(current.get("encryption") or "Unknown"),
                signal_percent=current.get("signal") if isinstance(current.get("signal"), int) else None,
                channel=channel if isinstance(channel, int) else None,
                radio_type=str(current.get("radio") or ""),
                band=_band(channel if isinstance(channel, int) else None, str(current.get("band") or "")),
                network_type=str(current.get("network_type") or ""),
            )
        )
        current = None

    for raw in output.splitlines():
        line = raw.strip()
        if not line or ":" not in line:
            continue
        left, right = line.split(":", 1)
        label = _normalize(left)
        value = right.strip()
        if label.startswith("ssid "):
            flush()
            ssid = value or "<hidden>"
            auth, encryption, network_type = "Unknown", "Unknown", ""
        elif label in {"network type", "tipo de red"}:
            network_type = value
        elif label in {"authentication", "autenticacion"}:
            auth = value
        elif label in {"encryption", "cifrado"}:
            encryption = value
        elif label.startswith("bssid "):
            flush()
            current = {
                "ssid": ssid,
                "bssid": value,
                "authentication": auth,
                "encryption": encryption,
                "network_type": network_type,
            }
        elif current is not None:
            if label in {"signal", "senal"}:
                current["signal"] = _number(value)
            elif label in {"channel", "canal"}:
                current["channel"] = _number(value)
            elif label in {"radio type", "tipo de radio"}:
                current["radio"] = value
            elif label in {"band", "banda"}:
                current["band"] = value
    flush()
    return points


def scan_access_points(cancel_event: threading.Event | None = None) -> list[AccessPoint]:
    _check_cancel(cancel_event)
    output = _run_netsh(["wlan", "show", "networks", "mode=bssid"])
    _check_cancel(cancel_event)
    return parse_networks(output)


def _security_kind(point: AccessPoint) -> str:
    auth = _normalize(point.authentication)
    encryption = _normalize(point.encryption)
    if "wep" in auth or "wep" in encryption:
        return "legacy"
    if "wpa3" in auth:
        return "modern"
    if "wpa2" in auth:
        return "modern"
    if "wpa" in auth:
        return "legacy"
    if "open" in auth or "abierta" in auth or encryption in {"none", "ninguno", "ninguna"}:
        return "open"
    return "unknown"


def security_rating(point: AccessPoint) -> str:
    return {
        "modern": "Good",
        "legacy": "Review",
        "open": "Review",
        "unknown": "Unknown",
    }[_security_kind(point)]


def analyze_access_points(points: list[AccessPoint]) -> tuple[int, list[AuditFinding]]:
    findings: list[AuditFinding] = []
    by_ssid: dict[str, set[str]] = defaultdict(set)
    for point in points:
        kind = _security_kind(point)
        by_ssid[point.ssid].add(kind)
        if kind == "open":
            findings.append(
                AuditFinding(
                    "high",
                    f"Red abierta: {point.ssid}",
                    f"{point.bssid} aparece sin autenticación protegida.",
                    "Revise si la red abierta es intencionada y use WPA2/WPA3 cuando corresponda.",
                    15,
                )
            )
        elif kind == "legacy":
            findings.append(
                AuditFinding(
                    "high",
                    f"Configuración heredada: {point.ssid}",
                    f"{point.bssid} anuncia un esquema WiFi heredado.",
                    "Revise compatibilidad y migre a WPA2-AES o WPA3 cuando sea posible.",
                    10,
                )
            )

    for ssid, kinds in sorted(by_ssid.items()):
        meaningful = {kind for kind in kinds if kind != "unknown"}
        if len(meaningful) > 1:
            findings.append(
                AuditFinding(
                    "medium",
                    f"Política inconsistente: {ssid}",
                    f"El SSID aparece con perfiles de seguridad distintos: {', '.join(sorted(meaningful))}.",
                    "Confirme que todos los BSSID pertenecen a la infraestructura esperada y aplican la misma política.",
                    8,
                )
            )

    channels = Counter((point.band, point.channel) for point in points if point.channel is not None)
    for (band, channel), count in channels.items():
        if count >= 4:
            findings.append(
                AuditFinding(
                    "medium",
                    f"Canal concurrido: {band} canal {channel}",
                    f"Se observan {count} BSSID en el mismo canal.",
                    "Revise planificación de canal y ancho para reducir interferencia co-canal.",
                    4,
                )
            )

    if not points:
        findings.append(
            AuditFinding(
                "info",
                "Sin redes visibles",
                "Windows no devolvió BSSID en este snapshot.",
                "Compruebe el adaptador WiFi y vuelva a ejecutar el inventario.",
                0,
            )
        )
    return max(0, 100 - min(100, sum(item.penalty for item in findings))), findings


def _payload(
    generated_at: str,
    score: int,
    points: list[AccessPoint],
    findings: list[AuditFinding],
) -> dict[str, object]:
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": generated_at,
        "score": score,
        "access_points": [asdict(point) for point in points],
        "findings": [asdict(item) for item in findings],
        "limitations": list(LIMITATIONS),
    }


def _digest(payload: dict[str, object]) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def build_report(points: list[AccessPoint], generated_at: str | None = None) -> AuditReport:
    timestamp = generated_at or datetime.now(timezone.utc).isoformat()
    score, findings = analyze_access_points(points)
    payload = _payload(timestamp, score, points, findings)
    return AuditReport(
        timestamp,
        score,
        tuple(points),
        tuple(findings),
        LIMITATIONS,
        _digest(payload),
    )


def run_audit(cancel_event: threading.Event | None = None) -> AuditReport:
    return build_report(scan_access_points(cancel_event))


def report_to_dict(report: AuditReport) -> dict[str, object]:
    data = _payload(
        report.generated_at,
        report.score,
        list(report.access_points),
        list(report.findings),
    )
    data["evidence_sha256"] = report.evidence_sha256
    return data


def export_report(path: str | Path, report: AuditReport) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(
        report_to_dict(report),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, destination)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise
    return destination


def verify_report_data(data: dict[str, object]) -> bool:
    expected = data.get("evidence_sha256")
    if not isinstance(expected, str) or not expected:
        return False
    payload = dict(data)
    payload.pop("evidence_sha256", None)
    return _digest(payload) == expected


def verify_report_file(path: str | Path) -> bool:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return isinstance(data, dict) and verify_report_data(data)
