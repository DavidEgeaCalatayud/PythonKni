from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class EndpointScope(str, Enum):
    LOOPBACK = "loopback"
    PRIVATE = "private"
    PUBLIC = "public"
    LINK_LOCAL = "link_local"
    MULTICAST = "multicast"
    UNSPECIFIED = "unspecified"
    UNKNOWN = "unknown"


class EventSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True, slots=True)
class NetworkAdapter:
    name: str
    addresses: tuple[str, ...]
    is_up: bool
    speed_mbps: int
    mtu: int
    bytes_sent: int
    bytes_recv: int


@dataclass(frozen=True, slots=True)
class TrafficCounters:
    timestamp: float
    bytes_sent: int
    bytes_recv: int


@dataclass(frozen=True, slots=True)
class TrafficSample:
    rx_bps: float = 0.0
    tx_bps: float = 0.0

    @property
    def total_bps(self) -> float:
        return self.rx_bps + self.tx_bps


@dataclass(frozen=True, slots=True)
class ConnectionObservation:
    transport: str
    family: str
    local_ip: str
    local_port: int
    remote_ip: str | None
    remote_port: int | None
    status: str
    pid: int | None
    process_name: str
    adapter: str
    scope: EndpointScope
    protocol: str
    hostname: str = ""

    @property
    def is_listener(self) -> bool:
        return self.remote_ip is None and self.local_port > 0

    @property
    def key(self) -> str:
        remote = f"{self.remote_ip or '-'}:{self.remote_port or 0}"
        return (
            f"{self.transport}|{self.pid or 0}|{self.local_ip}:{self.local_port}|"
            f"{remote}|{self.status}"
        )


@dataclass(frozen=True, slots=True)
class MonitorSnapshot:
    timestamp: float
    adapter: str
    traffic: TrafficSample
    connections: tuple[ConnectionObservation, ...]


@dataclass(frozen=True, slots=True)
class AsnInfo:
    asns: tuple[int, ...] = ()
    prefix: str = ""

    @property
    def label(self) -> str:
        if not self.asns:
            return ""
        return ", ".join(f"AS{value}" for value in self.asns)


@dataclass(frozen=True, slots=True)
class KnownAssetRef:
    asset_id: str
    ip: str
    label: str


@dataclass(frozen=True, slots=True)
class ProcessActivity:
    pid: int | None
    process_name: str
    connection_count: int
    external_connections: int
    remote_hosts: tuple[str, ...]
    protocols: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HostActivity:
    ip: str
    hostname: str
    scope: EndpointScope
    connection_count: int
    processes: tuple[str, ...]
    ports: tuple[int, ...]
    known_asset_id: str = ""
    known_asset_label: str = ""
    asn: str = ""
    prefix: str = ""


@dataclass(frozen=True, slots=True)
class MonitorEvent:
    event_id: str
    kind: str
    severity: EventSeverity
    timestamp: float
    title: str
    description: str
    process_name: str = ""
    remote_ip: str = ""
    port: int | None = None
    asset_id: str = ""


@dataclass(frozen=True, slots=True)
class MonitorHistoryPoint:
    timestamp: float
    rx_bps: float
    tx_bps: float
    connections: int
    external_connections: int
    remote_hosts: int


@dataclass(frozen=True, slots=True)
class MonitorUpdate:
    snapshot: MonitorSnapshot
    processes: tuple[ProcessActivity, ...]
    hosts: tuple[HostActivity, ...]
    events: tuple[MonitorEvent, ...]
    history: tuple[MonitorHistoryPoint, ...]


@dataclass(frozen=True, slots=True)
class PcapCaptureResult:
    etl_path: str
    pcapng_path: str
