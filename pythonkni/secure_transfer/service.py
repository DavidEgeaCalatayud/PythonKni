from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from pathlib import Path

from .models import (
    BackendInfo,
    ForwardPortRequest,
    ReceiveFilesRequest,
    SendPathRequest,
    SendTextRequest,
    ServePortRequest,
    TransferEvent,
    TransferEventKind,
    TransferMode,
    TransferResult,
)
from .tailcat_backend import TailcatBackend, normalize_port

EventCallback = Callable[[TransferEvent], None]


class SecureTransferService:
    """Framework-independent orchestration for bounded Secure Transfer workflows."""

    def __init__(self, backend: TailcatBackend | None = None) -> None:
        self.backend = backend or TailcatBackend()

    def backend_info(self) -> BackendInfo:
        return self.backend.info()

    def validate_token(self, token: str) -> Mapping[str, object]:
        self.backend.info()
        return self.backend.parse_address(token)

    @staticmethod
    def _emit(
        callback: EventCallback | None,
        kind: TransferEventKind,
        message: str,
        *,
        token: str = "",
        text: str = "",
    ) -> None:
        if callback is not None:
            callback(TransferEvent(kind, message, token=token, text=text))

    def receive_files(
        self,
        request: ReceiveFilesRequest,
        *,
        stop_event: threading.Event,
        on_event: EventCallback | None = None,
    ) -> TransferResult:
        destination = Path(request.destination).expanduser()
        if not destination.exists():
            raise ValueError("La carpeta de destino no existe.")
        if not destination.is_dir():
            raise ValueError("El destino de recepción debe ser una carpeta.")
        self.backend.info()
        self._emit(
            on_event,
            TransferEventKind.STATUS,
            "Preparando receptor cifrado con clave efímera...",
        )

        def ready(token: str) -> None:
            message = "Receptor listo. Comparte este token solo con la persona esperada."
            if request.accept_directories:
                message += " La recepción de carpetas está habilitada."
            self._emit(on_event, TransferEventKind.READY, message, token=token)

        self.backend.receive_files(
            destination,
            accept_directories=request.accept_directories,
            stop_event=stop_event,
            on_ready=ready,
        )
        return TransferResult(
            TransferMode.FOLDER if request.accept_directories else TransferMode.FILE,
            "Receptor detenido.",
            destination=destination,
        )

    def send_path(
        self,
        request: SendPathRequest,
        *,
        stop_event: threading.Event,
        on_event: EventCallback | None = None,
    ) -> TransferResult:
        source = Path(request.source).expanduser()
        if not source.exists():
            raise ValueError("El archivo o carpeta seleccionado no existe.")
        if not source.is_file() and not source.is_dir():
            raise ValueError("Solo se pueden enviar archivos o carpetas normales.")
        self.backend.info()
        recursive = source.is_dir()
        mode = TransferMode.FOLDER if recursive else TransferMode.FILE
        self._emit(
            on_event,
            TransferEventKind.STATUS,
            f"Enviando {'carpeta' if recursive else 'archivo'} mediante WireGuard...",
        )
        self.backend.send_path(
            request.token,
            source,
            recursive=recursive,
            stop_event=stop_event,
        )
        size = source.stat().st_size if source.is_file() else None
        self._emit(on_event, TransferEventKind.STATUS, "Transferencia completada.")
        return TransferResult(
            mode,
            "Transferencia completada.",
            source=source,
            bytes_transferred=size,
        )

    def receive_text(
        self,
        *,
        stop_event: threading.Event,
        on_event: EventCallback | None = None,
    ) -> TransferResult:
        self.backend.info()
        self._emit(on_event, TransferEventKind.STATUS, "Preparando recepción de texto cifrado...")

        def ready(token: str) -> None:
            self._emit(
                on_event,
                TransferEventKind.READY,
                "Receptor de texto listo. El token es efímero para esta sesión.",
                token=token,
            )

        text = self.backend.receive_text(stop_event=stop_event, on_ready=ready)
        if stop_event.is_set():
            return TransferResult(TransferMode.TEXT, "Recepción de texto detenida.")
        self._emit(
            on_event,
            TransferEventKind.TEXT,
            "Texto recibido.",
            text=text,
        )
        return TransferResult(
            TransferMode.TEXT,
            "Texto recibido.",
            bytes_transferred=len(text.encode("utf-8")),
        )

    def send_text(
        self,
        request: SendTextRequest,
        *,
        stop_event: threading.Event,
        on_event: EventCallback | None = None,
    ) -> TransferResult:
        if not request.text:
            raise ValueError("Escribe algún texto antes de enviarlo.")
        self.backend.info()
        self._emit(on_event, TransferEventKind.STATUS, "Enviando texto cifrado...")
        self.backend.send_text(request.token, request.text, stop_event=stop_event)
        size = len(request.text.encode("utf-8"))
        self._emit(on_event, TransferEventKind.STATUS, "Texto enviado.")
        return TransferResult(
            TransferMode.TEXT,
            "Texto enviado.",
            bytes_transferred=size,
        )

    def serve_port(
        self,
        request: ServePortRequest,
        *,
        stop_event: threading.Event,
        on_event: EventCallback | None = None,
    ) -> TransferResult:
        port = normalize_port(request.local_port)
        self.backend.info()
        self._emit(
            on_event,
            TransferEventKind.STATUS,
            f"Compartiendo únicamente localhost:{port} mediante Tailcat...",
        )

        def ready(token: str) -> None:
            self._emit(
                on_event,
                TransferEventKind.READY,
                f"Túnel listo para localhost:{port}.",
                token=token,
            )

        self.backend.serve_port(port, stop_event=stop_event, on_ready=ready)
        return TransferResult(TransferMode.SERVE_PORT, "Túnel detenido.")

    def forward_port(
        self,
        request: ForwardPortRequest,
        *,
        stop_event: threading.Event,
        on_event: EventCallback | None = None,
    ) -> TransferResult:
        remote_port = normalize_port(request.remote_port)
        local_port = normalize_port(request.local_port)
        self.backend.info()
        self._emit(
            on_event,
            TransferEventKind.STATUS,
            f"Creando forward 127.0.0.1:{local_port} → peer:{remote_port}...",
        )

        def ready() -> None:
            self._emit(
                on_event,
                TransferEventKind.READY,
                f"Forward activo en 127.0.0.1:{local_port}.",
            )

        self.backend.forward_port(
            request.token,
            remote_port=remote_port,
            local_port=local_port,
            stop_event=stop_event,
            on_ready=ready,
        )
        return TransferResult(TransferMode.FORWARD_PORT, "Forward detenido.")
