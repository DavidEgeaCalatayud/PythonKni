from __future__ import annotations
from .models import (
    DiscoveredHost,
    NetworkInterface,
    OpenPort,
)
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
