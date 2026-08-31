from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


@dataclass(frozen=True, slots=True)
class OnvifDiscoveryMatch:
    ip: str
    endpoint_reference: str = ""
    types: tuple[str, ...] = ()
    scopes: tuple[str, ...] = ()
    xaddrs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CameraServiceFinding:
    protocol: str
    port: int
    endpoint: str = ""
    status: str = ""
    auth_required: bool | None = None
    cleartext: bool = False
    evidence: str = ""


@dataclass(frozen=True, slots=True)
class CameraDevice:
    ip: str
    vendor: str
    name: str
    hardware: str
    services: tuple[CameraServiceFinding, ...]
    onvif: bool
    confidence: str
    risk: RiskLevel
    risk_reasons: tuple[str, ...] = ()
    onvif_scopes: tuple[str, ...] = ()
    onvif_xaddrs: tuple[str, ...] = ()

    @property
    def service_labels(self) -> tuple[str, ...]:
        labels = []
        for finding in self.services:
            label = finding.protocol.upper()
            if label not in labels:
                labels.append(label)
        return tuple(labels)


@dataclass(frozen=True, slots=True)
class AuditProgress:
    kind: str
    checked: int
    total: int
    message: str = ""
    device: CameraDevice | None = None
