from __future__ import annotations

import ipaddress

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from pythonkni.camera_auditor.service import MAX_CAMERA_HOSTS, parse_camera_scope
from pythonkni.network.service import detect_default_network, scan_network_hosts
from tools.base_tool import BaseTool
from tools.ui_feedback import show_error, show_warning
from tools.worker import Worker

from .models import NetworkIntelligenceDevice
from .service import analyze_hosts


def _default_scope() -> str:
    try:
        interface = detect_default_network()
        network = ipaddress.ip_network(interface.cidr, strict=False)
        if network.num_addresses > MAX_CAMERA_HOSTS:
            network = ipaddress.ip_network(f"{interface.address}/24", strict=False)
        return parse_camera_scope(network.with_prefixlen).with_prefixlen
    except (RuntimeError, ValueError):
        return "192.168.1.0/24"


def _run_network_intelligence(worker: Worker, scope: str):
    found = []
    checked = 0

    def on_found(host):
        found.append(host)
        worker.report_progress(
            {
                "phase": "discovery",
                "message": f"Host detectado: {host.ip}",
                "found": len(found),
                "checked": checked,
            }
        )

    def on_checked(_ip):
        nonlocal checked
        checked += 1
        if checked == 1 or checked % 16 == 0:
            worker.report_progress(
                {
                    "phase": "discovery",
                    "message": f"Descubrimiento: {checked} hosts comprobados; {len(found)} activos.",
                    "found": len(found),
                    "checked": checked,
                }
            )

    scan_network_hosts(
        scope,
        stop_event=worker.cancel_event,
        on_found=on_found,
        on_checked=on_checked,
    )
    worker.check_cancelled()

    classified = 0

    def on_device(device):
        nonlocal classified
        classified += 1
        worker.report_progress(
            {
                "phase": "classification",
                "message": (
                    f"Clasificando: {classified}/{len(found)} · "
                    f"{device.host.ip} → {device.kind.value}"
                ),
                "device": device,
            }
        )

    def on_classified(_host):
        worker.check_cancelled()

    return analyze_hosts(
        scope,
        found,
        stop_event=worker.cancel_event,
        on_device=on_device,
        on_checked=on_classified,
    )


class Tool(BaseTool):
    name = "Network Intelligence"
    description = (
        "Descubre y clasifica dispositivos locales como PC, router, impresora, NAS o cámara, "
        "y conecta cámaras detectadas con Camera Exposure Auditor."
    )
    category = "Network Intelligence"

    def setup_ui(self) -> None:
        self.setWindowTitle(self.name)
        self.setGeometry(160, 100, 1120, 760)
        self.worker: Worker | None = None
        self.devices: list[NetworkIntelligenceDevice] = []
        self._camera_windows = []

        root = QWidget()
        layout = QVBoxLayout(root)

        scope_row = QHBoxLayout()
        scope_row.addWidget(QLabel("Scope:"))
        self.scope_input = QLineEdit(_default_scope())
        self.scope_input.setPlaceholderText("192.168.1.0/24")
        scope_row.addWidget(self.scope_input, 1)
        self.discover_button = QPushButton("Discover & classify")
        self.discover_button.clicked.connect(self.start_scan)
        scope_row.addWidget(self.discover_button)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_scan)
        scope_row.addWidget(self.stop_button)
        layout.addLayout(scope_row)

        self.status_label = QLabel(
            "Network Intelligence solo analiza redes locales permitidas y un máximo de 256 hosts."
        )
        layout.addWidget(self.status_label)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["IP", "Hostname", "MAC", "Type", "Services", "Risk"])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.currentCellChanged.connect(self._selection_changed)
        layout.addWidget(self.table, 3)

        self.detail_area = QTextEdit()
        self.detail_area.setReadOnly(True)
        self.detail_area.setPlaceholderText(
            "Selecciona un dispositivo para ver las señales utilizadas en la clasificación."
        )
        layout.addWidget(self.detail_area, 2)

        action_row = QHBoxLayout()
        self.camera_button = QPushButton("Open in Camera Auditor")
        self.camera_button.setEnabled(False)
        self.camera_button.clicked.connect(self.open_selected_camera)
        action_row.addWidget(self.camera_button)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        self.setCentralWidget(root)

    def _set_running(self, running: bool) -> None:
        self.discover_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.scope_input.setEnabled(not running)

    def start_scan(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        try:
            network = parse_camera_scope(self.scope_input.text().strip())
        except ValueError as error:
            show_warning(self, self.name, str(error))
            return

        self.devices = []
        self.table.setRowCount(0)
        self.detail_area.clear()
        self.camera_button.setEnabled(False)
        self._set_running(True)
        self.status_label.setText(f"Descubriendo hosts en {network.with_prefixlen}...")

        worker = Worker(_run_network_intelligence, network.with_prefixlen, parent=self)
        worker.progress.connect(self._handle_progress)
        worker.result.connect(self._scan_finished)
        worker.error.connect(self._scan_failed)
        worker.cancelled.connect(self._scan_cancelled)
        worker.finished.connect(self._worker_finished)
        self.worker = worker
        self.start_managed_worker(worker, cancel=worker.cancel)

    def stop_scan(self) -> None:
        if self.worker is None or not self.worker.isRunning():
            return
        self.stop_button.setEnabled(False)
        self.status_label.setText("Cancelando Network Intelligence de forma cooperativa...")
        self.worker.cancel()

    def _handle_progress(self, payload) -> None:
        if isinstance(payload, dict):
            message = payload.get("message")
            if message:
                self.status_label.setText(str(message))
            device = payload.get("device")
            if isinstance(device, NetworkIntelligenceDevice):
                self._upsert_device(device)

    def _scan_finished(self, devices) -> None:
        self.devices = list(devices)
        self._rebuild_table()
        counts = {}
        for device in self.devices:
            counts[device.kind.value] = counts.get(device.kind.value, 0) + 1
        summary = ", ".join(f"{kind}: {count}" for kind, count in sorted(counts.items()))
        self.status_label.setText(
            f"Network Intelligence completado: {len(self.devices)} dispositivos clasificados"
            + (f" · {summary}" if summary else "")
        )

    def _scan_failed(self, error) -> None:
        show_error(
            self,
            self.name,
            "No se pudo completar Network Intelligence.",
            error=error if isinstance(error, BaseException) else None,
            details=None if isinstance(error, BaseException) else str(error),
        )
        self.status_label.setText("Network Intelligence finalizó con error.")

    def _scan_cancelled(self) -> None:
        self.status_label.setText(
            f"Network Intelligence cancelado. Se conservan {len(self.devices)} resultados parciales."
        )

    def _worker_finished(self) -> None:
        self._set_running(False)
        self.worker = None

    def _upsert_device(self, device: NetworkIntelligenceDevice) -> None:
        for index, current in enumerate(self.devices):
            if current.host.ip == device.host.ip:
                self.devices[index] = device
                self._write_row(index, device)
                return
        self.devices.append(device)
        self.devices.sort(key=lambda item: ipaddress.ip_address(item.host.ip))
        self._rebuild_table()

    def _write_row(self, row: int, device: NetworkIntelligenceDevice) -> None:
        values = (
            device.host.ip,
            device.host.hostname,
            device.host.mac,
            device.kind.value,
            " ".join(device.services),
            device.risk.value,
        )
        for column, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            item.setData(Qt.UserRole, device.host.ip)
            self.table.setItem(row, column, item)

    def _rebuild_table(self) -> None:
        selected_ip = self._selected_ip()
        self.table.setRowCount(len(self.devices))
        for row, device in enumerate(self.devices):
            self._write_row(row, device)
            if selected_ip == device.host.ip:
                self.table.selectRow(row)

    def _selected_ip(self) -> str | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        return item.data(Qt.UserRole) or item.text()

    def _selected_device(self) -> NetworkIntelligenceDevice | None:
        selected_ip = self._selected_ip()
        return next(
            (device for device in self.devices if device.host.ip == selected_ip),
            None,
        )

    def _selection_changed(self, *_args) -> None:
        device = self._selected_device()
        if device is None:
            self.detail_area.clear()
            self.camera_button.setEnabled(False)
            return
        lines = [
            f"IP: {device.host.ip}",
            f"Hostname: {device.host.hostname}",
            f"MAC: {device.host.mac}",
            f"Type: {device.kind.value}",
            f"Risk: {device.risk.value}",
            f"Services: {', '.join(device.services) or 'No signals'}",
            "",
            "Classification evidence:",
            *[f"- {item}" for item in device.evidence],
        ]
        if device.camera is not None:
            lines.extend(
                [
                    "",
                    "Camera evidence:",
                    f"- Vendor: {device.camera.vendor}",
                    f"- Confidence: {device.camera.confidence}",
                    f"- ONVIF: {'Yes' if device.camera.onvif else 'No'}",
                ]
            )
        self.detail_area.setPlainText("\n".join(lines))
        self.camera_button.setEnabled(device.can_open_camera)

    def open_selected_camera(self) -> None:
        device = self._selected_device()
        if device is None or not device.can_open_camera:
            return
        from pythonkni.camera_auditor.window import Tool as CameraAuditorTool

        window = CameraAuditorTool()
        window.scope_input.setText(f"{device.host.ip}/32")
        window.show()
        window.start_audit()
        self._camera_windows.append(window)
