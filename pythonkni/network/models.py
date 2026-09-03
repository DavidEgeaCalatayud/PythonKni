from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping


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


class SecurityFindingSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"
    UNKNOWN = "unknown"


class UdpPortState(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    OPEN_FILTERED = "open|filtered"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ServiceSecurityFinding:
    finding_id: str
    severity: SecurityFindingSeverity
    description: str
    evidence: str = ""


@dataclass(frozen=True)
class ServiceFingerprint:
    host: str
    ip: str
    port: int
    protocol: str
    transport: str = "tcp"
    product: str = ""
    version: str = ""
    metadata: Mapping[str, object] = field(default_factory=dict)
    state: str = "open"
    security_findings: tuple[ServiceSecurityFinding, ...] = ()

    @property
    def endpoint(self) -> str:
        return f"{self.ip or self.host}:{self.port}"


@dataclass(frozen=True)
class UdpProbeResult:
    host: str
    ip: str
    port: int
    state: UdpPortState
    fingerprint: ServiceFingerprint | None = None
