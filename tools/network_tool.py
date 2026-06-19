from __future__ import annotations

import csv
import json
import logging
import os
import platform
import socket
import subprocess

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from tools.app_paths import SCAN_HISTORY_FILE, ensure_app_dirs


logger = logging.getLogger(__name__)


def validate_port_range(port_range: str) -> tuple[int, int]:
    try:
        start_text, end_text = port_range.split("-", 1)
        start_port = int(start_text.strip())
        end_port = int(end_text.strip())
    except ValueError as error:
        raise ValueError("El rango debe tener formato 'inicio-fin'.") from error

    if start_port < 1 or end_port > 65535:
        raise ValueError("Los puertos deben estar entre 1 y 65535.")
    if start_port > end_port:
        raise ValueError("El puerto inicial no puede ser mayor que el final.")

    return start_port, end_port


def _ping_command(ip: str) -> list[str]:
    if platform.system() == "Windows":
        return ["ping", "-n", "1", "-w", "1000", ip]
    return ["ping", "-c", "1", "-W", "1", ip]


def _ping_succeeded(output: str) -> bool:
    lowered = output.lower()
    return "ttl=" in lowered or "tiempo" in lowered or "time=" in lowered


def get_mac_address(ip: str) -> str:
    try:
        output = subprocess.run(["arp", "-a", ip], capture_output=True, text=True, timeout=2)
        for line in output.stdout.splitlines():
            if ip in line:
                parts = line.split()
                if len(parts) > 1:
                    return parts[1]
    except Exception:
        logger.exception("Could not read MAC address for %s", ip)
    return "No disponible"


class NetworkScanWorker(QThread):
    message = pyqtSignal(str)
    finished_summary = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._stop_requested = False

    def stop(self):
        self._stop_requested = True

    def run(self):
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        self.message.emit(f"Direccion IP local: {local_ip}\n")

        network_base = ".".join(local_ip.split(".")[:-1])
        self.message.emit(f"Escaneando en: {network_base}.x\n")

        found_devices = []
        for i in range(1, 255):
            if self._stop_requested:
                self.message.emit("Escaneo detenido por el usuario.\n")
                break

            ip = f"{network_base}.{i}"
            try:
                output = subprocess.run(
                    _ping_command(ip), capture_output=True, text=True, timeout=2
                )
                if _ping_succeeded(output.stdout):
                    try:
                        host_name = socket.gethostbyaddr(ip)[0]
                    except socket.herror:
                        host_name = "No resuelto"

                    mac_address = get_mac_address(ip)
                    device_info = f"{ip} - Hostname: {host_name} - MAC: {mac_address}"
                    found_devices.append(device_info)
                    self.message.emit(f"Dispositivo encontrado: {device_info}\n")
            except subprocess.TimeoutExpired:
                pass
            except Exception as error:
                self.message.emit(f"Error escaneando {ip}: {error}\n")

        if found_devices:
            summary = "Escaneo completado:\n" + "\n".join(found_devices)
        else:
            summary = f"Escaneo completado. No se encontraron dispositivos en {network_base}.x."

        self.message.emit("Exploracion completada.\n")
        self.finished_summary.emit(summary)


class PortScanWorker(QThread):
    message = pyqtSignal(str)
    finished_summary = pyqtSignal(str)

    def __init__(self, target: str, start_port: int, end_port: int):
        super().__init__()
        self.target = target
        self.start_port = start_port
        self.end_port = end_port
        self._stop_requested = False

    def stop(self):
        self._stop_requested = True

    def run(self):
        results = []
        for port in range(self.start_port, self.end_port + 1):
            if self._stop_requested:
                self.message.emit("Escaneo detenido por el usuario.\n")
                break

            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.5)
                result = sock.connect_ex((self.target, port))

            status = "ABIERTO" if result == 0 else "CERRADO"
            line = f"Puerto {port}: {status}"
            results.append(line)
            self.message.emit(line)

        if results:
            summary = (
                f"Escaneo de puertos en {self.target} ({self.start_port}-{self.end_port}):\n"
                + "\n".join(results)
            )
        else:
            summary = (
                f"Escaneo de puertos en {self.target} ({self.start_port}-{self.end_port}): "
                "Sin resultados."
            )

        self.message.emit("Escaneo completado.\n")
        self.finished_summary.emit(summary)


class NetworkScanner(QWidget):
    def __init__(self, history_tab):
        super().__init__()
        self.history_tab = history_tab
        self.worker: NetworkScanWorker | None = None

        layout = QVBoxLayout()
        layout.addWidget(QLabel("Haz clic en 'Explorar red' para detectar dispositivos conectados."))

        self.result_area = QTextEdit()
        self.result_area.setReadOnly(True)
        layout.addWidget(self.result_area)

        self.scan_button = QPushButton("Explorar red")
        self.scan_button.clicked.connect(self.scan_network)
        layout.addWidget(self.scan_button)

        self.stop_button = QPushButton("Detener escaneo")
        self.stop_button.clicked.connect(self.stop_scan)
        layout.addWidget(self.stop_button)

        self.setLayout(layout)

    def scan_network(self):
        if self.worker and self.worker.isRunning():
            return

        self.result_area.clear()
        self.result_area.append("Escaneando la red...\n")
        self.worker = NetworkScanWorker()
        self.worker.message.connect(self.result_area.append)
        self.worker.finished_summary.connect(self.history_tab.append_to_history)
        self.worker.finished.connect(lambda: self.scan_button.setEnabled(True))
        self.scan_button.setEnabled(False)
        self.worker.start()

    def stop_scan(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()


class PortScanner(QWidget):
    def __init__(self, history_tab):
        super().__init__()
        self.history_tab = history_tab
        self.worker: PortScanWorker | None = None

        layout = QVBoxLayout()

        ip_layout = QHBoxLayout()
        ip_layout.addWidget(QLabel("Direccion IP o dominio:"))
        self.ip_input = QLineEdit()
        self.ip_input.setPlaceholderText("Ejemplo: 192.168.1.1 o google.com")
        ip_layout.addWidget(self.ip_input)
        layout.addLayout(ip_layout)

        port_layout = QHBoxLayout()
        port_layout.addWidget(QLabel("Rango de puertos:"))
        self.port_range_input = QLineEdit()
        self.port_range_input.setPlaceholderText("Ejemplo: 20-80")
        port_layout.addWidget(self.port_range_input)
        layout.addLayout(port_layout)

        self.result_area = QTextEdit()
        self.result_area.setReadOnly(True)
        layout.addWidget(self.result_area)

        self.scan_button = QPushButton("Escanear Puertos")
        self.scan_button.clicked.connect(self.scan_ports)
        layout.addWidget(self.scan_button)

        self.stop_button = QPushButton("Detener Escaneo")
        self.stop_button.clicked.connect(self.stop_scan)
        layout.addWidget(self.stop_button)

        self.setLayout(layout)

    def scan_ports(self):
        if self.worker and self.worker.isRunning():
            return

        target = self.ip_input.text().strip()
        port_range = self.port_range_input.text().strip()

        if not target:
            self.result_area.append("Error: Debes ingresar una direccion IP o dominio.\n")
            return
        if not port_range:
            self.result_area.append("Error: Debes ingresar un rango de puertos.\n")
            return

        try:
            start_port, end_port = validate_port_range(port_range)
        except ValueError as error:
            self.result_area.append(f"Error: {error}\n")
            return

        self.result_area.append(f"Escaneando {target} ({start_port}-{end_port})...\n")
        self.worker = PortScanWorker(target, start_port, end_port)
        self.worker.message.connect(self.result_area.append)
        self.worker.finished_summary.connect(self.history_tab.append_to_history)
        self.worker.finished.connect(lambda: self.scan_button.setEnabled(True))
        self.scan_button.setEnabled(False)
        self.worker.start()

    def stop_scan(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()


class HistoryTab(QWidget):
    def __init__(self):
        super().__init__()
        self.history_file = SCAN_HISTORY_FILE
        ensure_app_dirs()

        layout = QVBoxLayout()
        layout.addWidget(QLabel("Registro historico de escaneos:"))

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
                    writer.writerow([line])

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


class Tool(QMainWindow):
    name = "Explorador de Red"

    def __init__(self):
        super().__init__()
        self.setWindowTitle(self.name)
        self.setGeometry(200, 200, 800, 600)

        history_tab = HistoryTab()
        network_scanner = NetworkScanner(history_tab)
        port_scanner = PortScanner(history_tab)

        tabs = QTabWidget()
        tabs.addTab(network_scanner, "Escaner de Red")
        tabs.addTab(port_scanner, "Escaner de Puertos")
        tabs.addTab(history_tab, "Historico")

        self.setCentralWidget(tabs)
