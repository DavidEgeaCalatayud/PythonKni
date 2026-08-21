from __future__ import annotations

from tools.base_tool import BaseTool

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


logger = logging.getLogger(__name__)
MAX_NETWORK_HOSTS = 4096
NETWORK_SCAN_WORKERS = 32
PORT_SCAN_WORKERS = 64
PORT_TIMEOUT_SECONDS = 0.35
REVERSE_DNS_TIMEOUT_SECONDS = 0.4
THREAD_SHUTDOWN_WAIT_MS = 3000
PENDING_TASK_FACTOR = 2
DEFAULT_ROUTE_PROBE = ("8.8.8.8", 80)
MAC_PATTERN = re.compile(r"\b(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}\b")

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


def _usable_host_count(network: ipaddress.IPv4Network) -> int:
    if network.prefixlen >= 31:
        return network.num_addresses
    return max(0, network.num_addresses - 2)


def parse_network_cidr(value: str, max_hosts: int = MAX_NETWORK_HOSTS) -> ipaddress.IPv4Network:
    try:
        network = ipaddress.ip_network(value.strip(), strict=False)
    except ValueError as error:
        raise ValueError(
            "Introduce una red IPv4 en formato CIDR, por ejemplo 192.168.1.0/24."
        ) from error

    if not isinstance(network, ipaddress.IPv4Network):
        raise ValueError("El escáner de red admite actualmente redes IPv4.")

    host_count = _usable_host_count(network)
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


def get_default_route_address() -> str | None:
    """Return the IPv4 address selected by the OS routing table without sending data."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(DEFAULT_ROUTE_PROBE)
        return sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()


def detect_default_network(
    interfaces: list[NetworkInterface] | None = None,
) -> NetworkInterface:
    interfaces = interfaces if interfaces is not None else get_ipv4_interfaces()
    if not interfaces:
        raise RuntimeError("No se encontró ninguna interfaz IPv4 activa con máscara de red.")

    route_address = get_default_route_address()
    if route_address:
        for interface in interfaces:
            if interface.address == route_address:
                return interface

    def priority(interface):
        ip = ipaddress.ip_address(interface.address)
        return (ip.is_link_local, not ip.is_private, interface.name.casefold())

    return sorted(interfaces, key=priority)[0]


def _ping_command(ip: str) -> list[str]:
    if platform.system() == "Windows":
        return ["ping", "-n", "1", "-w", "800", ip]
    return ["ping", "-c", "1", "-W", "1", ip]


def _ping_succeeded(output: str) -> bool:
    lowered = output.lower()
    return "ttl=" in lowered or "time=" in lowered or "tiempo=" in lowered


def _parse_arp_mac(output: str, ip: str) -> str:
    for line in output.splitlines():
        tokens = [token.strip("()") for token in line.split()]
        if ip not in tokens:
            continue
        match = MAC_PATTERN.search(line)
        if match:
            return match.group(0)
    return "No disponible"


def get_mac_address(ip: str) -> str:
    try:
        output = subprocess.run(["arp", "-a", ip], capture_output=True, text=True, timeout=2)
        return _parse_arp_mac(output.stdout, ip)
    except (OSError, subprocess.TimeoutExpired):
        logger.exception("Could not read MAC address for %s", ip)
    return "No disponible"


def reverse_dns_name(ip: str, timeout: float = REVERSE_DNS_TIMEOUT_SECONDS) -> str:
    """Resolve reverse DNS without allowing the system resolver to stall a scan worker."""
    result = []

    def lookup():
        try:
            result.append(socket.gethostbyaddr(ip)[0])
        except (OSError, socket.herror, socket.gaierror):
            return

    resolver = threading.Thread(target=lookup, daemon=True)
    resolver.start()
    resolver.join(max(0.0, timeout))
    if resolver.is_alive() or not result:
        return "No resuelto"
    return result[0]


def _probe_host(ip: str, stop_event: threading.Event) -> DiscoveredHost | None:
    if stop_event.is_set():
        return None
    try:
        result = subprocess.run(_ping_command(ip), capture_output=True, text=True, timeout=2)
        if result.returncode != 0 or not _ping_succeeded(result.stdout):
            return None
        if stop_event.is_set():
            return None
        host_name = reverse_dns_name(ip)
        if stop_event.is_set():
            return None
        return DiscoveredHost(ip=ip, hostname=host_name, mac=get_mac_address(ip))
    except (subprocess.TimeoutExpired, OSError):
        return None


def _bounded_future_results(
    items,
    executor,
    submit_item,
    stop_event: threading.Event,
    max_pending: int,
):
    iterator = iter(items)
    pending = {}
    exhausted = False
    pending_limit = max(1, max_pending)

    def fill_pending():
        nonlocal exhausted
        while not exhausted and not stop_event.is_set() and len(pending) < pending_limit:
            try:
                item = next(iterator)
            except StopIteration:
                exhausted = True
                break
            pending[executor.submit(submit_item, item)] = item

    fill_pending()
    while pending:
        done, _ = wait(tuple(pending), return_when=FIRST_COMPLETED)
        for future in done:
            item = pending.pop(future)
            yield item, future
        if stop_event.is_set():
            for future in pending:
                future.cancel()
            break
        fill_pending()


def scan_network_hosts(
    cidr: str,
    stop_event: threading.Event | None = None,
    max_workers: int = NETWORK_SCAN_WORKERS,
    probe_func=None,
    on_found=None,
    on_checked=None,
    max_pending: int | None = None,
) -> list[DiscoveredHost]:
    network = parse_network_cidr(cidr)
    stop_event = stop_event or threading.Event()
    probe_func = probe_func or _probe_host
    host_count = _usable_host_count(network)
    workers = max(1, min(max_workers, host_count or 1))
    pending_limit = max_pending or workers * PENDING_TASK_FACTOR
    found = []

    with ThreadPoolExecutor(max_workers=workers) as executor:
        results = _bounded_future_results(
            (str(host) for host in network.hosts()),
            executor,
            lambda ip: probe_func(ip, stop_event),
            stop_event,
            pending_limit,
        )
        for ip, future in results:
            if stop_event.is_set():
                break
            try:
                host = future.result()
            except Exception:
                logger.exception("Network probe failed for %s", ip)
                host = None
            if on_checked is not None:
                on_checked(ip)
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
    on_checked=None,
    max_pending: int | None = None,
) -> list[OpenPort]:
    ip = socket.gethostbyname(target)
    stop_event = stop_event or threading.Event()
    probe_func = probe_func or _probe_port
    total_ports = end_port - start_port + 1
    workers = max(1, min(max_workers, total_ports or 1))
    pending_limit = max_pending or workers * PENDING_TASK_FACTOR
    open_ports = []

    with ThreadPoolExecutor(max_workers=workers) as executor:
        results = _bounded_future_results(
            range(start_port, end_port + 1),
            executor,
            lambda port: probe_func(ip, port, timeout),
            stop_event,
            pending_limit,
        )
        for port, future in results:
            if stop_event.is_set():
                break
            try:
                is_open = future.result()
            except OSError:
                is_open = False
            except Exception:
                logger.exception("Port probe failed for %s:%s", ip, port)
                is_open = False
            if on_checked is not None:
                on_checked(port)
            if is_open:
                result = OpenPort(port=port, service=known_service_name(port))
                open_ports.append(result)
                if on_open is not None:
                    on_open(result)

    return sorted(open_ports, key=lambda item: item.port)


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
