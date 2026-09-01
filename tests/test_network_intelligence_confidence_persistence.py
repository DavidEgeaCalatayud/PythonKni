from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from pythonkni.network.models import DiscoveredHost
from pythonkni.network_intelligence.inventory import InventoryStore
from pythonkni.network_intelligence.service import classify_device

SCOPE = "192.168.1.0/24"
NOW = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)


def _create_legacy_assets_table(path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE assets (
                asset_id TEXT PRIMARY KEY,
                scope TEXT NOT NULL,
                ip TEXT NOT NULL,
                mac TEXT NOT NULL,
                hostname TEXT NOT NULL,
                vendor TEXT NOT NULL,
                kind TEXT NOT NULL,
                services_json TEXT NOT NULL,
                ports_json TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                risk TEXT NOT NULL,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                last_change TEXT NOT NULL,
                is_online INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        timestamp = NOW.isoformat()
        connection.execute(
            """
            INSERT INTO assets(
                asset_id, scope, ip, mac, hostname, vendor, kind,
                services_json, ports_json, evidence_json, risk,
                first_seen, last_seen, last_change, is_online
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                "ip:192.168.1.20",
                SCOPE,
                "192.168.1.20",
                "Unknown",
                "device.local",
                "Unknown",
                "Unknown",
                "[]",
                "[]",
                "[]",
                "LOW",
                timestamp,
                timestamp,
                timestamp,
            ),
        )
        connection.commit()


def test_store_migrates_legacy_assets_without_losing_data(tmp_path):
    path = tmp_path / "network.sqlite3"
    _create_legacy_assets_table(path)

    store = InventoryStore(path)
    asset = store.get_asset("ip:192.168.1.20")

    assert asset is not None
    assert asset.ip == "192.168.1.20"
    assert asset.classification_confidence == 0
    assert asset.classification_signals == ()
    with sqlite3.connect(path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(assets)")}
    assert {"classification_confidence", "classification_signals_json"} <= columns


def test_confidence_and_signals_survive_sqlite_round_trip(tmp_path):
    store = InventoryStore(tmp_path / "network.sqlite3")
    device = classify_device(
        DiscoveredHost("192.168.1.20", "device.local", "Unknown"),
        (554,),
    )

    persisted = store.record_device(SCOPE, device, observed_at=NOW)
    reloaded = store.get_asset(persisted.asset_id)

    assert reloaded is not None
    assert reloaded.classification_confidence == 30
    assert reloaded.classification_signals == device.classification_signals
