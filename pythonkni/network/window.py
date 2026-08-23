from __future__ import annotations
from tools.base_tool import BaseTool
from tools.csv_utils import safe_csv_cell
import csv
import ipaddress
import json
import logging
import platform
import re
import socket
import subprocess
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
import psutil
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from tools.app_paths import SCAN_HISTORY_FILE, ensure_app_dirs
from .service import (
    COMMON_TCP_SERVICES,
    DEFAULT_ROUTE_PROBE,
    DiscoveredHost,
    MAC_PATTERN,
    MAX_NETWORK_HOSTS,
    NETWORK_SCAN_WORKERS,
    NetworkInterface,
    OpenPort,
    PENDING_TASK_FACTOR,
    PORT_SCAN_WORKERS,
    PORT_TIMEOUT_SECONDS,
    REVERSE_DNS_TIMEOUT_SECONDS,
    THREAD_SHUTDOWN_WAIT_MS,
    _bounded_future_results,
    _parse_arp_mac,
    _ping_command,
    _ping_succeeded,
    _probe_host,
    _probe_port,
    _usable_host_count,
    detect_default_network,
    get_default_route_address,
    get_ipv4_interfaces,
    get_mac_address,
    known_service_name,
    logger,
    parse_network_cidr,
    reverse_dns_name,
    scan_network_hosts,
    scan_open_ports,
    validate_port_range,
)
from . import service as _service
import sys as _sys
import types as _types

class NetworkScanWorker(QThread):
    message = pyqtSignal(str)
    finished_summary = pyqtSignal(str)
    cancelled = pyqtSignal(str)

    def __init__(self, cidr: str):
        super().__init__()
        self.cidr = cidr
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def run(self):
        checked = 0
        try:
            network = parse_network_cidr(self.cidr)
            self.message.emit(
                f"Escaneando {network.with_prefixlen} con hasta {NETWORK_SCAN_WORKERS} tareas concurrentes.\n"
            )

            def report_found(host):
                self.message.emit(
                    f"Dispositivo: {host.ip} - Hostname: {host.hostname} - MAC: {host.mac}"
                )

            def report_checked(_ip):
                nonlocal checked
                checked += 1

            found_devices = scan_network_hosts(
                network.with_prefixlen,
                stop_event=self._stop_event,
                on_found=report_found,
                on_checked=report_checked,
            )
        except Exception as error:
            self.message.emit(f"Error: {error}\n")
            self.finished_summary.emit(f"Escaneo de red fallido: {error}")
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

        self.message.emit("Exploración completada.\n")
        self.finished_summary.emit(summary)
class PortScanWorker(QThread):
    message = pyqtSignal(str)
    finished_summary = pyqtSignal(str)
    cancelled = pyqtSignal(str)

    def __init__(self, target: str, start_port: int, end_port: int):
        super().__init__()
        self.target = target
        self.start_port = start_port
        self.end_port = end_port
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def run(self):
        total = self.end_port - self.start_port + 1
        checked = 0
        self.message.emit(
            f"Escaneando {total} puertos con hasta {PORT_SCAN_WORKERS} conexiones concurrentes..."
        )

        def report_open(result):
            self.message.emit(f"ABIERTO  {result.port}/tcp  {result.service}")

        def report_checked(_port):
            nonlocal checked
            checked += 1

        try:
            results = scan_open_ports(
                self.target,
                self.start_port,
                self.end_port,
                stop_event=self._stop_event,
                on_open=report_open,
                on_checked=report_checked,
            )
        except OSError as error:
            self.message.emit(f"Error resolviendo o escaneando {self.target}: {error}")
            self.finished_summary.emit(f"Escaneo de puertos fallido para {self.target}: {error}")
            return

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
class NetworkScanner(QWidget):
    def __init__(self, history_tab):
        super().__init__()
        self.history_tab = history_tab
        self.worker: NetworkScanWorker | None = None
        self.interfaces = get_ipv4_interfaces()

        layout = QVBoxLayout()
        layout.addWidget(
            QLabel("Selecciona una interfaz detectada o introduce una red CIDR manualmente.")
        )

        interface_layout = QHBoxLayout()
        interface_layout.addWidget(QLabel("Interfaz:"))
        self.interface_combo = QComboBox()
        for interface in self.interfaces:
            self.interface_combo.addItem(
                f"{interface.name} — {interface.address} / {interface.netmask}",
                interface.cidr,
            )
        if not self.interfaces:
            self.interface_combo.addItem("No se detectaron interfaces IPv4 activas", "")
        else:
            try:
                default_interface = detect_default_network(self.interfaces)
            except RuntimeError:
                default_interface = None
            if default_interface is not None:
                for index, interface in enumerate(self.interfaces):
                    if interface == default_interface:
                        self.interface_combo.setCurrentIndex(index)
                        break
        self.interface_combo.currentIndexChanged.connect(self._apply_selected_interface)
        interface_layout.addWidget(self.interface_combo)
        layout.addLayout(interface_layout)

        cidr_layout = QHBoxLayout()
        cidr_layout.addWidget(QLabel("Red CIDR:"))
        self.cidr_input = QLineEdit()
        self.cidr_input.setPlaceholderText("Ejemplo: 192.168.1.0/24")
        cidr_layout.addWidget(self.cidr_input)
        layout.addLayout(cidr_layout)
        self._apply_selected_interface()

        self.result_area = QTextEdit()
        self.result_area.setReadOnly(True)
        layout.addWidget(self.result_area)

        self.scan_button = QPushButton("Explorar red")
        self.scan_button.clicked.connect(self.scan_network)
        layout.addWidget(self.scan_button)

        self.stop_button = QPushButton("Detener escaneo")
        self.stop_button.clicked.connect(self.stop_scan)
        self.stop_button.setEnabled(False)
        layout.addWidget(self.stop_button)

        self.setLayout(layout)

    def _apply_selected_interface(self):
        cidr = self.interface_combo.currentData()
        if cidr:
            self.cidr_input.setText(cidr)

    def _set_running(self, running: bool):
        self.scan_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.interface_combo.setEnabled(not running)
        self.cidr_input.setEnabled(not running)

    def _worker_finished(self):
        self._set_running(False)

    def scan_network(self):
        if self.worker and self.worker.isRunning():
            return

        cidr = self.cidr_input.text().strip()
        try:
            network = parse_network_cidr(cidr)
        except ValueError as error:
            self.result_area.append(f"Error: {error}\n")
            return

        self.result_area.clear()
        self.result_area.append(f"Escaneando {network.with_prefixlen}...\n")
        self.worker = NetworkScanWorker(network.with_prefixlen)
        self.worker.message.connect(self.result_area.append)
        self.worker.finished_summary.connect(self.history_tab.append_to_history)
        self.worker.finished.connect(self._worker_finished)
        self._set_running(True)
        self.worker.start()

    def stop_scan(self):
        if self.worker and self.worker.isRunning():
            self.stop_button.setEnabled(False)
            self.result_area.append("Cancelando escaneo...")
            self.worker.stop()

    def running_worker(self):
        if self.worker and self.worker.isRunning():
            return self.worker
        return None
class PortScanner(QWidget):
    def __init__(self, history_tab):
        super().__init__()
        self.history_tab = history_tab
        self.worker: PortScanWorker | None = None

        layout = QVBoxLayout()

        ip_layout = QHBoxLayout()
        ip_layout.addWidget(QLabel("Dirección IP o dominio:"))
        self.ip_input = QLineEdit()
        self.ip_input.setPlaceholderText("Ejemplo: 192.168.1.1 o servidor.local")
        ip_layout.addWidget(self.ip_input)
        layout.addLayout(ip_layout)

        port_layout = QHBoxLayout()
        port_layout.addWidget(QLabel("Rango de puertos:"))
        self.port_range_input = QLineEdit()
        self.port_range_input.setPlaceholderText("Ejemplo: 1-1024")
        port_layout.addWidget(self.port_range_input)
        layout.addLayout(port_layout)

        layout.addWidget(
            QLabel("Se muestran principalmente puertos abiertos y su servicio conocido.")
        )
        self.result_area = QTextEdit()
        self.result_area.setReadOnly(True)
        layout.addWidget(self.result_area)

        self.scan_button = QPushButton("Escanear puertos")
        self.scan_button.clicked.connect(self.scan_ports)
        layout.addWidget(self.scan_button)

        self.stop_button = QPushButton("Detener escaneo")
        self.stop_button.clicked.connect(self.stop_scan)
        self.stop_button.setEnabled(False)
        layout.addWidget(self.stop_button)

        self.setLayout(layout)

    def _set_running(self, running: bool):
        self.scan_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.ip_input.setEnabled(not running)
        self.port_range_input.setEnabled(not running)

    def _worker_finished(self):
        self._set_running(False)

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
            start_port, end_port = validate_port_range(port_range)
        except ValueError as error:
            self.result_area.append(f"Error: {error}\n")
            return

        self.result_area.clear()
        self.result_area.append(f"Escaneando {target} ({start_port}-{end_port})...\n")
        self.worker = PortScanWorker(target, start_port, end_port)
        self.worker.message.connect(self.result_area.append)
        self.worker.finished_summary.connect(self.history_tab.append_to_history)
        self.worker.finished.connect(self._worker_finished)
        self._set_running(True)
        self.worker.start()

    def stop_scan(self):
        if self.worker and self.worker.isRunning():
            self.stop_button.setEnabled(False)
            self.result_area.append("Cancelando escaneo...")
            self.worker.stop()

    def running_worker(self):
        if self.worker and self.worker.isRunning():
            return self.worker
        return None
class HistoryTab(QWidget):
    def __init__(self):
        super().__init__()
        self.history_file = SCAN_HISTORY_FILE
        ensure_app_dirs()

        layout = QVBoxLayout()
        layout.addWidget(QLabel("Registro histórico de escaneos:"))

        self.history_area = QTextEdit()
        self.history_area.setReadOnly(True)
        layout.addWidget(self.history_area)

        btn_load = QPushButton("Cargar historial")
        btn_load.clicked.connect(self.load_history)
        layout.addWidget(btn_load)

        btn_clear = QPushButton("Limpiar historial")
        btn_clear.clicked.connect(self.clear_history)
        layout.addWidget(btn_clear)

        btn_export = QPushButton("Exportar historial")
        btn_export.clicked.connect(self.export_history)
        layout.addWidget(btn_export)

        btn_import = QPushButton("Importar historial")
        btn_import.clicked.connect(self.import_history)
        layout.addWidget(btn_import)

        self.setLayout(layout)
        self.load_history()

    def load_history(self):
        if self.history_file.exists():
            with self.history_file.open("r", encoding="utf-8") as file:
                self.history_area.setText(file.read())
        else:
            self.history_area.setText("No hay historial disponible.\n")

    def clear_history(self):
        self.history_file.write_text("", encoding="utf-8")
        self.history_area.setText("Historial limpiado.\n")

    def append_to_history(self, entry):
        self.history_area.append(entry)
        with self.history_file.open("a", encoding="utf-8") as file:
            file.write(entry + "\n")

    def export_history(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar historial",
            "",
            "Archivos TXT (*.txt);;Archivos JSON (*.json);;Archivos CSV (*.csv)",
        )
        if not file_path:
            return

        data = self.history_area.toPlainText().splitlines()
        if file_path.endswith(".txt"):
            with open(file_path, "w", encoding="utf-8") as file:
                file.write("\n".join(data))
        elif file_path.endswith(".json"):
            with open(file_path, "w", encoding="utf-8") as file:
                json.dump(data, file, indent=4)
        elif file_path.endswith(".csv"):
            with open(file_path, "w", newline="", encoding="utf-8") as file:
                writer = csv.writer(file)
                for line in data:
                    writer.writerow([safe_csv_cell(line)])

    def import_history(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Importar historial",
            "",
            "Archivos TXT (*.txt);;Archivos JSON (*.json);;Archivos CSV (*.csv)",
        )
        if not file_path:
            return

        data = []
        if file_path.endswith(".txt"):
            with open(file_path, "r", encoding="utf-8") as file:
                data = file.read().splitlines()
        elif file_path.endswith(".json"):
            with open(file_path, "r", encoding="utf-8") as file:
                data = json.load(file)
        elif file_path.endswith(".csv"):
            with open(file_path, "r", encoding="utf-8") as file:
                data = [",".join(row) for row in csv.reader(file)]

        self.history_area.setText("\n".join(data))
        with self.history_file.open("w", encoding="utf-8") as file:
            file.write("\n".join(data))
class Tool(BaseTool):
    name = "Explorador de Red"
    description = "Ejecuta diagnósticos y utilidades de red."
    category = "Red"

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

    def _running_workers(self):
        workers = []
        for scanner in (self.network_scanner, self.port_scanner):
            worker = scanner.running_worker()
            if worker is not None:
                workers.append(worker)
        return workers

    def _retry_deferred_close(self):
        if self._close_when_workers_finish and not self._running_workers():
            self._close_when_workers_finish = False
            self.close()

    def closeEvent(self, event):
        workers = self._running_workers()
        if not workers:
            event.accept()
            return

        for worker in workers:
            worker.stop()

        deadline = time.monotonic() + THREAD_SHUTDOWN_WAIT_MS / 1000.0
        unfinished = []
        for worker in workers:
            remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
            if not worker.wait(remaining_ms):
                unfinished.append(worker)

        if not unfinished:
            event.accept()
            return

        if not self._close_when_workers_finish:
            self._close_when_workers_finish = True
            for worker in unfinished:
                worker.finished.connect(self._retry_deferred_close)
        event.ignore()

class _CompatibilityModule(_types.ModuleType):
    """Forward legacy monkeypatches to the separated service module."""

    def __setattr__(self, name, value):
        if hasattr(_service, name):
            setattr(_service, name, value)
        super().__setattr__(name, value)

    def __delattr__(self, name):
        if hasattr(_service, name):
            delattr(_service, name)
        super().__delattr__(name)


_sys.modules[__name__].__class__ = _CompatibilityModule
