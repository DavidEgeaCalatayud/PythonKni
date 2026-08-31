from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from pythonkni.camera_auditor.models import RiskLevel
from pythonkni.network_intelligence.models import (
    AssetRecord,
    DeviceKind,
    NetworkRelationship,
    RelationshipConfidence,
    RelationshipKind,
)
from pythonkni.network_intelligence.physical_evidence import import_physical_snapshot
from pythonkni.network_intelligence.relationship_store import RelationshipStore
from pythonkni.network_intelligence.relationships import INTERNET_NODE_ID, lan_node_id
from pythonkni.network_intelligence.topology import build_logical_topology


NOW = datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc)
SCOPE = "192.168.1.0/24"


def make_asset(ip: str, mac: str, *, kind: DeviceKind = DeviceKind.PC) -> AssetRecord:
    return AssetRecord(
        asset_id=f"mac:{mac}",
        scope=SCOPE,
        ip=ip,
        mac=mac,
        hostname=f"host-{ip.rsplit('.', 1)[-1]}.local",
        vendor="Lab Vendor",
        kind=kind,
        services=(),
        open_ports=(),
        evidence=("fixture",),
        risk=RiskLevel.LOW,
        first_seen=NOW,
        last_seen=NOW,
        last_change=NOW,
        is_online=True,
    )


def physical_payload(*, source, target, protocol="LLDP", source_port="Gi1/0/1", target_port="eth0"):
    source = dict(source)
    target = dict(target)
    if source_port:
        source["port"] = source_port
    if target_port:
        target["port"] = target_port
    return {
        "version": 1,
        "scope": SCOPE,
        "observed_at": "2026-09-01T00:00:00Z",
        "links": [
            {
                "protocol": protocol,
                "source": source,
                "target": target,
                "evidence": ["exported from managed infrastructure"],
            }
        ],
    }


def test_lldp_snapshot_with_mac_identity_confirms_physical_link():
    switch = make_asset("192.168.1.2", "AA:BB:CC:DD:EE:02", kind=DeviceKind.ROUTER)
    pc = make_asset("192.168.1.30", "AA:BB:CC:DD:EE:30")
    payload = physical_payload(
        source={"mac": switch.mac},
        target={"mac": pc.mac},
    )

    result = import_physical_snapshot(payload, [switch, pc], expected_scope=SCOPE)

    assert result.imported_count == 1
    assert result.warnings == ()
    relation = result.relationships[0]
    assert relation.kind == RelationshipKind.PHYSICAL_LINK
    assert relation.confidence == RelationshipConfidence.CONFIRMED
    assert relation.source_id == switch.asset_id
    assert relation.target_id == pc.asset_id
    assert relation.source_port == "Gi1/0/1"
    assert relation.target_port == "eth0"
    assert relation.protocol == "LLDP"


def test_ip_only_endpoint_keeps_physical_link_inferred():
    switch = make_asset("192.168.1.2", "AA:BB:CC:DD:EE:02", kind=DeviceKind.ROUTER)
    pc = make_asset("192.168.1.30", "AA:BB:CC:DD:EE:30")
    payload = physical_payload(
        source={"asset_id": switch.asset_id},
        target={"ip": pc.ip},
    )

    result = import_physical_snapshot(payload, [switch, pc])

    relation = result.relationships[0]
    assert relation.confidence == RelationshipConfidence.INFERRED
    assert any("IPv4 address" in item for item in relation.evidence)


def test_snapshot_scope_must_match_active_scope():
    switch = make_asset("192.168.1.2", "AA:BB:CC:DD:EE:02")

    with pytest.raises(ValueError, match="does not match the active scope"):
        import_physical_snapshot(
            {"scope": SCOPE, "links": []},
            [switch],
            expected_scope="10.0.0.0/24",
        )


def test_unresolved_endpoint_is_reported_without_importing_link():
    switch = make_asset("192.168.1.2", "AA:BB:CC:DD:EE:02")
    payload = physical_payload(
        source={"mac": switch.mac},
        target={"mac": "AA:BB:CC:DD:EE:99"},
    )

    result = import_physical_snapshot(payload, [switch])

    assert result.relationships == ()
    assert len(result.warnings) == 1
    assert "could not resolve" in result.warnings[0]


def test_conflicting_endpoint_identifiers_are_rejected():
    switch = make_asset("192.168.1.2", "AA:BB:CC:DD:EE:02")
    pc = make_asset("192.168.1.30", "AA:BB:CC:DD:EE:30")
    payload = physical_payload(
        source={"asset_id": switch.asset_id, "mac": pc.mac},
        target={"mac": pc.mac},
    )

    result = import_physical_snapshot(payload, [switch, pc])

    assert result.relationships == ()
    assert "different inventory assets" in result.warnings[0]


def test_mac_table_requires_switch_port():
    switch = make_asset("192.168.1.2", "AA:BB:CC:DD:EE:02")
    pc = make_asset("192.168.1.30", "AA:BB:CC:DD:EE:30")
    payload = physical_payload(
        source={"mac": switch.mac},
        target={"mac": pc.mac},
        protocol="MAC_TABLE",
        source_port="",
        target_port="",
    )

    result = import_physical_snapshot(payload, [switch, pc])

    assert result.relationships == ()
    assert "requires source.port" in result.warnings[0]


def test_duplicate_directed_pair_keeps_first_link_and_warns():
    switch = make_asset("192.168.1.2", "AA:BB:CC:DD:EE:02")
    pc = make_asset("192.168.1.30", "AA:BB:CC:DD:EE:30")
    payload = physical_payload(source={"mac": switch.mac}, target={"mac": pc.mac})
    payload["links"].append(dict(payload["links"][0]))

    result = import_physical_snapshot(payload, [switch, pc])

    assert result.imported_count == 1
    assert len(result.warnings) == 1
    assert "duplicate physical link" in result.warnings[0]


def test_store_migrates_old_relationship_schema(tmp_path):
    path = tmp_path / "network.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE network_relationships (
            scope TEXT NOT NULL,
            source_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            confidence TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            PRIMARY KEY(scope, source_id, target_id, kind)
        )
        """
    )
    connection.commit()
    connection.close()

    store = RelationshipStore(path)

    connection = sqlite3.connect(path)
    columns = {row[1] for row in connection.execute("PRAGMA table_info(network_relationships)")}
    connection.close()
    assert {"source_port", "target_port", "protocol"} <= columns
    assert store.list(scope=SCOPE) == []


def test_logical_and_physical_snapshots_replace_independently(tmp_path):
    store = RelationshipStore(tmp_path / "network.sqlite3")
    lan_id = lan_node_id(SCOPE)
    logical = NetworkRelationship(
        scope=SCOPE,
        source_id=INTERNET_NODE_ID,
        target_id=lan_id,
        kind=RelationshipKind.DEFAULT_GATEWAY,
        confidence=RelationshipConfidence.UNKNOWN,
        evidence=("logical",),
        observed_at=NOW,
    )
    physical = NetworkRelationship(
        scope=SCOPE,
        source_id="mac:AA:BB:CC:DD:EE:02",
        target_id="mac:AA:BB:CC:DD:EE:30",
        kind=RelationshipKind.PHYSICAL_LINK,
        confidence=RelationshipConfidence.CONFIRMED,
        evidence=("physical",),
        observed_at=NOW,
        source_port="Gi1/0/1",
        target_port="eth0",
        protocol="LLDP",
    )

    store.replace_logical(SCOPE, [logical])
    store.replace_physical(SCOPE, [physical])
    store.replace_logical(SCOPE, [logical])

    relationships = store.list(scope=SCOPE)
    assert {item.kind for item in relationships} == {
        RelationshipKind.DEFAULT_GATEWAY,
        RelationshipKind.PHYSICAL_LINK,
    }
    persisted_physical = next(
        item for item in relationships if item.kind == RelationshipKind.PHYSICAL_LINK
    )
    assert persisted_physical.source_port == "Gi1/0/1"
    assert persisted_physical.target_port == "eth0"
    assert persisted_physical.protocol == "LLDP"


def test_topology_marks_confirmed_imported_physical_links():
    switch = make_asset("192.168.1.2", "AA:BB:CC:DD:EE:02", kind=DeviceKind.ROUTER)
    pc = make_asset("192.168.1.30", "AA:BB:CC:DD:EE:30")
    physical = import_physical_snapshot(
        physical_payload(source={"mac": switch.mac}, target={"mac": pc.mac}),
        [switch, pc],
    ).relationships[0]

    topology = build_logical_topology([switch, pc], [physical])

    assert topology.physical_links_known is True
    edge = next(item for item in topology.edges if item.relationship == "Physical link")
    assert edge.source_port == "Gi1/0/1"
    assert edge.target_port == "eth0"
    assert edge.protocol == "LLDP"
    assert "Hybrid topology" in topology.note
