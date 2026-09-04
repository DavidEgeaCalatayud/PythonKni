from __future__ import annotations

import ipaddress
import json
import socket
import time
from pathlib import Path

import psutil
import requests

from .models import (
    AsnInfo,
    ConnectionObservation,
    EndpointScope,
    MonitorEvent,
    MonitorHistoryPoint,
    MonitorSnapshot,
    NetworkAdapter,
    TrafficCounters,
    TrafficSample,
)

ALL_ADAPTERS = "All adapters"
UNKNOWN_PROCESS = "Unknown"
WILDCARD_ADDRESSES = {"0.0.0.0", "::", ""}
PROTOCOL_PORTS = {
    20: "FTP-DATA",
    21: "FTP",
    22: "SSH",
    23: "TELNET",
    25: "SMTP",
    53: "DNS",
    67: "DHCP",
    68: "DHCP",
    80: "HTTP",
    110: "POP3",
    123: "NTP",
    137: "NETBIOS",
    138: "NETBIOS",
    139: "NETBIOS",
    143: "IMAP",
    161: "SNMP",
    389: "LDAP",
    443: "HTTPS",
    445: "SMB",
    465: "SMTPS",
    514: "SYSLOG",
    587: "SMTP-SUBMISSION",
    636: "LDAPS",
    853: "DNS-TLS",
    993: "IMAPS",
    995: "POP3S",
    1433: "MSSQL",
    3306: "MYSQL",
    3389: "RDP",
    5353: "MDNS",
    5432: "POSTGRESQL",
    6379: "REDIS",
    8080: "HTTP-ALT",
    8443: "HTTPS-ALT",
}


def classify_ip(value: str | None) -> EndpointScope:
    if not value:
        return EndpointScope.UNSPECIFIED
    try:
        address = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return EndpointScope.UNKNOWN
    if address.is_unspecified:
        return EndpointScope.UNSPECIFIED
    if address.is_loopback:
        return EndpointScope.LOOPBACK
    if address.is_link_local:
        return EndpointScope.LINK_LOCAL
    if address.is_multicast:
        return EndpointScope.MULTICAST
    if address.is_private:
        return EndpointScope.PRIVATE
    if address.is_global:
        return EndpointScope.PUBLIC
    return EndpointScope.UNKNOWN


def infer_protocol(transport: str, local_port: int, remote_port: int | None) -> str:
    port = remote_port or local_port
    known = PROTOCOL_PORTS.get(port)
    if known:
        return known
    return transport.upper()


def _adapter_addresses() -> dict[str, tuple[str, ...]]:
    addresses: dict[str, tuple[str, ...]] = {}
    for name, entries in psutil.net_if_addrs().items():
        values = tuple(
            entry.address.split("%", 1)[0]
            for entry in entries
            if entry.family in {socket.AF_INET, socket.AF_INET6} and entry.address
        )
        addresses[name] = values
    return addresses


def list_adapters() -> tuple[NetworkAdapter, ...]:
    address_map = _adapter_addresses()
    stats = psutil.net_if_stats()
    counters = psutil.net_io_counters(pernic=True)
    adapters = []
    for name in sorted(set(address_map) | set(stats) | set(counters), key=str.casefold):
        stat = stats.get(name)
        counter = counters.get(name)
        adapters.append(
            NetworkAdapter(
                name=name,
                addresses=address_map.get(name, ()),
                is_up=bool(stat and stat.isup),
                speed_mbps=max(0, int(stat.speed)) if stat else 0,
                mtu=max(0, int(stat.mtu)) if stat else 0,
                bytes_sent=max(0, int(counter.bytes_sent)) if counter else 0,
                bytes_recv=max(0, int(counter.bytes_recv)) if counter else 0,
            )
        )
    return tuple(adapters)


def _selected_addresses(adapter_name: str, adapters: tuple[NetworkAdapter, ...]) -> set[str]:
    if adapter_name == ALL_ADAPTERS:
        return {address for adapter in adapters for address in adapter.addresses}
    for adapter in adapters:
        if adapter.name == adapter_name:
            return set(adapter.addresses)
    return set()


def _adapter_for_ip(local_ip: str, adapters: tuple[NetworkAdapter, ...]) -> str:
    if local_ip in WILDCARD_ADDRESSES:
        return ALL_ADAPTERS
    for adapter in adapters:
        if local_ip in adapter.addresses:
            return adapter.name
    return "Unknown"


def _endpoint(value: object) -> tuple[str, int]:
    if not value:
        return "", 0
    ip = getattr(value, "ip", None)
    port = getattr(value, "port", None)
    if ip is not None:
        return str(ip).split("%", 1)[0], int(port or 0)
    if isinstance(value, tuple) and len(value) >= 2:
        return str(value[0]).split("%", 1)[0], int(value[1])
    return "", 0


def _process_name(pid: int | None, cache: dict[int, str]) -> str:
    if pid is None:
        return UNKNOWN_PROCESS
    if pid in cache:
        return cache[pid]
    try:
        name = psutil.Process(pid).name() or UNKNOWN_PROCESS
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        name = UNKNOWN_PROCESS
    cache[pid] = name
    return name


def collect_connections(
    adapter_name: str = ALL_ADAPTERS,
    *,
    adapters: tuple[NetworkAdapter, ...] | None = None,
    process_cache: dict[int, str] | None = None,
) -> tuple[ConnectionObservation, ...]:
    adapters = list_adapters() if adapters is None else adapters
    process_cache = {} if process_cache is None else process_cache
    selected = _selected_addresses(adapter_name, adapters)
    observations = []
    for connection in psutil.net_connections(kind="inet"):
        local_ip, local_port = _endpoint(connection.laddr)
        remote_ip, remote_port = _endpoint(connection.raddr)
        if adapter_name != ALL_ADAPTERS and local_ip not in selected | WILDCARD_ADDRESSES:
            continue
        transport = "tcp" if connection.type == socket.SOCK_STREAM else "udp"
        family = "ipv6" if connection.family == socket.AF_INET6 else "ipv4"
        status = str(connection.status or "NONE")
        remote_value = remote_ip or None
        remote_port_value = remote_port or None
        observations.append(
            ConnectionObservation(
                transport=transport,
                family=family,
                local_ip=local_ip,
                local_port=local_port,
                remote_ip=remote_value,
                remote_port=remote_port_value,
                status=status,
                pid=connection.pid,
                process_name=_process_name(connection.pid, process_cache),
                adapter=_adapter_for_ip(local_ip, adapters),
                scope=classify_ip(remote_value),
                protocol=infer_protocol(transport, local_port, remote_port_value),
            )
        )
    return tuple(sorted(observations, key=lambda item: (item.process_name.casefold(), item.key)))


def read_traffic_counters(
    adapter_name: str = ALL_ADAPTERS,
    *,
    adapters: tuple[NetworkAdapter, ...] | None = None,
    timestamp: float | None = None,
) -> TrafficCounters:
    adapters = list_adapters() if adapters is None else adapters
    selected = (
        adapters
        if adapter_name == ALL_ADAPTERS
        else tuple(adapter for adapter in adapters if adapter.name == adapter_name)
    )
    return TrafficCounters(
        timestamp=time.monotonic() if timestamp is None else timestamp,
        bytes_sent=sum(item.bytes_sent for item in selected),
        bytes_recv=sum(item.bytes_recv for item in selected),
    )


def calculate_traffic(previous: TrafficCounters | None, current: TrafficCounters) -> TrafficSample:
    if previous is None:
        return TrafficSample()
    elapsed = current.timestamp - previous.timestamp
    if elapsed <= 0:
        return TrafficSample()
    sent = max(0, current.bytes_sent - previous.bytes_sent)
    received = max(0, current.bytes_recv - previous.bytes_recv)
    return TrafficSample(rx_bps=received / elapsed, tx_bps=sent / elapsed)


def collect_snapshot(
    adapter_name: str,
    previous_counters: TrafficCounters | None,
    *,
    process_cache: dict[int, str] | None = None,
) -> tuple[MonitorSnapshot, TrafficCounters]:
    adapters = list_adapters()
    current = read_traffic_counters(adapter_name, adapters=adapters)
    traffic = calculate_traffic(previous_counters, current)
    connections = collect_connections(
        adapter_name,
        adapters=adapters,
        process_cache=process_cache,
    )
    return (
        MonitorSnapshot(
            timestamp=time.time(),
            adapter=adapter_name,
            traffic=traffic,
            connections=connections,
        ),
        current,
    )


def reverse_dns(ip: str) -> str:
    try:
        hostname, _aliases, _addresses = socket.gethostbyaddr(ip)
    except (socket.herror, socket.gaierror, TimeoutError, OSError):
        return ""
    return hostname.rstrip(".")


RIPESTAT_NETWORK_INFO_URL = "https://stat.ripe.net/data/network-info/data.json"
JSONL_TRIM_BYTES = 8 * 1024 * 1024
JSONL_MAX_RECORDS = 10_000


def lookup_asn(ip: str, *, timeout: float = 3.0) -> AsnInfo:
    if classify_ip(ip) is not EndpointScope.PUBLIC:
        return AsnInfo()
    try:
        response = requests.get(
            RIPESTAT_NETWORK_INFO_URL,
            params={"resource": ip, "sourceapp": "pythonkni-network-monitor"},
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError, TypeError):
        return AsnInfo()
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    raw_asns = data.get("asns", []) if isinstance(data, dict) else []
    asns = []
    if isinstance(raw_asns, list):
        for value in raw_asns:
            try:
                number = int(value)
            except (TypeError, ValueError):
                continue
            if number > 0 and number not in asns:
                asns.append(number)
    prefix = str(data.get("prefix") or "") if isinstance(data, dict) else ""
    return AsnInfo(asns=tuple(asns), prefix=prefix)


def _append_jsonl_bounded(path: Path, records: tuple[dict[str, object], ...]) -> None:
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    try:
        oversized = path.stat().st_size > JSONL_TRIM_BYTES
    except OSError:
        return
    if not oversized:
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()[-JSONL_MAX_RECORDS:]
        temporary = path.with_suffix(path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(lines) + "\n")
        temporary.replace(path)
    except OSError:
        return


def append_history_jsonl(path: Path, point: MonitorHistoryPoint) -> None:
    _append_jsonl_bounded(
        path,
        (
            {
                "timestamp": point.timestamp,
                "rx_bps": point.rx_bps,
                "tx_bps": point.tx_bps,
                "connections": point.connections,
                "external_connections": point.external_connections,
                "remote_hosts": point.remote_hosts,
            },
        ),
    )


def append_events_jsonl(path: Path, events: tuple[MonitorEvent, ...]) -> None:
    _append_jsonl_bounded(
        path,
        tuple(
            {
                "event_id": event.event_id,
                "kind": event.kind,
                "severity": event.severity.value,
                "timestamp": event.timestamp,
                "title": event.title,
                "description": event.description,
                "process_name": event.process_name,
                "remote_ip": event.remote_ip,
                "port": event.port,
                "asset_id": event.asset_id,
            }
            for event in events
        ),
    )
