from __future__ import annotations

import csv
import ipaddress
import json
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGroupBox,
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

from pythonkni.infrastructure.paths import CAMERA_REPORTS_DIR, ensure_app_dirs
from pythonkni.network.service import detect_default_network
from tools.base_tool import BaseTool
from tools.csv_utils import safe_csv_cell
from tools.ui_feedback import UserFeedback, show_error, show_feedback, show_warning
from tools.worker import Worker

from .models import AuditProgress, CameraDevice, CameraServiceFinding
from .service import MAX_CAMERA_HOSTS, audit_camera_exposure, parse_camera_scope


def _default_scope() -> str:
    try:
        interface = detect_default_network()
        network = ipaddress.ip_network(interface.cidr, strict=False)
        if network.num_addresses > MAX_CAMERA_HOSTS:
            network = ipaddress.ip_network(f"{interface.address}/24", strict=False)
        parse_camera_scope(network.with_prefixlen)
        return network.with_prefixlen
    except (RuntimeError, ValueError):
        return "192.168.1.0/24"


def _auth_label(value: bool | None) -> str:
    if value is True:
        return "Requerida"
    if value is False:
        return "No requerida"
    return "No determinada"


def _service_to_dict(finding: CameraServiceFinding) -> dict[str, object]:
    return {
        "protocol": finding.protocol,
        "port": finding.port,
        "endpoint": finding.endpoint,
        "status": finding.status,
        "auth_required": finding.auth_required,
        "cleartext": finding.cleartext,
        "evidence": finding.evidence,
    }


def _device_to_dict(device: CameraDevice) -> dict[str, object]:
    return {
        "ip": device.ip,
        "vendor": device.vendor,
        "name": device.name,
        "hardware": device.hardware,
        "services": [_service_to_dict(item) for item in device.services],
        "onvif": device.onvif,
        "confidence": device.confidence,
        "risk": device.risk.value,
        "risk_reasons": list(device.risk_reasons),
        "onvif_scopes": list(device.onvif_scopes),
        "onvif_xaddrs": list(device.onvif_xaddrs),
    }


def _device_report(device: CameraDevice) -> str:
    lines = [
        f"IP: {device.ip}",
        f"Vendor: {device.vendor}",
        f"Name: {device.name or 'No anunciado'}",
        f"Hardware: {device.hardware or 'No anunciado'}",
        f"Confidence: {device.confidence}",
        f"Risk: {device.risk.value}",
        f"ONVIF: {'Sí' if device.onvif else 'No'}",
        "",
        "Servicios:",
    ]
    for service in device.services:
        lines.extend(
            [
                f"- {service.protocol} :{service.port}",
                f"  Estado: {service.status or 'Detectado'}",
                f"  Autenticación: {_auth_label(service.auth_required)}",
                f"  Transporte claro: {'Sí' if service.cleartext else 'No'}",
                f"  Endpoint: {service.endpoint or 'No anunciado'}",
            ]
        )
        if service.evidence:
            lines.append(f"  Evidencia: {service.evidence}")
    lines.extend(["", "Clasificación:"])
    lines.extend(f"- {reason}" for reason in device.risk_reasons)
    if device.onvif_xaddrs:
        lines.extend(["", "ONVIF XAddrs:"])
        lines.extend(f"- {value}" for value in device.onvif_xaddrs)
    return "\n".join(lines)


def _run_audit(worker: Worker, scope: str, protocols: tuple[str, ...]):
    return audit_camera_exposure(
        scope,
        protocols,
        stop_event=worker.cancel_event,
        on_progress=worker.report_progress,
    )


class Tool(BaseTool):
    name = "Camera Exposure Auditor"
    description = "Descubre cámaras IP locales y evalúa exposición HTTP, HTTPS, RTSP y ONVIF."
    category = "Red"

    def setup_ui(self) -> None:
        ensure_app_dirs()
        CAMERA_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        self.setWindowTitle(self.name)
        self.setGeometry(180, 120, 1050, 720)
        self.worker: Worker | None = None
        self.devices: list[CameraDevice] = []

        root = QWidget()
        layout = QVBoxLayout(root)

        scope_row = QHBoxLayout()
        scope_row.addWidget(QLabel("Scope:"))
        self.scope_input = QLineEdit(_default_scope())
        self.scope_input.setPlaceholderText("192.168.1.0/24")
        scope_row.addWidget(self.scope_input)
        self.discover_button = QPushButton("Discover")
        self.discover_button.clicked.connect(self.start_audit)
        scope_row.addWidget(self.discover_button)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_audit)
        scope_row.addWidget(self.stop_button)
        layout.addLayout(scope_row)

        protocol_group = QGroupBox("Protocols")
        protocol_layout = QHBoxLayout(protocol_group)
        self.protocol_checks = {}
        for protocol in ("HTTP", "HTTPS", "RTSP", "ONVIF"):
            check = QCheckBox(protocol)
            check.setChecked(True)
            self.protocol_checks[protocol] = check
            protocol_layout.addWidget(check)
        protocol_layout.addStretch(1)
        layout.addWidget(protocol_group)

        self.status_label = QLabel(
            "Solo se auditan rangos locales permitidos; no se prueban contraseñas ni credenciales."
        )
        layout.addWidget(self.status_label)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["IP", "Vendor", "Services", "Confidence", "Risk"])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.currentCellChanged.connect(self._selection_changed)
        layout.addWidget(self.table, 3)

        detail_group = QGroupBox("Selected device")
        detail_layout = QVBoxLayout(detail_group)
        self.detail_area = QTextEdit()
        self.detail_area.setReadOnly(True)
        self.detail_area.setPlaceholderText("Selecciona un dispositivo para ver la evidencia.")
        detail_layout.addWidget(self.detail_area)

        action_row = QHBoxLayout()
        self.report_button = QPushButton("Detailed report")
        self.report_button.clicked.connect(self.show_detailed_report)
        self.report_button.setEnabled(False)
        action_row.addWidget(self.report_button)
        self.export_button = QPushButton("Export")
        self.export_button.clicked.connect(self.export_results)
        self.export_button.setEnabled(False)
        action_row.addWidget(self.export_button)
        action_row.addStretch(1)
        detail_layout.addLayout(action_row)
        layout.addWidget(detail_group, 2)

        self.setCentralWidget(root)

    def _selected_protocols(self) -> tuple[str, ...]:
        return tuple(
            protocol for protocol, check in self.protocol_checks.items() if check.isChecked()
        )

    def _set_running(self, running: bool) -> None:
        self.discover_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.scope_input.setEnabled(not running)
        for check in self.protocol_checks.values():
            check.setEnabled(not running)

    def start_audit(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        scope = self.scope_input.text().strip()
        protocols = self._selected_protocols()
        try:
            network = parse_camera_scope(scope)
            if not protocols:
                raise ValueError("Selecciona al menos un protocolo.")
        except ValueError as error:
            show_warning(self, "Camera Exposure Auditor", str(error))
            return

        self.devices = []
        self.table.setRowCount(0)
        self.detail_area.clear()
        self.report_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self.status_label.setText(
            f"Auditando {network.with_prefixlen} con un máximo de {MAX_CAMERA_HOSTS} hosts..."
        )
        self._set_running(True)

        worker = Worker(_run_audit, network.with_prefixlen, protocols, parent=self)
        worker.progress.connect(self._handle_progress)
        worker.result.connect(self._audit_finished)
        worker.error.connect(self._audit_failed)
        worker.cancelled.connect(self._audit_cancelled)
        worker.finished.connect(self._worker_finished)
        self.worker = worker
        self.start_managed_worker(worker, cancel=worker.cancel)

    def stop_audit(self) -> None:
        if self.worker is None or not self.worker.isRunning():
            return
        self.stop_button.setEnabled(False)
        self.status_label.setText("Cancelando auditoría de forma cooperativa...")
        self.worker.cancel()

    def _handle_progress(self, progress: AuditProgress) -> None:
        if progress.kind == "status" and progress.message:
            self.status_label.setText(progress.message)
            return
        if progress.device is not None:
            self._upsert_device(progress.device)
        self.status_label.setText(
            f"Comprobados {progress.checked}/{progress.total} hosts; "
            f"{len(self.devices)} candidatos identificados."
        )

    def _upsert_device(self, device: CameraDevice) -> None:
        for index, current in enumerate(self.devices):
            if current.ip == device.ip:
                self.devices[index] = device
                self._write_row(index, device)
                return
        self.devices.append(device)
        self.devices.sort(key=lambda item: ipaddress.ip_address(item.ip))
        self._rebuild_table()

    def _write_row(self, row: int, device: CameraDevice) -> None:
        values = (
            device.ip,
            device.vendor,
            " ".join(device.service_labels),
            device.confidence,
            device.risk.value,
        )
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setData(Qt.UserRole, device.ip)
            self.table.setItem(row, column, item)

    def _rebuild_table(self) -> None:
        selected_ip = self._selected_ip()
        self.table.setRowCount(len(self.devices))
        for row, device in enumerate(self.devices):
            self._write_row(row, device)
            if selected_ip == device.ip:
                self.table.selectRow(row)
        self.export_button.setEnabled(bool(self.devices))

    def _audit_finished(self, devices: list[CameraDevice]) -> None:
        self.devices = list(devices)
        self._rebuild_table()
        self.status_label.setText(
            f"Auditoría completada: {len(self.devices)} candidatos de cámara identificados."
        )

    def _audit_cancelled(self) -> None:
        self.status_label.setText(
            f"Auditoría cancelada. Se conservan {len(self.devices)} resultados parciales visibles."
        )
        self.export_button.setEnabled(bool(self.devices))

    def _audit_failed(self, error) -> None:
        show_error(
            self,
            "Camera Exposure Auditor",
            "No se pudo completar la auditoría de cámaras.",
            error=error if isinstance(error, BaseException) else None,
            details=None if isinstance(error, BaseException) else str(error),
        )
        self.status_label.setText("La auditoría finalizó con error.")

    def _worker_finished(self) -> None:
        self._set_running(False)
        self.worker = None

    def _selected_ip(self) -> str | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        return item.data(Qt.UserRole) or item.text()

    def _selected_device(self) -> CameraDevice | None:
        selected_ip = self._selected_ip()
        return next((device for device in self.devices if device.ip == selected_ip), None)

    def _selection_changed(self, *_args) -> None:
        device = self._selected_device()
        if device is None:
            self.detail_area.clear()
            self.report_button.setEnabled(False)
            return
        self.detail_area.setPlainText(_device_report(device))
        self.report_button.setEnabled(True)

    def show_detailed_report(self) -> None:
        device = self._selected_device()
        if device is None:
            return
        show_feedback(
            self,
            UserFeedback.information(
                f"Camera report — {device.ip}",
                f"{device.vendor} · riesgo {device.risk.value} · confianza {device.confidence}",
                details=json.dumps(_device_to_dict(device), indent=2, ensure_ascii=False),
            ),
        )

    def export_results(self) -> None:
        if not self.devices:
            show_warning(self, "Camera Exposure Auditor", "No hay resultados para exportar.")
            return
        ensure_app_dirs()
        CAMERA_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        suggested = str(CAMERA_REPORTS_DIR / "camera_exposure_audit.json")
        file_path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Exportar auditoría",
            suggested,
            "JSON (*.json);;CSV (*.csv)",
        )
        if not file_path:
            return
        path = Path(file_path)
        if not path.suffix:
            path = path.with_suffix(".csv" if "CSV" in selected_filter else ".json")
        try:
            if path.suffix.lower() == ".json":
                data = [_device_to_dict(item) for item in self.devices]
                path.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
            elif path.suffix.lower() == ".csv":
                with path.open("w", newline="", encoding="utf-8") as handle:
                    writer = csv.writer(handle)
                    writer.writerow(["ip", "vendor", "services", "confidence", "risk", "reasons"])
                    for device in self.devices:
                        writer.writerow(
                            [
                                safe_csv_cell(device.ip),
                                safe_csv_cell(device.vendor),
                                safe_csv_cell(" ".join(device.service_labels)),
                                safe_csv_cell(device.confidence),
                                safe_csv_cell(device.risk.value),
                                safe_csv_cell(" | ".join(device.risk_reasons)),
                            ]
                        )
            else:
                raise ValueError("Formato de exportación no compatible. Usa JSON o CSV.")
        except Exception as error:
            show_error(
                self,
                "Camera Exposure Auditor",
                "No se pudieron exportar los resultados.",
                error=error,
            )
            return
        self.status_label.setText(f"Resultados exportados a {path}.")
