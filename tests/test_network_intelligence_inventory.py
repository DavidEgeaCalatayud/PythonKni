from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pythonkni.camera_auditor.models import RiskLevel
from pythonkni.network.models import DiscoveredHost
from pythonkni.network_intelligence.inventory import InventoryStore, asset_identity
from pythonkni.network_intelligence.models import (
    DeviceKind,
    NetworkIntelligenceDevice,
    NetworkRelationship,
    RelationshipConfidence,
    RelationshipKind,
)
from pythonkni.network_intelligence.relationship_store import RelationshipStore


def device(
    *,
    ip="192.168.1.34",
    mac="AA:BB:CC:DD:EE:FF",
    hostname="diskstation",
    kind=DeviceKind.NAS,
    ports=(445, 5001),
    services=("SMB", "NAS-Web-TLS"),
    risk=RiskLevel.LOW,
    vendor="Synology",
):
    return NetworkIntelligenceDevice(
        host=DiscoveredHost(ip=ip, hostname=hostname, mac=mac),
        kind=kind,
        open_ports=ports,
        services=services,
        evidence=("classified",),
        risk=risk,
        vendor=vendor,
    )


def test_asset_identity_prefers_mac_and_falls_back_to_ip():
    assert asset_identity(device()) == "mac:AA:BB:CC:DD:EE:FF"
    assert asset_identity(device(mac="No disponible")) == "ip:192.168.1.34"


def test_new_asset_is_persisted_with_first_and_last_seen(tmp_path):
    store = InventoryStore(tmp_path / "inventory.sqlite3")
    observed = datetime(2026, 8, 31, 17, 0, tzinfo=timezone.utc)

    asset = store.record_device("192.168.1.0/24", device(), observed_at=observed)

    assert asset.ip == "192.168.1.34"
    assert asset.vendor == "Synology"
    assert asset.first_seen == observed
    assert asset.last_seen == observed
    assert asset.is_online is True
    events = store.list_events(scope="192.168.1.0/24")
    assert [event.event_type for event in events] == ["new_device"]


def test_existing_asset_keeps_first_seen_and_tracks_ip_port_and_risk_changes(tmp_path):
    store = InventoryStore(tmp_path / "inventory.sqlite3")
    first = datetime(2026, 8, 31, 17, 0, tzinfo=timezone.utc)
    later = first + timedelta(minutes=10)
    original = device()
    changed = device(
        ip="192.168.1.35",
        ports=(22, 445, 5001),
        services=("SSH", "SMB", "NAS-Web-TLS"),
        risk=RiskLevel.MEDIUM,
    )

    store.record_device("192.168.1.0/24", original, observed_at=first)
    asset = store.record_device("192.168.1.0/24", changed, observed_at=later)

    assert asset.first_seen == first
    assert asset.last_seen == later
    assert asset.ip == "192.168.1.35"
    assert asset.risk == RiskLevel.MEDIUM
    event_types = {event.event_type for event in store.list_events(scope="192.168.1.0/24")}
    assert {"new_device", "ip_changed", "port_opened", "risk_changed"} <= event_types


def test_completed_scan_marks_missing_devices_offline_and_return_is_tracked(tmp_path):
    store = InventoryStore(tmp_path / "inventory.sqlite3")
    first = datetime(2026, 8, 31, 17, 0, tzinfo=timezone.utc)
    second = first + timedelta(minutes=5)
    third = second + timedelta(minutes=5)

    store.record_scan("192.168.1.0/24", [device()], observed_at=first)
    assets = store.record_scan("192.168.1.0/24", [], observed_at=second, complete=True)
    assert assets[0].is_online is False

    assets = store.record_scan("192.168.1.0/24", [device()], observed_at=third, complete=True)
    assert assets[0].is_online is True
    event_types = [event.event_type for event in store.list_events(scope="192.168.1.0/24")]
    assert "device_disappeared" in event_types
    assert "device_returned" in event_types


def test_incomplete_scan_never_marks_unseen_assets_offline(tmp_path):
    store = InventoryStore(tmp_path / "inventory.sqlite3")
    store.record_scan("192.168.1.0/24", [device()])
    assets = store.record_scan("192.168.1.0/24", [], complete=False)
    assert assets[0].is_online is True


def test_inventory_is_separated_by_scope(tmp_path):
    store = InventoryStore(tmp_path / "inventory.sqlite3")
    store.record_device("192.168.1.0/24", device())
    other = device(ip="10.0.0.5", mac="11:22:33:44:55:66", hostname="pc")
    store.record_device("10.0.0.0/24", other)

    first_scope = store.list_assets(scope="192.168.1.0/24")
    second_scope = store.list_assets(scope="10.0.0.0/24")
    assert [asset.ip for asset in first_scope] == ["192.168.1.34"]
    assert [asset.ip for asset in second_scope] == ["10.0.0.5"]


def test_mac_reconciles_prior_ip_fallback_without_duplicate_asset(tmp_path):
    store = InventoryStore(tmp_path / "inventory.sqlite3")
    scope = "192.168.1.0/24"
    first = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)
    later = first + timedelta(minutes=5)

    provisional = store.record_device(scope, device(mac="Unknown"), observed_at=first)
    reconciled = store.record_device(scope, device(), observed_at=later)

    assert provisional.asset_id == "ip:192.168.1.34"
    assert reconciled.asset_id == "mac:AA:BB:CC:DD:EE:FF"
    assert reconciled.first_seen == first
    assert reconciled.last_seen == later
    assets = store.list_assets(scope=scope)
    assert [asset.asset_id for asset in assets] == ["mac:AA:BB:CC:DD:EE:FF"]

    events = store.list_events(scope=scope)
    assert [event.event_type for event in events].count("new_device") == 1
    assert any(event.event_type == "identity_reconciled" for event in events)
    assert all(event.asset_id == "mac:AA:BB:CC:DD:EE:FF" for event in events)


def test_reconciliation_merges_relationship_references_and_evidence(tmp_path):
    database = tmp_path / "inventory.sqlite3"
    store = InventoryStore(database)
    relationships = RelationshipStore(database)
    scope = "192.168.1.0/24"
    first = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)
    later = first + timedelta(minutes=5)
    peer_id = "mac:11:22:33:44:55:66"
    canonical_id = "mac:AA:BB:CC:DD:EE:FF"
    provisional_id = "ip:192.168.1.34"

    store.record_device(scope, device(mac="Unknown"), observed_at=first)
    relationships.replace(
        scope,
        [
            NetworkRelationship(
                scope=scope,
                source_id=provisional_id,
                target_id=peer_id,
                kind=RelationshipKind.PHYSICAL_LINK,
                confidence=RelationshipConfidence.CONFIRMED,
                evidence=("legacy LLDP",),
                observed_at=first,
                source_port="eth0",
                target_port="Gi1/0/1",
                protocol="LLDP",
            ),
            NetworkRelationship(
                scope=scope,
                source_id=canonical_id,
                target_id=peer_id,
                kind=RelationshipKind.PHYSICAL_LINK,
                confidence=RelationshipConfidence.INFERRED,
                evidence=("new observation",),
                observed_at=later,
                protocol="LLDP",
            ),
        ],
    )

    store.record_device(scope, device(), observed_at=later)

    persisted = relationships.list(scope=scope)
    assert len(persisted) == 1
    relationship = persisted[0]
    assert relationship.source_id == canonical_id
    assert relationship.target_id == peer_id
    assert relationship.confidence == RelationshipConfidence.CONFIRMED
    assert relationship.evidence == ("new observation", "legacy LLDP")
    assert relationship.observed_at == later
    assert relationship.source_port == "eth0"
    assert relationship.target_port == "Gi1/0/1"
