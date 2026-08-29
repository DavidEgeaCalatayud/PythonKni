from __future__ import annotations

import hashlib
import logging
import os

import psutil
import requests

from .models import (
    ProcessDetails,
    VirusTotalResult,
)

logger = logging.getLogger(__name__)
SYSTEM_PROCESS_NAMES = {
    "csrss.exe",
    "fontdrvhost.exe",
    "lsass.exe",
    "registry",
    "services.exe",
    "smss.exe",
    "system",
    "system idle process",
    "svchost.exe",
    "wininit.exe",
    "winlogon.exe",
}
SYSTEM_USERNAMES = {
    "local service",
    "network service",
    "nt authority\\local service",
    "nt authority\\network service",
    "nt authority\\system",
    "system",
}


class ProcessOperationError(RuntimeError):
    """Base error for process operations that should be presented safely by the UI."""


class OwnProcessTerminationError(ProcessOperationError):
    """Raised when PythonKni is asked to terminate its own process."""


class ProcessUnavailableError(ProcessOperationError):
    """Raised when a process disappeared or cannot be inspected/managed."""


class ProcessIdentityChangedError(ProcessOperationError):
    """Raised when a PID was recycled between inspection and termination."""


def get_vt_api_key():
    return os.getenv("VIRUSTOTAL_API_KEY")


def is_own_process(pid, app_pid=None):
    """Indica si el PID pertenece a la instancia actual de PythonKni."""
    return pid == (os.getpid() if app_pid is None else app_pid)


def is_system_process(details):
    """Clasifica conservadoramente procesos que requieren una advertencia extra."""
    name = details.name.casefold()
    username = details.username.casefold()
    exe_path = details.exe_path.casefold().replace("/", "\\")

    if details.pid in {0, 4}:
        return True
    if name in SYSTEM_PROCESS_NAMES:
        return True
    if username in SYSTEM_USERNAMES:
        return True
    return "\\windows\\system32\\" in exe_path or "\\windows\\syswow64\\" in exe_path


def format_process_identity(details):
    return f"PID: {details.pid}\nNombre: {details.name}\nRuta: {details.exe_path}"


def _safe_process_value(getter, fallback="No disponible"):
    try:
        value = getter()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return fallback
    return str(value) if value else fallback


def get_process_details(proc):
    """Obtiene una instantánea del proceso sin fallar por campos restringidos."""
    return ProcessDetails(
        pid=proc.pid,
        name=_safe_process_value(proc.name, "Desconocido"),
        exe_path=_safe_process_value(proc.exe),
        username=_safe_process_value(proc.username),
        create_time=proc.create_time(),
    )


def get_termination_target(pid: int, app_pid: int | None = None) -> ProcessDetails:
    """Inspect and validate a process before the UI asks the user for confirmation."""
    if is_own_process(pid, app_pid=app_pid):
        raise OwnProcessTerminationError(
            "PythonKni no puede terminar su propio proceso desde el Gestor de Procesos."
        )

    try:
        proc = psutil.Process(pid)
        return get_process_details(proc)
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as error:
        raise ProcessUnavailableError(
            "El proceso ya no existe o no se puede consultar con los permisos actuales."
        ) from error


def terminate_process(details: ProcessDetails) -> None:
    """Terminate the previously inspected process after revalidating its identity.

    PID reuse is explicitly checked through ``create_time`` so a process that
    disappeared and was replaced after the confirmation dialog is never targeted.
    """
    if is_own_process(details.pid):
        raise OwnProcessTerminationError(
            "PythonKni no puede terminar su propio proceso desde el Gestor de Procesos."
        )

    try:
        proc = psutil.Process(details.pid)
        if not proc.is_running() or proc.create_time() != details.create_time:
            raise ProcessIdentityChangedError(
                "El proceso seleccionado ya no es el mismo. Se ha cancelado la operación por seguridad."
            )
        proc.terminate()
    except ProcessIdentityChangedError:
        raise
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as error:
        raise ProcessUnavailableError(
            "El proceso ya no existe o no se puede administrar con los permisos actuales."
        ) from error


CPU_SAMPLE_SECONDS = 0.1


def load_processes_task(worker, cpu_min, mem_min):
    """Collect process metrics with one shared non-blocking CPU sample window."""
    candidates = []
    for proc in psutil.process_iter(["pid", "name"]):
        worker.check_cancelled()
        try:
            proc.cpu_percent(interval=None)
            candidates.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    if candidates:
        if worker.cancel_event.wait(CPU_SAMPLE_SECONDS):
            worker.check_cancelled()

    processes = []
    for proc in candidates:
        worker.check_cancelled()
        try:
            cpu = proc.cpu_percent(interval=None)
            mem = proc.memory_percent()
            if cpu < cpu_min and mem < mem_min:
                continue
            processes.append((proc.pid, proc.info["name"] or "Desconocido", cpu, mem))
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return processes


def analyze_process_task(worker, pid, api_key):
    """Hash an executable and query VirusTotal without blocking the GUI."""
    worker.report_progress({"message": f"Leyendo proceso {pid}..."})
    proc = psutil.Process(pid)
    exe_path = proc.exe()

    file_size = max(os.path.getsize(exe_path), 1)
    hashed_bytes = 0
    sha256_hash = hashlib.sha256()
    worker.report_progress({"message": "Calculando SHA-256...", "percent": 0})

    with open(exe_path, "rb") as file:
        while True:
            worker.check_cancelled()
            chunk = file.read(1024 * 1024)
            if not chunk:
                break
            sha256_hash.update(chunk)
            hashed_bytes += len(chunk)
            percent = min(100, int((hashed_bytes / file_size) * 100))
            worker.report_progress(
                {"message": f"Calculando SHA-256... {percent}%", "percent": percent}
            )

    file_hash = sha256_hash.hexdigest()
    worker.report_progress({"message": "Consultando VirusTotal..."})
    response = requests.get(
        f"https://www.virustotal.com/api/v3/files/{file_hash}",
        headers={"x-apikey": api_key},
        timeout=20,
    )
    worker.check_cancelled()

    if response.status_code == 404:
        return VirusTotalResult("not_found", exe_path, file_hash)
    if response.status_code != 200:
        return VirusTotalResult(
            "http_error",
            exe_path,
            file_hash,
            response_text=response.text,
        )

    data = response.json()
    attributes = data["data"]["attributes"]
    stats = attributes["last_analysis_stats"]
    scans = attributes["last_analysis_results"]
    detections = tuple(
        f"{engine}: {result['result']}"
        for engine, result in scans.items()
        if result["category"] == "malicious"
    )
    return VirusTotalResult(
        "found",
        exe_path,
        file_hash,
        positives=stats.get("malicious", 0),
        total=sum(stats.values()),
        detections=detections,
    )
