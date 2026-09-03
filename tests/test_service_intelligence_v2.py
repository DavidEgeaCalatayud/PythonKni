from __future__ import annotations

import threading
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from pythonkni.camera_auditor.models import RiskLevel
from pythonkni.network import fingerprinting
from pythonkni.network.models import (
    DiscoveredHost,
    SecurityFindingSeverity,
    ServiceFingerprint,
    ServiceSecurityFinding,
    UdpPortState,
)
from pythonkni.network_intelligence import fingerprint_policy
from pythonkni.network_intelligence.fingerprint_policy import FingerprintPolicy
from pythonkni.network_intelligence.fingerprints import (
    device_from_asset,
    persist_asset_fingerprints,
)
from pythonkni.network_intelligence.inventory import InventoryStore
from pythonkni.network_intelligence.models import AssetRecord, DeviceKind
from pythonkni.network_intelligence.score import calculate_security_score

NOW = datetime(2026, 9, 3, 9, 30, tzinfo=timezone.utc)
SCOPE = "192.168.1.0/24"


def _asset(
    asset_id: str = "mac:00:11:22:33:44:55",
    ip: str = "192.168.1.20",
    *,
    ports: tuple[int, ...] = (22, 443),
    services: tuple[str, ...] = ("SSH", "HTTPS"),
    evidence: tuple[str, ...] = (),
    last_change: datetime = NOW,
) -> AssetRecord:
    return AssetRecord(
        asset_id=asset_id,
        scope=SCOPE,
        ip=ip,
        mac="00:11:22:33:44:55",
        hostname="host.local",
        vendor="Example",
        kind=DeviceKind.PC,
        services=services,
        open_ports=ports,
        evidence=evidence,
        risk=RiskLevel.LOW,
        first_seen=NOW - timedelta(days=1),
        last_seen=NOW,
        last_change=last_change,
        is_online=True,
    )


def test_nerva_command_modes_are_explicit_and_transport_bounded():
    base = fingerprinting.build_nerva_command("nerva.exe", "192.0.2.1", [53])
    assert "--udp" not in base
    assert "--sctp" not in base
    assert "--misconfigs" not in base

    udp = fingerprinting.build_nerva_command(
        "nerva.exe", "192.0.2.1", [53], transport="udp"
    )
    assert udp[-1] == "--udp"
    assert "--misconfigs" not in udp

    findings = fingerprinting.build_nerva_command(
        "nerva.exe", "192.0.2.1", [22], misconfigs=True
    )
    assert findings[-1] == "--misconfigs"
    assert "--udp" not in findings

    sctp = fingerprinting.build_nerva_command(
        "nerva", "192.0.2.1", [3868], transport="sctp", system_name="Linux"
    )
    assert sctp[-1] == "--sctp"
    with pytest.raises(fingerprinting.FingerprintCapabilityUnavailable, match="Linux"):
        fingerprinting.build_nerva_command(
            "nerva.exe",
            "192.0.2.1",
            [3868],
            transport="sctp",
            system_name="Windows",
        )
    with pytest.raises(ValueError, match="Transporte"):
        fingerprinting.build_nerva_command(
            "nerva.exe", "192.0.2.1", [80], transport="icmp"
        )
    with pytest.raises(ValueError, match="booleano"):
        fingerprinting.build_nerva_command(
            "nerva.exe", "192.0.2.1", [80], misconfigs="yes"  # type: ignore[arg-type]
        )


def test_transport_available_is_truthful_for_sctp():
    assert fingerprinting.transport_available("tcp", system_name="Windows")
    assert fingerprinting.transport_available("udp", system_name="Windows")
    assert not fingerprinting.transport_available("sctp", system_name="Windows")
    assert fingerprinting.transport_available("sctp", system_name="Linux")
    assert not fingerprinting.transport_available("bogus", system_name="Linux")


def test_nerva_security_findings_are_normalized_into_first_party_models():
    result = fingerprinting.parse_nerva_output(
        '{"host":"node","ip":"192.0.2.4","port":2375,"protocol":"docker",'
        '"security_findings":[{"id":"docker-unauth-api","severity":"critical",'
        '"description":"Docker API accessible without authentication",'
        '"evidence":"queried /version"},{"id":"future","severity":"surprise",'
        '"description":"Future severity"}]}'
    )[0]

    assert result.security_findings == (
        ServiceSecurityFinding(
            finding_id="docker-unauth-api",
            severity=SecurityFindingSeverity.CRITICAL,
            description="Docker API accessible without authentication",
            evidence="queried /version",
        ),
        ServiceSecurityFinding(
            finding_id="future",
            severity=SecurityFindingSeverity.UNKNOWN,
            description="Future severity",
        ),
    )
    assert "security_findings" not in result.metadata

    with pytest.raises(ValueError, match="security_findings"):
        fingerprinting.parse_nerva_output(
            '{"host":"x","port":22,"protocol":"ssh","security_findings":{}}'
        )
    with pytest.raises(ValueError, match="security finding"):
        fingerprinting.parse_nerva_output(
            '{"host":"x","port":22,"protocol":"ssh","security_findings":[3]}'
        )


def test_udp_state_semantics_never_treat_silence_as_closed():
    assert fingerprinting.classify_udp_state(identified=True) is UdpPortState.OPEN
    assert fingerprinting.classify_udp_state(explicitly_closed=True) is UdpPortState.CLOSED
    assert fingerprinting.classify_udp_state(probe_sent=True) is UdpPortState.OPEN_FILTERED
    assert fingerprinting.classify_udp_state() is UdpPortState.UNKNOWN


def test_udp_probe_maps_identified_and_silent_ports(monkeypatch):
    monkeypatch.setattr(fingerprinting.socket, "gethostbyname", lambda _target: "192.0.2.10")
    calls = []

    def fake_fingerprint(target, ports, **kwargs):
        calls.append((target, tuple(ports), kwargs))
        return [
            ServiceFingerprint(
                host=target,
                ip="192.0.2.10",
                port=53,
                protocol="dns",
                transport="udp",
            )
        ]

    monkeypatch.setattr(fingerprinting, "fingerprint_open_ports", fake_fingerprint)
    results = fingerprinting.probe_udp_ports("dns.local", [161, 53, 53])

    assert [(item.port, item.state) for item in results] == [
        (53, UdpPortState.OPEN),
        (161, UdpPortState.OPEN_FILTERED),
    ]
    assert results[0].fingerprint is not None
    assert results[1].fingerprint is None
    assert calls[0][2]["transport"] == "udp"
    assert calls[0][2]["misconfigs"] is False


def test_udp_and_security_findings_persist_without_polluting_tcp_ports(tmp_path):
    store = InventoryStore(tmp_path / "inventory.sqlite3")
    seed = _asset()
    asset = store.record_device(SCOPE, device_from_asset(seed), observed_at=NOW)
    observed = NOW + timedelta(minutes=5)
    finding = ServiceSecurityFinding(
        finding_id="snmp-public-community",
        severity=SecurityFindingSeverity.HIGH,
        description="SNMP community exposure",
        evidence="response obtained without authentication",
    )
    fingerprint = ServiceFingerprint(
        host=asset.hostname,
        ip=asset.ip,
        port=161,
        protocol="snmp",
        transport="udp",
        product="SNMPv2c",
        security_findings=(finding,),
    )

    persisted = persist_asset_fingerprints(
        store, asset, [fingerprint], observed_at=observed
    )

    assert persisted.open_ports == asset.open_ports
    assert persisted.services == asset.services
    assert persisted.risk is asset.risk
    assert any("161/udp: snmp" in item for item in persisted.evidence)
    assert any("Nerva finding [high] snmp-public-community" in item for item in persisted.evidence)
    events = store.list_events(scope=SCOPE)
    assert any(event.event_type == "service_observed" and "161/udp" in event.details for event in events)
    assert any(
        event.event_type == "security_finding" and "snmp-public-community" in event.details
        for event in events
    )

    event_count = len(events)
    repeated = persist_asset_fingerprints(
        store, persisted, [fingerprint], observed_at=observed + timedelta(minutes=1)
    )
    assert repeated.evidence == persisted.evidence
    assert len(store.list_events(scope=SCOPE)) == event_count


def test_security_score_deductions_are_deterministic_bounded_and_do_not_require_risk_change():
    critical_one = "Nerva finding [critical] a on 1/tcp: first"
    critical_two = "Nerva finding [critical] b on 2/tcp: second"
    info = "Nerva finding [info] c on 3/tcp: informational"
    asset = _asset(ports=(), services=(), evidence=(critical_one, critical_two, info))

    score = calculate_security_score([asset], now=NOW)

    assert asset.risk is RiskLevel.LOW
    assert score.score == 80
    assert any("3 persisted service-security finding" in item for item in score.findings)
    assert any("20 bounded deduction" in item for item in score.findings)


def test_non_finding_evidence_does_not_change_security_score():
    asset = _asset(ports=(), services=(), evidence=("ordinary evidence",))
    assert calculate_security_score([asset], now=NOW).score == 100


class _FakeStore:
    def __init__(self, assets):
        self.assets = list(assets)

    def list_assets(self, *, scope=None, online_only=False):
        assert scope == SCOPE
        return [asset for asset in self.assets if not online_only or asset.is_online]


def test_scheduled_fingerprinting_is_tcp_only_bounded_and_never_enables_misconfigs(monkeypatch):
    assets = [
        _asset(asset_id=f"asset-{index}", ip=f"192.168.1.{index + 10}", ports=tuple(range(1, 30)), services=tuple("X" for _ in range(29)))
        for index in range(3)
    ]
    store = _FakeStore(assets)
    calls = []
    persisted = []

    def fake_fingerprint(target, ports, **kwargs):
        calls.append((target, tuple(ports), kwargs))
        return [
            ServiceFingerprint(
                host=target,
                ip=target,
                port=tuple(ports)[0],
                protocol="ssh",
            )
        ]

    monkeypatch.setattr(fingerprint_policy, "fingerprint_open_ports", fake_fingerprint)
    monkeypatch.setattr(
        fingerprint_policy,
        "persist_asset_fingerprints",
        lambda _store, asset, fingerprints: persisted.append((asset, tuple(fingerprints))),
    )

    result = fingerprint_policy.run_scheduled_fingerprinting(
        store, SCOPE, FingerprintPolicy.AUTOMATIC_AFTER_DISCOVERY, max_hosts=2, max_ports_per_host=3
    )

    assert result.selected_assets == 2
    assert result.attempted_assets == 2
    assert result.fingerprinted_assets == 2
    assert len(calls) == 2
    assert all(len(ports) == 3 for _target, ports, _kwargs in calls)
    assert all(kwargs["transport"] == "tcp" for _target, _ports, kwargs in calls)
    assert all(kwargs["misconfigs"] is False for _target, _ports, kwargs in calls)
    assert len(persisted) == 2


def test_scheduled_fingerprint_policy_disabled_manual_changed_only_and_cancel(monkeypatch):
    old = _asset(asset_id="old", ip="192.168.1.20", last_change=NOW - timedelta(hours=2))
    changed = replace(
        _asset(asset_id="changed", ip="192.168.1.21"),
        mac="00:11:22:33:44:66",
        last_change=NOW,
    )
    store = _FakeStore([old, changed])
    calls = []

    monkeypatch.setattr(
        fingerprint_policy,
        "fingerprint_open_ports",
        lambda target, ports, **kwargs: calls.append(target) or [],
    )

    for policy in (FingerprintPolicy.DISABLED, FingerprintPolicy.MANUAL):
        result = fingerprint_policy.run_scheduled_fingerprinting(store, SCOPE, policy)
        assert result.selected_assets == 0
    assert not calls

    result = fingerprint_policy.run_scheduled_fingerprinting(
        store,
        SCOPE,
        FingerprintPolicy.CHANGED_SERVICES_ONLY,
        changed_since=NOW - timedelta(hours=1),
    )
    assert result.selected_assets == 1
    assert calls == [changed.ip]

    stop_event = threading.Event()
    stop_event.set()
    cancelled = fingerprint_policy.run_scheduled_fingerprinting(
        store,
        SCOPE,
        FingerprintPolicy.AUTOMATIC_AFTER_DISCOVERY,
        stop_event=stop_event,
    )
    assert cancelled.cancelled
    assert cancelled.attempted_assets == 0


def test_scheduled_fingerprint_bounds_are_rejected():
    store = _FakeStore([])
    with pytest.raises(ValueError, match="hosts"):
        fingerprint_policy.run_scheduled_fingerprinting(
            store,
            SCOPE,
            FingerprintPolicy.AUTOMATIC_AFTER_DISCOVERY,
            max_hosts=0,
        )
    with pytest.raises(ValueError, match="ports per host"):
        fingerprint_policy.run_scheduled_fingerprinting(
            store,
            SCOPE,
            FingerprintPolicy.AUTOMATIC_AFTER_DISCOVERY,
            max_ports_per_host=0,
        )
