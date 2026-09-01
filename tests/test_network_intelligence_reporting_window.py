from __future__ import annotations

from datetime import datetime, timezone

from pythonkni.camera_auditor.models import RiskLevel
from pythonkni.network_intelligence import reporting_window, window as base_window
from pythonkni.network_intelligence.models import AssetRecord, DeviceKind

NOW = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)
SCOPE = "192.168.1.0/24"


def asset() -> AssetRecord:
    return AssetRecord(
        asset_id="ip:192.168.1.10",
        scope=SCOPE,
        ip="192.168.1.10",
        mac="Unknown",
        hostname="camera.local",
        vendor="Reolink",
        kind=DeviceKind.CAMERA,
        services=("RTSP",),
        open_ports=(554,),
        evidence=("persisted",),
        risk=RiskLevel.MEDIUM,
        first_seen=NOW,
        last_seen=NOW,
        last_change=NOW,
        is_online=True,
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
    instance = reporting_window.Tool()
    qtbot.addWidget(instance)
    return instance


def test_reporting_composition_adds_export_action(qtbot, monkeypatch, tmp_path):
    tool = make_tool(qtbot, monkeypatch, tmp_path)

    assert tool.export_report_button.text() == "Export snapshot report"
    assert tool.export_report_button.isEnabled()
    assert (tmp_path / "reports").is_dir()


def test_export_button_tracks_running_state(qtbot, monkeypatch, tmp_path):
    tool = make_tool(qtbot, monkeypatch, tmp_path)

    tool._set_running(True)
    assert not tool.export_report_button.isEnabled()
    tool._set_running(False)
    assert tool.export_report_button.isEnabled()


def test_empty_snapshot_warns_without_opening_save_dialog(qtbot, monkeypatch, tmp_path):
    tool = make_tool(qtbot, monkeypatch, tmp_path)
    warnings = []
    monkeypatch.setattr(reporting_window, "show_warning", lambda *args, **kwargs: warnings.append(args))
    monkeypatch.setattr(
        reporting_window.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("dialog should not open")),
    )

    tool.export_snapshot_report()

    assert warnings
    assert "No hay datos persistidos" in warnings[0][2]


def test_export_uses_persisted_snapshot_and_infers_zip_suffix(qtbot, monkeypatch, tmp_path):
    tool = make_tool(qtbot, monkeypatch, tmp_path)
    current_asset = asset()
    monkeypatch.setattr(tool.inventory, "list_assets", lambda **kwargs: [current_asset])
    monkeypatch.setattr(tool.inventory, "list_events", lambda **kwargs: [])
    monkeypatch.setattr(tool.relationship_store, "list", lambda **kwargs: [])
    monkeypatch.setattr(
        reporting_window.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(tmp_path / "snapshot"), "Evidence bundle (*.zip)"),
    )
    exported = []

    def fake_export(path, report):
        exported.append((path, report))
        return path

    monkeypatch.setattr(reporting_window, "export_network_report", fake_export)

    tool.export_snapshot_report()

    assert len(exported) == 1
    path, report = exported[0]
    assert path == tmp_path / "snapshot.zip"
    assert report["scope"] == SCOPE
    assert report["assets"][0]["ip"] == "192.168.1.10"
    assert "1 activo(s)" in tool.status_label.text()


def test_export_failure_is_reported(qtbot, monkeypatch, tmp_path):
    tool = make_tool(qtbot, monkeypatch, tmp_path)
    monkeypatch.setattr(tool.inventory, "list_assets", lambda **kwargs: [asset()])
    monkeypatch.setattr(tool.inventory, "list_events", lambda **kwargs: [])
    monkeypatch.setattr(tool.relationship_store, "list", lambda **kwargs: [])
    monkeypatch.setattr(
        reporting_window.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(tmp_path / "snapshot.json"), "JSON report (*.json)"),
    )
    errors = []
    monkeypatch.setattr(
        reporting_window,
        "export_network_report",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )
    monkeypatch.setattr(reporting_window, "show_error", lambda *args, **kwargs: errors.append((args, kwargs)))

    tool.export_snapshot_report()

    assert errors
    assert "No se pudo exportar" in errors[0][0][2]
