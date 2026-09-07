from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class TraceProtocol(str, Enum):
    ICMP = "icmp"
    UDP = "udp"
    TCP = "tcp"


class AddressFamily(str, Enum):
    AUTO = "system"
    IPV4 = "ipv4"
    IPV6 = "ipv6"


class PathEventSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True, slots=True)
class BackendInfo:
    name: str
    version: str
    executable: Path
    available: bool
    elevated: bool


@dataclass(frozen=True, slots=True)
class TraceRequest:
    target: str
    protocol: TraceProtocol = TraceProtocol.ICMP
    interval_seconds: float = 1.0
    max_ttl: int = 30
    port: int | None = None
    address_family: AddressFamily = AddressFamily.AUTO


@dataclass(frozen=True, slots=True)
class HopHost:
    ip: str
    hostname: str = ""

    @property
    def label(self) -> str:
        return self.hostname or self.ip


@dataclass(frozen=True, slots=True)
class HopProbe:
    ttl: int
    hosts: tuple[HopHost, ...]
    sent: int
    received: int
    loss_pct: float
    last_ms: float | None

    @property
    def responded(self) -> bool:
        return self.received > 0 and bool(self.hosts)

    @property
    def primary_ip(self) -> str:
        return self.hosts[0].ip if self.hosts else ""

    @property
    def primary_hostname(self) -> str:
        return self.hosts[0].hostname if self.hosts else ""

    @property
    def host_ips(self) -> tuple[str, ...]:
        return tuple(host.ip for host in self.hosts)


@dataclass(frozen=True, slots=True)
class TraceSnapshot:
    timestamp: float
    target: str
    target_ip: str
    target_hostname: str
    protocol: TraceProtocol
    port: int | None
    hops: tuple[HopProbe, ...]
    reached_destination: bool

    @property
    def destination_hop(self) -> HopProbe | None:
        for hop in reversed(self.hops):
            if self.target_ip and self.target_ip in hop.host_ips:
                return hop
        return None


@dataclass(frozen=True, slots=True)
class HopStats:
    ttl: int
    hosts: tuple[HopHost, ...]
    sent: int
    received: int
    loss_pct: float
    last_ms: float | None
    avg_ms: float | None
    min_ms: float | None
    max_ms: float | None
    jitter_ms: float | None
    status: str

    @property
    def primary_ip(self) -> str:
        return self.hosts[0].ip if self.hosts else ""

    @property
    def primary_hostname(self) -> str:
        return self.hosts[0].hostname if self.hosts else ""


@dataclass(frozen=True, slots=True)
class PathEvent:
    event_id: str
    kind: str
    severity: PathEventSeverity
    timestamp: float
    title: str
    description: str
    target: str
    hop_ttl: int | None = None
    hop_ip: str = ""


@dataclass(frozen=True, slots=True)
class PathHistoryPoint:
    timestamp: float
    target: str
    destination_rtt_ms: float | None
    destination_loss_pct: float
    hop_count: int
    reached_destination: bool
    issue_hop_ttl: int | None = None


@dataclass(frozen=True, slots=True)
class PathUpdate:
    snapshot: TraceSnapshot
    hops: tuple[HopStats, ...]
    events: tuple[PathEvent, ...]
    history: tuple[PathHistoryPoint, ...]
    issue_hop_ttl: int | None = None
