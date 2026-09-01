from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from pythonkni.camera_auditor.models import RiskLevel

from .models import (
    AssetRecord,
    DeviceKind,
    NetworkRelationship,
    NetworkSecurityScore,
    RelationshipConfidence,
    RelationshipKind,
)

_ROLE_RISK_DEDUCTIONS = {
    DeviceKind.ROUTER: {RiskLevel.HIGH: 4, RiskLevel.MEDIUM: 2},
    DeviceKind.NAS: {RiskLevel.HIGH: 3, RiskLevel.MEDIUM: 1},
}
_GATEWAY_RISK_DEDUCTIONS = {RiskLevel.HIGH: 4, RiskLevel.MEDIUM: 2}
_INFRASTRUCTURE_LINK_DEDUCTIONS = {RiskLevel.HIGH: 2, RiskLevel.MEDIUM: 1}


def _risk_weight(risk: RiskLevel, weights: dict[RiskLevel, int]) -> int:
    return weights.get(risk, 0)


def _contextual_deductions(
    online: list[AssetRecord],
    relationships: list[NetworkRelationship] | tuple[NetworkRelationship, ...],
) -> tuple[int, tuple[str, ...]]:
    if not online:
        return 0, ()

    asset_by_id = {asset.asset_id: asset for asset in online}
    deductions = 0
    findings: list[str] = []

    for kind, weights in _ROLE_RISK_DEDUCTIONS.items():
        affected = [
            asset for asset in online if asset.kind == kind and _risk_weight(asset.risk, weights)
        ]
        role_deduction = sum(_risk_weight(asset.risk, weights) for asset in affected)
        if not role_deduction:
            continue
        deductions += role_deduction
        findings.append(
            f"{len(affected)} elevated-risk {kind.value} asset(s) receive critical-role prioritization "
            f"({role_deduction} contextual deduction)."
        )

    confirmed_gateways = {
        relationship.target_id
        for relationship in relationships
        if relationship.kind == RelationshipKind.DEFAULT_GATEWAY
        and relationship.confidence == RelationshipConfidence.CONFIRMED
        and relationship.target_id in asset_by_id
    }
    elevated_gateways = {
        asset_id
        for asset_id in confirmed_gateways
        if _risk_weight(asset_by_id[asset_id].risk, _GATEWAY_RISK_DEDUCTIONS)
    }
    gateway_deduction = sum(
        _risk_weight(asset_by_id[asset_id].risk, _GATEWAY_RISK_DEDUCTIONS)
        for asset_id in elevated_gateways
    )
    if gateway_deduction:
        deductions += gateway_deduction
        findings.append(
            f"{len(elevated_gateways)} confirmed default-gateway asset(s) have elevated risk "
            f"({gateway_deduction} contextual deduction)."
        )

    infrastructure_ids = {
        asset.asset_id for asset in online if asset.kind == DeviceKind.ROUTER
    } | confirmed_gateways
    linked_risky_assets: set[str] = set()
    for relationship in relationships:
        if (
            relationship.kind != RelationshipKind.PHYSICAL_LINK
            or relationship.confidence != RelationshipConfidence.CONFIRMED
        ):
            continue
        endpoints = (relationship.source_id, relationship.target_id)
        for infrastructure_id, peer_id in (endpoints, endpoints[::-1]):
            if infrastructure_id not in infrastructure_ids or peer_id not in asset_by_id:
                continue
            peer = asset_by_id[peer_id]
            if peer.asset_id == infrastructure_id:
                continue
            if _risk_weight(peer.risk, _INFRASTRUCTURE_LINK_DEDUCTIONS):
                linked_risky_assets.add(peer.asset_id)

    link_deduction = sum(
        _risk_weight(asset_by_id[asset_id].risk, _INFRASTRUCTURE_LINK_DEDUCTIONS)
        for asset_id in linked_risky_assets
    )
    if link_deduction:
        deductions += link_deduction
        findings.append(
            f"{len(linked_risky_assets)} elevated-risk asset(s) have a confirmed physical link to "
            f"router/gateway infrastructure ({link_deduction} contextual deduction)."
        )

    return deductions, tuple(findings)


def calculate_security_score(
    assets: list[AssetRecord],
    *,
    relationships: list[NetworkRelationship] | tuple[NetworkRelationship, ...] = (),
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

    base_deductions = (
        risk_counts[RiskLevel.HIGH] * 15
        + risk_counts[RiskLevel.MEDIUM] * 6
        + len(unknown) * 4
        + len(cameras_with_rtsp) * 4
        + len(cleartext_http) * 2
        + len(new_unknown_today) * 3
    )
    contextual_deductions, contextual_findings = _contextual_deductions(online, relationships)
    score = max(0, min(100, 100 - base_deductions - contextual_deductions))

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
    findings.extend(contextual_findings)
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
