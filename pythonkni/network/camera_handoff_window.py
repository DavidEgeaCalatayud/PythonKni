from __future__ import annotations

import json
import sys as _sys
import types as _types
from dataclasses import asdict

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QComboBox, QFileDialog, QHBoxLayout, QLabel, QPushButton, QTabWidget

from pythonkni.infrastructure.paths import NETWORK_INTELLIGENCE_DB
from pythonkni.network_intelligence.inventory import InventoryStore

from . import fingerprinting as _fingerprinting
from . import service as _service
from . import window as _base
from .camera_handoff import CameraHandoffCandidate, match_persisted_cameras

HistoryTab = _base.HistoryTab
SCAN_HISTORY_FILE = _base.SCAN_HISTORY_FILE
fingerprint_open_ports = _fingerprinting.fingerprint_open_ports


def _fingerprint_label(result) -> str:
    identity = " ".join(part for part in (result.product, result.version) if part).strip()
    if identity:
        return f"{result.protocol} — {identity}"
    return result.protocol


class PortScanWorker(_base.PortScanWorker):
    results_ready = pyqtSignal(object)

    def run(self):
        total = self.end_port - self.start_port + 1
        checked = 0
        self.message.emit(
            f"Escaneando {total} puertos con hasta {_base.PORT_SCAN_WORKERS} conexiones concurrentes..."
        )

        def report_open(result):
            self.message.emit(f"ABIERTO  {result.port}/tcp  {result.service}")

        def report_checked(_port):
            nonlocal checked
            checked += 1

        try:
            results = _base.scan_open_ports(
                self.target,
                self.start_port,
                self.end_port,
                stop_event=self._stop_event,
                on_open=report_open,
                on_checked=report_checked,
            )
        except Exception as error:
            self.message.emit(f"No se pudo completar el escaneo de puertos de {self.target}.")
            self.failed.emit(error)
            self.finished_summary.emit(f"Escaneo de puertos fallido para {self.target}.")
            return

        self.results_ready.emit(results)
        rows = [f"{result.port}/tcp abierto ({result.service})" for result in results]
        if self._stop_event.is_set():
            summary = (
                f"[CANCELADO] Escaneo de puertos en {self.target} ({self.start_port}-{self.end_port}): "
                f"{checked} de {total} puertos comprobados; {len(results)} abiertos. "
                "Resultados parciales."
            )
            if rows:
                summary += "\n" + "\n".join(rows)
            self.message.emit("Escaneo cancelado. Los resultados mostrados son parciales.")
            self.cancelled.emit(summary)
            self.finished_summary.emit(summary)
            return

        if rows:
            summary = (
                f"Puertos abiertos en {self.target} ({self.start_port}-{self.end_port}):\n"
                + "\n".join(rows)
            )
        else:
            summary = (
                f"Escaneo de {self.target} ({self.start_port}-{self.end_port}): "
                "no se encontraron puertos abiertos."
            )

        self.message.emit(
            f"Escaneo completado: {len(results)} puertos abiertos de {checked} comprobados.\n"
        )
        self.finished_summary.emit(summary)


class FingerprintWorker(_base.QThread):
    message = pyqtSignal(str)
    finished_summary = pyqtSignal(str)
    cancelled = pyqtSignal(str)
    failed = pyqtSignal(object)
    results_ready = pyqtSignal(object)

    def __init__(self, target: str, open_ports):
        super().__init__()
        self.target = target
        self.open_ports = tuple(open_ports)
        self._stop_event = _base.threading.Event()

    def stop(self):
        self._stop_event.set()

    def run(self):
        self.message.emit(
            f"Identificando servicios de aplicación en {len(self.open_ports)} puerto(s) abierto(s) "
            "con Nerva verificado..."
        )

        def report_found(result):
            self.message.emit(
                f"IDENTIFICADO  {result.port}/{result.transport}  {_fingerprint_label(result)}"
            )

        try:
            results = fingerprint_open_ports(
                self.target,
                self.open_ports,
                stop_event=self._stop_event,
                on_found=report_found,
            )
        except Exception as error:
            self.message.emit(f"No se pudo completar el fingerprinting de {self.target}.")
            self.failed.emit(error)
            self.finished_summary.emit(f"Fingerprinting de servicios fallido para {self.target}.")
            return

        self.results_ready.emit(results)
        rows = [
            f"{result.port}/{result.transport}: {_fingerprint_label(result)}" for result in results
        ]
        if self._stop_event.is_set():
            summary = (
                f"[CANCELADO] Fingerprinting en {self.target}: {len(results)} servicio(s) "
                "identificado(s). Resultados parciales."
            )
            if rows:
                summary += "\n" + "\n".join(rows)
            self.message.emit("Fingerprinting cancelado. Los resultados mostrados son parciales.")
            self.cancelled.emit(summary)
            self.finished_summary.emit(summary)
            return

        if rows:
            summary = f"Servicios identificados en {self.target}:\n" + "\n".join(rows)
        else:
            summary = (
                f"Fingerprinting de {self.target}: Nerva no identificó un protocolo compatible "
                "en los puertos abiertos seleccionados."
            )
        self.message.emit(
            f"Fingerprinting completado: {len(results)} servicio(s) identificado(s) sobre "
            f"{len(self.open_ports)} puerto(s) abierto(s).\n"
        )
        self.finished_summary.emit(summary)


class PortScanner(_base.PortScanner):
    fingerprints_ready = pyqtSignal(object)

    def __init__(self, history_tab):
        self.open_ports = ()
        self.fingerprints = ()
        super().__init__(history_tab)

        self.layout().addWidget(
            QLabel(
                "Fingerprinting opcional: identifica el protocolo real únicamente en los puertos "
                "que el escáner ya confirmó abiertos."
            )
        )
        self.fingerprint_button = QPushButton("Identificar servicios (Nerva)")
        self.fingerprint_button.setEnabled(False)
        self.fingerprint_button.clicked.connect(self.fingerprint_services)
        self.layout().addWidget(self.fingerprint_button)

        self.export_fingerprints_button = QPushButton("Exportar fingerprints JSON")
        self.export_fingerprints_button.setEnabled(False)
        self.export_fingerprints_button.clicked.connect(self.export_fingerprints)
        self.layout().addWidget(self.export_fingerprints_button)

    def _set_running(self, running: bool):
        super()._set_running(running)
        self.fingerprint_button.setEnabled(not running and bool(self.open_ports))
        self.export_fingerprints_button.setEnabled(not running and bool(self.fingerprints))

    def _remember_open_ports(self, results) -> None:
        self.open_ports = tuple(results)
        self.fingerprints = ()
        self.fingerprint_button.setEnabled(False)
        self.export_fingerprints_button.setEnabled(False)

    def _remember_fingerprints(self, results) -> None:
        self.fingerprints = tuple(results)
        self.fingerprints_ready.emit(self.fingerprints)

    def _fingerprint_failed(self, error):
        _base._show_exception(
            self,
            "Fingerprinting de servicios",
            "No se pudo completar la identificación de servicios. Nerva es un motor opcional y "
            "nunca se descarga automáticamente durante el uso de la aplicación.",
            error,
        )

    def scan_ports(self):
        if self.worker and self.worker.isRunning():
            return

        target = self.ip_input.text().strip()
        port_range = self.port_range_input.text().strip()

        if not target:
            self.result_area.append("Error: Debes ingresar una dirección IP o dominio.\n")
            return
        if not port_range:
            self.result_area.append("Error: Debes ingresar un rango de puertos.\n")
            return

        try:
            start_port, end_port = _base.validate_port_range(port_range)
        except ValueError as error:
            self.result_area.append(f"Error: {error}\n")
            return

        self.open_ports = ()
        self.fingerprints = ()
        self.result_area.clear()
        self.result_area.append(f"Escaneando {target} ({start_port}-{end_port})...\n")
        self.worker = PortScanWorker(target, start_port, end_port)
        self.worker.message.connect(self.result_area.append)
        self.worker.failed.connect(self._scan_failed)
        self.worker.results_ready.connect(self._remember_open_ports)
        self.worker.finished_summary.connect(self.history_tab.append_to_history)
        self.worker.finished.connect(self._worker_finished)
        self._set_running(True)
        self.worker.start()

    def fingerprint_services(self):
        if self.worker and self.worker.isRunning():
            return
        if not self.open_ports:
            self.result_area.append(
                "No hay puertos abiertos confirmados para identificar. Ejecuta primero el escaneo de puertos."
            )
            return

        target = self.ip_input.text().strip()
        if not target:
            return
        self.fingerprints = ()
        self.result_area.append("\n--- Fingerprinting de servicios ---")
        self.worker = FingerprintWorker(target, self.open_ports)
        self.worker.message.connect(self.result_area.append)
        self.worker.failed.connect(self._fingerprint_failed)
        self.worker.results_ready.connect(self._remember_fingerprints)
        self.worker.finished_summary.connect(self.history_tab.append_to_history)
        self.worker.finished.connect(self._worker_finished)
        self._set_running(True)
        self.worker.start()

    def export_fingerprints(self):
        if not self.fingerprints:
            return
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar fingerprints",
            "service-fingerprints.json",
            "Archivos JSON (*.json)",
        )
        if not file_path:
            return
        try:
            with open(file_path, "w", encoding="utf-8") as file:
                json.dump(
                    [asdict(item) for item in self.fingerprints],
                    file,
                    ensure_ascii=False,
                    indent=2,
                )
        except Exception as error:
            _base._show_exception(
                self,
                "Exportar fingerprints",
                "No se pudieron exportar los fingerprints de servicios.",
                error,
            )
            return
        self.result_area.append(f"Fingerprints exportados a: {file_path}")


class NetworkScanWorker(_base.NetworkScanWorker):
    results_ready = pyqtSignal(object)

    def run(self):
        checked = 0
        try:
            network = _base.parse_network_cidr(self.cidr)
            self.message.emit(
                f"Escaneando {network.with_prefixlen} con hasta {_base.NETWORK_SCAN_WORKERS} tareas concurrentes.\n"
            )

            def report_found(host):
                self.message.emit(
                    f"Dispositivo: {host.ip} - Hostname: {host.hostname} - MAC: {host.mac}"
                )

            def report_checked(_ip):
                nonlocal checked
                checked += 1

            found_devices = _base.scan_network_hosts(
                network.with_prefixlen,
                stop_event=self._stop_event,
                on_found=report_found,
                on_checked=report_checked,
            )
        except Exception as error:
            self.message.emit("No se pudo completar el escaneo de red.\n")
            self.failed.emit(error)
            self.finished_summary.emit("Escaneo de red fallido.")
            return

        rows = [
            f"{host.ip} - Hostname: {host.hostname} - MAC: {host.mac}" for host in found_devices
        ]
        if self._stop_event.is_set():
            summary = (
                f"[CANCELADO] Escaneo de {network.with_prefixlen}: {checked} hosts comprobados; "
                f"{len(found_devices)} encontrados. Resultados parciales."
            )
            if rows:
                summary += "\n" + "\n".join(rows)
            self.message.emit("Escaneo cancelado. Los resultados mostrados son parciales.\n")
            self.cancelled.emit(summary)
            self.finished_summary.emit(summary)
            return

        if rows:
            summary = f"Escaneo de {network.with_prefixlen}:\n" + "\n".join(rows)
        else:
            summary = f"Escaneo de {network.with_prefixlen}: no se encontraron dispositivos."

        self.results_ready.emit(found_devices)
        self.message.emit("Exploración completada.\n")
        self.finished_summary.emit(summary)


class NetworkScanner(_base.NetworkScanner):
    def __init__(self, history_tab):
        super().__init__(history_tab)
        self.camera_candidates: tuple[CameraHandoffCandidate, ...] = ()
        self._camera_windows = []

        handoff_row = QHBoxLayout()
        handoff_row.addWidget(QLabel("Network Intelligence cameras:"))
        self.camera_combo = QComboBox()
        self.camera_combo.setEnabled(False)
        handoff_row.addWidget(self.camera_combo, 1)
        self.camera_button = QPushButton("Open in Camera Auditor")
        self.camera_button.setEnabled(False)
        self.camera_button.clicked.connect(self.open_selected_camera)
        handoff_row.addWidget(self.camera_button)
        self.layout().addLayout(handoff_row)

    def _set_camera_candidates(
        self, candidates: tuple[CameraHandoffCandidate, ...] | list[CameraHandoffCandidate]
    ) -> None:
        self.camera_candidates = tuple(candidates)
        self.camera_combo.clear()
        for candidate in self.camera_candidates:
            self.camera_combo.addItem(candidate.label, candidate.ip)
        enabled = bool(self.camera_candidates)
        self.camera_combo.setEnabled(enabled)
        self.camera_button.setEnabled(enabled)

    def _load_inventory_assets(self, scope: str):
        return InventoryStore(NETWORK_INTELLIGENCE_DB).list_assets(scope=scope)

    def _scan_results_ready(self, hosts) -> None:
        try:
            scope = _base.parse_network_cidr(self.cidr_input.text().strip()).with_prefixlen
            assets = self._load_inventory_assets(scope)
            candidates = match_persisted_cameras(scope, list(hosts), assets)
        except Exception as error:
            self._set_camera_candidates(())
            self.result_area.append(
                f"Network Intelligence inventory unavailable for camera handoff: {error}"
            )
            return

        self._set_camera_candidates(candidates)
        if candidates:
            self.result_area.append(
                f"Network Intelligence: {len(candidates)} persisted camera(s) matched current discovery."
            )
        else:
            self.result_area.append(
                "Network Intelligence: no currently discovered host matched a persisted Camera identity."
            )

    def scan_network(self):
        if self.worker and self.worker.isRunning():
            return

        cidr = self.cidr_input.text().strip()
        try:
            network = _base.parse_network_cidr(cidr)
        except ValueError as error:
            self.result_area.append(f"Error: {error}\n")
            return

        self._set_camera_candidates(())
        self.result_area.clear()
        self.result_area.append(f"Escaneando {network.with_prefixlen}...\n")
        self.worker = NetworkScanWorker(network.with_prefixlen)
        self.worker.message.connect(self.result_area.append)
        self.worker.failed.connect(self._scan_failed)
        self.worker.results_ready.connect(self._scan_results_ready)
        self.worker.finished_summary.connect(self.history_tab.append_to_history)
        self.worker.finished.connect(self._worker_finished)
        self._set_running(True)
        self.worker.start()

    def open_selected_camera(self) -> None:
        ip = self.camera_combo.currentData()
        if not ip:
            return
        from pythonkni.camera_auditor.window import Tool as CameraAuditorTool

        window = CameraAuditorTool()
        window.scope_input.setText(f"{ip}/32")
        window.show()
        window.start_audit()
        self._camera_windows.append(window)


class Tool(_base.Tool):
    def setup_ui(self):
        self.setWindowTitle(self.name)
        self.setGeometry(200, 200, 800, 600)
        self._close_when_workers_finish = False

        self.history_tab = HistoryTab()
        self.network_scanner = NetworkScanner(self.history_tab)
        self.port_scanner = PortScanner(self.history_tab)

        tabs = QTabWidget()
        tabs.addTab(self.network_scanner, "Escáner de Red")
        tabs.addTab(self.port_scanner, "Escáner de Puertos")
        tabs.addTab(self.history_tab, "Histórico")
        self.setCentralWidget(tabs)


class _CompatibilityModule(_types.ModuleType):
    def __setattr__(self, name, value):
        if hasattr(_service, name):
            setattr(_service, name, value)
        if hasattr(_base, name):
            setattr(_base, name, value)
        super().__setattr__(name, value)

    def __delattr__(self, name):
        if hasattr(_service, name):
            delattr(_service, name)
        if hasattr(_base, name):
            delattr(_base, name)
        super().__delattr__(name)


_sys.modules[__name__].__class__ = _CompatibilityModule
