from __future__ import annotations

from pathlib import Path
from typing import Callable

from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from tools.base_tool import BaseTool
from tools.ui_feedback import show_error, show_warning
from tools.worker import Worker

from .models import (
    ForwardPortRequest,
    ReceiveFilesRequest,
    SendPathRequest,
    SendTextRequest,
    ServePortRequest,
    TransferEvent,
    TransferEventKind,
    TransferResult,
)
from .service import SecureTransferService


def _run_operation(worker: Worker, operation: Callable[..., TransferResult]) -> TransferResult:
    return operation(stop_event=worker.cancel_event, on_event=worker.report_progress)


class Tool(BaseTool):
    name = "Secure Transfer"
    description = (
        "Transfiere archivos, carpetas, texto y puertos mediante Tailcat cifrado con WireGuard."
    )
    category = "Red"

    def setup_ui(self) -> None:
        self.setWindowTitle(self.name)
        self.setGeometry(140, 80, 1080, 760)
        self.service = SecureTransferService()
        self.worker: Worker | None = None
        self.selected_path: Path | None = None
        self._ready_field: QLineEdit | None = None

        root = QWidget()
        layout = QVBoxLayout(root)

        banner = QLabel(
            "Tailcat v0.5.0 · WireGuard + NAT traversal / DERP. Las sesiones creadas por "
            "PythonKni fuerzan claves efímeras. Tailcat sigue siendo experimental entre "
            "peers que no confían entre sí."
        )
        banner.setWordWrap(True)
        layout.addWidget(banner)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._files_tab(), "Files")
        self.tabs.addTab(self._text_tab(), "Text")
        self.tabs.addTab(self._tunnel_tab(), "Tunnel")
        self.tabs.addTab(self._diagnostics_tab(), "Diagnostics")
        layout.addWidget(self.tabs, 1)

        bottom = QHBoxLayout()
        self.status_label = QLabel("Ready. No session is active.")
        self.status_label.setWordWrap(True)
        bottom.addWidget(self.status_label, 1)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_operation)
        bottom.addWidget(self.stop_button)
        layout.addLayout(bottom)

        self.setCentralWidget(root)

    def _files_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        receive = QGroupBox("Receive file / folder")
        receive_layout = QFormLayout(receive)
        destination_row = QHBoxLayout()
        self.receive_destination = QLineEdit()
        self.receive_destination.setPlaceholderText("Choose an inbox folder")
        destination_row.addWidget(self.receive_destination, 1)
        choose_destination = QPushButton("Browse…")
        choose_destination.clicked.connect(self.choose_receive_destination)
        destination_row.addWidget(choose_destination)
        receive_layout.addRow("Destination:", destination_row)
        self.accept_folders = QCheckBox(
            "Accept folder trees (reveals more filename/directory metadata to the sender)"
        )
        self.accept_folders.setChecked(False)
        receive_layout.addRow("", self.accept_folders)
        self.receive_files_button = QPushButton("Start receiver")
        self.receive_files_button.clicked.connect(self.start_receive_files)
        receive_layout.addRow("", self.receive_files_button)
        self.receive_token = self._token_field(receive_layout, "Connection token:")
        copy_receive = QPushButton("Copy token")
        copy_receive.clicked.connect(lambda: self.copy_token(self.receive_token))
        receive_layout.addRow("", copy_receive)
        layout.addWidget(receive)

        send = QGroupBox("Send file / folder")
        send_layout = QFormLayout(send)
        self.send_token = QLineEdit()
        self.send_token.setPlaceholderText("tc…")
        send_layout.addRow("Token:", self.send_token)
        source_row = QHBoxLayout()
        self.send_path = QLineEdit()
        self.send_path.setReadOnly(True)
        source_row.addWidget(self.send_path, 1)
        choose_file = QPushButton("File…")
        choose_file.clicked.connect(self.choose_send_file)
        source_row.addWidget(choose_file)
        choose_folder = QPushButton("Folder…")
        choose_folder.clicked.connect(self.choose_send_folder)
        source_row.addWidget(choose_folder)
        send_layout.addRow("Source:", source_row)
        scp_note = QLabel(
            "File/folder sending uses Tailcat cp and therefore requires Windows OpenSSH scp.exe."
        )
        scp_note.setWordWrap(True)
        send_layout.addRow("", scp_note)
        self.send_path_button = QPushButton("Send")
        self.send_path_button.clicked.connect(self.start_send_path)
        send_layout.addRow("", self.send_path_button)
        layout.addWidget(send)
        layout.addStretch(1)
        return page

    def _text_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        receive = QGroupBox("Receive text")
        receive_layout = QFormLayout(receive)
        self.receive_text_button = QPushButton("Start text receiver")
        self.receive_text_button.clicked.connect(self.start_receive_text)
        receive_layout.addRow("", self.receive_text_button)
        self.receive_text_token = self._token_field(receive_layout, "Connection token:")
        copy_token = QPushButton("Copy token")
        copy_token.clicked.connect(lambda: self.copy_token(self.receive_text_token))
        receive_layout.addRow("", copy_token)
        self.received_text = QTextEdit()
        self.received_text.setReadOnly(True)
        receive_layout.addRow("Received:", self.received_text)
        layout.addWidget(receive)

        send = QGroupBox("Send text")
        send_layout = QFormLayout(send)
        self.send_text_token = QLineEdit()
        self.send_text_token.setPlaceholderText("tc…")
        send_layout.addRow("Token:", self.send_text_token)
        self.outgoing_text = QTextEdit()
        self.outgoing_text.setPlaceholderText("Text to send")
        send_layout.addRow("Text:", self.outgoing_text)
        self.send_text_button = QPushButton("Send text")
        self.send_text_button.clicked.connect(self.start_send_text)
        send_layout.addRow("", self.send_text_button)
        layout.addWidget(send)
        return page

    def _tunnel_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        share = QGroupBox("Share a local TCP service")
        share_layout = QFormLayout(share)
        self.serve_port = self._port_spinbox(8080)
        share_layout.addRow("Localhost port:", self.serve_port)
        self.serve_button = QPushButton("Start secure tunnel")
        self.serve_button.clicked.connect(self.start_serve_port)
        share_layout.addRow("", self.serve_button)
        self.serve_token = self._token_field(share_layout, "Connection token:")
        copy_serve = QPushButton("Copy token")
        copy_serve.clicked.connect(lambda: self.copy_token(self.serve_token))
        share_layout.addRow("", copy_serve)
        layout.addWidget(share)

        forward = QGroupBox("Forward a peer port to this PC")
        forward_layout = QFormLayout(forward)
        self.forward_token = QLineEdit()
        self.forward_token.setPlaceholderText("tc…")
        forward_layout.addRow("Token:", self.forward_token)
        self.remote_port = self._port_spinbox(8080)
        forward_layout.addRow("Peer port:", self.remote_port)
        self.local_port = self._port_spinbox(18080)
        forward_layout.addRow("Local port:", self.local_port)
        loopback = QLabel(
            "PythonKni always binds the local listener to 127.0.0.1. There is no 0.0.0.0 option."
        )
        loopback.setWordWrap(True)
        forward_layout.addRow("", loopback)
        self.forward_button = QPushButton("Start local forward")
        self.forward_button.clicked.connect(self.start_forward_port)
        forward_layout.addRow("", self.forward_button)
        layout.addWidget(forward)
        layout.addStretch(1)
        return page

    def _diagnostics_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.backend_button = QPushButton("Check Tailcat runtime")
        self.backend_button.clicked.connect(self.check_backend)
        layout.addWidget(self.backend_button)
        self.backend_label = QLabel("Runtime not checked yet.")
        self.backend_label.setWordWrap(True)
        layout.addWidget(self.backend_label)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log, 1)
        return page

    @staticmethod
    def _token_field(layout: QFormLayout, label: str) -> QLineEdit:
        field = QLineEdit()
        field.setReadOnly(True)
        field.setPlaceholderText("Created when the receiver/tunnel is ready")
        layout.addRow(label, field)
        return field

    @staticmethod
    def _port_spinbox(default: int) -> QSpinBox:
        field = QSpinBox()
        field.setRange(1, 65535)
        field.setValue(default)
        return field

    def choose_receive_destination(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Choose receive folder")
        if selected:
            self.receive_destination.setText(selected)

    def choose_send_file(self) -> None:
        selected, _filter = QFileDialog.getOpenFileName(self, "Choose file to send")
        if selected:
            self.selected_path = Path(selected)
            self.send_path.setText(selected)

    def choose_send_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Choose folder to send")
        if selected:
            self.selected_path = Path(selected)
            self.send_path.setText(selected)

    def copy_token(self, field: QLineEdit) -> None:
        token = field.text().strip()
        if not token:
            show_warning(self, self.name, "Todavía no hay un token listo para copiar.")
            return
        QApplication.clipboard().setText(token)
        self.status_label.setText("Connection token copied to clipboard.")

    def _start(
        self,
        operation: Callable[..., TransferResult],
        description: str,
        *,
        ready_field: QLineEdit | None = None,
    ) -> None:
        if self.worker is not None and self.worker.isRunning():
            show_warning(self, self.name, "Ya hay una sesión Secure Transfer en ejecución.")
            return
        worker = Worker(_run_operation, operation, parent=self)
        worker.progress.connect(self._progress)
        worker.result.connect(self._completed)
        worker.error.connect(self._failed)
        worker.cancelled.connect(self._cancelled)
        worker.finished.connect(self._worker_finished)
        self.worker = worker
        self._ready_field = ready_field
        self._set_running(True)
        self.status_label.setText(description)
        self.log.append(description)
        self.start_managed_worker(worker, cancel=worker.cancel)

    def _set_running(self, running: bool) -> None:
        self.stop_button.setEnabled(running)
        for button in (
            self.receive_files_button,
            self.send_path_button,
            self.receive_text_button,
            self.send_text_button,
            self.serve_button,
            self.forward_button,
            self.backend_button,
        ):
            button.setEnabled(not running)

    def start_receive_files(self) -> None:
        destination = self.receive_destination.text().strip()
        if not destination:
            show_warning(self, self.name, "Selecciona una carpeta de destino.")
            return
        self.receive_token.clear()
        request = ReceiveFilesRequest(Path(destination), self.accept_folders.isChecked())
        self._start(
            lambda **kwargs: self.service.receive_files(request, **kwargs),
            "Starting encrypted file receiver…",
            ready_field=self.receive_token,
        )

    def start_send_path(self) -> None:
        token = self.send_token.text().strip()
        if not token or self.selected_path is None:
            show_warning(self, self.name, "Introduce el token y selecciona un archivo o carpeta.")
            return
        request = SendPathRequest(token, self.selected_path)
        self._start(
            lambda **kwargs: self.service.send_path(request, **kwargs),
            "Starting encrypted file transfer…",
        )

    def start_receive_text(self) -> None:
        self.receive_text_token.clear()
        self.received_text.clear()
        self._start(
            self.service.receive_text,
            "Starting encrypted text receiver…",
            ready_field=self.receive_text_token,
        )

    def start_send_text(self) -> None:
        token = self.send_text_token.text().strip()
        text = self.outgoing_text.toPlainText()
        if not token or not text:
            show_warning(self, self.name, "Introduce el token y el texto que quieres enviar.")
            return
        request = SendTextRequest(token, text)
        self._start(
            lambda **kwargs: self.service.send_text(request, **kwargs),
            "Starting encrypted text transfer…",
        )

    def start_serve_port(self) -> None:
        self.serve_token.clear()
        request = ServePortRequest(self.serve_port.value())
        self._start(
            lambda **kwargs: self.service.serve_port(request, **kwargs),
            "Starting secure local-service tunnel…",
            ready_field=self.serve_token,
        )

    def start_forward_port(self) -> None:
        token = self.forward_token.text().strip()
        if not token:
            show_warning(self, self.name, "Introduce el token del peer.")
            return
        request = ForwardPortRequest(token, self.remote_port.value(), self.local_port.value())
        self._start(
            lambda **kwargs: self.service.forward_port(request, **kwargs),
            "Starting localhost-only port forward…",
        )

    def stop_operation(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.stop_button.setEnabled(False)
            self.status_label.setText("Stopping session cooperatively…")
            self.worker.cancel()

    def _progress(self, event: TransferEvent) -> None:
        self.status_label.setText(event.message)
        self.log.append(event.message)
        if event.kind == TransferEventKind.READY and event.token and self._ready_field is not None:
            self._ready_field.setText(event.token)
        if event.kind == TransferEventKind.TEXT:
            self.received_text.setPlainText(event.text)

    def _completed(self, result: TransferResult) -> None:
        self.status_label.setText(result.message)
        self.log.append(result.message)

    def _failed(self, error: Exception) -> None:
        show_error(self, self.name, str(error))
        self.status_label.setText(f"Secure Transfer failed: {error}")
        self.log.append(f"ERROR: {error}")

    def _cancelled(self) -> None:
        self.status_label.setText("Secure Transfer session cancelled.")
        self.log.append("Session cancelled.")

    def _worker_finished(self) -> None:
        self.worker = None
        self._ready_field = None
        self._set_running(False)

    def check_backend(self) -> None:
        try:
            info = self.service.backend_info()
        except Exception as error:
            self.backend_label.setText(f"Tailcat unavailable: {error}")
            show_error(self, self.name, str(error))
            return
        self.backend_label.setText(
            f"{info.name} v{info.version} · pinned runtime OK · {info.executable}"
        )
