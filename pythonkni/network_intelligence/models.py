from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class NetworkIntelligenceDevice:
    host: DiscoveredHost
    kind: DeviceKind
    open_ports: tuple[int, ...]
    services: tuple[str, ...]
    evidence: tuple[str, ...]
    risk: RiskLevel = RiskLevel.LOW
    camera: CameraDevice | None = None

    @property
    def can_open_camera(self) -> bool:
        return self.kind == DeviceKind.CAMERA
