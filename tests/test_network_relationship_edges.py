from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from pythonkni.camera_auditor.models import RiskLevel
from pythonkni.network_intelligence.models import AssetRecord, DeviceKind, RelationshipConfidence
from pythonkni.network_intelligence.relationship_store import RelationshipStore
from pythonkni.network_intelligence.relationships import build_relationships


def make_asset(*, mac="", online=True):
    now = datetime(2026, 8, 31, 20, 30, tzinfo=timezone.utc)
    return AssetRecord(
        asset_id="ip:192.168.1.30" if not mac else f"mac:{mac}",
        scope="192.168.1.0/24",
        ip="192.168.1.30",
        mac=mac,
        hostname="device.local",
        vendor="Unknown",
        kind=DeviceKind.PC,
        services=("HTTPS",),
        open_ports=(443,),
        evidence=("classified",),
        risk=RiskLevel.LOW,
        first_seen=now,
        last_seen=now,
        last_change=now,
        is_online=online,
    )


def test_online_asset_without_valid_neighbor_mac_is_inferred():
    asset = make_asset(mac="No disponible")
    relationships = build_relationships(asset.scope, [asset], gateway_ip=None)
    link = next(item for item in relationships if item.target_id == asset.asset_id)
    assert link.confidence == RelationshipConfidence.INFERRED
    assert any("no valid neighbor MAC" in item for item in link.evidence)


def test_public_scope_is_rejected_by_relationship_builder():
    with pytest.raises(ValueError):
        build_relationships("8.8.8.0/24", [], gateway_ip=None)


def test_relationship_store_parses_legacy_naive_timestamp(tmp_path):
    path = tmp_path / "network.sqlite3"
    store = RelationshipStore(path)
    connection = sqlite3.connect(path)
    connection.execute(
        """
        INSERT INTO network_relationships(
            scope, source_id, target_id, kind, confidence, evidence_json, observed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "192.168.1.0/24",
            "synthetic:internet",
            "synthetic:lan:192.168.1.0/24",
            "Default gateway",
            "UNKNOWN",
            "[]",
            "2026-08-31T20:30:00",
        ),
    )
    connection.commit()
    connection.close()

    loaded = store.list(scope="192.168.1.0/24")
    assert loaded[0].observed_at.tzinfo is not None
