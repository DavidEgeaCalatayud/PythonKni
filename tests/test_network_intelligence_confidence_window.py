from __future__ import annotations

from datetime import datetime, timezone

from pythonkni.camera_auditor.models import RiskLevel
from pythonkni.network_intelligence import confidence_window, reporting_window
from pythonkni.network_intelligence import window as base_window
from pythonkni.network_intelligence.models import (
    AssetRecord,
    ClassificationSignal,
    DeviceKind,
)

NOW = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
SCOPE = "192.168.1.0/24"


def asset() -> AssetRecord:
    return AssetRecord(
        asset_id="ip:192.168.1.20",
        scope=SCOPE,
        ip="192.168.1.20",
        mac="Unknown",
        hostname="camera.local",
        vendor="Unknown",
        kind=DeviceKind.CAMERA,
        services=("RTSP",),
        open_ports=(554,),
        evidence=("RTSP exposure",),
        risk=RiskLevel.MEDIUM,
        first_seen=NOW,
        last_seen=NOW,
        last_change=NOW,
        is_online=True,
        classification_confidence=30,
        classification_signals=(
            ClassificationSignal(
                key="camera.rtsp",
                label="RTSP service :554",
                weight=30,
                matched=True,
                evidence="RTSP :554 is reachable on the local network.",
            ),
            ClassificationSignal(
                key="camera.onvif",
                label="ONVIF device evidence",
                weight=45,
                matched=False,
                evidence="No ONVIF camera evidence was observed.",
            ),
        ),
    )


def make_tool(qtbot, monkeypatch, tmp_path):
    monkeypatch.setattr(base_window, "_default_scope", lambda: SCOPE)
    monkeypatch.setattr(base_window, "NETWORK_INTELLIGENCE_DB", tmp_path / "network.sqlite3")
    monkeypatch.setattr(reporting_window, "ensure_app_dirs", lambda: None)
    monkeypatch.setattr(
        reporting_window,
        "NETWORK_INTELLIGENCE_REPORTS_DIR",
        tmp_path / "reports",
    )
    instance = confidence_window.Tool()
    qtbot.addWidget(instance)
    return instance


def test_confidence_composition_adds_inventory_column(qtbot, monkeypatch, tmp_path):
    tool = make_tool(qtbot, monkeypatch, tmp_path)

    assert tool.table.columnCount() == 10
    assert tool.table.horizontalHeaderItem(4).text() == "Confidence"
    assert tool.export_report_button.text() == "Export snapshot report"


def test_confidence_row_and_profile_keep_risk_separate(qtbot, monkeypatch, tmp_path):
    tool = make_tool(qtbot, monkeypatch, tmp_path)
    current = asset()
    tool.assets = [current]
    tool.table.setRowCount(1)
    tool._write_asset_row(0, current)
    tool.table.selectRow(0)
    tool._selection_changed()

    assert tool.table.item(0, 4).text() == "30/100 · LOW"
    assert tool.table.item(0, 6).text() == "MEDIUM"
    profile = tool.detail_area.toPlainText()
    assert "Classification confidence" in profile
    assert "30/100 · LOW" in profile
    assert "✓ RTSP service :554  +30" in profile
    assert "✗ ONVIF device evidence  +0" in profile
    assert "independent from security risk" in profile


def test_topology_selection_uses_confidence_profile(qtbot, monkeypatch, tmp_path):
    tool = make_tool(qtbot, monkeypatch, tmp_path)
    current = asset()
    tool.assets = [current]
    tool.table.setRowCount(1)
    tool._write_asset_row(0, current)

    tool._topology_asset_selected(current.asset_id)

    assert "30/100 · LOW" in tool.topology_detail.toPlainText()


def test_write_row_delegates_while_base_setup_still_has_nine_columns(qtbot, monkeypatch, tmp_path):
    tool = make_tool(qtbot, monkeypatch, tmp_path)
    current = asset()
    tool.table.removeColumn(9)
    tool.table.setRowCount(1)

    tool._write_asset_row(0, current)

    assert tool.table.item(0, 0).text() == current.ip
    assert tool.table.columnCount() == 9
