from __future__ import annotations

import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from pythonkni.camera_auditor.models import RiskLevel
from pythonkni.network_intelligence.models import (
    AssetRecord,
    DeviceKind,
    NetworkRelationship,
    RelationshipConfidence,
    RelationshipKind,
)
from pythonkni.network_intelligence.relationship_store import RelationshipStore
from pythonkni.network_intelligence.relationships import (
    INTERNET_NODE_ID,
    build_relationships,
    discover_default_gateway,
    discover_relationships,
    lan_node_id,
    parse_posix_default_gateway,
    parse_windows_default_gateway,
)


def make_asset(
    *,
    asset_id="mac:AA:BB:CC:DD:EE:30",
    ip="192.168.1.30",
    mac="AA:BB:CC:DD:EE:30",
    hostname="device.local",
    kind=DeviceKind.PC,
    online=True,
    scope="192.168.1.0/24",
):
    now = datetime(2026, 8, 31, 20, 0, tzinfo=timezone.utc)
    return AssetRecord(
        asset_id=asset_id,
        scope=scope,
        ip=ip,
        mac=mac,
        hostname=hostname,
        vendor="Unknown",
        kind=kind,
        services=("HTTPS",),
        open_ports=(443,),
        evidence=("classified",),
        risk=RiskLevel.LOW,
        first_seen=now,
        last_seen=now,
        last_change=now,
        is_online=online,
    )


def test_parse_windows_default_gateway_chooses_lowest_metric():
    output = """
    Network Destination        Netmask          Gateway       Interface  Metric
              0.0.0.0          0.0.0.0      192.168.1.254    192.168.1.30     50
              0.0.0.0          0.0.0.0        192.168.1.1    192.168.1.30     25
    """
    assert parse_windows_default_gateway(output) == "192.168.1.1"


def test_parse_windows_default_gateway_ignores_invalid_rows_and_metric():
    output = """
    0.0.0.0 0.0.0.0 On-link 192.168.1.30 metric
    0.0.0.0 0.0.0.0 192.168.1.1 192.168.1.30 metric
    """
    assert parse_windows_default_gateway(output) == "192.168.1.1"
    assert parse_windows_default_gateway("no route") is None


def test_parse_posix_default_gateway_handles_via_and_invalid_rows():
    assert parse_posix_default_gateway("default via 192.168.1.1 dev eth0") == "192.168.1.1"
    assert parse_posix_default_gateway("default dev eth0") is None
    assert parse_posix_default_gateway("default via invalid dev eth0") is None


def test_discover_default_gateway_uses_expected_local_commands():
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="0.0.0.0 0.0.0.0 192.168.1.1 192.168.1.20 25")

    assert discover_default_gateway(command_runner=runner, system_name="Windows") == "192.168.1.1"
    assert calls[0][0] == ["route", "print", "-4", "0.0.0.0"]
    assert calls[0][1]["timeout"] == 2

    def posix_runner(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="default via 10.0.0.1 dev eth0")

    assert discover_default_gateway(command_runner=posix_runner, system_name="Linux") == "10.0.0.1"
    assert calls[-1][0] == ["ip", "route", "show", "default"]


def test_discover_default_gateway_degrades_to_none_on_command_failures():
    assert (
        discover_default_gateway(
            command_runner=lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout=""),
            system_name="Windows",
        )
        is None
    )

    def raises(*args, **kwargs):
        raise OSError("missing")

    assert discover_default_gateway(command_runner=raises, system_name="Windows") is None

    def times_out(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 2)

    assert discover_default_gateway(command_runner=times_out, system_name="Windows") is None


def test_build_relationships_confirms_os_gateway_and_online_membership():
    router = make_asset(
        asset_id="mac:AA:BB:CC:DD:EE:01",
        ip="192.168.1.1",
        mac="AA:BB:CC:DD:EE:01",
        hostname="router.local",
        kind=DeviceKind.ROUTER,
    )
    pc = make_asset()
    relationships = build_relationships(router.scope, [router, pc], gateway_ip="192.168.1.1")
    lan_id = lan_node_id(router.scope)

    gateway = next(item for item in relationships if item.kind == RelationshipKind.DEFAULT_GATEWAY)
    pc_link = next(item for item in relationships if item.target_id == pc.asset_id)

    assert gateway.source_id == INTERNET_NODE_ID
    assert gateway.target_id == router.asset_id
    assert gateway.confidence == RelationshipConfidence.CONFIRMED
    assert any("routing table" in item for item in gateway.evidence)
    assert any(
        item.source_id == router.asset_id
        and item.target_id == lan_id
        and item.confidence == RelationshipConfidence.CONFIRMED
        for item in relationships
    )
    assert pc_link.source_id == lan_id
    assert pc_link.confidence == RelationshipConfidence.CONFIRMED
    assert any("MAC AA:BB:CC:DD:EE:30" in item for item in pc_link.evidence)


def test_build_relationships_marks_offline_asset_unknown_and_skips_out_of_scope():
    offline = make_asset(online=False, mac="Unknown")
    outside = make_asset(
        asset_id="mac:AA:BB:CC:DD:EE:99",
        ip="10.0.0.5",
        mac="AA:BB:CC:DD:EE:99",
    )
    invalid = make_asset(asset_id="ip:invalid", ip="invalid", mac="")

    relationships = build_relationships(
        "192.168.1.0/24",
        [offline, outside, invalid],
        gateway_ip=None,
    )

    gateway = next(item for item in relationships if item.kind == RelationshipKind.DEFAULT_GATEWAY)
    offline_link = next(item for item in relationships if item.target_id == offline.asset_id)
    assert gateway.confidence == RelationshipConfidence.UNKNOWN
    assert "could not be determined" in gateway.evidence[0]
    assert offline_link.confidence == RelationshipConfidence.UNKNOWN
    assert all(outside.asset_id not in (item.source_id, item.target_id) for item in relationships)
    assert all(invalid.asset_id not in (item.source_id, item.target_id) for item in relationships)
    assert not any("MAC" in item for item in offline_link.evidence)


def test_build_relationships_records_unmatched_gateway_as_unknown():
    asset = make_asset()
    relationships = build_relationships(asset.scope, [asset], gateway_ip="192.168.1.1")
    gateway = next(item for item in relationships if item.kind == RelationshipKind.DEFAULT_GATEWAY)
    assert gateway.target_id == lan_node_id(asset.scope)
    assert gateway.confidence == RelationshipConfidence.UNKNOWN
    assert "no online asset" in gateway.evidence[0]


def test_build_relationships_rejects_ipv6_scope():
    with pytest.raises(ValueError):
        build_relationships("2001:db8::/64", [], gateway_ip=None)


def test_discover_relationships_delegates_gateway_discovery():
    asset = make_asset()
    relationships = discover_relationships(
        asset.scope,
        [asset],
        gateway_discovery=lambda: "192.168.1.1",
    )
    gateway = next(item for item in relationships if item.kind == RelationshipKind.DEFAULT_GATEWAY)
    assert gateway.confidence == RelationshipConfidence.UNKNOWN


def test_relationship_store_replaces_snapshots_and_preserves_evidence(tmp_path):
    path = tmp_path / "network.sqlite3"
    store = RelationshipStore(path)
    now = datetime(2026, 8, 31, 20, 0, tzinfo=timezone.utc)
    scope = "192.168.1.0/24"
    first = NetworkRelationship(
        scope=scope,
        source_id=INTERNET_NODE_ID,
        target_id="mac:AA:BB:CC:DD:EE:01",
        kind=RelationshipKind.DEFAULT_GATEWAY,
        confidence=RelationshipConfidence.CONFIRMED,
        evidence=("route table", "asset match"),
        observed_at=now,
    )
    second = NetworkRelationship(
        scope=scope,
        source_id=lan_node_id(scope),
        target_id="mac:AA:BB:CC:DD:EE:30",
        kind=RelationshipKind.LAN_MEMBERSHIP,
        confidence=RelationshipConfidence.INFERRED,
        evidence=("same scope",),
        observed_at=now + timedelta(seconds=1),
    )

    store.replace(scope, [second, first])
    loaded = store.list(scope=scope)

    assert [item.confidence for item in loaded] == [
        RelationshipConfidence.CONFIRMED,
        RelationshipConfidence.INFERRED,
    ]
    assert loaded[0].evidence == ("route table", "asset match")
    assert loaded[0].observed_at == now

    store.replace(scope, [second])
    assert store.list(scope=scope) == [second]


def test_relationship_store_rejects_scope_mismatch_without_replacing(tmp_path):
    store = RelationshipStore(tmp_path / "network.sqlite3")
    relationship = NetworkRelationship(
        scope="10.0.0.0/24",
        source_id=INTERNET_NODE_ID,
        target_id="synthetic:lan:10.0.0.0/24",
        kind=RelationshipKind.DEFAULT_GATEWAY,
        confidence=RelationshipConfidence.UNKNOWN,
        evidence=(),
        observed_at=datetime(2026, 8, 31, 20, 0, tzinfo=timezone.utc),
    )
    with pytest.raises(ValueError):
        store.replace("192.168.1.0/24", [relationship])
    assert store.list(scope="192.168.1.0/24") == []


def test_relationship_store_handles_naive_datetime_and_corrupt_evidence(tmp_path):
    path = tmp_path / "network.sqlite3"
    store = RelationshipStore(path)
    scope = "192.168.1.0/24"
    relationship = NetworkRelationship(
        scope=scope,
        source_id=INTERNET_NODE_ID,
        target_id=lan_node_id(scope),
        kind=RelationshipKind.DEFAULT_GATEWAY,
        confidence=RelationshipConfidence.UNKNOWN,
        evidence=("gateway unavailable",),
        observed_at=datetime(2026, 8, 31, 20, 0),
    )
    store.replace(scope, [relationship])

    connection = sqlite3.connect(path)
    connection.execute(
        "UPDATE network_relationships SET evidence_json = ? WHERE scope = ?",
        ("not-json", scope),
    )
    connection.commit()
    connection.close()

    loaded = store.list(scope=scope)
    assert loaded[0].evidence == ()
    assert loaded[0].observed_at.tzinfo is not None
