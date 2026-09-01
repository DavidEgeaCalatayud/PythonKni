from __future__ import annotations

import threading
from datetime import datetime, timezone

from pythonkni.camera_auditor.models import RiskLevel
from pythonkni.network.models import DiscoveredHost
from pythonkni.network_intelligence import window
from pythonkni.network_intelligence.models import (
    DeviceKind,
    NetworkIntelligenceDevice,
    NetworkRelationship,
    RelationshipConfidence,
    RelationshipKind,
)
from pythonkni.network_intelligence.relationships import INTERNET_NODE_ID, lan_node_id


def make_device(ip, kind, mac):
    return NetworkIntelligenceDevice(
        host=DiscoveredHost(ip=ip, hostname=f"{kind.value.lower()}.local", mac=mac),
        kind=kind,
        open_ports=(80,) if kind == DeviceKind.ROUTER else (3389,),
        services=("HTTP",) if kind == DeviceKind.ROUTER else ("RDP",),
        evidence=("classified",),
        risk=RiskLevel.MEDIUM if kind == DeviceKind.ROUTER else RiskLevel.LOW,
        vendor="Unknown",
    )


class FakeWorker:
    def __init__(self):
        self.cancel_event = threading.Event()
        self.progress = []
        self.cancel_checks = 0

    def report_progress(self, payload):
        self.progress.append(payload)

    def check_cancelled(self):
        self.cancel_checks += 1
        if self.cancel_event.is_set():
            raise RuntimeError("cancelled")


def test_worker_result_contains_gateway_evidence_source(monkeypatch):
    worker = FakeWorker()
    host = DiscoveredHost(
        ip="192.168.1.1",
        hostname="router.local",
        mac="AA:BB:CC:DD:EE:01",
    )
    device = make_device("192.168.1.1", DeviceKind.ROUTER, "AA:BB:CC:DD:EE:01")

    def fake_scan(scope, *, stop_event, on_found, on_checked):
        assert scope == "192.168.1.0/24"
        assert stop_event is worker.cancel_event
        on_found(host)
        on_checked(host.ip)

    def fake_analyze(scope, hosts, *, stop_event, on_device, on_checked):
        assert hosts == [host]
        assert stop_event is worker.cancel_event
        on_checked(host)
        on_device(device)
        return [device]

    monkeypatch.setattr(window, "scan_network_hosts", fake_scan)
    monkeypatch.setattr(window, "analyze_hosts", fake_analyze)
    monkeypatch.setattr(window, "discover_default_gateway", lambda: "192.168.1.1")

    result = window._run_network_intelligence(worker, "192.168.1.0/24")

    assert result == {"devices": [device], "gateway_ip": "192.168.1.1"}
    assert worker.cancel_checks >= 3
    assert any(item.get("phase") == "discovery" for item in worker.progress)
    assert any(item.get("phase") == "classification" for item in worker.progress)


def test_finished_snapshot_persists_confirmed_relationships(qtbot, monkeypatch, tmp_path):
    monkeypatch.setattr(window, "_default_scope", lambda: "192.168.1.0/24")
    monkeypatch.setattr(window, "NETWORK_INTELLIGENCE_DB", tmp_path / "network.sqlite3")
    tool = window.Tool()
    qtbot.addWidget(tool)

    router = make_device("192.168.1.1", DeviceKind.ROUTER, "AA:BB:CC:DD:EE:01")
    pc = make_device("192.168.1.30", DeviceKind.PC, "AA:BB:CC:DD:EE:30")
    tool._scan_finished({"devices": [router, pc], "gateway_ip": "192.168.1.1"})

    relationships = tool.relationship_store.list(scope="192.168.1.0/24")
    assert len(relationships) == 3
    gateway = next(item for item in relationships if item.kind == RelationshipKind.DEFAULT_GATEWAY)
    assert gateway.target_id.endswith("EE:01")
    assert gateway.confidence == RelationshipConfidence.CONFIRMED
    assert tool.relationship_table.rowCount() == 3
    assert "confirmed" in tool.topology_note.text().casefold()
    assert "gateway 192.168.1.1" in tool.status_label.text()


def test_cancelled_scan_keeps_previous_relationship_snapshot(qtbot, monkeypatch, tmp_path):
    monkeypatch.setattr(window, "_default_scope", lambda: "192.168.1.0/24")
    monkeypatch.setattr(window, "NETWORK_INTELLIGENCE_DB", tmp_path / "network.sqlite3")
    tool = window.Tool()
    qtbot.addWidget(tool)
    scope = "192.168.1.0/24"
    relation = NetworkRelationship(
        scope=scope,
        source_id=INTERNET_NODE_ID,
        target_id=lan_node_id(scope),
        kind=RelationshipKind.DEFAULT_GATEWAY,
        confidence=RelationshipConfidence.UNKNOWN,
        evidence=("previous snapshot",),
        observed_at=datetime(2026, 8, 31, 20, 0, tzinfo=timezone.utc),
    )
    tool.relationship_store.replace(scope, [relation])

    tool._scan_cancelled()

    assert tool.relationship_store.list(scope=scope) == [relation]
    status = tool.status_label.text().casefold()
    assert "cancelado" in status
    assert "evidencia de relaciones" in status
    assert "escaneo incompleto" in status


def test_relationship_persistence_failure_is_reported_without_losing_inventory(
    qtbot, monkeypatch, tmp_path
):
    monkeypatch.setattr(window, "_default_scope", lambda: "192.168.1.0/24")
    monkeypatch.setattr(window, "NETWORK_INTELLIGENCE_DB", tmp_path / "network.sqlite3")
    tool = window.Tool()
    qtbot.addWidget(tool)
    errors = []
    monkeypatch.setattr(window, "show_error", lambda *args, **kwargs: errors.append((args, kwargs)))
    monkeypatch.setattr(
        tool.relationship_store,
        "replace",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("db relationship failure")),
    )
    pc = make_device("192.168.1.30", DeviceKind.PC, "AA:BB:CC:DD:EE:30")

    tool._scan_finished({"devices": [pc], "gateway_ip": None})

    assert errors
    assert any(asset.ip == "192.168.1.30" for asset in tool.assets)


def test_relationship_endpoint_labels_cover_synthetic_missing_and_asset(
    qtbot, monkeypatch, tmp_path
):
    monkeypatch.setattr(window, "_default_scope", lambda: "192.168.1.0/24")
    monkeypatch.setattr(window, "NETWORK_INTELLIGENCE_DB", tmp_path / "network.sqlite3")
    tool = window.Tool()
    qtbot.addWidget(tool)
    pc = make_device("192.168.1.30", DeviceKind.PC, "AA:BB:CC:DD:EE:30")
    tool._scan_finished({"devices": [pc], "gateway_ip": None})

    asset = tool.assets[0]
    assert tool._relationship_endpoint_text(INTERNET_NODE_ID) == "Internet / WAN"
    assert tool._relationship_endpoint_text(lan_node_id(asset.scope)).startswith("LAN ")
    assert "192.168.1.30" in tool._relationship_endpoint_text(asset.asset_id)
    assert tool._relationship_endpoint_text("missing") == "missing"
