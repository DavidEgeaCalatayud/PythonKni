from __future__ import annotations

from datetime import datetime, timezone

from pythonkni.camera_auditor.models import RiskLevel
from pythonkni.network_intelligence import reporting_window, risk_window, window as base_window
from pythonkni.network_intelligence.models import (
    AssetRecord,
    DeviceKind,
    NetworkRelationship,
    RelationshipConfidence,
    RelationshipKind,
)
from pythonkni.network_intelligence.reporting import build_network_report
from pythonkni.network_intelligence.score import calculate_security_score

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
SCOPE = "192.168.1.0/24"


def asset(
    asset_id: str,
    ip: str,
    *,
    kind: DeviceKind,
    risk: RiskLevel = RiskLevel.LOW,
    online: bool = True,
) -> AssetRecord:
    return AssetRecord(
        asset_id=asset_id,
        scope=SCOPE,
        ip=ip,
        mac="AA:BB:CC:DD:EE:FF",
        hostname=f"{kind.value.lower()}.local",
        vendor="Vendor",
        kind=kind,
        services=(),
        open_ports=(),
        evidence=("classified",),
        risk=risk,
        first_seen=NOW,
        last_seen=NOW,
        last_change=NOW,
        is_online=online,
    )


def relationship(
    source_id: str,
    target_id: str,
    *,
    kind: RelationshipKind,
    confidence: RelationshipConfidence = RelationshipConfidence.CONFIRMED,
) -> NetworkRelationship:
    return NetworkRelationship(
        scope=SCOPE,
        source_id=source_id,
        target_id=target_id,
        kind=kind,
        confidence=confidence,
        evidence=("persisted topology evidence",),
        observed_at=NOW,
    )


def test_low_risk_assets_keep_legacy_score_without_contextual_penalty():
    score = calculate_security_score(
        [asset("nas", "192.168.1.10", kind=DeviceKind.NAS)],
        relationships=(),
        now=NOW,
    )

    assert score.score == 100
    assert score.findings == ("No critical findings in the current online inventory.",)


def test_elevated_nas_risk_receives_critical_role_prioritization():
    score = calculate_security_score(
        [asset("nas", "192.168.1.10", kind=DeviceKind.NAS, risk=RiskLevel.MEDIUM)],
        now=NOW,
    )

    assert score.score == 93
    assert any("NAS" in finding and "critical-role" in finding for finding in score.findings)


def test_confirmed_gateway_context_prioritizes_risky_router():
    router = asset("router", "192.168.1.1", kind=DeviceKind.ROUTER, risk=RiskLevel.MEDIUM)
    gateway = relationship(
        "synthetic:internet",
        router.asset_id,
        kind=RelationshipKind.DEFAULT_GATEWAY,
    )

    score = calculate_security_score([router], relationships=(gateway,), now=NOW)

    assert score.score == 90
    assert any("critical-role" in finding for finding in score.findings)
    assert any("default-gateway" in finding for finding in score.findings)


def test_inferred_gateway_does_not_receive_gateway_penalty():
    router = asset("router", "192.168.1.1", kind=DeviceKind.ROUTER, risk=RiskLevel.MEDIUM)
    gateway = relationship(
        "synthetic:internet",
        router.asset_id,
        kind=RelationshipKind.DEFAULT_GATEWAY,
        confidence=RelationshipConfidence.INFERRED,
    )

    score = calculate_security_score([router], relationships=(gateway,), now=NOW)

    assert score.score == 92
    assert not any("default-gateway" in finding for finding in score.findings)


def test_confirmed_physical_link_adds_bounded_infrastructure_context_once():
    router = asset("router", "192.168.1.1", kind=DeviceKind.ROUTER)
    pc = asset("pc", "192.168.1.20", kind=DeviceKind.PC, risk=RiskLevel.MEDIUM)
    links = (
        relationship(router.asset_id, pc.asset_id, kind=RelationshipKind.PHYSICAL_LINK),
        relationship(pc.asset_id, router.asset_id, kind=RelationshipKind.PHYSICAL_LINK),
    )

    score = calculate_security_score([router, pc], relationships=links, now=NOW)

    assert score.score == 93
    assert any("confirmed physical link" in finding for finding in score.findings)


def test_offline_risky_asset_never_contributes_contextual_penalty():
    router = asset("router", "192.168.1.1", kind=DeviceKind.ROUTER)
    pc = asset("pc", "192.168.1.20", kind=DeviceKind.PC, risk=RiskLevel.HIGH, online=False)
    link = relationship(router.asset_id, pc.asset_id, kind=RelationshipKind.PHYSICAL_LINK)

    score = calculate_security_score([router, pc], relationships=(link,), now=NOW)

    assert score.score == 100


def test_snapshot_report_uses_same_contextual_score_as_live_dashboard():
    router = asset("router", "192.168.1.1", kind=DeviceKind.ROUTER, risk=RiskLevel.MEDIUM)
    gateway = relationship(
        "synthetic:internet",
        router.asset_id,
        kind=RelationshipKind.DEFAULT_GATEWAY,
    )

    report = build_network_report(SCOPE, [router], [gateway], [], generated_at=NOW)

    assert report["security_score"]["score"] == 90
    assert any("default-gateway" in finding for finding in report["security_score"]["findings"])


def test_risk_window_renders_relationship_aware_score(qtbot, monkeypatch, tmp_path):
    monkeypatch.setattr(base_window, "_default_scope", lambda: SCOPE)
    monkeypatch.setattr(base_window, "NETWORK_INTELLIGENCE_DB", tmp_path / "network.sqlite3")
    monkeypatch.setattr(reporting_window, "ensure_app_dirs", lambda: None)
    monkeypatch.setattr(
        reporting_window,
        "NETWORK_INTELLIGENCE_REPORTS_DIR",
        tmp_path / "reports",
    )
    tool = risk_window.Tool()
    qtbot.addWidget(tool)

    router = asset("router", "192.168.1.1", kind=DeviceKind.ROUTER, risk=RiskLevel.MEDIUM)
    gateway = relationship(
        "synthetic:internet",
        router.asset_id,
        kind=RelationshipKind.DEFAULT_GATEWAY,
    )
    monkeypatch.setattr(tool.inventory, "list_assets", lambda **kwargs: [router])
    monkeypatch.setattr(tool.inventory, "list_events", lambda **kwargs: [])
    monkeypatch.setattr(tool.relationship_store, "list", lambda **kwargs: [gateway])

    tool.refresh_inventory()

    assert "90/100" in tool.score_label.text()
    assert "default-gateway" in tool.score_findings.toPlainText()
