from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from pythonkni.camera_auditor.models import RiskLevel

from .models import AssetRecord, DeviceKind, NetworkSecurityScore


def calculate_security_score(
    assets: list[AssetRecord],
    *,
    now: datetime | None = None,
) -> NetworkSecurityScore:
    now = now or datetime.now(timezone.utc)
    online = [asset for asset in assets if asset.is_online]
    risk_counts = Counter(asset.risk for asset in online)
    unknown = [asset for asset in online if asset.kind == DeviceKind.UNKNOWN]
    cameras_with_rtsp = [
        asset for asset in online if asset.kind == DeviceKind.CAMERA and "RTSP" in asset.services
    ]
    cleartext_http = [asset for asset in online if "HTTP" in asset.services]
    new_unknown_today = [
        asset
        for asset in unknown
        if asset.first_seen.astimezone(timezone.utc).date() == now.astimezone(timezone.utc).date()
    ]

    deductions = (
        risk_counts[RiskLevel.HIGH] * 15
        + risk_counts[RiskLevel.MEDIUM] * 6
        + len(unknown) * 4
        + len(cameras_with_rtsp) * 4
        + len(cleartext_http) * 2
        + len(new_unknown_today) * 3
    )
    score = max(0, min(100, 100 - deductions))

    findings: list[str] = []
    if cameras_with_rtsp:
        findings.append(f"{len(cameras_with_rtsp)} camera(s) expose RTSP on the local network.")
    if cleartext_http:
        findings.append(
            f"{len(cleartext_http)} device(s) expose clear-text HTTP on the local network."
        )
    if new_unknown_today:
        findings.append(f"{len(new_unknown_today)} unknown device(s) appeared today.")
    if risk_counts[RiskLevel.HIGH]:
        findings.append(f"{risk_counts[RiskLevel.HIGH]} high-risk device(s) require review.")
    if not findings:
        findings.append("No critical findings in the current online inventory.")

    return NetworkSecurityScore(
        score=score,
        total_devices=len(online),
        unknown_devices=len(unknown),
        high_risk=risk_counts[RiskLevel.HIGH],
        medium_risk=risk_counts[RiskLevel.MEDIUM],
        low_risk=risk_counts[RiskLevel.LOW],
        findings=tuple(findings),
    )
