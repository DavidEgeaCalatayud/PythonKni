from __future__ import annotations

from tools.base_tool import BaseTool

import csv
import ipaddress
import json
import logging
import platform
import socket
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
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


logger = logging.getLogger(__name__)
MAX_NETWORK_HOSTS = 4096
NETWORK_SCAN_WORKERS = 32
PORT_SCAN_WORKERS = 64
PORT_TIMEOUT_SECONDS = 0.35

COMMON_TCP_SERVICES = {
    20: "ftp-data",
    21: "ftp",
    22: "ssh",
    23: "telnet",
    25: "smtp",
    53: "domain",
    80: "http",
    110: "pop3",
    135: "msrpc",
    139: "netbios-ssn",
    143: "imap",
    443: "https",
    445: "microsoft-ds",
    587: "submission",
    993: "imaps",
    995: "pop3s",
    1433: "ms-sql-s",
    3306: "mysql",
    3389: "ms-wbt-server",
    5432: "postgresql",
    5900: "vnc",
    6379: "redis",
    8080: "http-alt",
}


@dataclass(frozen=True)
class NetworkInterface:
    name: str
    address: str
    netmask: str
    cidr: str


@dataclass(frozen=True)
class DiscoveredHost:
    ip: str
    hostname: str
    mac: str


@dataclass(frozen=True)
class OpenPort:
    port: int
    service: str


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


def parse_network_cidr(value: str, max_hosts: int = MAX_NETWORK_HOSTS) -> ipaddress.IPv4Network:
    try:
        network = ipaddress.ip_network(value.strip(), strict=False)
    except ValueError as error:
        raise ValueError(
            "Introduce una red IPv4 en formato CIDR, por ejemplo 192.168.1.0/24."
        ) from error

    if not isinstance(network, ipaddress.IPv4Network):
        raise ValueError("El escáner de red admite actualmente redes IPv4.")

    host_count = network.num_addresses
    if network.prefixlen < 31:
        host_count = max(0, host_count - 2)
    if host_count > max_hosts:
        raise ValueError(
            f"La red {network.with_prefixlen} contiene {host_count} hosts utilizables. "
            f"Acota el CIDR a un máximo de {max_hosts} hosts por escaneo."
        )
    return network


def get_ipv4_interfaces() -> list[NetworkInterface]:
    interfaces = []
    stats = psutil.net_if_stats()
    for name, addresses in psutil.net_if_addrs().items():
        interface_stats = stats.get(name)
        if interface_stats is not None and not interface_stats.isup:
            continue

        for address in addresses:
            if address.family != socket.AF_INET or not address.address or not address.netmask:
                continue
            try:
                ip = ipaddress.ip_address(address.address)
                if ip.is_loopback or ip.is_unspecified:
                    continue
                network = ipaddress.ip_network(f"{address.address}/{address.netmask}", strict=False)
            except ValueError:
                continue
            interfaces.append(
                NetworkInterface(
                    name=name,
                    address=address.address,
                    netmask=address.netmask,
                    cidr=network.with_prefixlen,
                )
            )
    return interfaces


def detect_default_network() -> NetworkInterface:
    interfaces = get_ipv4_interfaces()
    if not interfaces:
        raise RuntimeError("No se encontró ninguna interfaz IPv4 activa con máscara de red.")

    def priority(interface):
        ip = ipaddress.ip_address(interface.address)
        return (not ip.is_private, ip.is_link_local, interface.name.casefold())

    return sorted(interfaces, key=priority)[0]


def _ping_command(ip: str) -> list[str]:
    if platform.system() == "Windows":
        return ["ping", "-n", "1", "-w", "800", ip]
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


def _probe_host(ip: str, stop_event: threading.Event) -> DiscoveredHost | None:
    if stop_event.is_set():
        return None
    try:
        result = subprocess.run(_ping_command(ip), capture_output=True, text=True, timeout=2)
        if result.returncode != 0:
            return None
        try:
            host_name = socket.gethostbyaddr(ip)[0]
        except (socket.herror, socket.gaierror):
            host_name = "No resuelto"
        return DiscoveredHost(ip=ip, hostname=host_name, mac=get_mac_address(ip))
    except (subprocess.TimeoutExpired, OSError):
        return None


def scan_network_hosts(
    cidr: str,
    stop_event: threading.Event | None = None,
    max_workers: int = NETWORK_SCAN_WORKERS,
    probe_func=None,
    on_found=None,
) -> list[DiscoveredHost]:
    network = parse_network_cidr(cidr)
    stop_event = stop_event or threading.Event()
    probe_func = probe_func or _probe_host
    hosts = [str(host) for host in network.hosts()]
    found = []

    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(hosts) or 1))) as executor:
        futures = {executor.submit(probe_func, ip, stop_event): ip for ip in hosts}
        for future in as_completed(futures):
            if stop_event.is_set():
                for pending in futures:
                    pending.cancel()
                break
            try:
                host = future.result()
            except Exception:
                logger.exception("Network probe failed for %s", futures[future])
                continue
            if host is not None:
                found.append(host)
                if on_found is not None:
                    on_found(host)

    return sorted(found, key=lambda item: ipaddress.ip_address(item.ip))


def known_service_name(port: int) -> str:
    try:
        return socket.getservbyport(port, "tcp")
    except OSError:
        return COMMON_TCP_SERVICES.get(port, "desconocido")


def _probe_port(ip: str, port: int, timeout: float) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((ip, port)) == 0


def scan_open_ports(
    target: str,
    start_port: int,
    end_port: int,
    stop_event: threading.Event | None = None,
    max_workers: int = PORT_SCAN_WORKERS,
    timeout: float = PORT_TIMEOUT_SECONDS,
    probe_func=None,
    on_open=None,
) -> list[OpenPort]:
    ip = socket.gethostbyname(target)
    stop_event = stop_event or threading.Event()
    probe_func = probe_func or _probe_port
    ports = list(range(start_port, end_port + 1))
    open_ports = []

    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(ports) or 1))) as executor:
        futures = {executor.submit(probe_func, ip, port, timeout): port for port in ports}
        for future in as_completed(futures):
            if stop_event.is_set():
                for pending in futures:
                    pending.cancel()
                break
            port = futures[future]
            try:
                is_open = future.result()
            except OSError:
                is_open = False
            if is_open:
                result = OpenPort(port=port, service=known_service_name(port))
                open_ports.append(result)
                if on_open is not None:
                    on_open(result)

    return sorted(open_ports, key=lambda item: item.port)


class NetworkScanWorker(QThread):
    message = pyqtSignal(str)
    finished_summary = pyqtSignal(str)

    def __init__(self, cidr: str):
        super().__init__()
        self.cidr = cidr
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def run(self):
        try:
            network = parse_network_cidr(self.cidr)
            self.message.emit(
                f"Escaneando {network.with_prefixlen} con hasta {NETWORK_SCAN_WORKERS} tareas concurrentes.\n"
            )

            def report_found(host):
                self.message.emit(
                    f"Dispositivo: {host.ip} - Hostname: {host.hostname} - MAC: {host.mac}"
                )

            found_devices = scan_network_hosts(
                network.with_prefixlen,
                stop_event=self._stop_event,
                on_found=report_found,
            )
        except Exception as error:
            self.message.emit(f"Error: {error}\n")
            self.finished_summary.emit(f"Escaneo de red fallido: {error}")
            return

        if self._stop_event.is_set():
            self.message.emit("Escaneo detenido por el usuario.\n")

        if found_devices:
            rows = [
                f"{host.ip} - Hostname: {host.hostname} - MAC: {host.mac}" for host in found_devices
            ]
            summary = f"Escaneo de {network.with_prefixlen}:\n" + "\n".join(rows)
        else:
            summary = f"Escaneo de {network.with_prefixlen}: no se encontraron dispositivos."

        self.message.emit("Exploración completada.\n")
        self.finished_summary.emit(summary)


class PortScanWorker(QThread):
    message = pyqtSignal(str)
    finished_summary = pyqtSignal(str)

    def __init__(self, target: str, start_port: int, end_port: int):
        super().__init__()
        self.target = target
        self.start_port = start_port
        self.end_port = end_port
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def run(self):
        checked = self.end_port - self.start_port + 1
        self.message.emit(
            f"Escaneando {checked} puertos con hasta {PORT_SCAN_WORKERS} conexiones concurrentes..."
        )

        def report_open(result):
            self.message.emit(f"ABIERTO  {result.port}/tcp  {result.service}")

        try:
            results = scan_open_ports(
                self.target,
                self.start_port,
                self.end_port,
                stop_event=self._stop_event,
                on_open=report_open,
            )
        except (OSError, socket.gaierror) as error:
            self.message.emit(f"Error resolviendo o escaneando {self.target}: {error}")
            self.finished_summary.emit(f"Escaneo de puertos fallido para {self.target}: {error}")
            return

        if self._stop_event.is_set():
            self.message.emit("Escaneo detenido por el usuario.")

        if results:
            rows = [f"{result.port}/tcp abierto ({result.service})" for result in results]
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
        layout.addWidget(self.stop_button)

        self.setLayout(layout)

    def _apply_selected_interface(self):
        cidr = self.interface_combo.currentData()
        if cidr:
            self.cidr_input.setText(cidr)

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
        layout.addWidget(self.stop_button)

        self.setLayout(layout)

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


class Tool(BaseTool):
    name = "Explorador de Red"
    description = "Ejecuta diagnósticos y utilidades de red."
    category = "Red"

    def setup_ui(self):
        self.setWindowTitle(self.name)
        self.setGeometry(200, 200, 800, 600)

        history_tab = HistoryTab()
        network_scanner = NetworkScanner(history_tab)
        port_scanner = PortScanner(history_tab)

        tabs = QTabWidget()
        tabs.addTab(network_scanner, "Escáner de Red")
        tabs.addTab(port_scanner, "Escáner de Puertos")
        tabs.addTab(history_tab, "Histórico")

        self.setCentralWidget(tabs)
