from __future__ import annotations

import json
from pathlib import Path

from pythonkni.network_intelligence import (
    notification_window,
    reporting_window,
    scheduler_window,
)
from pythonkni.network_intelligence import window as base_window
from pythonkni.network_intelligence.automatic_snapshot import AutomaticSnapshotResult
from pythonkni.network_intelligence.notifications import (
    build_change_notifications,
    load_notification_inbox,
    save_notification_inbox,
)

SCOPE = "192.168.1.0/24"
BASELINE_TIME = "2026-09-01T20:00:00Z"
CURRENT_TIME = "2026-09-01T21:00:00Z"


def asset(*, ports: list[int]) -> dict:
    return {
        "asset_id": "asset-1",
        "ip": "192.168.1.10",
        "mac": "AA:BB:CC:DD:EE:FF",
        "hostname": "server",
        "vendor": "Example",
        "kind": "PC",
        "risk": "LOW",
        "open_ports": ports,
        "services": [],
        "classification_confidence": 80,
        "is_online": True,
    }


def report(generated_at: str, *, ports: list[int]) -> dict:
    return {
        "schema_version": 2,
        "generated_at": generated_at,
        "scope": SCOPE,
        "summary": {},
        "security_score": {
            "score": 90,
            "total_devices": 1,
            "unknown_devices": 0,
            "high_risk": 0,
            "medium_risk": 0,
            "low_risk": 1,
            "findings": [],
        },
        "assets": [asset(ports=ports)],
        "relationships": [],
        "timeline": [],
    }


def write_report(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def make_tool(qtbot, monkeypatch, tmp_path):
    schedule_path = tmp_path / "network_intelligence_schedule.json"
    automatic_dir = tmp_path / "reports" / "scheduled"
    notification_path = tmp_path / "network_intelligence_notifications.json"

    monkeypatch.setattr(base_window, "_default_scope", lambda: SCOPE)
    monkeypatch.setattr(base_window, "NETWORK_INTELLIGENCE_DB", tmp_path / "network.sqlite3")
    monkeypatch.setattr(reporting_window, "ensure_app_dirs", lambda: None)
    monkeypatch.setattr(reporting_window, "NETWORK_INTELLIGENCE_REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(scheduler_window, "ensure_app_dirs", lambda: None)
    monkeypatch.setattr(scheduler_window, "NETWORK_INTELLIGENCE_SCHEDULE_FILE", schedule_path)
    monkeypatch.setattr(
        scheduler_window,
        "NETWORK_INTELLIGENCE_AUTOMATIC_SNAPSHOTS_DIR",
        automatic_dir,
    )
    monkeypatch.setattr(notification_window, "ensure_app_dirs", lambda: None)
    monkeypatch.setattr(
        notification_window,
        "NETWORK_INTELLIGENCE_NOTIFICATIONS_FILE",
        notification_path,
    )

    tool = notification_window.Tool()
    qtbot.addWidget(tool)
    tool.schedule_timer.stop()
    return tool, notification_path, automatic_dir


def test_notification_center_starts_empty_and_non_blocking(qtbot, monkeypatch, tmp_path):
    tool, _notification_path, _automatic_dir = make_tool(qtbot, monkeypatch, tmp_path)

    assert tool.notifications == ()
    assert "0 sin leer" in tool.notification_status.text()
    assert not tool.notification_button.isEnabled()
    tool._open_notifications()


def test_notification_control_sync_is_safe_before_notification_widgets_exist(
    qtbot, monkeypatch, tmp_path
):
    tool, _notification_path, _automatic_dir = make_tool(qtbot, monkeypatch, tmp_path)
    status = tool.notification_status
    del tool.notification_status

    tool._sync_notification_controls()

    tool.notification_status = status


def test_opening_notification_center_marks_existing_items_read(qtbot, monkeypatch, tmp_path):
    notification_path = tmp_path / "network_intelligence_notifications.json"
    batch = build_change_notifications(
        report(BASELINE_TIME, ports=[80]),
        report(CURRENT_TIME, ports=[80, 443]),
    )
    save_notification_inbox(notification_path, batch.notifications)
    monkeypatch.setattr(notification_window, "NETWORK_INTELLIGENCE_NOTIFICATIONS_FILE", notification_path)
    monkeypatch.setattr(notification_window.ChangeNotificationDialog, "exec_", lambda self: 0)

    tool, _path, _automatic_dir = make_tool(qtbot, monkeypatch, tmp_path)
    tool._open_notifications()

    assert all(item.read for item in load_notification_inbox(notification_path))
    assert "0 sin leer" in tool.notification_status.text()
    assert tool.notification_button.text() == "Ver cambios"


def test_opening_notification_center_preserves_unread_state_when_save_fails(
    qtbot, monkeypatch, tmp_path
):
    notification_path = tmp_path / "network_intelligence_notifications.json"
    batch = build_change_notifications(
        report(BASELINE_TIME, ports=[80]),
        report(CURRENT_TIME, ports=[80, 443]),
    )
    save_notification_inbox(notification_path, batch.notifications)
    monkeypatch.setattr(notification_window, "NETWORK_INTELLIGENCE_NOTIFICATIONS_FILE", notification_path)
    monkeypatch.setattr(notification_window.ChangeNotificationDialog, "exec_", lambda self: 0)
    errors = []
    monkeypatch.setattr(
        notification_window,
        "show_error",
        lambda *args, **kwargs: errors.append((args, kwargs)),
    )
    tool, _path, _automatic_dir = make_tool(qtbot, monkeypatch, tmp_path)
    monkeypatch.setattr(
        notification_window,
        "save_notification_inbox",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )

    tool._open_notifications()

    assert errors
    assert any(not item.read for item in tool.notifications)
    assert any(not item.read for item in load_notification_inbox(notification_path))
    assert "1 sin leer" in tool.notification_status.text()


def test_first_automatic_snapshot_only_establishes_change_baseline(qtbot, monkeypatch, tmp_path):
    tool, notification_path, automatic_dir = make_tool(qtbot, monkeypatch, tmp_path)
    automatic_dir.mkdir(parents=True, exist_ok=True)
    current = automatic_dir / "current.json"
    write_report(current, report(CURRENT_TIME, ports=[80]))

    suffix = tool._automatic_snapshot_published(
        previous_snapshot=None,
        snapshot=AutomaticSnapshotResult(path=current, pruned_count=0),
        generated_at=tool.schedule_config.last_started_at,
    )

    assert "baseline" in suffix
    assert not notification_path.exists()


def test_post_snapshot_engine_persists_and_deduplicates_same_pair(qtbot, monkeypatch, tmp_path):
    tool, notification_path, automatic_dir = make_tool(qtbot, monkeypatch, tmp_path)
    automatic_dir.mkdir(parents=True, exist_ok=True)
    previous = automatic_dir / "previous.json"
    current = automatic_dir / "current.json"
    write_report(previous, report(BASELINE_TIME, ports=[80]))
    write_report(current, report(CURRENT_TIME, ports=[80, 443]))
    snapshot = AutomaticSnapshotResult(path=current, pruned_count=0)

    first = tool._automatic_snapshot_published(
        previous_snapshot=previous,
        snapshot=snapshot,
        generated_at=tool.schedule_config.last_started_at,
    )
    second = tool._automatic_snapshot_published(
        previous_snapshot=previous,
        snapshot=snapshot,
        generated_at=tool.schedule_config.last_started_at,
    )

    stored = load_notification_inbox(notification_path)
    assert len(stored) == 1
    assert stored[0].category == "ports_opened"
    assert "1 cambio" in first
    assert "sin duplicados" in second
    assert "1 sin leer" in tool.notification_status.text()


def test_post_snapshot_engine_reports_clean_pair_without_creating_inbox(
    qtbot, monkeypatch, tmp_path
):
    tool, notification_path, automatic_dir = make_tool(qtbot, monkeypatch, tmp_path)
    automatic_dir.mkdir(parents=True, exist_ok=True)
    previous = automatic_dir / "previous.json"
    current = automatic_dir / "current.json"
    write_report(previous, report(BASELINE_TIME, ports=[80]))
    write_report(current, report(CURRENT_TIME, ports=[80]))

    suffix = tool._automatic_snapshot_published(
        previous_snapshot=previous,
        snapshot=AutomaticSnapshotResult(path=current, pruned_count=0),
        generated_at=tool.schedule_config.last_started_at,
    )

    assert "sin cambios relevantes" in suffix
    assert tool.notifications == ()
    assert not notification_path.exists()


def test_missing_previous_snapshot_does_not_create_false_change_events(
    qtbot, monkeypatch, tmp_path
):
    warnings = []
    monkeypatch.setattr(
        notification_window,
        "show_warning",
        lambda *args, **kwargs: warnings.append((args, kwargs)),
    )
    tool, notification_path, automatic_dir = make_tool(qtbot, monkeypatch, tmp_path)
    automatic_dir.mkdir(parents=True, exist_ok=True)
    current = automatic_dir / "current.json"
    write_report(current, report(CURRENT_TIME, ports=[80, 443]))

    suffix = tool._automatic_snapshot_published(
        previous_snapshot=automatic_dir / "missing.json",
        snapshot=AutomaticSnapshotResult(path=current, pruned_count=0),
        generated_at=tool.schedule_config.last_started_at,
    )

    assert warnings
    assert "baseline no disponible" in suffix
    assert not notification_path.exists()


def test_corrupt_notification_inbox_is_never_overwritten_during_change_processing(
    qtbot, monkeypatch, tmp_path
):
    notification_path = tmp_path / "network_intelligence_notifications.json"
    notification_path.write_text("not-json", encoding="utf-8")
    warnings = []
    monkeypatch.setattr(
        notification_window,
        "show_warning",
        lambda *args, **kwargs: warnings.append((args, kwargs)),
    )
    tool, _path, automatic_dir = make_tool(qtbot, monkeypatch, tmp_path)
    automatic_dir.mkdir(parents=True, exist_ok=True)
    previous = automatic_dir / "previous.json"
    current = automatic_dir / "current.json"
    write_report(previous, report(BASELINE_TIME, ports=[80]))
    write_report(current, report(CURRENT_TIME, ports=[80, 443]))

    suffix = tool._automatic_snapshot_published(
        previous_snapshot=previous,
        snapshot=AutomaticSnapshotResult(path=current, pruned_count=0),
        generated_at=tool.schedule_config.last_started_at,
    )

    assert warnings
    assert "no disponible" in suffix
    assert notification_path.read_text(encoding="utf-8") == "not-json"
