from __future__ import annotations

import ipaddress
import socket
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from pythonkni.camera_auditor.models import CameraDevice, OnvifDiscoveryMatch, RiskLevel
from pythonkni.camera_auditor.service import (
    PROBE_TIMEOUT_SECONDS,
    discover_onvif_devices,
    probe_camera_host,
)
from pythonkni.network.models import DiscoveredHost

from .models import DeviceKind, NetworkIntelligenceDevice

INTELLIGENCE_WORKERS = 16
INTELLIGENCE_PORT_TIMEOUT_SECONDS = 0.25
INTELLIGENCE_PORTS = {
    22: "SSH",
    53: "DNS",
    80: "HTTP",
    139: "NetBIOS",
    443: "HTTPS",
    445: "SMB",
    515: "LPD",
    554: "RTSP",
    631: "IPP",
    2049: "NFS",
    3389: "RDP",
    5000: "NAS-Web",
    5001: "NAS-Web-TLS",
    9100: "JetDirect",
}
PRINTER_PORTS = frozenset({515, 631, 9100})
NAS_PORTS = frozenset({2049, 5000, 5001})
WEB_PORTS = frozenset({80, 443})
COMPUTER_PORTS = frozenset({22, 3389})
ROUTER_HOSTNAME_HINTS = ("router", "gateway", "fritz", "livebox", "homebox")
NAS_HOSTNAME_HINTS = ("nas", "synology", "qnap", "diskstation")
PRINTER_HOSTNAME_HINTS = ("printer", "epson", "brother", "canon", "hp-", "xerox")
CAMERA_HOSTNAME_HINTS = ("camera", "cam", "hikvision", "reolink", "dahua", "axis")


def _is_local_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local


def _probe_port(ip: str, port: int, timeout: float = INTELLIGENCE_PORT_TIMEOUT_SECONDS) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def probe_intelligence_ports(
    ip: str,
    *,
    timeout: float = INTELLIGENCE_PORT_TIMEOUT_SECONDS,
    probe_func=None,
) -> tuple[int, ...]:
    if not _is_local_ip(ip):
        raise ValueError("Network Intelligence solo admite direcciones IP locales.")
    probe_func = probe_func or _probe_port
    open_ports = [
        port for port in INTELLIGENCE_PORTS if probe_func(ip, port, timeout)
    ]
    return tuple(sorted(open_ports))


def _hostname_contains(hostname: str, hints: tuple[str, ...]) -> bool:
    lowered = (hostname or "").casefold()
    return any(hint in lowered for hint in hints)


def _gateway_style_address(ip: str) -> bool:
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if not isinstance(address, ipaddress.IPv4Address):
        return False
    return int(str(address).split(".")[-1]) in {1, 254}


def classify_device(
    host: DiscoveredHost,
    open_ports: tuple[int, ...],
    *,
    camera: CameraDevice | None = None,
) -> NetworkIntelligenceDevice:
    ports = frozenset(open_ports)
    evidence: list[str] = []
    risk = RiskLevel.LOW

    if camera is not None or 554 in ports or _hostname_contains(host.hostname, CAMERA_HOSTNAME_HINTS):
        evidence.append("Señales compatibles con cámara IP (ONVIF/RTSP/vendor/hostname).")
        if camera is not None:
            evidence.extend(camera.risk_reasons)
            risk = camera.risk
        elif 554 in ports:
            evidence.append("RTSP :554 accesible en la LAN.")
            risk = RiskLevel.MEDIUM
        kind = DeviceKind.CAMERA
    elif ports & PRINTER_PORTS or _hostname_contains(host.hostname, PRINTER_HOSTNAME_HINTS):
        kind = DeviceKind.PRINTER
        evidence.append("Servicios o hostname compatibles con impresora.")
        if 515 in ports or 9100 in ports:
            risk = RiskLevel.MEDIUM
            evidence.append("Servicio de impresión en texto claro accesible en la LAN.")
    elif ports & NAS_PORTS or _hostname_contains(host.hostname, NAS_HOSTNAME_HINTS):
        kind = DeviceKind.NAS
        evidence.append("Servicios o hostname compatibles con NAS.")
        if 5000 in ports or 2049 in ports:
            risk = RiskLevel.MEDIUM
            evidence.append("Servicio NAS sin TLS o NFS accesible en la LAN.")
    elif (
        _hostname_contains(host.hostname, ROUTER_HOSTNAME_HINTS)
        or (_gateway_style_address(host.ip) and 53 in ports and bool(ports & WEB_PORTS))
    ):
        kind = DeviceKind.ROUTER
        evidence.append("Hostname o combinación DNS+Web en dirección típica de gateway.")
        if 80 in ports:
            risk = RiskLevel.MEDIUM
            evidence.append("Interfaz HTTP de administración accesible sin TLS.")
    elif ports & COMPUTER_PORTS or (445 in ports and not ports & NAS_PORTS):
        kind = DeviceKind.PC
        evidence.append("Servicios interactivos/SMB compatibles con estación o servidor.")
    else:
        kind = DeviceKind.UNKNOWN
        evidence.append("No hay señales suficientes para clasificar el dispositivo con confianza.")

    services = tuple(INTELLIGENCE_PORTS[port] for port in open_ports if port in INTELLIGENCE_PORTS)
    return NetworkIntelligenceDevice(
        host=host,
        kind=kind,
        open_ports=tuple(sorted(open_ports)),
        services=services,
        evidence=tuple(dict.fromkeys(evidence)),
        risk=risk,
        camera=camera,
    )


def inspect_host(
    host: DiscoveredHost,
    *,
    onvif_match: OnvifDiscoveryMatch | None = None,
    stop_event: threading.Event | None = None,
    port_probe_func=None,
) -> NetworkIntelligenceDevice | None:
    stop_event = stop_event or threading.Event()
    if stop_event.is_set():
        return None
    if not _is_local_ip(host.ip):
        return None

    open_ports = probe_intelligence_ports(host.ip, probe_func=port_probe_func)
    if stop_event.is_set():
        return None

    camera = None
    if onvif_match is not None or 554 in open_ports:
        camera = probe_camera_host(
            host.ip,
            frozenset({"HTTP", "HTTPS", "RTSP", "ONVIF"}),
            onvif_match=onvif_match,
            timeout=PROBE_TIMEOUT_SECONDS,
        )
    return classify_device(host, open_ports, camera=camera)


def analyze_hosts(
    cidr: str,
    hosts: list[DiscoveredHost],
    *,
    stop_event: threading.Event | None = None,
    max_workers: int = INTELLIGENCE_WORKERS,
    on_device=None,
    on_checked=None,
    discovery_func=discover_onvif_devices,
    inspect_func=inspect_host,
) -> list[NetworkIntelligenceDevice]:
    network = ipaddress.ip_network(cidr, strict=False)
    if not isinstance(network, ipaddress.IPv4Network):
        raise ValueError("Network Intelligence admite actualmente redes IPv4.")
    if not (network.is_private or network.is_loopback or network.is_link_local):
        raise ValueError("Network Intelligence solo admite redes IPv4 locales.")

    stop_event = stop_event or threading.Event()
    onvif_matches = []
    if not stop_event.is_set():
        onvif_matches = discovery_func(network, stop_event=stop_event)
    onvif_by_ip = {match.ip: match for match in onvif_matches}

    candidates = [host for host in hosts if _is_local_ip(host.ip) and ipaddress.ip_address(host.ip) in network]
    workers = max(1, min(max_workers, len(candidates) or 1))
    pending = {}
    results: list[NetworkIntelligenceDevice] = []
    iterator = iter(candidates)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        def fill_pending():
            while not stop_event.is_set() and len(pending) < workers * 2:
                try:
                    host = next(iterator)
                except StopIteration:
                    break
                future = executor.submit(
                    inspect_func,
                    host,
                    onvif_match=onvif_by_ip.get(host.ip),
                    stop_event=stop_event,
                )
                pending[future] = host

        fill_pending()
        while pending:
            done, _ = wait(tuple(pending), return_when=FIRST_COMPLETED)
            for future in done:
                host = pending.pop(future)
                if stop_event.is_set():
                    continue
                try:
                    device = future.result()
                except Exception:
                    device = None
                if on_checked is not None:
                    on_checked(host)
                if device is not None:
                    results.append(device)
                    if on_device is not None:
                        on_device(device)
                fill_pending()
            if stop_event.is_set():
                for future in pending:
                    future.cancel()
                break

    return sorted(results, key=lambda item: ipaddress.ip_address(item.host.ip))
