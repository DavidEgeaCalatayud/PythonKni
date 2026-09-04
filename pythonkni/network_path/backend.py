from __future__ import annotations

import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from pythonkni.infrastructure.paths import PROJECT_ROOT

from .models import BackendInfo, HopHost, HopProbe, TraceProtocol, TraceRequest, TraceSnapshot

SUPPORTED_TRIPPY_VERSION = "0.13.0"
VERSION_PATTERN = re.compile(r"(?:^|\D)v?(\d+\.\d+\.\d+)(?:\D|$)")
COMMAND_POLL_SECONDS = 0.10
PROCESS_STOP_GRACE_SECONDS = 2.0
MAX_OUTPUT_BYTES = 2 * 1024 * 1024
DEFAULT_UDP_PORT = 33434
DEFAULT_TCP_PORT = 443


class TrippyUnavailable(RuntimeError):
    """Raised when the pinned Trippy executable cannot be located."""


class TrippyVersionUnsupported(RuntimeError):
    """Raised when the discovered Trippy version differs from the pinned contract."""


class TrippyPrivilegesRequired(PermissionError):
    """Raised when Windows raw-socket tracing is attempted without elevation."""


class TrippyExecutionError(RuntimeError):
    """Raised when Trippy fails or returns an unexpected report."""


class TraceCancelled(RuntimeError):
    """Internal cancellation sentinel used while a Trippy subprocess is active."""


def resolve_trippy_executable(explicit_path: str | os.PathLike[str] | None = None) -> Path:
    candidates: list[Path] = []
    if explicit_path:
        candidates.append(Path(explicit_path))

    configured = os.getenv("PYTHONKNI_TRIPPY_PATH")
    if configured:
        candidates.append(Path(configured))

    candidates.append(PROJECT_ROOT / "third_party" / "trippy" / "trip.exe")

    path_candidate = shutil.which("trip")
    if path_candidate:
        candidates.append(Path(path_candidate))

    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()

    raise TrippyUnavailable(
        "Trippy no está disponible. Ejecuta scripts/fetch_trippy.ps1 o configura "
        "PYTHONKNI_TRIPPY_PATH con el binario Trippy v0.13.0 verificado."
    )


def windows_is_elevated() -> bool:
    if sys.platform != "win32":
        return True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def _creationflags() -> int:
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _diagnostic(value: bytes | str | None) -> str:
    if value is None:
        return "sin diagnóstico adicional"
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    else:
        text = value
    compact = " ".join(text.split())
    return (compact or "sin diagnóstico adicional")[:4000]


def _clean_environment() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if not key.startswith("TRIP_")}


def _duration_argument(seconds: float) -> str:
    milliseconds = max(250, int(round(seconds * 1000)))
    return f"{milliseconds}ms"


def effective_port(request: TraceRequest) -> int | None:
    if request.protocol is TraceProtocol.ICMP:
        return None
    if request.port is not None:
        return request.port
    if request.protocol is TraceProtocol.UDP:
        return DEFAULT_UDP_PORT
    return DEFAULT_TCP_PORT


def build_trace_command(
    executable: str | os.PathLike[str],
    request: TraceRequest,
    *,
    config_file: str | os.PathLike[str],
) -> list[str]:
    interval = _duration_argument(request.interval_seconds)
    command = [
        str(executable),
        request.target,
        "--config-file",
        str(config_file),
        "--mode",
        "json",
        "--report-cycles",
        "1",
        "--protocol",
        request.protocol.value,
        "--addr-family",
        request.address_family.value,
        "--dns-resolve-method",
        "system",
        "--max-ttl",
        str(request.max_ttl),
        "--min-round-duration",
        interval,
        "--max-round-duration",
        interval,
    ]
    port = effective_port(request)
    if port is not None:
        command.extend(["--target-port", str(port)])
    if request.protocol is TraceProtocol.UDP:
        command.extend(["--multipath-strategy", "dublin"])
    return command


def _as_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: object) -> float | None:
    if value in (None, "", "-"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_hosts(value: object) -> tuple[HopHost, ...]:
    if not isinstance(value, list):
        return ()
    result: list[HopHost] = []
    seen: set[tuple[str, str]] = set()
    for raw in value:
        if not isinstance(raw, Mapping):
            continue
        ip = str(raw.get("ip") or "").strip()
        hostname = str(raw.get("hostname") or "").strip().rstrip(".")
        if not ip:
            continue
        key = (ip, hostname)
        if key in seen:
            continue
        seen.add(key)
        result.append(HopHost(ip=ip, hostname=hostname))
    return tuple(result)


def parse_trippy_report(
    payload: str | bytes | Mapping[str, Any],
    request: TraceRequest,
    *,
    timestamp: float | None = None,
) -> TraceSnapshot:
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", errors="replace")
    if isinstance(payload, str):
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError as error:
            raise TrippyExecutionError("Trippy devolvió un informe JSON no válido.") from error
    else:
        decoded = payload
    if not isinstance(decoded, Mapping):
        raise TrippyExecutionError("Trippy devolvió una estructura de informe inesperada.")

    info = decoded.get("info")
    target_info = info.get("target") if isinstance(info, Mapping) else None
    if not isinstance(target_info, Mapping):
        target_info = {}
    target_ip = str(target_info.get("ip") or "").strip()
    target_hostname = str(target_info.get("hostname") or "").strip().rstrip(".")

    raw_hops = decoded.get("hops")
    if not isinstance(raw_hops, list):
        raise TrippyExecutionError("El informe JSON de Trippy no contiene una lista de saltos.")

    hops: list[HopProbe] = []
    for raw in raw_hops:
        if not isinstance(raw, Mapping):
            continue
        ttl = _as_int(raw.get("ttl"))
        if ttl < 1:
            continue
        sent = max(0, _as_int(raw.get("sent")))
        received = max(0, _as_int(raw.get("recv")))
        raw_loss = _as_float(raw.get("loss_pct"))
        if raw_loss is None:
            loss = ((sent - received) / sent * 100.0) if sent else 0.0
        else:
            loss = min(100.0, max(0.0, raw_loss))
        hops.append(
            HopProbe(
                ttl=ttl,
                hosts=_parse_hosts(raw.get("hosts")),
                sent=sent,
                received=received,
                loss_pct=loss,
                last_ms=_as_float(raw.get("last")),
            )
        )

    hops.sort(key=lambda item: item.ttl)
    reached = bool(target_ip) and any(target_ip in hop.host_ips for hop in hops)
    return TraceSnapshot(
        timestamp=time.time() if timestamp is None else timestamp,
        target=request.target,
        target_ip=target_ip,
        target_hostname=target_hostname,
        protocol=request.protocol,
        port=effective_port(request),
        hops=tuple(hops),
        reached_destination=reached,
    )


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=PROCESS_STOP_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=PROCESS_STOP_GRACE_SECONDS)


class TrippyBackend:
    """Narrow adapter around the pinned Trippy JSON reporting contract."""

    def __init__(
        self,
        executable: str | os.PathLike[str] | None = None,
        *,
        run_command: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        popen_factory: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
    ) -> None:
        self._explicit_path = executable
        self._run_command = run_command
        self._popen_factory = popen_factory

    @property
    def executable(self) -> Path:
        return resolve_trippy_executable(self._explicit_path)

    def info(self) -> BackendInfo:
        executable = self.executable
        completed = self._run_command(
            [str(executable), "--version"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            shell=False,
            creationflags=_creationflags(),
            check=False,
            env=_clean_environment(),
        )
        if completed.returncode != 0:
            raise TrippyExecutionError(
                f"No se pudo consultar la versión de Trippy: {_diagnostic(completed.stderr)}"
            )
        match = VERSION_PATTERN.search(completed.stdout.strip())
        if match is None:
            raise TrippyExecutionError("Trippy devolvió una versión no reconocible.")
        version = match.group(1)
        if version != SUPPORTED_TRIPPY_VERSION:
            raise TrippyVersionUnsupported(
                f"PythonKni soporta Trippy v{SUPPORTED_TRIPPY_VERSION}; se encontró v{version}."
            )
        return BackendInfo("Trippy", version, executable, True, windows_is_elevated())

    def trace_once(self, request: TraceRequest, *, stop_event) -> TraceSnapshot:
        if sys.platform == "win32" and not windows_is_elevated():
            raise TrippyPrivilegesRequired(
                "Network Path Analyzer requiere ejecutar PythonKni como administrador en Windows "
                "porque Trippy utiliza sockets raw para ICMP/UDP/TCP traceroute."
            )

        executable = self.executable
        with tempfile.TemporaryDirectory(prefix="pythonkni-trippy-") as temp_dir:
            config_path = Path(temp_dir) / "trippy.toml"
            config_path.write_text("# PythonKni deterministic Trippy configuration\n", encoding="utf-8")
            command = build_trace_command(executable, request, config_file=config_path)
            process = self._popen_factory(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                creationflags=_creationflags(),
                cwd=temp_dir,
                env=_clean_environment(),
            )
            while True:
                if stop_event.is_set():
                    _stop_process(process)
                    raise TraceCancelled()
                try:
                    stdout, stderr = process.communicate(timeout=COMMAND_POLL_SECONDS)
                    break
                except subprocess.TimeoutExpired:
                    continue

        if process.returncode != 0:
            raise TrippyExecutionError(
                f"Trippy terminó con código {process.returncode}: {_diagnostic(stderr)}"
            )
        if len(stdout) > MAX_OUTPUT_BYTES:
            raise TrippyExecutionError("El informe de Trippy supera el límite de salida permitido.")
        return parse_trippy_report(stdout, request)
