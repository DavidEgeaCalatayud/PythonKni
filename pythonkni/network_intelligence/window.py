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
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from pythonkni.camera_auditor.service import MAX_CAMERA_HOSTS, parse_camera_scope
from pythonkni.infrastructure.paths import NETWORK_INTELLIGENCE_DB
from pythonkni.network.service import detect_default_network, scan_network_hosts
from tools.base_tool import BaseTool
from tools.ui_feedback import show_error, show_warning
from tools.worker import Worker

from .audit_window import DeviceAuditorDialog
from .inventory import InventoryStore
from .models import AssetRecord, DeviceKind, NetworkIntelligenceDevice
from .score import calculate_security_score
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


def _format_time(value) -> str:
    return value.astimezone().strftime("%d/%m/%Y %H:%M:%S")


class Tool(BaseTool):
    name = "Network Intelligence"
    description = (
        "Mantiene un inventario persistente de activos locales, clasifica dispositivos, "
        "calcula exposición de red y registra cambios entre escaneos."
    )
    category = "Network Intelligence"

    def setup_ui(self) -> None:
        self.setWindowTitle(self.name)
        self.setGeometry(120, 70, 1260, 820)
        self.worker: Worker | None = None
        self.devices: list[NetworkIntelligenceDevice] = []
        self.assets: list[AssetRecord] = []
        self.inventory = InventoryStore(NETWORK_INTELLIGENCE_DB)
        self._camera_windows = []
        self._audit_windows = []

        root = QWidget()
        layout = QVBoxLayout(root)

        scope_row = QHBoxLayout()
        scope_row.addWidget(QLabel("Scope:"))
        self.scope_input = QLineEdit(_default_scope())
        self.scope_input.setPlaceholderText("192.168.1.0/24")
        self.scope_input.editingFinished.connect(self.refresh_inventory)
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
            "Network Intelligence conserva activos y cambios entre ejecuciones. "
            "Solo se analizan redes locales permitidas y hasta 256 hosts."
        )
        layout.addWidget(self.status_label)

        self.score_label = QLabel()
        layout.addWidget(self.score_label)
        self.score_findings = QTextEdit()
        self.score_findings.setReadOnly(True)
        self.score_findings.setMaximumHeight(92)
        layout.addWidget(self.score_findings)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        inventory_tab = QWidget()
        inventory_layout = QVBoxLayout(inventory_tab)
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(
            [
                "IP",
                "Hostname",
                "Vendor",
                "Type",
                "Services",
                "Risk",
                "Status",
                "First seen",
                "Last seen",
            ]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.currentCellChanged.connect(self._selection_changed)
        inventory_layout.addWidget(self.table, 3)

        self.detail_area = QTextEdit()
        self.detail_area.setReadOnly(True)
        self.detail_area.setPlaceholderText(
            "Selecciona un activo para ver su Device Profile y evidencia de clasificación."
        )
        inventory_layout.addWidget(self.detail_area, 2)

        action_row = QHBoxLayout()
        self.device_audit_button = QPushButton("Open device auditor")
        self.device_audit_button.setEnabled(False)
        self.device_audit_button.clicked.connect(self.open_selected_device_auditor)
        action_row.addWidget(self.device_audit_button)
        self.camera_button = QPushButton("Open in Camera Auditor")
        self.camera_button.setEnabled(False)
        self.camera_button.clicked.connect(self.open_selected_camera)
        action_row.addWidget(self.camera_button)
        refresh_button = QPushButton("Refresh inventory")
        refresh_button.clicked.connect(self.refresh_inventory)
        action_row.addWidget(refresh_button)
        action_row.addStretch(1)
        inventory_layout.addLayout(action_row)
        self.tabs.addTab(inventory_tab, "Asset Inventory")

        timeline_tab = QWidget()
        timeline_layout = QVBoxLayout(timeline_tab)
        self.timeline_table = QTableWidget(0, 4)
        self.timeline_table.setHorizontalHeaderLabels(["Time", "Event", "IP", "Details"])
        self.timeline_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.timeline_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        timeline_layout.addWidget(self.timeline_table)
        self.tabs.addTab(timeline_tab, "Network Timeline")

        self.setCentralWidget(root)
        self.refresh_inventory()

    def _active_scope(self) -> str:
        try:
            return parse_camera_scope(self.scope_input.text().strip()).with_prefixlen
        except ValueError:
            return self.scope_input.text().strip()

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
        if not isinstance(payload, dict):
            return
        message = payload.get("message")
        if message:
            self.status_label.setText(str(message))
        device = payload.get("device")
        if isinstance(device, NetworkIntelligenceDevice):
            self._upsert_device(device)
            try:
                self.inventory.record_device(self._active_scope(), device)
            except Exception as error:
                self.status_label.setText(f"Clasificado {device.host.ip}; inventario: {error}")
            self.refresh_inventory(keep_status=True)

    def _scan_finished(self, devices) -> None:
        self.devices = list(devices)
        scope = self._active_scope()
        try:
            self.inventory.record_scan(scope, self.devices, complete=True)
        except Exception as error:
            show_error(self, self.name, "No se pudo actualizar el inventario persistente.", error=error)
        self.refresh_inventory(keep_status=True)
        counts = {}
        for asset in self.assets:
            if not asset.is_online:
                continue
            counts[asset.kind.value] = counts.get(asset.kind.value, 0) + 1
        summary = ", ".join(f"{kind}: {count}" for kind, count in sorted(counts.items()))
        self.status_label.setText(
            f"Network Intelligence completado: {sum(counts.values())} activos online"
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
        self.refresh_inventory(keep_status=True)
        self.status_label.setText(
            "Network Intelligence cancelado. Los activos ya clasificados se conservan; "
            "no se marcan desapariciones en un escaneo incompleto."
        )

    def _worker_finished(self) -> None:
        self._set_running(False)
        self.worker = None

    def _upsert_device(self, device: NetworkIntelligenceDevice) -> None:
        for index, current in enumerate(self.devices):
            if current.host.ip == device.host.ip:
                self.devices[index] = device
                return
        self.devices.append(device)
        self.devices.sort(key=lambda item: ipaddress.ip_address(item.host.ip))

    def refresh_inventory(self, *, keep_status: bool = False) -> None:
        try:
            scope = self._active_scope()
            parse_camera_scope(scope)
            self.assets = self.inventory.list_assets(scope=scope)
            events = self.inventory.list_events(scope=scope, limit=250)
        except Exception as error:
            if not keep_status:
                self.status_label.setText(f"No se pudo cargar el inventario: {error}")
            return

        selected_id = self._selected_asset_id()
        self.table.setRowCount(len(self.assets))
        for row, asset in enumerate(self.assets):
            self._write_asset_row(row, asset)
            if asset.asset_id == selected_id:
                self.table.selectRow(row)

        self.timeline_table.setRowCount(len(events))
        for row, event in enumerate(events):
            values = (_format_time(event.created_at), event.summary, event.ip, event.details)
            for column, value in enumerate(values):
                self.timeline_table.setItem(row, column, QTableWidgetItem(str(value)))

        score = calculate_security_score(self.assets)
        self.score_label.setText(
            f"Network Security Score: {score.score}/100  ·  Devices {score.total_devices}  ·  "
            f"Unknown {score.unknown_devices}  ·  High {score.high_risk}  ·  "
            f"Medium {score.medium_risk}  ·  Low {score.low_risk}"
        )
        self.score_findings.setPlainText("\n".join(f"• {item}" for item in score.findings))
        self._selection_changed()

    def _write_asset_row(self, row: int, asset: AssetRecord) -> None:
        values = (
            asset.ip,
            asset.hostname,
            asset.vendor,
            asset.kind.value,
            " ".join(asset.services),
            asset.risk.value,
            "Online" if asset.is_online else "Offline",
            _format_time(asset.first_seen),
            _format_time(asset.last_seen),
        )
        for column, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            item.setData(Qt.UserRole, asset.asset_id)
            self.table.setItem(row, column, item)

    def _selected_asset_id(self) -> str | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        return item.data(Qt.UserRole)

    def _selected_asset(self) -> AssetRecord | None:
        selected_id = self._selected_asset_id()
        return next((asset for asset in self.assets if asset.asset_id == selected_id), None)

    def _selection_changed(self, *_args) -> None:
        asset = self._selected_asset()
        if asset is None:
            self.detail_area.clear()
            self.camera_button.setEnabled(False)
            self.device_audit_button.setEnabled(False)
            return

        lines = [
            asset.ip,
            asset.kind.value,
            "",
            f"Hostname      {asset.hostname}",
            f"MAC           {asset.mac}",
            f"Vendor        {asset.vendor}",
            f"First seen    {_format_time(asset.first_seen)}",
            f"Last seen     {_format_time(asset.last_seen)}",
            f"Last change   {_format_time(asset.last_change)}",
            f"Status        {'Online' if asset.is_online else 'Offline'}",
            "",
            "Services",
        ]
        if asset.services:
            for port, service in zip(asset.open_ports, asset.services):
                lines.append(f"✓ {service:<14} {port}")
        else:
            lines.append("No known services detected")
        lines.extend(["", "Risk", asset.risk.value, "", "Classification evidence"])
        lines.extend(f"• {item}" for item in asset.evidence)
        self.detail_area.setPlainText("\n".join(lines))
        self.device_audit_button.setEnabled(True)
        self.camera_button.setEnabled(asset.kind == DeviceKind.CAMERA and asset.is_online)

    def open_selected_device_auditor(self) -> None:
        asset = self._selected_asset()
        if asset is None:
            return
        window = DeviceAuditorDialog(asset, self)
        window.show()
        self._audit_windows.append(window)

    def open_selected_camera(self) -> None:
        asset = self._selected_asset()
        if asset is None or asset.kind != DeviceKind.CAMERA or not asset.is_online:
            return
        from pythonkni.camera_auditor.window import Tool as CameraAuditorTool

        window = CameraAuditorTool()
        window.scope_input.setText(f"{asset.ip}/32")
        window.show()
        window.start_audit()
        self._camera_windows.append(window)
