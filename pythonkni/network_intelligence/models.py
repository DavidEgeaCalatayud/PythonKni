from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from pythonkni.camera_auditor.models import CameraDevice, RiskLevel
from pythonkni.network.models import DiscoveredHost


class DeviceKind(str, Enum):
    PC = "PC"
    ROUTER = "Router"
    PRINTER = "Printer"
    NAS = "NAS"
    CAMERA = "Camera"
    UNKNOWN = "Unknown"


class ClassificationConfidenceLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


@dataclass(frozen=True, slots=True)
class ClassificationSignal:
    key: str
    label: str
    weight: int
    matched: bool
    evidence: str

    @property
    def contribution(self) -> int:
        return self.weight if self.matched else 0


class RelationshipConfidence(str, Enum):
    CONFIRMED = "CONFIRMED"
    INFERRED = "INFERRED"
    UNKNOWN = "UNKNOWN"


class RelationshipKind(str, Enum):
    DEFAULT_GATEWAY = "Default gateway"
    LAN_MEMBERSHIP = "LAN membership"
    SAME_SCOPE = "Same local scope"
    PHYSICAL_LINK = "Physical link"


@dataclass(frozen=True, slots=True)
class NetworkIntelligenceDevice:
    host: DiscoveredHost
    kind: DeviceKind
    open_ports: tuple[int, ...]
    services: tuple[str, ...]
    evidence: tuple[str, ...]
    risk: RiskLevel = RiskLevel.LOW
    camera: CameraDevice | None = None
    vendor: str = "Unknown"
    classification_confidence: int = 0
    classification_signals: tuple[ClassificationSignal, ...] = ()

    @property
    def can_open_camera(self) -> bool:
        return self.kind == DeviceKind.CAMERA


@dataclass(frozen=True, slots=True)
class AssetRecord:
    asset_id: str
    scope: str
    ip: str
    mac: str
    hostname: str
    vendor: str
    kind: DeviceKind
    services: tuple[str, ...]
    open_ports: tuple[int, ...]
    evidence: tuple[str, ...]
    risk: RiskLevel
    first_seen: datetime
    last_seen: datetime
    last_change: datetime
    is_online: bool
    classification_confidence: int = 0
    classification_signals: tuple[ClassificationSignal, ...] = ()


@dataclass(frozen=True, slots=True)
class NetworkRelationship:
    scope: str
    source_id: str
    target_id: str
    kind: RelationshipKind
    confidence: RelationshipConfidence
    evidence: tuple[str, ...]
    observed_at: datetime
    source_port: str = ""
    target_port: str = ""
    protocol: str = ""


@dataclass(frozen=True, slots=True)
class TimelineEvent:
    event_id: int
    asset_id: str
    scope: str
    created_at: datetime
    event_type: str
    summary: str
    details: str
    ip: str


@dataclass(frozen=True, slots=True)
class NetworkSecurityScore:
    score: int
    total_devices: int
    unknown_devices: int
    high_risk: int
    medium_risk: int
    low_risk: int
    findings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AuditFinding:
    severity: RiskLevel
    title: str
    evidence: str
    recommendation: str


@dataclass(frozen=True, slots=True)
class DeviceAuditReport:
    asset_id: str
    title: str
    risk: RiskLevel
    findings: tuple[AuditFinding, ...]
