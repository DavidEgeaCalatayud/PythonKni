from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import threading
import unicodedata
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from pythonkni.core.tasks import WorkerCancelled

from .models import (
    AccessPoint,
    AuditFinding,
    AuditPlanItem,
    AuditReport,
    CaptureInspection,
)

NETSH_TIMEOUT_SECONDS = 12.0
TSHARK_TIMEOUT_SECONDS = 20.0
REPORT_SCHEMA_VERSION = 2
LIMITATIONS = (
    "El inventario usa la enumeración WiFi disponible en Windows y no activa modo monitor.",
    "El informe evalúa configuración visible; no intenta obtener ni validar credenciales.",
    "No se realiza sondeo WPS activo; WPS solo puede revisarse con información pasiva disponible.",
    "Las inconsistencias de SSID son indicadores para revisión manual, no una atribución de rogue AP.",
    "El análisis de capturas es exclusivamente offline y no extrae material para recuperación de contraseñas.",
)

_CAPTURE_MAGICS = {
    b"\xd4\xc3\xb2\xa1": "pcap",
    b"\xa1\xb2\xc3\xd4": "pcap",
    b"\x4d\x3c\xb2\xa1": "pcap",
    b"\xa1\xb2\x3c\x4d": "pcap",
    b"\x0a\x0d\x0d\x0a": "pcapng",
}


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
                signal_percent=current.get("signal")
                if isinstance(current.get("signal"), int)
                else None,
                channel=channel if isinstance(channel, int) else None,
                radio_type=str(current.get("radio") or ""),
                band=_band(
                    channel if isinstance(channel, int) else None,
                    str(current.get("band") or ""),
                ),
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
            if current is not None:
                current["authentication"] = value
        elif label in {"encryption", "cifrado"}:
            encryption = value
            if current is not None:
                current["encryption"] = value
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
    if "wep" in auth or "wep" in encryption or "tkip" in encryption:
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


def recommend_audit_plan(points: list[AccessPoint]) -> list[AuditPlanItem]:
    items: list[AuditPlanItem] = []
    kinds = [_security_kind(point) for point in points]
    by_ssid: dict[str, set[str]] = defaultdict(set)
    for point, kind in zip(points, kinds):
        by_ssid[point.ssid].add(kind)

    if not points:
        items.append(
            AuditPlanItem(
                100,
                "adapter-visibility-review",
                "Comprobar visibilidad del adaptador",
                "Windows no ha expuesto BSSID en el snapshot actual.",
                "Revise estado del adaptador, permisos y ubicación antes de repetir el inventario.",
            )
        )
    if any(kind in {"open", "legacy"} for kind in kinds):
        items.append(
            AuditPlanItem(
                100,
                "security-policy-review",
                "Revisar política de cifrado",
                "Hay redes abiertas o configuraciones WiFi heredadas visibles.",
                "Priorice migración a WPA2-AES/WPA3 y confirme que las redes abiertas sean intencionadas.",
            )
        )
    if any(
        len({kind for kind in ssid_kinds if kind != "unknown"}) > 1
        for ssid_kinds in by_ssid.values()
    ):
        items.append(
            AuditPlanItem(
                90,
                "ssid-consistency-review",
                "Validar consistencia de SSID/BSSID",
                "Un mismo SSID anuncia políticas de seguridad diferentes.",
                "Compare inventario autorizado de BSSID, ubicación y configuración antes de atribuir un rogue AP.",
            )
        )
    if any(kind == "unknown" for kind in kinds):
        items.append(
            AuditPlanItem(
                75,
                "capability-review",
                "Completar capacidades no identificadas",
                "Windows no ha expuesto suficiente información de seguridad para todos los BSSID.",
                "Contraste la configuración del controlador/AP y documente autenticación y cifrado esperados.",
            )
        )

    channels = Counter((point.band, point.channel) for point in points if point.channel is not None)
    if any(count >= 4 for count in channels.values()):
        items.append(
            AuditPlanItem(
                70,
                "channel-planning-review",
                "Revisar planificación RF",
                "Existe al menos un canal con alta densidad visible de BSSID.",
                "Revise canal, ancho y distribución de AP para reducir interferencia co-canal.",
            )
        )

    if points:
        items.append(
            AuditPlanItem(
                50,
                "offline-capture-review",
                "Analizar evidencia de captura offline",
                "Una captura PCAP/PCAPNG autorizada puede aportar contexto adicional sin interactuar con la red.",
                "Importe una captura existente para identificar formato, integridad y presencia de tramas EAPOL/RSN.",
            )
        )
        items.append(
            AuditPlanItem(
                20,
                "evidence-baseline",
                "Conservar baseline verificable",
                "El snapshot actual puede servir como referencia para comparaciones posteriores.",
                "Exporte el informe JSON y conserve su SHA-256 junto con la fecha y el alcance autorizado.",
            )
        )

    best: dict[str, AuditPlanItem] = {}
    for item in items:
        previous = best.get(item.code)
        if previous is None or item.priority > previous.priority:
            best[item.code] = item
    return sorted(best.values(), key=lambda item: (-item.priority, item.code))


def _payload(
    generated_at: str,
    score: int,
    points: list[AccessPoint],
    findings: list[AuditFinding],
    plan: list[AuditPlanItem],
) -> dict[str, object]:
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": generated_at,
        "score": score,
        "access_points": [asdict(point) for point in points],
        "findings": [asdict(item) for item in findings],
        "plan": [asdict(item) for item in plan],
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
    plan = recommend_audit_plan(points)
    payload = _payload(timestamp, score, points, findings, plan)
    return AuditReport(
        timestamp,
        score,
        tuple(points),
        tuple(findings),
        LIMITATIONS,
        _digest(payload),
        tuple(plan),
    )


def run_audit(cancel_event: threading.Event | None = None) -> AuditReport:
    return build_report(scan_access_points(cancel_event))


def report_to_dict(report: AuditReport) -> dict[str, object]:
    data = _payload(
        report.generated_at,
        report.score,
        list(report.access_points),
        list(report.findings),
        list(report.plan),
    )
    data["evidence_sha256"] = report.evidence_sha256
    return data


def export_report(path: str | Path, report: AuditReport) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    data = (
        json.dumps(
            report_to_dict(report),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
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


def _capture_format(header: bytes) -> str | None:
    return _CAPTURE_MAGICS.get(header[:4])


def _sha256_file(path: Path, cancel_event: threading.Event | None = None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            _check_cancel(cancel_event)
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    _check_cancel(cancel_event)
    return digest.hexdigest()


def _count_tshark_frames(path: Path, display_filter: str) -> int | None:
    if shutil.which("tshark") is None:
        return None
    try:
        completed = subprocess.run(
            [
                "tshark",
                "-r",
                str(path),
                "-Y",
                display_filter,
                "-T",
                "fields",
                "-e",
                "frame.number",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
            timeout=TSHARK_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return sum(1 for line in completed.stdout.splitlines() if line.strip())


def inspect_capture(
    path: str | Path,
    cancel_event: threading.Event | None = None,
) -> CaptureInspection:
    _check_cancel(cancel_event)
    capture = Path(path)
    if not capture.is_file():
        raise FileNotFoundError(capture)

    with capture.open("rb") as handle:
        header = handle.read(4)
    capture_format = _capture_format(header)
    if capture_format is None:
        raise ValueError("El archivo no tiene una cabecera PCAP/PCAPNG reconocida.")

    sha256 = _sha256_file(capture, cancel_event)
    _check_cancel(cancel_event)
    eapol_frames = _count_tshark_frames(capture, "eapol")
    _check_cancel(cancel_event)
    rsn_frames = _count_tshark_frames(capture, "wlan.rsn")
    analyzer = "tshark" if eapol_frames is not None or rsn_frames is not None else "builtin"
    return CaptureInspection(
        str(capture),
        capture_format,
        capture.stat().st_size,
        sha256,
        eapol_frames,
        rsn_frames,
        analyzer,
    )


def capture_inspection_to_dict(inspection: CaptureInspection) -> dict[str, object]:
    return asdict(inspection)
