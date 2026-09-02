from __future__ import annotations

from datetime import datetime, timezone

from pythonkni.network.models import DiscoveredHost
from pythonkni.network_intelligence.inventory import InventoryStore
from pythonkni.network_intelligence.reporting import build_network_report
from pythonkni.network_intelligence.service import classify_device

SCOPE = "192.168.1.0/24"
NOW = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)


def test_oui_vendor_flows_from_classification_to_inventory_and_report(tmp_path):
    device = classify_device(
        DiscoveredHost(
            ip="192.168.1.20",
            hostname="No resuelto",
            mac="00:11:32:12:34:56",
        ),
        (5001,),
    )
    inventory = InventoryStore(tmp_path / "network.sqlite3")

    persisted = inventory.record_device(SCOPE, device, observed_at=NOW)
    report = build_network_report(SCOPE, [persisted], [], [], generated_at=NOW)

    assert persisted.vendor == "Synology Incorporated"
    assert persisted.asset_id == "mac:00:11:32:12:34:56"
    assert report["assets"][0]["vendor"] == "Synology Incorporated"
    assert any(
        "OUI MAC: Synology Incorporated" in item
        for item in report["assets"][0]["evidence"]
    )
