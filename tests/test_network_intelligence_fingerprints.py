from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from pythonkni.camera_auditor.models import RiskLevel
from pythonkni.network.models import DiscoveredHost, ServiceFingerprint
from pythonkni.network_intelligence.fingerprints import (
    device_from_asset,
    enrich_asset_with_fingerprints,
    enrich_device_with_fingerprints,
    persist_asset_fingerprints,
)
from pythonkni.network_intelligence.inventory import InventoryStore
from pythonkni.network_intelligence.models import AssetRecord, DeviceKind, NetworkIntelligenceDevice


def _device() -> NetworkIntelligenceDevice:
    return NetworkIntelligenceDevice(
        host=DiscoveredHost(ip="192.168.1.20", hostname="server.local", mac="00:11:22:33:44:55"),
        kind=DeviceKind.PC,
        open_ports=(22, 443),
        services=("SSH", "HTTPS"),
        evidence=("Base evidence",),
        risk=RiskLevel.MEDIUM,
    )


def _asset() -> AssetRecord:
    observed = datetime(2026, 9, 2, 20, 0, tzinfo=timezone.utc)
    return AssetRecord(
        asset_id="mac:00:11:22:33:44:55",
        scope="192.168.1.0/24",
        ip="192.168.1.20",
        mac="00:11:22:33:44:55",
        hostname="server.local",
        vendor="Example Vendor",
        kind=DeviceKind.PC,
        services=("SSH", "HTTPS"),
        open_ports=(22, 443),
        evidence=("Base evidence",),
        risk=RiskLevel.MEDIUM,
        first_seen=observed,
        last_seen=observed,
        last_change=observed,
        is_online=True,
        classification_confidence=80,
    )


def _persisted_asset(tmp_path) -> tuple[InventoryStore, AssetRecord]:
    seed = _asset()
    store = InventoryStore(tmp_path / "inventory.sqlite3")
    persisted = store.record_device(
        seed.scope,
        device_from_asset(seed),
        observed_at=seed.first_seen,
    )
    return store, persisted


def test_fingerprints_enrich_services_and_evidence_without_changing_risk_or_kind():
    device = _device()
    enriched = enrich_device_with_fingerprints(
        device,
        [
            ServiceFingerprint(
                host="server.local",
                ip="192.168.1.20",
                port=22,
                protocol="ssh",
                product="OpenSSH",
                version="9.8",
            ),
            ServiceFingerprint(
                host="server.local",
                ip="192.168.1.20",
                port=443,
                protocol="https",
                product="nginx",
                version="1.27",
            ),
        ],
    )

    assert enriched.services == ("SSH (OpenSSH 9.8)", "HTTPS (nginx 1.27)")
    assert enriched.kind is device.kind
    assert enriched.risk is device.risk
    assert "Fingerprint de aplicación 22/tcp: ssh — OpenSSH 9.8." in enriched.evidence
    assert "Fingerprint de aplicación 443/tcp: https — nginx 1.27." in enriched.evidence


def test_fingerprints_ignore_other_assets_and_closed_ports():
    device = _device()
    irrelevant = [
        ServiceFingerprint(host="x", ip="192.168.1.99", port=22, protocol="ssh"),
        ServiceFingerprint(host="x", ip="192.168.1.20", port=6379, protocol="redis"),
    ]

    assert enrich_device_with_fingerprints(device, irrelevant) is device


def test_multiple_protocols_on_same_port_are_deterministic_and_existing_fallback_is_preserved():
    device = _device()
    enriched = enrich_device_with_fingerprints(
        device,
        [
            ServiceFingerprint(host="x", ip="192.168.1.20", port=443, protocol="http"),
            ServiceFingerprint(host="x", ip="192.168.1.20", port=443, protocol="https"),
        ],
    )

    assert enriched.services == ("SSH", "HTTP / HTTPS")


def test_device_from_asset_preserves_persisted_inventory_observation():
    asset = _asset()

    device = device_from_asset(asset)

    assert device.host.ip == asset.ip
    assert device.host.hostname == asset.hostname
    assert device.host.mac == asset.mac
    assert device.kind is asset.kind
    assert device.open_ports == asset.open_ports
    assert device.services == asset.services
    assert device.evidence == asset.evidence
    assert device.risk is asset.risk
    assert device.vendor == asset.vendor
    assert device.classification_confidence == asset.classification_confidence


def test_explicit_asset_enrichment_can_add_nerva_identified_port_without_changing_risk():
    asset = _asset()
    enriched = enrich_asset_with_fingerprints(
        asset,
        [
            ServiceFingerprint(
                host="server.local",
                ip=asset.ip,
                port=6379,
                protocol="redis",
                product="Redis",
                version="8.2",
            )
        ],
    )

    assert enriched.open_ports == (22, 443, 6379)
    assert enriched.services == ("SSH", "HTTPS", "REDIS (Redis 8.2)")
    assert enriched.risk is asset.risk
    assert "Fingerprint de aplicación 6379/tcp: redis — Redis 8.2." in enriched.evidence


def test_asset_enrichment_ignores_fingerprints_for_other_ip():
    asset = _asset()

    enriched = enrich_asset_with_fingerprints(
        asset,
        [ServiceFingerprint(host="x", ip="192.168.1.99", port=6379, protocol="redis")],
    )

    assert enriched == device_from_asset(asset)


def test_persisted_fingerprint_change_records_service_timeline_event(tmp_path):
    store, asset = _persisted_asset(tmp_path)
    observed = asset.last_seen + timedelta(minutes=5)

    persisted = persist_asset_fingerprints(
        store,
        asset,
        [
            ServiceFingerprint(
                host=asset.hostname,
                ip=asset.ip,
                port=22,
                protocol="ssh",
                product="OpenSSH",
                version="9.9",
            )
        ],
        observed_at=observed,
    )

    assert persisted.services == ("SSH (OpenSSH 9.9)", "HTTPS")
    assert persisted.risk is asset.risk
    assert persisted.kind is asset.kind
    assert persisted.last_change == observed
    events = store.list_events(scope=asset.scope)
    service_events = [event for event in events if event.event_type == "service_changed"]
    assert len(service_events) == 1
    assert "22/tcp SSH → SSH (OpenSSH 9.9)" in service_events[0].details


def test_persisted_new_nerva_port_uses_normal_port_opened_event(tmp_path):
    store, asset = _persisted_asset(tmp_path)
    observed = asset.last_seen + timedelta(minutes=5)

    persisted = persist_asset_fingerprints(
        store,
        asset,
        [
            ServiceFingerprint(
                host=asset.hostname,
                ip=asset.ip,
                port=6379,
                protocol="redis",
                product="Redis",
                version="8.2",
            )
        ],
        observed_at=observed,
    )

    assert persisted.open_ports == (22, 443, 6379)
    assert persisted.services[-1] == "REDIS (Redis 8.2)"
    assert persisted.last_change == observed
    events = store.list_events(scope=asset.scope)
    assert any(
        event.event_type == "port_opened" and "6379/tcp REDIS (Redis 8.2)" in event.details
        for event in events
    )


def test_persisted_fingerprints_refuse_missing_or_stale_asset(tmp_path):
    store = InventoryStore(tmp_path / "inventory.sqlite3")
    missing = _asset()
    fingerprint = ServiceFingerprint(host="x", ip=missing.ip, port=22, protocol="ssh")

    with pytest.raises(ValueError, match="no longer exists"):
        persist_asset_fingerprints(store, missing, [fingerprint])

    persisted = store.record_device(
        missing.scope,
        device_from_asset(missing),
        observed_at=missing.first_seen,
    )
    changed = NetworkIntelligenceDevice(
        host=DiscoveredHost(ip="192.168.1.21", hostname=persisted.hostname, mac=persisted.mac),
        kind=persisted.kind,
        open_ports=persisted.open_ports,
        services=persisted.services,
        evidence=persisted.evidence,
        risk=persisted.risk,
        vendor=persisted.vendor,
        classification_confidence=persisted.classification_confidence,
        classification_signals=persisted.classification_signals,
    )
    store.record_device(
        missing.scope, changed, observed_at=missing.first_seen + timedelta(minutes=1)
    )

    with pytest.raises(ValueError, match="changed before fingerprints"):
        persist_asset_fingerprints(store, persisted, [fingerprint])


def test_persisted_noop_fingerprint_returns_current_asset_without_new_event(tmp_path):
    store, asset = _persisted_asset(tmp_path)
    before_events = store.list_events(scope=asset.scope)

    result = persist_asset_fingerprints(
        store,
        asset,
        [ServiceFingerprint(host="x", ip="192.168.1.99", port=22, protocol="ssh")],
    )

    assert result == asset
    assert store.list_events(scope=asset.scope) == before_events
