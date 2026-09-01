from __future__ import annotations

import ipaddress

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QFileDialog,
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
from .models import AssetRecord, DeviceKind, NetworkIntelligenceDevice, NetworkRelationship
from .physical_import import load_physical_snapshot_file
from .relationship_store import RelationshipStore
from .relationships import build_relationships, discover_default_gateway
from .score import calculate_security_score
from .service import analyze_hosts
from .topology_view import NetworkTopologyView


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

    devices = analyze_hosts(
        scope,
        found,
        stop_event=worker.cancel_event,
        on_device=on_device,
        on_checked=on_classified,
    )
    worker.check_cancelled()
    gateway_ip = discover_default_gateway()
    worker.check_cancelled()
    return {"devices": devices, "gateway_ip": gateway_ip}


def _format_time(value) -> str:
    return value.astimezone().strftime("%d/%m/%Y %H:%M:%S")


def _asset_profile_text(asset: AssetRecord) -> str:
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
    return "\n".join(lines)


class Tool(BaseTool):
    name = "Network Intelligence"
    description = (
        "Mantiene un inventario persistente de activos locales, clasifica dispositivos, "
        "calcula exposición, conserva relaciones con evidencia y registra cambios entre escaneos."
    )
    category = "Network Intelligence"

    def setup_ui(self) -> None:
        self.setWindowTitle(self.name)
        self.setGeometry(120, 70, 1260, 820)
        self.worker: Worker | None = None
        self.devices: list[NetworkIntelligenceDevice] = []
        self.assets: list[AssetRecord] = []
        self.relationships: list[NetworkRelationship] = []
        self.inventory = InventoryStore(NETWORK_INTELLIGENCE_DB)
        self.relationship_store = RelationshipStore(NETWORK_INTELLIGENCE_DB)
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
            "Network Intelligence conserva activos, relaciones y cambios entre ejecuciones. "
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

        topology_tab = QWidget()
        topology_layout = QVBoxLayout(topology_tab)
        self.topology_note = QLabel()
        self.topology_note.setWordWrap(True)
        topology_layout.addWidget(self.topology_note)
        self.topology_view = NetworkTopologyView()
        self.topology_view.asset_selected.connect(self._topology_asset_selected)
        topology_layout.addWidget(self.topology_view, 3)
        self.topology_detail = QTextEdit()
        self.topology_detail.setReadOnly(True)
        self.topology_detail.setMaximumHeight(190)
        self.topology_detail.setPlaceholderText(
            "Pulsa un activo del mapa para ver su Device Profile."
        )
        topology_layout.addWidget(self.topology_detail, 1)
        self.tabs.addTab(topology_tab, "Network Topology")

        relationships_tab = QWidget()
        relationships_layout = QVBoxLayout(relationships_tab)
        relationship_help = QLabel(
            "Solid = CONFIRMED · dashed = INFERRED · dotted = UNKNOWN. "
            "Las relaciones lógicas se descubren automáticamente; los enlaces físicos solo se "
            "aceptan desde snapshots administrativos LLDP/MAC-table validados contra el inventario."
        )
        relationship_help.setWordWrap(True)
        relationships_layout.addWidget(relationship_help)
        relationship_actions = QHBoxLayout()
        self.import_physical_button = QPushButton("Import LLDP/MAC snapshot...")
        self.import_physical_button.clicked.connect(self.import_physical_evidence)
        relationship_actions.addWidget(self.import_physical_button)
        relationship_actions.addStretch(1)
        relationships_layout.addLayout(relationship_actions)
        self.relationship_table = QTableWidget(0, 9)
        self.relationship_table.setHorizontalHeaderLabels(
            [
                "Confidence",
                "Kind",
                "Protocol",
                "Source",
                "Source port",
                "Target",
                "Target port",
                "Observed",
                "Evidence",
            ]
        )
        self.relationship_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.relationship_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        relationships_layout.addWidget(self.relationship_table)
        self.tabs.addTab(relationships_tab, "Relationship Evidence")

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
        self.import_physical_button.setEnabled(not running)

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

    def import_physical_evidence(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Import physical network evidence",
            "",
            "JSON files (*.json);;All files (*)",
        )
        if not path:
            return

        scope = self._active_scope()
        try:
            parse_camera_scope(scope)
            current_assets = self.inventory.list_assets(scope=scope)
            result = load_physical_snapshot_file(path, current_assets, expected_scope=scope)
        except (OSError, ValueError) as error:
            show_error(
                self,
                self.name,
                "No se pudo cargar el snapshot de evidencia física.",
                error=error,
            )
            return

        if result.warnings:
            show_warning(
                self,
                self.name,
                "El snapshot contiene enlaces que no se pueden validar. "
                "La evidencia física anterior se conserva sin cambios.",
                details="\n".join(result.warnings),
            )
            self.status_label.setText(
                "Importación física rechazada: el snapshot anterior se conserva íntegro."
            )
            return

        try:
            self.relationship_store.replace_physical(scope, list(result.relationships))
        except Exception as error:
            show_error(
                self,
                self.name,
                "El snapshot es válido, pero no se pudo persistir la evidencia física.",
                error=error,
            )
            return

        self.refresh_inventory(keep_status=True)
        self.status_label.setText(
            f"Evidencia física importada: {result.imported_count} enlace(s) para {result.scope}."
        )

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

    def _scan_finished(self, result) -> bool:
        if isinstance(result, dict):
            devices = result.get("devices", [])
            gateway_ip = result.get("gateway_ip")
        else:
            devices = result
            gateway_ip = None
        self.devices = list(devices)
        scope = self._active_scope()
        persistence_ok = True
        try:
            self.inventory.record_scan(scope, self.devices, complete=True)
        except Exception as error:
            persistence_ok = False
            show_error(
                self, self.name, "No se pudo actualizar el inventario persistente.", error=error
            )

        if persistence_ok:
            try:
                current_assets = self.inventory.list_assets(scope=scope)
                relationships = build_relationships(scope, current_assets, gateway_ip=gateway_ip)
                self.relationship_store.replace_logical(scope, relationships)
            except Exception as error:
                persistence_ok = False
                show_error(
                    self,
                    self.name,
                    "El inventario se guardó, pero no se pudo actualizar la evidencia de relaciones.",
                    error=error,
                )

        self.refresh_inventory(keep_status=True)
        counts = {}
        for asset in self.assets:
            if not asset.is_online:
                continue
            counts[asset.kind.value] = counts.get(asset.kind.value, 0) + 1
        summary = ", ".join(f"{kind}: {count}" for kind, count in sorted(counts.items()))
        gateway_summary = f" · gateway {gateway_ip}" if gateway_ip else " · gateway no confirmado"
        persistence_summary = "" if persistence_ok else " · persistencia incompleta"
        self.status_label.setText(
            f"Network Intelligence completado: {sum(counts.values())} activos online"
            + (f" · {summary}" if summary else "")
            + gateway_summary
            + persistence_summary
        )
        return persistence_ok

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
            "no se marcan desapariciones ni se reemplaza la evidencia de relaciones con un escaneo incompleto."
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
            self.relationships = self.relationship_store.list(scope=scope)
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

        self._render_relationships()
        self.topology_view.set_assets(self.assets, self.relationships or None)
        if self.topology_view.graph is not None:
            confirmed = sum(
                relationship.confidence.value == "CONFIRMED" for relationship in self.relationships
            )
            inferred = sum(
                relationship.confidence.value == "INFERRED" for relationship in self.relationships
            )
            unknown = sum(
                relationship.confidence.value == "UNKNOWN" for relationship in self.relationships
            )
            relationship_summary = (
                f"relationships: {confirmed} confirmed, {inferred} inferred, {unknown} unknown. "
                if self.relationships
                else "No persisted relationship snapshot yet; conservative inventory fallback. "
            )
            self.topology_note.setText(
                "Network topology · "
                f"{len(self.assets)} persisted asset(s) · {relationship_summary}"
                f"{self.topology_view.graph.note}"
            )

        score = calculate_security_score(self.assets)
        self.score_label.setText(
            f"Network Security Score: {score.score}/100  ·  Devices {score.total_devices}  ·  "
            f"Unknown {score.unknown_devices}  ·  High {score.high_risk}  ·  "
            f"Medium {score.medium_risk}  ·  Low {score.low_risk}"
        )
        self.score_findings.setPlainText("\n".join(f"• {item}" for item in score.findings))
        self._selection_changed()
        selected_asset = self._selected_asset()
        self.topology_detail.setPlainText(
            _asset_profile_text(selected_asset) if selected_asset is not None else ""
        )

    def _relationship_endpoint_text(self, endpoint_id: str) -> str:
        if endpoint_id == "synthetic:internet":
            return "Internet / WAN"
        if endpoint_id.startswith("synthetic:lan:"):
            return f"LAN {endpoint_id.removeprefix('synthetic:lan:')}"
        asset = next((item for item in self.assets if item.asset_id == endpoint_id), None)
        if asset is None:
            return endpoint_id
        label = (
            asset.hostname if asset.hostname and asset.hostname != "Unknown" else asset.kind.value
        )
        return f"{label} ({asset.ip})"

    def _render_relationships(self) -> None:
        self.relationship_table.setRowCount(len(self.relationships))
        for row, relationship in enumerate(self.relationships):
            values = (
                relationship.confidence.value,
                relationship.kind.value,
                relationship.protocol or "—",
                self._relationship_endpoint_text(relationship.source_id),
                relationship.source_port or "—",
                self._relationship_endpoint_text(relationship.target_id),
                relationship.target_port or "—",
                _format_time(relationship.observed_at),
                "; ".join(relationship.evidence),
            )
            for column, value in enumerate(values):
                self.relationship_table.setItem(row, column, QTableWidgetItem(str(value)))

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

        self.detail_area.setPlainText(_asset_profile_text(asset))
        self.device_audit_button.setEnabled(True)
        self.camera_button.setEnabled(asset.kind == DeviceKind.CAMERA and asset.is_online)

    def _topology_asset_selected(self, asset_id: str) -> None:
        asset = next((item for item in self.assets if item.asset_id == asset_id), None)
        if asset is None:
            self.topology_detail.clear()
            return
        self.topology_detail.setPlainText(_asset_profile_text(asset))
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None and item.data(Qt.UserRole) == asset_id:
                self.table.selectRow(row)
                self.table.scrollToItem(item)
                break

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
