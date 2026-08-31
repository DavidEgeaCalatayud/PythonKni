from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from PyQt5.QtWidgets import QTextEdit

from pythonkni.camera_auditor.models import RiskLevel
from pythonkni.network.models import DiscoveredHost
from pythonkni.network_intelligence import inventory, window
from pythonkni.network_intelligence.audit_window import DeviceAuditorDialog
from pythonkni.network_intelligence.auditors import build_device_audit
from pythonkni.network_intelligence.inventory import InventoryStore
from pythonkni.network_intelligence.models import AssetRecord, DeviceKind, NetworkIntelligenceDevice
from pythonkni.network_intelligence.score import calculate_security_score


def make_device(
    *,
    ip="192.168.1.30",
    mac="AA:BB:CC:DD:EE:30",
    hostname="device.local",
    kind=DeviceKind.PC,
    ports=(3389,),
    services=("RDP",),
    risk=RiskLevel.LOW,
    vendor="Unknown",
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


def make_asset(
    *,
    kind=DeviceKind.PC,
    ports=(),
    services=(),
    risk=RiskLevel.LOW,
    online=True,
):
    now = datetime(2026, 8, 31, 17, 0, tzinfo=timezone.utc)
    return AssetRecord(
        asset_id="mac:AA:BB:CC:DD:EE:30",
        scope="192.168.1.0/24",
        ip="192.168.1.30",
        mac="AA:BB:CC:DD:EE:30",
        hostname="device.local",
        vendor="Unknown",
        kind=kind,
        services=services,
        open_ports=ports,
        evidence=("classified",),
        risk=risk,
        first_seen=now,
        last_seen=now,
        last_change=now,
        is_online=online,
    )


def test_inventory_tracks_closed_port_type_change_and_unchanged_refresh(tmp_path):
    store = InventoryStore(tmp_path / "inventory.sqlite3")
    first = datetime(2026, 8, 31, 17, 0, tzinfo=timezone.utc)
    second = first + timedelta(minutes=5)
    third = second + timedelta(minutes=5)
    initial = make_device(
        kind=DeviceKind.PC,
        ports=(22, 3389),
        services=("SSH", "RDP"),
        risk=RiskLevel.MEDIUM,
    )
    changed = make_device(kind=DeviceKind.UNKNOWN, ports=(), services=(), risk=RiskLevel.LOW)

    store.record_device("192.168.1.0/24", initial, observed_at=first)
    changed_asset = store.record_device("192.168.1.0/24", changed, observed_at=second)
    unchanged_asset = store.record_device("192.168.1.0/24", changed, observed_at=third)

    assert changed_asset.kind == DeviceKind.UNKNOWN
    assert unchanged_asset.first_seen == first
    assert unchanged_asset.last_seen == third
    event_types = [event.event_type for event in store.list_events()]
    assert "type_changed" in event_types
    assert "risk_changed" in event_types
    assert event_types.count("port_closed") == 2


def test_inventory_filters_online_assets_and_missing_asset(tmp_path):
    store = InventoryStore(tmp_path / "inventory.sqlite3")
    store.record_scan("192.168.1.0/24", [make_device()])
    store.record_scan("192.168.1.0/24", [], complete=True)
    assert store.list_assets(scope="192.168.1.0/24", online_only=True) == []
    assert len(store.list_assets()) == 1
    assert store.get_asset("missing") is None
    assert len(store.list_events(limit=9999)) >= 2


def test_inventory_helpers_handle_naive_datetime_and_corrupt_json():
    naive = datetime(2026, 8, 31, 17, 0)
    assert inventory._parse_datetime(inventory._iso(naive)).tzinfo is not None
    assert inventory._load_tuple("not-json") == ()
    assert inventory._normalize_mac("invalid") == ""


@pytest.mark.parametrize(
    ("asset", "expected_title"),
    [
        (
            make_asset(
                kind=DeviceKind.ROUTER,
                ports=(22, 53, 80),
                services=("SSH", "DNS", "HTTP"),
            ),
            "Router Security Auditor",
        ),
        (
            make_asset(
                kind=DeviceKind.NAS,
                ports=(445, 2049, 5000),
                services=("SMB", "NFS", "NAS-Web"),
            ),
            "NAS Security Auditor",
        ),
        (
            make_asset(
                kind=DeviceKind.PRINTER,
                ports=(515, 9100),
                services=("LPD", "JetDirect"),
            ),
            "Printer Security Auditor",
        ),
        (make_asset(kind=DeviceKind.UNKNOWN), "Unknown Security Auditor"),
    ],
)
def test_device_auditor_profiles_cover_common_exposure_paths(asset, expected_title):
    report = build_device_audit(asset)
    assert report.title == expected_title
    assert report.findings


def test_device_auditor_emits_no_notable_exposure_for_quiet_pc():
    report = build_device_audit(make_asset(kind=DeviceKind.PC))
    assert report.risk == RiskLevel.LOW
    assert report.findings[0].title == "No notable exposure"


def test_score_clamps_at_zero_for_many_high_risk_assets():
    assets = [
        AssetRecord(
            **{
                **make_asset(risk=RiskLevel.HIGH).__dict__,
                "asset_id": f"asset-{index}",
            }
        )
        for index in range(10)
    ]
    score = calculate_security_score(assets)
    assert score.score == 0
    assert score.high_risk == 10
    assert any("high-risk" in finding for finding in score.findings)


def test_audit_dialog_renders_report(qtbot):
    dialog = DeviceAuditorDialog(
        make_asset(kind=DeviceKind.NAS, ports=(445,), services=("SMB",))
    )
    qtbot.addWidget(dialog)
    assert dialog.windowTitle() == "NAS Security Auditor"
    areas = dialog.findChildren(QTextEdit)
    assert areas
    assert "SMB" in areas[0].toPlainText()


def test_window_edge_actions_are_safe_without_selection(qtbot, monkeypatch, tmp_path):
    monkeypatch.setattr(window, "_default_scope", lambda: "192.168.1.0/24")
    monkeypatch.setattr(window, "NETWORK_INTELLIGENCE_DB", tmp_path / "window.sqlite3")
    tool = window.Tool()
    qtbot.addWidget(tool)

    tool._handle_progress("not-a-dict")
    tool.stop_scan()
    tool.open_selected_device_auditor()
    tool.open_selected_camera()
    tool._selection_changed()
    assert tool.detail_area.toPlainText() == ""


def test_window_refresh_rejects_invalid_scope_without_crashing(qtbot, monkeypatch, tmp_path):
    monkeypatch.setattr(window, "_default_scope", lambda: "192.168.1.0/24")
    monkeypatch.setattr(window, "NETWORK_INTELLIGENCE_DB", tmp_path / "window.sqlite3")
    tool = window.Tool()
    qtbot.addWidget(tool)
    tool.scope_input.setText("invalid")
    tool.refresh_inventory()
    assert "No se pudo cargar" in tool.status_label.text()
