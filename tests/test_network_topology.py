from __future__ import annotations

from datetime import datetime, timezone

from PyQt5.QtWidgets import QGraphicsRectItem

from pythonkni.camera_auditor.models import RiskLevel
from pythonkni.network.models import DiscoveredHost
from pythonkni.network_intelligence import window
from pythonkni.network_intelligence.models import AssetRecord, DeviceKind, NetworkIntelligenceDevice
from pythonkni.network_intelligence.topology import build_logical_topology
from pythonkni.network_intelligence.topology_view import NetworkTopologyView


def make_asset(
    *,
    asset_id="mac:AA:BB:CC:DD:EE:30",
    ip="192.168.1.30",
    hostname="device.local",
    kind=DeviceKind.PC,
    risk=RiskLevel.LOW,
    online=True,
):
    now = datetime(2026, 8, 31, 18, 0, tzinfo=timezone.utc)
    return AssetRecord(
        asset_id=asset_id,
        scope="192.168.1.0/24",
        ip=ip,
        mac=asset_id.removeprefix("mac:"),
        hostname=hostname,
        vendor="Unknown",
        kind=kind,
        services=("HTTPS",),
        open_ports=(443,),
        evidence=("classified",),
        risk=risk,
        first_seen=now,
        last_seen=now,
        last_change=now,
        is_online=online,
    )


def make_device(asset: AssetRecord) -> NetworkIntelligenceDevice:
    return NetworkIntelligenceDevice(
        host=DiscoveredHost(ip=asset.ip, hostname=asset.hostname, mac=asset.mac),
        kind=asset.kind,
        open_ports=asset.open_ports,
        services=asset.services,
        evidence=asset.evidence,
        risk=asset.risk,
        vendor=asset.vendor,
    )


def test_topology_prefers_online_router_and_keeps_offline_assets():
    router = make_asset(
        asset_id="mac:AA:BB:CC:DD:EE:01",
        ip="192.168.1.1",
        hostname="router.local",
        kind=DeviceKind.ROUTER,
    )
    pc = make_asset()
    nas = make_asset(
        asset_id="mac:AA:BB:CC:DD:EE:40",
        ip="192.168.1.40",
        hostname="diskstation",
        kind=DeviceKind.NAS,
        risk=RiskLevel.MEDIUM,
        online=False,
    )

    graph = build_logical_topology([nas, pc, router])

    assert graph.gateway_node_id == router.asset_id
    assert graph.physical_links_known is False
    assert {node.asset_id for node in graph.nodes if node.asset_id} == {
        router.asset_id,
        pc.asset_id,
        nas.asset_id,
    }
    relationships = {(edge.source_id, edge.target_id) for edge in graph.edges}
    assert ("synthetic:internet", router.asset_id) in relationships
    assert (router.asset_id, pc.asset_id) in relationships
    assert (router.asset_id, nas.asset_id) in relationships
    assert "physical switch" in graph.note


def test_topology_uses_synthetic_lan_when_router_is_not_classified():
    graph = build_logical_topology([make_asset()])

    assert graph.gateway_node_id == "synthetic:lan"
    assert any(node.node_id == "synthetic:lan" and node.synthetic for node in graph.nodes)
    assert any(edge.target_id == "synthetic:lan" for edge in graph.edges)
    assert any(edge.target_id == "mac:AA:BB:CC:DD:EE:30" for edge in graph.edges)


def test_topology_falls_back_to_offline_router_and_handles_invalid_ip():
    router = make_asset(
        asset_id="mac:AA:BB:CC:DD:EE:01",
        ip="not-an-ip",
        hostname="router.local",
        kind=DeviceKind.ROUTER,
        online=False,
    )
    graph = build_logical_topology([router, make_asset()])
    assert graph.gateway_node_id == router.asset_id


def test_topology_view_renders_and_emits_asset_selection(qtbot):
    router = make_asset(
        asset_id="mac:AA:BB:CC:DD:EE:01",
        ip="192.168.1.1",
        hostname="router.local",
        kind=DeviceKind.ROUTER,
    )
    offline = make_asset(online=False, risk=RiskLevel.MEDIUM)
    view = NetworkTopologyView()
    qtbot.addWidget(view)
    selected = []
    view.asset_selected.connect(selected.append)

    view.set_assets([router, offline])

    assert view.graph is not None
    assert view.scene() is not None
    asset_items = [
        item
        for item in view.scene().items()
        if isinstance(item, QGraphicsRectItem) and item.data(0)
    ]
    assert len(asset_items) == 2
    offline_item = next(item for item in asset_items if item.data(0) == offline.asset_id)
    offline_item.setSelected(True)
    assert selected == [offline.asset_id]
    child_text = "\n".join(child.text() for child in offline_item.childItems())
    assert "OFFLINE" in child_text
    assert "MEDIUM" in child_text


def test_topology_view_handles_empty_inventory(qtbot):
    view = NetworkTopologyView()
    qtbot.addWidget(view)
    view.set_assets([])
    assert view.graph is not None
    assert view.graph.gateway_node_id == "synthetic:lan"
    assert len(view.scene().items()) >= 3


def test_network_window_topology_selection_shows_device_profile(qtbot, monkeypatch, tmp_path):
    monkeypatch.setattr(window, "_default_scope", lambda: "192.168.1.0/24")
    monkeypatch.setattr(window, "NETWORK_INTELLIGENCE_DB", tmp_path / "network.sqlite3")
    tool = window.Tool()
    qtbot.addWidget(tool)
    asset = make_asset(
        hostname="diskstation",
        kind=DeviceKind.NAS,
        risk=RiskLevel.MEDIUM,
    )
    tool.inventory.record_device(asset.scope, make_device(asset))

    tool.refresh_inventory()
    tool._topology_asset_selected(asset.asset_id)

    assert tool.tabs.tabText(1) == "Network Topology"
    assert "diskstation" in tool.topology_detail.toPlainText()
    assert "NAS" in tool.topology_detail.toPlainText()
    assert tool.table.currentRow() == 0
