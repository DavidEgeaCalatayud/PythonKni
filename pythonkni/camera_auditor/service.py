from __future__ import annotations

import ipaddress
import logging
import re
import socket
import ssl
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from urllib.parse import unquote, urlparse

from .models import (
    AuditProgress,
    CameraDevice,
    CameraServiceFinding,
    OnvifDiscoveryMatch,
    RiskLevel,
)

logger = logging.getLogger(__name__)

MAX_CAMERA_HOSTS = 256
CAMERA_SCAN_WORKERS = 16
PROBE_TIMEOUT_SECONDS = 0.45
ONVIF_DISCOVERY_TIMEOUT_SECONDS = 1.8
PENDING_TASK_FACTOR = 2
WS_DISCOVERY_ADDRESS = "239.255.255.250"
WS_DISCOVERY_PORT = 3702
SUPPORTED_PROTOCOLS = frozenset({"HTTP", "HTTPS", "RTSP", "ONVIF"})

ALLOWED_LAN_NETWORKS = tuple(
    ipaddress.ip_network(value)
    for value in (
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "169.254.0.0/16",
        "127.0.0.0/8",
    )
)

VENDOR_PATTERNS = (
    ("Hikvision", re.compile(r"hikvision|hik-connect", re.I)),
    ("Reolink", re.compile(r"reolink", re.I)),
    ("Dahua", re.compile(r"dahua", re.I)),
    ("Axis", re.compile(r"axis communications|\baxis\b", re.I)),
    ("Hanwha", re.compile(r"hanwha|wisenet", re.I)),
    ("Bosch", re.compile(r"bosch", re.I)),
    ("Uniview", re.compile(r"uniview|unv", re.I)),
    ("Foscam", re.compile(r"foscam", re.I)),
    ("Amcrest", re.compile(r"amcrest", re.I)),
    ("TP-Link/Tapo", re.compile(r"tp-link|\btapo\b", re.I)),
    ("EZVIZ", re.compile(r"ezviz", re.I)),
)


def _usable_host_count(network: ipaddress.IPv4Network) -> int:
    if network.prefixlen >= 31:
        return network.num_addresses
    return max(0, network.num_addresses - 2)


def parse_camera_scope(
    value: str,
    *,
    max_hosts: int = MAX_CAMERA_HOSTS,
    allowed_networks: tuple[ipaddress.IPv4Network, ...] = ALLOWED_LAN_NETWORKS,
) -> ipaddress.IPv4Network:
    try:
        network = ipaddress.ip_network(value.strip(), strict=False)
    except ValueError as error:
        raise ValueError(
            "Introduce una red IPv4 privada en formato CIDR, por ejemplo 192.168.1.0/24."
        ) from error

    if not isinstance(network, ipaddress.IPv4Network):
        raise ValueError("Camera Exposure Auditor admite actualmente redes IPv4.")

    if not any(network.subnet_of(allowed) for allowed in allowed_networks):
        raise ValueError(
            "El alcance debe estar dentro de una red local permitida (RFC1918, link-local o loopback)."
        )

    host_count = _usable_host_count(network)
    if host_count > max_hosts:
        raise ValueError(
            f"El alcance {network.with_prefixlen} contiene {host_count} hosts utilizables. "
            f"Acótalo a un máximo de {max_hosts} hosts por auditoría."
        )
    return network


def normalize_protocols(protocols) -> frozenset[str]:
    normalized = frozenset(str(protocol).strip().upper() for protocol in protocols)
    unsupported = normalized - SUPPORTED_PROTOCOLS
    if unsupported:
        raise ValueError(f"Protocolos no compatibles: {', '.join(sorted(unsupported))}.")
    if not normalized:
        raise ValueError("Selecciona al menos un protocolo para la auditoría.")
    return normalized


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _element_text(element: ET.Element, name: str) -> str:
    for child in element.iter():
        if _local_name(child.tag) == name and child.text:
            return child.text.strip()
    return ""


def _split_xml_tokens(value: str) -> tuple[str, ...]:
    return tuple(token for token in value.split() if token)


def parse_ws_discovery_response(payload: bytes, source_ip: str) -> list[OnvifDiscoveryMatch]:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return []

    matches = []
    for element in root.iter():
        if _local_name(element.tag) != "ProbeMatch":
            continue
        types = _split_xml_tokens(_element_text(element, "Types"))
        scopes = _split_xml_tokens(_element_text(element, "Scopes"))
        xaddrs = _split_xml_tokens(_element_text(element, "XAddrs"))
        endpoint_reference = _element_text(element, "Address")
        matches.append(
            OnvifDiscoveryMatch(
                ip=source_ip,
                endpoint_reference=endpoint_reference,
                types=types,
                scopes=scopes,
                xaddrs=xaddrs,
            )
        )
    return matches


def build_ws_discovery_probe(message_id: str | None = None) -> bytes:
    message_id = message_id or f"uuid:{uuid.uuid4()}"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope" '
        'xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing" '
        'xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery" '
        'xmlns:dn="http://www.onvif.org/ver10/network/wsdl">'
        '<e:Header>'
        f'<w:MessageID>{message_id}</w:MessageID>'
        '<w:To e:mustUnderstand="true">urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>'
        '<w:Action e:mustUnderstand="true">'
        'http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe'
        '</w:Action>'
        '</e:Header>'
        '<e:Body><d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe></e:Body>'
        '</e:Envelope>'
    ).encode("utf-8")


def discover_onvif_devices(
    network: ipaddress.IPv4Network,
    *,
    timeout: float = ONVIF_DISCOVERY_TIMEOUT_SECONDS,
    stop_event: threading.Event | None = None,
    socket_factory=socket.socket,
) -> list[OnvifDiscoveryMatch]:
    stop_event = stop_event or threading.Event()
    deadline = time.monotonic() + max(0.05, timeout)
    discovered: dict[str, OnvifDiscoveryMatch] = {}
    sock = socket_factory(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.settimeout(min(0.25, max(0.05, timeout)))
        sock.sendto(build_ws_discovery_probe(), (WS_DISCOVERY_ADDRESS, WS_DISCOVERY_PORT))
        while not stop_event.is_set() and time.monotonic() < deadline:
            try:
                payload, source = sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            source_ip = source[0]
            for match in parse_ws_discovery_response(payload, source_ip):
                try:
                    candidate_ip = ipaddress.ip_address(match.ip)
                except ValueError:
                    continue
                if candidate_ip not in network:
                    continue
                previous = discovered.get(match.ip)
                if previous is None:
                    discovered[match.ip] = match
                else:
                    discovered[match.ip] = OnvifDiscoveryMatch(
                        ip=match.ip,
                        endpoint_reference=match.endpoint_reference or previous.endpoint_reference,
                        types=tuple(dict.fromkeys(previous.types + match.types)),
                        scopes=tuple(dict.fromkeys(previous.scopes + match.scopes)),
                        xaddrs=tuple(dict.fromkeys(previous.xaddrs + match.xaddrs)),
                    )
    finally:
        sock.close()
    return sorted(discovered.values(), key=lambda item: ipaddress.ip_address(item.ip))


def _read_response(sock, limit: int = 8192) -> bytes:
    chunks = []
    total = 0
    while total < limit:
        try:
            chunk = sock.recv(min(2048, limit - total))
        except (socket.timeout, TimeoutError):
            break
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if b"\r\n\r\n" in b"".join(chunks):
            break
    return b"".join(chunks)


def _parse_headers(response: bytes) -> tuple[str, dict[str, str]]:
    text = response.decode("iso-8859-1", errors="replace")
    lines = text.splitlines()
    status = lines[0].strip() if lines else ""
    headers = {}
    for line in lines[1:]:
        if ":" not in line:
            continue
        name, value = line.split(":", 1)
        headers[name.strip().lower()] = value.strip()
    return status, headers


def probe_http_service(
    ip: str,
    *,
    tls: bool,
    timeout: float = PROBE_TIMEOUT_SECONDS,
    connection_factory=socket.create_connection,
) -> CameraServiceFinding | None:
    protocol = "HTTPS" if tls else "HTTP"
    port = 443 if tls else 80
    raw_sock = None
    wrapped_sock = None
    try:
        raw_sock = connection_factory((ip, port), timeout=timeout)
        raw_sock.settimeout(timeout)
        sock = raw_sock
        if tls:
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            wrapped_sock = context.wrap_socket(raw_sock, server_hostname=ip)
            wrapped_sock.settimeout(timeout)
            sock = wrapped_sock
        request = (
            f"HEAD / HTTP/1.0\r\nHost: {ip}\r\nUser-Agent: PythonKni-CameraAuditor/1.0\r\n"
            "Connection: close\r\n\r\n"
        )
        sock.sendall(request.encode("ascii"))
        response = _read_response(sock)
        if not response:
            return None
        status, headers = _parse_headers(response)
        if not status.upper().startswith("HTTP/"):
            return None
        auth_required = True if status.startswith(("HTTP/1.0 401", "HTTP/1.1 401")) else None
        if "www-authenticate" in headers:
            auth_required = True
        evidence_parts = [part for part in (status, headers.get("server", "")) if part]
        return CameraServiceFinding(
            protocol=protocol,
            port=port,
            endpoint=f"{protocol.lower()}://{ip}:{port}/",
            status=status or "TCP reachable",
            auth_required=auth_required,
            cleartext=not tls,
            evidence=" | ".join(evidence_parts),
        )
    except (OSError, ssl.SSLError, TimeoutError):
        return None
    finally:
        try:
            if wrapped_sock is not None:
                wrapped_sock.close()
            elif raw_sock is not None:
                raw_sock.close()
        except OSError:
            pass


def probe_rtsp_service(
    ip: str,
    *,
    timeout: float = PROBE_TIMEOUT_SECONDS,
    connection_factory=socket.create_connection,
) -> CameraServiceFinding | None:
    port = 554
    sock = None
    try:
        sock = connection_factory((ip, port), timeout=timeout)
        sock.settimeout(timeout)
        request = (
            f"OPTIONS rtsp://{ip}/ RTSP/1.0\r\n"
            "CSeq: 1\r\n"
            "User-Agent: PythonKni-CameraAuditor/1.0\r\n\r\n"
        )
        sock.sendall(request.encode("ascii"))
        response = _read_response(sock)
        status, headers = _parse_headers(response)
        if not status.upper().startswith("RTSP/"):
            return None
        auth_required = True if " 401 " in f" {status} " else None
        if "www-authenticate" in headers:
            auth_required = True
        evidence_parts = [part for part in (status, headers.get("server", "")) if part]
        return CameraServiceFinding(
            protocol="RTSP",
            port=port,
            endpoint=f"rtsp://{ip}:{port}/",
            status=status,
            auth_required=auth_required,
            cleartext=True,
            evidence=" | ".join(evidence_parts),
        )
    except (OSError, TimeoutError):
        return None
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass


def infer_vendor(*evidence: str) -> str:
    combined = " ".join(value for value in evidence if value)
    for vendor, pattern in VENDOR_PATTERNS:
        if pattern.search(combined):
            return vendor
    return "Unknown"


def _scope_value(scopes: tuple[str, ...], key: str) -> str:
    marker = f"/{key}/"
    for scope in scopes:
        decoded = unquote(scope)
        if marker in decoded:
            return decoded.split(marker, 1)[1].replace("_", " ").strip()
    return ""


def _onvif_finding(match: OnvifDiscoveryMatch) -> CameraServiceFinding:
    endpoint = match.xaddrs[0] if match.xaddrs else ""
    port = WS_DISCOVERY_PORT
    if endpoint:
        parsed = urlparse(endpoint)
        if parsed.port:
            port = parsed.port
        elif parsed.scheme == "https":
            port = 443
        elif parsed.scheme == "http":
            port = 80
    return CameraServiceFinding(
        protocol="ONVIF",
        port=port,
        endpoint=endpoint,
        status="WS-Discovery ProbeMatch",
        auth_required=None,
        cleartext=endpoint.lower().startswith("http://") if endpoint else False,
        evidence=" ".join(match.types),
    )


def classify_risk(
    services: tuple[CameraServiceFinding, ...],
    *,
    onvif_match: OnvifDiscoveryMatch | None = None,
) -> tuple[RiskLevel, tuple[str, ...]]:
    reasons = []
    if any(item.protocol == "HTTP" and item.cleartext for item in services):
        reasons.append("Interfaz HTTP disponible sin cifrado de transporte.")
    if any(item.protocol == "RTSP" for item in services):
        reasons.append("Servicio RTSP expuesto en la red local.")
    if onvif_match and any(xaddr.lower().startswith("http://") for xaddr in onvif_match.xaddrs):
        reasons.append("ONVIF anuncia un endpoint HTTP sin TLS.")

    if reasons:
        return RiskLevel.MEDIUM, tuple(dict.fromkeys(reasons))
    return RiskLevel.LOW, ("No se detectaron exposiciones de transporte claras con estas sondas.",)


def probe_camera_host(
    ip: str,
    protocols: frozenset[str],
    *,
    onvif_match: OnvifDiscoveryMatch | None = None,
    timeout: float = PROBE_TIMEOUT_SECONDS,
) -> CameraDevice | None:
    findings = []
    if onvif_match is not None and "ONVIF" in protocols:
        findings.append(_onvif_finding(onvif_match))
    if "HTTP" in protocols:
        finding = probe_http_service(ip, tls=False, timeout=timeout)
        if finding is not None:
            findings.append(finding)
    if "HTTPS" in protocols:
        finding = probe_http_service(ip, tls=True, timeout=timeout)
        if finding is not None:
            findings.append(finding)
    if "RTSP" in protocols:
        finding = probe_rtsp_service(ip, timeout=timeout)
        if finding is not None:
            findings.append(finding)

    evidence = [item.evidence for item in findings]
    if onvif_match is not None:
        evidence.extend(onvif_match.scopes)
        evidence.extend(onvif_match.types)
    vendor = infer_vendor(*evidence)
    has_rtsp = any(item.protocol == "RTSP" for item in findings)
    if onvif_match is None and not has_rtsp and vendor == "Unknown":
        return None

    scopes = onvif_match.scopes if onvif_match else ()
    name = _scope_value(scopes, "name")
    hardware = _scope_value(scopes, "hardware")
    risk, reasons = classify_risk(tuple(findings), onvif_match=onvif_match)
    confidence = "Alta" if onvif_match is not None or has_rtsp else "Media"
    return CameraDevice(
        ip=ip,
        vendor=vendor,
        name=name,
        hardware=hardware,
        services=tuple(findings),
        onvif=onvif_match is not None,
        confidence=confidence,
        risk=risk,
        risk_reasons=reasons,
        onvif_scopes=scopes,
        onvif_xaddrs=onvif_match.xaddrs if onvif_match else (),
    )


def _bounded_results(items, executor, submit_item, stop_event, max_pending):
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


def audit_camera_exposure(
    scope: str,
    protocols,
    *,
    stop_event: threading.Event | None = None,
    max_workers: int = CAMERA_SCAN_WORKERS,
    timeout: float = PROBE_TIMEOUT_SECONDS,
    on_progress=None,
    discovery_func=discover_onvif_devices,
    host_probe_func=probe_camera_host,
) -> list[CameraDevice]:
    network = parse_camera_scope(scope)
    protocols = normalize_protocols(protocols)
    stop_event = stop_event or threading.Event()
    onvif_matches = []
    if "ONVIF" in protocols and not stop_event.is_set():
        if on_progress is not None:
            on_progress(AuditProgress("status", 0, _usable_host_count(network), "Buscando ONVIF..."))
        onvif_matches = discovery_func(network, stop_event=stop_event)
    onvif_by_ip = {match.ip: match for match in onvif_matches}

    hosts = [str(host) for host in network.hosts()]
    total = len(hosts)
    workers = max(1, min(max_workers, total or 1))
    pending_limit = workers * PENDING_TASK_FACTOR
    checked = 0
    devices: dict[str, CameraDevice] = {}

    with ThreadPoolExecutor(max_workers=workers) as executor:
        results = _bounded_results(
            hosts,
            executor,
            lambda ip: host_probe_func(
                ip,
                protocols,
                onvif_match=onvif_by_ip.get(ip),
                timeout=timeout,
            ),
            stop_event,
            pending_limit,
        )
        for ip, future in results:
            if stop_event.is_set():
                break
            checked += 1
            try:
                device = future.result()
            except Exception:
                logger.exception("Camera probe failed for %s", ip)
                device = None
            if device is not None:
                devices[device.ip] = device
                if on_progress is not None:
                    on_progress(AuditProgress("device", checked, total, device=device))
            elif on_progress is not None:
                on_progress(AuditProgress("progress", checked, total))

    return sorted(devices.values(), key=lambda item: ipaddress.ip_address(item.ip))
