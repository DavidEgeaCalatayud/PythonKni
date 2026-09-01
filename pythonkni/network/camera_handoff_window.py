from __future__ import annotations

import sys as _sys
import types as _types

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QTabWidget

from pythonkni.infrastructure.paths import NETWORK_INTELLIGENCE_DB
from pythonkni.network_intelligence.inventory import InventoryStore

from . import window as _base
from .camera_handoff import CameraHandoffCandidate, match_persisted_cameras

HistoryTab = _base.HistoryTab
PortScanner = _base.PortScanner
PortScanWorker = _base.PortScanWorker
SCAN_HISTORY_FILE = _base.SCAN_HISTORY_FILE


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
        if hasattr(_base, name):
            setattr(_base, name, value)
        super().__setattr__(name, value)

    def __delattr__(self, name):
        if hasattr(_base, name):
            delattr(_base, name)
        super().__delattr__(name)


_sys.modules[__name__].__class__ = _CompatibilityModule
