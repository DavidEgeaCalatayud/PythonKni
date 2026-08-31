from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from PyQt5.QtWidgets import QGraphicsLineItem

from pythonkni.camera_auditor.models import RiskLevel
from pythonkni.network.models import DiscoveredHost
from pythonkni.network_intelligence import window
from pythonkni.network_intelligence.models import (
    AssetRecord,
    DeviceKind,
    NetworkIntelligenceDevice,
    NetworkRelationship,
    RelationshipConfidence,
    RelationshipKind,
)
from pythonkni.network_intelligence.physical_import import (
    MAX_PHYSICAL_SNAPSHOT_BYTES,
    load_physical_snapshot_file,
)
from pythonkni.network_intelligence.topology_view import NetworkTopologyView

SCOPE = "192.168.1.0/24"
NOW = datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc)


def make_device(ip: str, kind: DeviceKind, mac: str) -> NetworkIntelligenceDevice:
    return NetworkIntelligenceDevice(
        host=DiscoveredHost(ip=ip, hostname=f"{kind.value.lower()}.local", mac=mac),
        kind=kind,
        open_ports=(80,) if kind == DeviceKind.ROUTER else (3389,),
        services=("HTTP",) if kind == DeviceKind.ROUTER else ("RDP",),
        evidence=("classified",),
        risk=RiskLevel.MEDIUM if kind == DeviceKind.ROUTER else RiskLevel.LOW,
        vendor="Lab Vendor",
    )


def make_asset(ip: str, mac: str, kind: DeviceKind) -> AssetRecord:
    return AssetRecord(
        asset_id=f"mac:{mac}",
        scope=SCOPE,
        ip=ip,
        mac=mac,
        hostname=f"{kind.value.lower()}.local",
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


def snapshot_payload(*, target_mac: str = "AA:BB:CC:DD:EE:30") -> dict:
    return {
        "version": 1,
        "scope": SCOPE,
        "observed_at": "2026-09-01T00:00:00Z",
        "links": [
            {
                "protocol": "LLDP",
                "source": {"mac": "AA:BB:CC:DD:EE:01", "port": "Gi1/0/30"},
                "target": {"mac": target_mac, "port": "eth0"},
                "evidence": ["managed switch export"],
            }
        ],
    }


def build_tool(qtbot, monkeypatch, tmp_path):
    monkeypatch.setattr(window, "_default_scope", lambda: SCOPE)
    monkeypatch.setattr(window, "NETWORK_INTELLIGENCE_DB", tmp_path / "network.sqlite3")
    tool = window.Tool()
    qtbot.addWidget(tool)
    router = make_device("192.168.1.1", DeviceKind.ROUTER, "AA:BB:CC:DD:EE:01")
    pc = make_device("192.168.1.30", DeviceKind.PC, "AA:BB:CC:DD:EE:30")
    tool._scan_finished({"devices": [router, pc], "gateway_ip": "192.168.1.1"})
    return tool


def test_valid_ui_import_persists_and_renders_physical_metadata(qtbot, monkeypatch, tmp_path):
    tool = build_tool(qtbot, monkeypatch, tmp_path)
    snapshot = tmp_path / "physical.json"
    snapshot.write_text(json.dumps(snapshot_payload()), encoding="utf-8")
    monkeypatch.setattr(
        window.QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: (str(snapshot), "JSON files (*.json)"),
    )

    tool.import_physical_evidence()

    relationships = tool.relationship_store.list(scope=SCOPE)
    physical = next(item for item in relationships if item.kind == RelationshipKind.PHYSICAL_LINK)
    assert physical.confidence == RelationshipConfidence.CONFIRMED
    assert physical.protocol == "LLDP"
    assert physical.source_port == "Gi1/0/30"
    assert physical.target_port == "eth0"
    assert tool.relationship_table.columnCount() == 9
    physical_row = next(
        row
        for row in range(tool.relationship_table.rowCount())
        if tool.relationship_table.item(row, 1).text() == RelationshipKind.PHYSICAL_LINK.value
    )
    assert tool.relationship_table.item(physical_row, 2).text() == "LLDP"
    assert tool.relationship_table.item(physical_row, 4).text() == "Gi1/0/30"
    assert tool.relationship_table.item(physical_row, 6).text() == "eth0"
    assert "1 enlace" in tool.status_label.text()


def test_warning_import_is_transactional_and_keeps_previous_physical_snapshot(
    qtbot, monkeypatch, tmp_path
):
    tool = build_tool(qtbot, monkeypatch, tmp_path)
    valid = tmp_path / "valid.json"
    valid.write_text(json.dumps(snapshot_payload()), encoding="utf-8")
    paths = [str(valid)]
    monkeypatch.setattr(
        window.QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: (paths.pop(0), "JSON files (*.json)"),
    )
    tool.import_physical_evidence()
    before = [
        item
        for item in tool.relationship_store.list(scope=SCOPE)
        if item.kind == RelationshipKind.PHYSICAL_LINK
    ]

    invalid = tmp_path / "invalid.json"
    invalid.write_text(
        json.dumps(snapshot_payload(target_mac="AA:BB:CC:DD:EE:99")),
        encoding="utf-8",
    )
    warnings = []
    paths.append(str(invalid))
    monkeypatch.setattr(
        window,
        "show_warning",
        lambda *args, **kwargs: warnings.append((args, kwargs)),
    )

    tool.import_physical_evidence()

    after = [
        item
        for item in tool.relationship_store.list(scope=SCOPE)
        if item.kind == RelationshipKind.PHYSICAL_LINK
    ]
    assert after == before
    assert warnings
    assert "conserva" in tool.status_label.text().casefold()


def test_cancelled_file_dialog_does_not_change_relationships(qtbot, monkeypatch, tmp_path):
    tool = build_tool(qtbot, monkeypatch, tmp_path)
    before = tool.relationship_store.list(scope=SCOPE)
    monkeypatch.setattr(
        window.QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: ("", ""),
    )

    tool.import_physical_evidence()

    assert tool.relationship_store.list(scope=SCOPE) == before


def test_bounded_loader_rejects_oversized_snapshot(tmp_path):
    path = tmp_path / "too-large.json"
    path.write_bytes(b"x" * (MAX_PHYSICAL_SNAPSHOT_BYTES + 1))

    with pytest.raises(ValueError, match="exceeds the 2 MiB limit"):
        load_physical_snapshot_file(path, [], expected_scope=SCOPE)


def test_bounded_loader_rejects_non_utf8_snapshot(tmp_path):
    path = tmp_path / "binary.json"
    path.write_bytes(b"\xff\xfe\xfd")

    with pytest.raises(ValueError, match="UTF-8 JSON"):
        load_physical_snapshot_file(path, [], expected_scope=SCOPE)


def test_topology_tooltip_surfaces_protocol_and_ports(qtbot):
    router = make_asset("192.168.1.1", "AA:BB:CC:DD:EE:01", DeviceKind.ROUTER)
    pc = make_asset("192.168.1.30", "AA:BB:CC:DD:EE:30", DeviceKind.PC)
    relation = NetworkRelationship(
        scope=SCOPE,
        source_id=router.asset_id,
        target_id=pc.asset_id,
        kind=RelationshipKind.PHYSICAL_LINK,
        confidence=RelationshipConfidence.CONFIRMED,
        evidence=("managed switch export",),
        observed_at=NOW,
        source_port="Gi1/0/30",
        target_port="eth0",
        protocol="LLDP",
    )
    view = NetworkTopologyView()
    qtbot.addWidget(view)

    view.set_assets([router, pc], [relation])

    lines = [item for item in view.scene().items() if isinstance(item, QGraphicsLineItem)]
    assert len(lines) == 1
    tooltip = lines[0].toolTip()
    assert "Protocol: LLDP" in tooltip
    assert "Ports: Gi1/0/30 -> eth0" in tooltip
    assert "managed switch export" in tooltip
