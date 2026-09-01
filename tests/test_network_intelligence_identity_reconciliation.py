from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pythonkni.camera_auditor.models import RiskLevel
from pythonkni.network.models import DiscoveredHost
from pythonkni.network_intelligence.inventory import InventoryStore
from pythonkni.network_intelligence.models import (
    DeviceKind,
    NetworkIntelligenceDevice,
    NetworkRelationship,
    RelationshipConfidence,
    RelationshipKind,
)
from pythonkni.network_intelligence.relationship_store import RelationshipStore

SCOPE = "192.168.1.0/24"
IP = "192.168.1.34"
MAC = "AA:BB:CC:DD:EE:FF"
FALLBACK_ID = f"ip:{IP}"
CANONICAL_ID = f"mac:{MAC}"


def device(*, mac: str) -> NetworkIntelligenceDevice:
    return NetworkIntelligenceDevice(
        host=DiscoveredHost(ip=IP, hostname="diskstation", mac=mac),
        kind=DeviceKind.NAS,
        open_ports=(445, 5001),
        services=("SMB", "NAS-Web-TLS"),
        evidence=("classified",),
        risk=RiskLevel.LOW,
        vendor="Synology",
    )


def test_active_ip_fallback_is_promoted_to_mac_without_duplicate(tmp_path):
    store = InventoryStore(tmp_path / "inventory.sqlite3")
    first = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)
    later = first + timedelta(minutes=5)

    initial = store.record_device(SCOPE, device(mac="No disponible"), observed_at=first)
    promoted = store.record_device(SCOPE, device(mac=MAC), observed_at=later)

    assert initial.asset_id == FALLBACK_ID
    assert promoted.asset_id == CANONICAL_ID
    assert promoted.first_seen == first
    assert promoted.last_seen == later
    assert promoted.mac == MAC
    assert store.get_asset(FALLBACK_ID) is None
    assert [asset.asset_id for asset in store.list_assets(scope=SCOPE)] == [CANONICAL_ID]

    events = store.list_events(scope=SCOPE)
    assert sum(event.event_type == "new_device" for event in events) == 1
    assert sum(event.event_type == "asset_identity_reconciled" for event in events) == 1
    assert all(event.asset_id == CANONICAL_ID for event in events)
    assert not any(event.event_type == "device_disappeared" for event in events)


def test_completed_scan_does_not_mark_promoted_fallback_as_disappeared(tmp_path):
    store = InventoryStore(tmp_path / "inventory.sqlite3")
    first = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)
    later = first + timedelta(minutes=5)

    store.record_scan(SCOPE, [device(mac="Unknown")], observed_at=first, complete=True)
    assets = store.record_scan(SCOPE, [device(mac=MAC)], observed_at=later, complete=True)

    assert len(assets) == 1
    assert assets[0].asset_id == CANONICAL_ID
    assert assets[0].is_online is True
    assert not any(
        event.event_type == "device_disappeared"
        for event in store.list_events(scope=SCOPE)
    )


def test_relationship_references_follow_promoted_identity_and_collisions_are_deduplicated(
    tmp_path,
):
    path = tmp_path / "inventory.sqlite3"
    store = InventoryStore(path)
    observed = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)
    store.record_device(SCOPE, device(mac="Unknown"), observed_at=observed)

    relationships = RelationshipStore(path)
    relationships.replace(
        SCOPE,
        [
            NetworkRelationship(
                scope=SCOPE,
                source_id=FALLBACK_ID,
                target_id="peer:one",
                kind=RelationshipKind.SAME_SCOPE,
                confidence=RelationshipConfidence.INFERRED,
                evidence=("fallback",),
                observed_at=observed,
            ),
            NetworkRelationship(
                scope=SCOPE,
                source_id=CANONICAL_ID,
                target_id="peer:one",
                kind=RelationshipKind.SAME_SCOPE,
                confidence=RelationshipConfidence.CONFIRMED,
                evidence=("canonical",),
                observed_at=observed,
            ),
            NetworkRelationship(
                scope=SCOPE,
                source_id="peer:two",
                target_id=FALLBACK_ID,
                kind=RelationshipKind.LAN_MEMBERSHIP,
                confidence=RelationshipConfidence.INFERRED,
                evidence=("target fallback",),
                observed_at=observed,
            ),
            NetworkRelationship(
                scope=SCOPE,
                source_id=FALLBACK_ID,
                target_id=CANONICAL_ID,
                kind=RelationshipKind.DEFAULT_GATEWAY,
                confidence=RelationshipConfidence.UNKNOWN,
                evidence=("becomes self edge",),
                observed_at=observed,
            ),
        ],
    )

    store.record_device(
        SCOPE,
        device(mac=MAC),
        observed_at=observed + timedelta(minutes=1),
    )

    current = relationships.list(scope=SCOPE)
    assert len(current) == 2
    assert any(
        item.source_id == CANONICAL_ID and item.target_id == "peer:one"
        for item in current
    )
    assert any(
        item.source_id == "peer:two" and item.target_id == CANONICAL_ID
        for item in current
    )
    assert not any(
        FALLBACK_ID in {item.source_id, item.target_id}
        for item in current
    )
    assert not any(item.source_id == item.target_id for item in current)


def test_offline_fallback_is_not_merged_into_new_mac_without_historical_fingerprint(
    tmp_path,
):
    path = tmp_path / "inventory.sqlite3"
    store = InventoryStore(path)
    first = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)
    disappeared = first + timedelta(minutes=5)
    mac_seen = disappeared + timedelta(minutes=5)

    store.record_device(SCOPE, device(mac="Unknown"), observed_at=first)
    store.record_scan(SCOPE, [], observed_at=disappeared, complete=True)
    store.record_device(SCOPE, device(mac=MAC), observed_at=mac_seen)

    reopened = InventoryStore(path)
    assets = reopened.list_assets(scope=SCOPE)
    assert {asset.asset_id for asset in assets} == {FALLBACK_ID, CANONICAL_ID}
    assert reopened.get_asset(FALLBACK_ID).is_online is False
    assert reopened.get_asset(CANONICAL_ID).is_online is True
    assert not any(
        event.event_type == "asset_identity_reconciled"
        for event in reopened.list_events(scope=SCOPE)
    )


def test_legacy_duplicate_is_repaired_on_store_initialization(tmp_path):
    path = tmp_path / "inventory.sqlite3"
    store = InventoryStore(path)
    first = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)
    transition = first + timedelta(minutes=5)

    store.record_device(SCOPE, device(mac="Unknown"), observed_at=first)
    store.record_scan(SCOPE, [], observed_at=transition, complete=True)
    store.record_device(SCOPE, device(mac=MAC), observed_at=transition)
    assert {asset.asset_id for asset in store.list_assets(scope=SCOPE)} == {
        FALLBACK_ID,
        CANONICAL_ID,
    }

    repaired = InventoryStore(path)
    assets = repaired.list_assets(scope=SCOPE)
    assert len(assets) == 1
    assert assets[0].asset_id == CANONICAL_ID
    assert assets[0].first_seen == first
    assert assets[0].is_online is True

    events = repaired.list_events(scope=SCOPE)
    assert sum(event.event_type == "new_device" for event in events) == 1
    assert sum(event.event_type == "asset_identity_reconciled" for event in events) == 1
    assert not any(event.event_type == "device_disappeared" for event in events)
    assert all(event.asset_id == CANONICAL_ID for event in events)
