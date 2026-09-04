from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from pythonkni.infrastructure.paths import PROJECT_ROOT

from .models import BackendInfo

SUPPORTED_TAILCAT_VERSION = "0.5.0"
STARTUP_TIMEOUT_SECONDS = 30.0
COMMAND_POLL_SECONDS = 0.10
PROCESS_STOP_GRACE_SECONDS = 2.0
POST_STREAM_EXIT_TIMEOUT_SECONDS = 5.0
MAX_TEXT_BYTES = 1024 * 1024
MAX_DIAGNOSTIC_CHARS = 4000
TOKEN_PATTERN = re.compile(r"^tc[A-Za-z0-9_-]{20,4096}$")
VERSION_PATTERN = re.compile(r"(?:^|\D)v?(\d+\.\d+\.\d+)(?:\D|$)")


class TailcatUnavailable(RuntimeError):
    """Raised when the pinned Tailcat transport cannot be located."""


class TailcatVersionUnsupported(RuntimeError):
    """Raised when the discovered Tailcat CLI version is not the pinned version."""


class TailcatExecutionError(RuntimeError):
    """Raised when Tailcat cannot complete a requested transport operation."""


class TailcatAddressError(ValueError):
    """Raised when a Tailcat address is malformed or rejected by ``tailcat parse``."""


def resolve_tailcat_executable(explicit_path: str | os.PathLike[str] | None = None) -> Path:
    candidates: list[Path] = []
    if explicit_path:
        candidates.append(Path(explicit_path))

    configured = os.getenv("PYTHONKNI_TAILCAT_PATH")
    if configured:
        candidates.append(Path(configured))

    candidates.append(PROJECT_ROOT / "third_party" / "tailcat" / "tailcat.exe")

    path_candidate = shutil.which("tailcat")
    if path_candidate:
        candidates.append(Path(path_candidate))

    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()

    raise TailcatUnavailable(
        "Tailcat no está disponible. Ejecuta scripts/fetch_tailcat.ps1 o configura "
        "PYTHONKNI_TAILCAT_PATH con el binario Tailcat v0.5.0 verificado."
    )


def require_scp_executable() -> Path:
    scp = shutil.which("scp")
    if not scp:
        raise TailcatUnavailable(
            "El envío de archivos y carpetas con Tailcat requiere scp.exe. "
            "Activa Windows OpenSSH Client o instala un cliente OpenSSH compatible."
        )
    return Path(scp).resolve()


def validate_address_shape(value: str) -> str:
    token = str(value).strip()
    if not token:
        raise TailcatAddressError("Introduce un token de conexión Tailcat.")
    if not TOKEN_PATTERN.fullmatch(token):
        raise TailcatAddressError("El token Tailcat no tiene un formato válido.")
    return token


def normalize_port(value: int | str) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError("El puerto debe ser un número entero.") from error
    if port < 1 or port > 65535:
        raise ValueError("El puerto debe estar entre 1 y 65535.")
    return port


def build_receive_command(
    executable: str | os.PathLike[str],
    destination: str | os.PathLike[str],
    *,
    accept_directories: bool = False,
) -> list[str]:
    command = [str(executable), "--json", "--key=new", "recv"]
    if accept_directories:
        command.append("--accept-dirs")
    command.append(str(destination))
    return command


def build_send_path_command(
    executable: str | os.PathLike[str],
    token: str,
    source: str | os.PathLike[str],
    *,
    recursive: bool = False,
) -> list[str]:
    validated = validate_address_shape(token)
    command = [str(executable), "--key=new", "cp"]
    if recursive:
        command.append("-r")
    command.extend([str(source), f"{validated}:"])
    return command


def build_send_text_command(executable: str | os.PathLike[str], token: str) -> list[str]:
    return [str(executable), "--key=new", validate_address_shape(token)]


def build_receive_text_command(executable: str | os.PathLike[str]) -> list[str]:
    return [str(executable), "--json", "--key=new"]


def build_serve_port_command(executable: str | os.PathLike[str], port: int | str) -> list[str]:
    return [str(executable), "--json", "--key=new", "serve", str(normalize_port(port))]


def build_forward_command(
    executable: str | os.PathLike[str],
    token: str,
    *,
    remote_port: int | str,
    local_port: int | str,
) -> list[str]:
    remote = normalize_port(remote_port)
    local = normalize_port(local_port)
    return [
        str(executable),
        "--key=new",
        "forward",
        "--bind=127.0.0.1",
        validate_address_shape(token),
        f"{local}:{remote}",
    ]


def _creationflags() -> int:
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _decode(data: bytes | str | None) -> str:
    if data is None:
        return ""
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return data


def _diagnostic(data: bytes | str | None) -> str:
    compact = " ".join(_decode(data).split())
    return (compact or "sin diagnóstico adicional")[:MAX_DIAGNOSTIC_CHARS]


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=PROCESS_STOP_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=PROCESS_STOP_GRACE_SECONDS)


def _wait_interruptibly(
    process: subprocess.Popen[bytes],
    *,
    stop_event: threading.Event,
) -> int:
    while True:
        if stop_event.is_set():
            _stop_process(process)
            return process.returncode if process.returncode is not None else -1
        returncode = process.poll()
        if returncode is not None:
            return returncode
        time.sleep(COMMAND_POLL_SECONDS)


def _wait_after_stream(process: subprocess.Popen[bytes]) -> int:
    deadline = time.monotonic() + POST_STREAM_EXIT_TIMEOUT_SECONDS
    while process.poll() is None:
        if time.monotonic() >= deadline:
            _stop_process(process)
            raise TailcatExecutionError("Tailcat no cerró la sesión después de recibir el texto.")
        time.sleep(COMMAND_POLL_SECONDS)
    return process.returncode if process.returncode is not None else -1


def _extract_token(payload: Mapping[str, Any]) -> str:
    for value in payload.values():
        if isinstance(value, str):
            try:
                return validate_address_shape(value)
            except TailcatAddressError:
                continue
    raise TailcatExecutionError("Tailcat no devolvió un token de escucha válido.")


class TailcatBackend:
    """Narrow adapter around one pinned Tailcat CLI release.

    Tailcat explicitly does not promise CLI or wire-format stability. Keeping all
    command construction and output parsing in this adapter limits future changes
    to one module and prevents PythonKni from depending on Tailcat's CBOR format.
    """

    def __init__(
        self,
        executable: str | os.PathLike[str] | None = None,
        *,
        popen_factory: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
        run_command: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self._explicit_path = executable
        self._popen_factory = popen_factory
        self._run_command = run_command

    @property
    def executable(self) -> Path:
        return resolve_tailcat_executable(self._explicit_path)

    def info(self) -> BackendInfo:
        executable = self.executable
        completed = self._run_command(
            [str(executable), "version"],
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
        )
        if completed.returncode != 0:
            raise TailcatExecutionError(
                f"No se pudo consultar la versión de Tailcat: {_diagnostic(completed.stderr)}"
            )
        match = VERSION_PATTERN.search(completed.stdout.strip())
        if match is None:
            raise TailcatExecutionError("Tailcat devolvió una versión no reconocible.")
        version = match.group(1)
        if version != SUPPORTED_TAILCAT_VERSION:
            raise TailcatVersionUnsupported(
                f"PythonKni soporta Tailcat v{SUPPORTED_TAILCAT_VERSION}; se encontró v{version}."
            )
        return BackendInfo("Tailcat", version, executable, True)

    def parse_address(self, token: str) -> dict[str, object]:
        validated = validate_address_shape(token)
        completed = self._run_command(
            [str(self.executable), "parse", validated],
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
        )
        if completed.returncode != 0:
            raise TailcatAddressError(
                f"Tailcat rechazó el token de conexión: {_diagnostic(completed.stderr)}"
            )
        try:
            decoded = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise TailcatExecutionError("`tailcat parse` devolvió JSON no válido.") from error
        if not isinstance(decoded, dict):
            raise TailcatExecutionError("`tailcat parse` devolvió una estructura inesperada.")
        return {str(key): value for key, value in decoded.items()}

    def _spawn(
        self,
        command: list[str],
        *,
        stdin: int | None = None,
        stdout: int | None = subprocess.PIPE,
        stderr: int | None = subprocess.PIPE,
    ) -> subprocess.Popen[bytes]:
        return self._popen_factory(
            command,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            shell=False,
            creationflags=_creationflags(),
        )

    def _server_ready_token(
        self,
        process: subprocess.Popen[bytes],
        *,
        stop_event: threading.Event,
    ) -> str:
        if process.stdout is None:
            raise TailcatExecutionError("Tailcat no expuso stdout para anunciar el token.")

        ready_queue: queue.Queue[bytes] = queue.Queue(maxsize=1)

        def read_line() -> None:
            try:
                ready_queue.put(process.stdout.readline())
            except Exception:
                ready_queue.put(b"")

        threading.Thread(target=read_line, daemon=True).start()
        deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
        while True:
            if stop_event.is_set():
                _stop_process(process)
                return ""
            if process.poll() is not None:
                stderr = process.stderr.read() if process.stderr is not None else b""
                raise TailcatExecutionError(
                    f"Tailcat terminó antes de anunciar el token: {_diagnostic(stderr)}"
                )
            try:
                line = ready_queue.get(timeout=COMMAND_POLL_SECONDS)
            except queue.Empty:
                if time.monotonic() >= deadline:
                    _stop_process(process)
                    raise TailcatExecutionError("Tailcat no anunció el token a tiempo.")
                continue
            if not line:
                raise TailcatExecutionError("Tailcat cerró stdout antes de anunciar el token.")
            try:
                decoded = json.loads(_decode(line))
            except json.JSONDecodeError as error:
                raise TailcatExecutionError("Tailcat devolvió un anuncio JSON no válido.") from error
            if not isinstance(decoded, Mapping):
                raise TailcatExecutionError("Tailcat devolvió un anuncio de escucha inesperado.")
            return _extract_token(decoded)

    def receive_files(
        self,
        destination: Path,
        *,
        accept_directories: bool,
        stop_event: threading.Event,
        on_ready: Callable[[str], None] | None = None,
    ) -> None:
        command = build_receive_command(
            self.executable,
            destination,
            accept_directories=accept_directories,
        )
        process = self._spawn(command, stdin=subprocess.DEVNULL)
        token = self._server_ready_token(process, stop_event=stop_event)
        if stop_event.is_set():
            return
        if on_ready is not None:
            on_ready(token)
        returncode = _wait_interruptibly(process, stop_event=stop_event)
        if stop_event.is_set():
            return
        if returncode != 0:
            stderr = process.stderr.read() if process.stderr is not None else b""
            raise TailcatExecutionError(
                f"El receptor Tailcat terminó con código {returncode}: {_diagnostic(stderr)}"
            )

    def send_path(
        self,
        token: str,
        source: Path,
        *,
        recursive: bool,
        stop_event: threading.Event,
    ) -> None:
        self.parse_address(token)
        require_scp_executable()
        command = build_send_path_command(self.executable, token, source, recursive=recursive)
        process = self._spawn(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        returncode = _wait_interruptibly(process, stop_event=stop_event)
        if stop_event.is_set():
            return
        if returncode != 0:
            raise TailcatExecutionError(f"El envío Tailcat terminó con código {returncode}.")

    def receive_text(
        self,
        *,
        stop_event: threading.Event,
        on_ready: Callable[[str], None] | None = None,
    ) -> str:
        process = self._spawn(build_receive_text_command(self.executable), stdin=subprocess.DEVNULL)
        token = self._server_ready_token(process, stop_event=stop_event)
        if stop_event.is_set():
            return ""
        if on_ready is not None:
            on_ready(token)
        if process.stdout is None:
            _stop_process(process)
            raise TailcatExecutionError("Tailcat no expuso stdout para recibir texto.")

        chunk_queue: queue.Queue[bytes | None] = queue.Queue()

        def read_payload() -> None:
            try:
                while True:
                    chunk = process.stdout.read(65536)
                    if not chunk:
                        break
                    chunk_queue.put(chunk)
            finally:
                chunk_queue.put(None)

        threading.Thread(target=read_payload, daemon=True).start()
        payload = bytearray()
        finished = False
        while not finished:
            if stop_event.is_set():
                _stop_process(process)
                return ""
            try:
                chunk = chunk_queue.get(timeout=COMMAND_POLL_SECONDS)
            except queue.Empty:
                continue
            if chunk is None:
                finished = True
                continue
            payload.extend(chunk)
            if len(payload) > MAX_TEXT_BYTES:
                _stop_process(process)
                raise TailcatExecutionError(
                    f"El texto recibido supera el límite de {MAX_TEXT_BYTES // 1024} KiB."
                )

        returncode = _wait_after_stream(process)
        if returncode != 0:
            stderr = process.stderr.read() if process.stderr is not None else b""
            raise TailcatExecutionError(
                f"La recepción de texto terminó con código {returncode}: {_diagnostic(stderr)}"
            )
        return payload.decode("utf-8", errors="replace")

    def send_text(
        self,
        token: str,
        text: str,
        *,
        stop_event: threading.Event,
    ) -> None:
        self.parse_address(token)
        payload = text.encode("utf-8")
        if len(payload) > MAX_TEXT_BYTES:
            raise ValueError(f"El texto no puede superar {MAX_TEXT_BYTES // 1024} KiB.")
        process = self._spawn(build_send_text_command(self.executable, token), stdin=subprocess.PIPE)
        stdout = b""
        stderr = b""
        try:
            stdout, stderr = process.communicate(input=payload, timeout=COMMAND_POLL_SECONDS)
        except subprocess.TimeoutExpired:
            while True:
                if stop_event.is_set():
                    _stop_process(process)
                    return
                try:
                    stdout, stderr = process.communicate(timeout=COMMAND_POLL_SECONDS)
                    break
                except subprocess.TimeoutExpired:
                    continue
        if process.returncode != 0:
            raise TailcatExecutionError(
                f"El envío de texto terminó con código {process.returncode}: {_diagnostic(stderr)}"
            )
        _ = stdout

    def serve_port(
        self,
        port: int,
        *,
        stop_event: threading.Event,
        on_ready: Callable[[str], None] | None = None,
    ) -> None:
        process = self._spawn(build_serve_port_command(self.executable, port), stdin=subprocess.DEVNULL)
        token = self._server_ready_token(process, stop_event=stop_event)
        if stop_event.is_set():
            return
        if on_ready is not None:
            on_ready(token)
        returncode = _wait_interruptibly(process, stop_event=stop_event)
        if stop_event.is_set():
            return
        if returncode != 0:
            stderr = process.stderr.read() if process.stderr is not None else b""
            raise TailcatExecutionError(
                f"El túnel Tailcat terminó con código {returncode}: {_diagnostic(stderr)}"
            )

    def forward_port(
        self,
        token: str,
        *,
        remote_port: int,
        local_port: int,
        stop_event: threading.Event,
        on_ready: Callable[[], None] | None = None,
    ) -> None:
        self.parse_address(token)
        command = build_forward_command(
            self.executable,
            token,
            remote_port=remote_port,
            local_port=local_port,
        )
        process = self._spawn(command, stdin=subprocess.DEVNULL)
        deadline = time.monotonic() + 0.25
        while process.poll() is None and time.monotonic() < deadline:
            if stop_event.is_set():
                _stop_process(process)
                return
            time.sleep(0.05)
        if process.poll() is not None:
            stderr = process.stderr.read() if process.stderr is not None else b""
            raise TailcatExecutionError(f"El forward Tailcat no pudo arrancar: {_diagnostic(stderr)}")
        if on_ready is not None:
            on_ready()
        returncode = _wait_interruptibly(process, stop_event=stop_event)
        if stop_event.is_set():
            return
        if returncode != 0:
            stderr = process.stderr.read() if process.stderr is not None else b""
            raise TailcatExecutionError(
                f"El forward Tailcat terminó con código {returncode}: {_diagnostic(stderr)}"
            )
