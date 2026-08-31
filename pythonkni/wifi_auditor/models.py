from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Severity = Literal["info", "low", "medium", "high", "critical"]


@dataclass(frozen=True, slots=True)
class AccessPoint:
    ssid: str
    bssid: str
    authentication: str
    encryption: str
    signal_percent: int | None = None
    channel: int | None = None
    radio_type: str = ""
    band: str = "Unknown"
    network_type: str = ""


@dataclass(frozen=True, slots=True)
class AuditFinding:
    severity: Severity
    title: str
    detail: str
    recommendation: str
    penalty: int = 0


@dataclass(frozen=True, slots=True)
class AuditReport:
    generated_at: str
    score: int
    access_points: tuple[AccessPoint, ...]
    findings: tuple[AuditFinding, ...]
    limitations: tuple[str, ...]
    evidence_sha256: str
