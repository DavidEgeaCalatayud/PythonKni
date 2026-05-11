from __future__ import annotations

import socket
import subprocess
import threading
import logging
from PyQt5.QtWidgets import QVBoxLayout, QLabel, QPushButton, QTextEdit, QWidget
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


class NetworkScanner(QWidget):
    def __init__(self, history_tab):
        super().__init__()
        self.history_tab = history_tab
        self.stop_scanning = False

        layout = QVBoxLayout()

        self.info_label = QLabel(
            "Haz clic en 'Explorar red' para detectar dispositivos conectados."
        )
        layout.addWidget(self.info_label)

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
        self.result_area.clear()
        self.result_area.append("Escaneando la red...\n")
        self.stop_scanning = False
        threading.Thread(target=self.perform_scan).start()

    def stop_scan(self):
        self.stop_scanning = True
        self.result_area.append("Escaneo detenido por el usuario.\n")

    def perform_scan(self):
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        self.result_area.append(f"Dirección IP local: {local_ip}\n")

        network_base = ".".join(local_ip.split(".")[:-1])
        self.result_area.append(f"Escaneando en: {network_base}.x\n")

        dispositivos_encontrados = []

        for i in range(1, 255):
            if self.stop_scanning:
                self.result_area.append("Escaneo detenido por el usuario.\n")
                break

            ip = f"{network_base}.{i}"
            try:
                output = subprocess.run(
                    ["ping", "-n", "1", ip], capture_output=True, text=True, timeout=1
                )
                if "Tiempo" in output.stdout or "time" in output.stdout:
                    try:
                        hostname = socket.gethostbyaddr(ip)[0]
                    except socket.herror:
                        hostname = "No resuelto"

                    mac_address = self.get_mac_address(ip)
                    dispositivo_info = f"{ip} - Hostname: {hostname} - MAC: {mac_address}"
                    dispositivos_encontrados.append(dispositivo_info)
                    self.result_area.append(f"Dispositivo encontrado: {dispositivo_info}\n")
            except subprocess.TimeoutExpired:
                pass
            except Exception as e:
                self.result_area.append(f"Error escaneando {ip}: {e}\n")

        if dispositivos_encontrados:
            entry = f"Escaneo completado:\n" + "\n".join(dispositivos_encontrados)
        else:
            entry = f"Escaneo completado. No se encontraron dispositivos en {network_base}.x."

        self.result_area.append("Exploración completada.\n")
        self.history_tab.append_to_history(entry)

    def get_mac_address(self, ip):
        try:
            output = subprocess.run(["arp", "-a", ip], capture_output=True, text=True)
            lines = output.stdout.splitlines()
            for line in lines:
                if ip in line:
                    parts = line.split()
                    if len(parts) > 1:
                        return parts[1]
        except Exception:
            logger.exception("Could not read MAC address for %s", ip)
        return "No disponible"


import socket
import threading
from PyQt5.QtWidgets import (
    QVBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QWidget,
    QLineEdit,
    QHBoxLayout,
)


class PortScanner(QWidget):
    def __init__(self, history_tab):
        super().__init__()
        self.history_tab = history_tab
        self.stop_scanning = False

        layout = QVBoxLayout()

        ip_layout = QHBoxLayout()
        ip_label = QLabel("Dirección IP o dominio:")
        self.ip_input = QLineEdit()
        self.ip_input.setPlaceholderText("Ejemplo: 192.168.1.1 o google.com")
        ip_layout.addWidget(ip_label)
        ip_layout.addWidget(self.ip_input)
        layout.addLayout(ip_layout)

        port_layout = QHBoxLayout()
        port_label = QLabel("Rango de puertos:")
        self.port_range_input = QLineEdit()
        self.port_range_input.setPlaceholderText("Ejemplo: 20-80")
        port_layout.addWidget(port_label)
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

        self.result_area.append(f"Escaneando {target} ({start_port}-{end_port})...\n")
        self.stop_scanning = False
        threading.Thread(target=self.perform_scan, args=(target, start_port, end_port)).start()

    def stop_scan(self):
        self.stop_scanning = True
        self.result_area.append("Escaneo detenido por el usuario.\n")

    def perform_scan(self, target, start_port, end_port):
        resultados = []
        for port in range(start_port, end_port + 1):
            if self.stop_scanning:
                break

            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                result = s.connect_ex((target, port))
                if result == 0:
                    resultado = f"Puerto {port}: ABIERTO"
                    resultados.append(resultado)
                    self.result_area.append(resultado)
                else:
                    resultado = f"Puerto {port}: CERRADO"
                    resultados.append(resultado)
                    self.result_area.append(resultado)

        if resultados:
            resumen = f"Escaneo de puertos en {target} ({start_port}-{end_port}):\n" + "\n".join(
                resultados
            )
        else:
            resumen = f"Escaneo de puertos en {target} ({start_port}-{end_port}): Sin resultados."

        self.result_area.append("Escaneo completado.\n")
        self.history_tab.append_to_history(resumen)


import os
import json
import csv
from PyQt5.QtWidgets import QVBoxLayout, QLabel, QPushButton, QTextEdit, QWidget, QFileDialog


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
            with open(file_path, "w") as f:
                f.write("\n".join(data))
        elif file_path.endswith(".json"):
            with open(file_path, "w") as f:
                json.dump(data, f, indent=4)
        elif file_path.endswith(".csv"):
            with open(file_path, "w", newline="") as f:
                writer = csv.writer(f)
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

        if file_path.endswith(".txt"):
            with open(file_path, "r") as f:
                data = f.read().splitlines()
        elif file_path.endswith(".json"):
            with open(file_path, "r") as f:
                data = json.load(f)
        elif file_path.endswith(".csv"):
            with open(file_path, "r") as f:
                data = [",".join(row) for row in csv.reader(f)]

        self.history_area.setText("\n".join(data))
        with self.history_file.open("w", encoding="utf-8") as f:
            f.write("\n".join(data))


from PyQt5.QtWidgets import (
    QVBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
    QComboBox,
    QLineEdit,
    QSpinBox,
    QFileDialog,
    QCheckBox,
)


class SettingsTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout()

        layout.addWidget(QLabel("Configuraciones generales."))

        theme_label = QLabel("Tema:")
        self.theme_combobox = QComboBox()
        self.theme_combobox.addItems(["Claro", "Oscuro"])
        layout.addWidget(theme_label)
        layout.addWidget(self.theme_combobox)

        font_label = QLabel("Tamaño de fuente:")
        self.font_size_spinbox = QSpinBox()
        self.font_size_spinbox.setRange(8, 24)
        self.font_size_spinbox.setValue(14)
        layout.addWidget(font_label)
        layout.addWidget(self.font_size_spinbox)

        proxy_label = QLabel("Proxy:")
        self.proxy_input = QLineEdit()
        layout.addWidget(proxy_label)
        layout.addWidget(self.proxy_input)

        btn_save_proxy = QPushButton("Guardar Proxy")
        layout.addWidget(btn_save_proxy)

        export_label = QLabel("Directorio por defecto:")
        btn_export_path = QPushButton("Seleccionar carpeta")
        layout.addWidget(export_label)
        layout.addWidget(btn_export_path)

        lang_label = QLabel("Idioma:")
        self.language_combobox = QComboBox()
        self.language_combobox.addItems(["Español", "Inglés"])
        layout.addWidget(lang_label)
        layout.addWidget(self.language_combobox)

        self.notifications_checkbox = QCheckBox("Activar notificaciones")
        layout.addWidget(self.notifications_checkbox)

        btn_save_settings = QPushButton("Guardar configuración")
        layout.addWidget(btn_save_settings)

        self.setLayout(layout)


from PyQt5.QtWidgets import QMainWindow, QTabWidget


class Tool(QMainWindow):
    name = "Explorador de Red"

    def __init__(self):
        super().__init__()
        self.setWindowTitle(self.name)
        self.setGeometry(200, 200, 800, 600)

        history_tab = HistoryTab()
        network_scanner = NetworkScanner(history_tab)
        port_scanner = PortScanner(history_tab)
        settings_tab = SettingsTab()

        tabs = QTabWidget()
        tabs.addTab(network_scanner, "Escáner de Red")
        tabs.addTab(port_scanner, "Escáner de Puertos")
        tabs.addTab(history_tab, "Histórico")
        tabs.addTab(settings_tab, "Configuración")

        self.setCentralWidget(tabs)
