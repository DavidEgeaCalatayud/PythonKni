from __future__ import annotations

import json
import math
import os
import platform
import shutil
import socket
import subprocess
import threading
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from pythonkni.infrastructure.paths import PROJECT_ROOT

from .models import (
    OpenPort,
    SecurityFindingSeverity,
    ServiceFingerprint,
    ServiceSecurityFinding,
    UdpPortState,
    UdpProbeResult,
)

DEFAULT_NERVA_TIMEOUT_MS = 2000
DEFAULT_NERVA_WORKERS = 20
DEFAULT_NERVA_MAX_HOST_CONNECTIONS = 4
PROCESS_POLL_SECONDS = 0.10
PROCESS_STOP_GRACE_SECONDS = 2.0
MAX_DIAGNOSTIC_CHARS = 2000
SUPPORTED_TRANSPORTS = frozenset({"tcp", "udp", "sctp"})


class FingerprintEngineUnavailable(RuntimeError):
    """Raised when the optional Nerva engine cannot be located."""


class FingerprintExecutionError(RuntimeError):
    """Raised when Nerva cannot complete a fingerprint batch."""


class FingerprintCapabilityUnavailable(RuntimeError):
    """Raised when a requested Nerva transport is unsupported on this platform."""


def resolve_nerva_executable(explicit_path: str | os.PathLike[str] | None = None) -> Path:
    candidates: list[Path] = []
    if explicit_path:
        candidates.append(Path(explicit_path))

    configured = os.getenv("PYTHONKNI_NERVA_PATH")
    if configured:
        candidates.append(Path(configured))

    candidates.append(PROJECT_ROOT / "third_party" / "nerva" / "nerva.exe")

    path_candidate = shutil.which("nerva")
    if path_candidate:
        candidates.append(Path(path_candidate))

    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()

    raise FingerprintEngineUnavailable(
        "Nerva no está disponible. Ejecuta scripts/fetch_nerva.ps1 o configura "
        "PYTHONKNI_NERVA_PATH con un binario Nerva verificado."
    )


def _normalize_ports(ports: Iterable[int | OpenPort]) -> list[int]:
    normalized: set[int] = set()
    for item in ports:
        port = item.port if isinstance(item, OpenPort) else int(item)
        if port < 1 or port > 65535:
            raise ValueError(f"Puerto fuera de rango: {port}")
        normalized.add(port)
    return sorted(normalized)


def transport_available(transport: str, *, system_name: str | None = None) -> bool:
    normalized = str(transport).strip().lower()
    if normalized not in SUPPORTED_TRANSPORTS:
        return False
    if normalized != "sctp":
        return True
    return (system_name or platform.system()).strip().lower() == "linux"


def build_nerva_command(
    executable: str | os.PathLike[str],
    ip: str,
    ports: Iterable[int | OpenPort],
    *,
    timeout_ms: int = DEFAULT_NERVA_TIMEOUT_MS,
    workers: int = DEFAULT_NERVA_WORKERS,
    max_host_connections: int = DEFAULT_NERVA_MAX_HOST_CONNECTIONS,
    transport: str = "tcp",
    misconfigs: bool = False,
    system_name: str | None = None,
) -> list[str]:
    normalized_ports = _normalize_ports(ports)
    if not normalized_ports:
        raise ValueError("Se requiere al menos un puerto abierto para fingerprinting.")
    if timeout_ms < 100 or timeout_ms > 60000:
        raise ValueError("El timeout de Nerva debe estar entre 100 y 60000 ms.")
    if workers < 1 or workers > 100:
        raise ValueError("Los workers de Nerva deben estar entre 1 y 100.")
    if max_host_connections < 1 or max_host_connections > 20:
        raise ValueError("El límite por host debe estar entre 1 y 20 conexiones.")
    if not isinstance(misconfigs, bool):
        raise ValueError("misconfigs debe ser un booleano explícito.")

    normalized_transport = str(transport).strip().lower()
    if normalized_transport not in SUPPORTED_TRANSPORTS:
        raise ValueError(f"Transporte Nerva no compatible: {transport}")
    if not transport_available(normalized_transport, system_name=system_name):
        raise FingerprintCapabilityUnavailable(
            "SCTP no está disponible en esta plataforma. Nerva v1.69.4 limita SCTP a Linux."
        )

    targets = ",".join(f"{ip}:{port}" for port in normalized_ports)
    command = [
        str(executable),
        "--json",
        "--targets",
        targets,
        "--timeout",
        str(timeout_ms),
        "--workers",
        str(workers),
        "--max-host-conn",
        str(max_host_connections),
    ]
    if normalized_transport == "udp":
        command.append("--udp")
    elif normalized_transport == "sctp":
        command.append("--sctp")
    if misconfigs:
        command.append("--misconfigs")
    return command


def _metadata_for(item: Mapping[str, Any]) -> dict[str, object]:
    metadata_value = item.get("metadata")
    if isinstance(metadata_value, Mapping):
        metadata: dict[str, object] = dict(metadata_value)
    elif metadata_value is None:
        metadata = {}
    else:
        metadata = {"value": metadata_value}

    structural = {
        "host",
        "ip",
        "port",
        "protocol",
        "transport",
        "metadata",
        "security_findings",
    }
    for key, value in item.items():
        if key not in structural and key not in metadata:
            metadata[key] = value
    return metadata


def _first_text(*sources: Mapping[str, Any], keys: Sequence[str]) -> str:
    for source in sources:
        for key in keys:
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _finding_severity(value: object) -> SecurityFindingSeverity:
    normalized = str(value or "").strip().lower()
    try:
        return SecurityFindingSeverity(normalized)
    except ValueError:
        return SecurityFindingSeverity.UNKNOWN


def _security_findings_for(item: Mapping[str, Any]) -> tuple[ServiceSecurityFinding, ...]:
    raw = item.get("security_findings")
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError("Resultado Nerva con security_findings no válido.")

    findings: list[ServiceSecurityFinding] = []
    for entry in raw:
        if not isinstance(entry, Mapping):
            raise ValueError("Resultado Nerva con un security finding no válido.")
        finding_id = str(entry.get("id") or entry.get("finding_id") or "unknown").strip()
        description = str(entry.get("description") or entry.get("title") or finding_id).strip()
        findings.append(
            ServiceSecurityFinding(
                finding_id=finding_id or "unknown",
                severity=_finding_severity(entry.get("severity")),
                description=description or finding_id or "Security finding",
                title=str(entry.get("title") or "").strip(),
                impact=str(entry.get("impact") or "").strip(),
                recommendation=str(entry.get("recommendation") or "").strip(),
                cvss=str(entry.get("cvss") or "").strip(),
                evidence=str(entry.get("evidence") or "").strip(),
            )
        )
    return tuple(findings)


def _parse_fingerprint(item: Mapping[str, Any]) -> ServiceFingerprint:
    try:
        port = int(item["port"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("Resultado Nerva sin un puerto válido.") from error
    if port < 1 or port > 65535:
        raise ValueError(f"Resultado Nerva con puerto fuera de rango: {port}")

    protocol = str(item.get("protocol") or "").strip().lower()
    if not protocol:
        raise ValueError("Resultado Nerva sin protocolo identificado.")

    host = str(item.get("host") or "").strip()
    ip = str(item.get("ip") or host).strip()
    transport = str(item.get("transport") or "tcp").strip().lower()
    metadata = _metadata_for(item)
    product = _first_text(
        item,
        metadata,
        keys=("product", "application", "software", "server", "name"),
    )
    version = _first_text(
        item,
        metadata,
        keys=("version", "product_version", "software_version", "server_version"),
    )
    return ServiceFingerprint(
        host=host,
        ip=ip,
        port=port,
        protocol=protocol,
        transport=transport,
        product=product,
        version=version,
        metadata=metadata,
        state="open",
        security_findings=_security_findings_for(item),
    )


def parse_nerva_output(output: str, *, allow_partial: bool = False) -> list[ServiceFingerprint]:
    text = output.strip()
    if not text:
        return []

    payloads: list[Mapping[str, Any]] = []
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for index, line in enumerate(lines):
            try:
                decoded_line = json.loads(line)
            except json.JSONDecodeError as error:
                if allow_partial and index == len(lines) - 1:
                    break
                raise ValueError("Nerva devolvió JSON no válido.") from error
            if not isinstance(decoded_line, Mapping):
                raise ValueError("Nerva devolvió una entrada JSON que no es un objeto.")
            payloads.append(decoded_line)
    else:
        if isinstance(decoded, Mapping):
            payloads.append(decoded)
        elif isinstance(decoded, list):
            for entry in decoded:
                if not isinstance(entry, Mapping):
                    raise ValueError("Nerva devolvió una entrada JSON que no es un objeto.")
                payloads.append(entry)
        else:
            raise ValueError("Nerva devolvió una estructura JSON no compatible.")

    results = [_parse_fingerprint(item) for item in payloads]
    return sorted(results, key=lambda item: (item.ip, item.port, item.transport, item.protocol))


def _diagnostic(stderr: str) -> str:
    compact = " ".join(stderr.split())
    if not compact:
        return "sin diagnóstico adicional"
    return compact[:MAX_DIAGNOSTIC_CHARS]


def _stop_process(process: subprocess.Popen[str]) -> tuple[str, str]:
    process.terminate()
    try:
        return process.communicate(timeout=PROCESS_STOP_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        return process.communicate()


def _execution_timeout_seconds(target_count: int, timeout_ms: int, workers: int) -> float:
    batches = max(1, math.ceil(target_count / max(1, workers)))
    return max(10.0, (timeout_ms / 1000.0) * batches * 3.0 + 5.0)


def fingerprint_open_ports(
    target: str,
    ports: Iterable[int | OpenPort],
    *,
    stop_event: threading.Event | None = None,
    executable: str | os.PathLike[str] | None = None,
    timeout_ms: int = DEFAULT_NERVA_TIMEOUT_MS,
    workers: int = DEFAULT_NERVA_WORKERS,
    max_host_connections: int = DEFAULT_NERVA_MAX_HOST_CONNECTIONS,
    transport: str = "tcp",
    misconfigs: bool = False,
    system_name: str | None = None,
    on_found: Callable[[ServiceFingerprint], None] | None = None,
    popen_factory: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
    monotonic: Callable[[], float] = time.monotonic,
) -> list[ServiceFingerprint]:
    stop_event = stop_event or threading.Event()
    normalized_ports = _normalize_ports(ports)
    if not normalized_ports or stop_event.is_set():
        return []

    ip = socket.gethostbyname(target)
    engine = resolve_nerva_executable(executable)
    command = build_nerva_command(
        engine,
        ip,
        normalized_ports,
        timeout_ms=timeout_ms,
        workers=workers,
        max_host_connections=max_host_connections,
        transport=transport,
        misconfigs=misconfigs,
        system_name=system_name,
    )
    process = popen_factory(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )

    started = monotonic()
    overall_timeout = _execution_timeout_seconds(len(normalized_ports), timeout_ms, workers)
    stdout = ""
    stderr = ""
    cancelled = False

    while True:
        if stop_event.is_set():
            stdout, stderr = _stop_process(process)
            cancelled = True
            break
        if monotonic() - started > overall_timeout:
            stdout, stderr = _stop_process(process)
            raise FingerprintExecutionError(
                f"Nerva excedió el tiempo máximo de ejecución ({overall_timeout:.1f} s)."
            )
        try:
            stdout, stderr = process.communicate(timeout=PROCESS_POLL_SECONDS)
            break
        except subprocess.TimeoutExpired:
            continue

    if not cancelled and process.returncode not in (0, None):
        raise FingerprintExecutionError(
            f"Nerva terminó con código {process.returncode}: {_diagnostic(stderr)}"
        )

    try:
        results = parse_nerva_output(stdout, allow_partial=cancelled)
    except ValueError as error:
        raise FingerprintExecutionError(str(error)) from error

    if on_found is not None:
        for result in results:
            on_found(result)
    return results


def classify_udp_state(
    *,
    identified: bool = False,
    explicitly_closed: bool = False,
    probe_sent: bool = False,
) -> UdpPortState:
    if identified:
        return UdpPortState.OPEN
    if explicitly_closed:
        return UdpPortState.CLOSED
    if probe_sent:
        return UdpPortState.OPEN_FILTERED
    return UdpPortState.UNKNOWN


def probe_udp_ports(
    target: str,
    ports: Iterable[int | OpenPort],
    *,
    stop_event: threading.Event | None = None,
    executable: str | os.PathLike[str] | None = None,
    timeout_ms: int = DEFAULT_NERVA_TIMEOUT_MS,
    workers: int = DEFAULT_NERVA_WORKERS,
    max_host_connections: int = DEFAULT_NERVA_MAX_HOST_CONNECTIONS,
    popen_factory: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
    monotonic: Callable[[], float] = time.monotonic,
) -> list[UdpProbeResult]:
    stop_event = stop_event or threading.Event()
    normalized_ports = _normalize_ports(ports)
    if not normalized_ports or stop_event.is_set():
        return []

    ip = socket.gethostbyname(target)
    fingerprints = fingerprint_open_ports(
        target,
        normalized_ports,
        stop_event=stop_event,
        executable=executable,
        timeout_ms=timeout_ms,
        workers=workers,
        max_host_connections=max_host_connections,
        transport="udp",
        misconfigs=False,
        popen_factory=popen_factory,
        monotonic=monotonic,
    )
    by_port: dict[int, ServiceFingerprint] = {}
    for fingerprint in fingerprints:
        by_port.setdefault(fingerprint.port, fingerprint)

    return [
        UdpProbeResult(
            host=target,
            ip=ip,
            port=port,
            state=classify_udp_state(identified=port in by_port, probe_sent=True),
            fingerprint=by_port.get(port),
        )
        for port in normalized_ports
    ]