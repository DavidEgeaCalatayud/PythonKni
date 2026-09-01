from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pythonkni.network_intelligence import reporting_window, scheduler_window
from pythonkni.network_intelligence import window as base_window
from pythonkni.network_intelligence.automatic_snapshot import AutomaticSnapshotResult
from pythonkni.network_intelligence.scheduler import ScheduleConfig, load_schedule, save_schedule

SCOPE = "192.168.1.0/24"


def test_notification_hook_failure_does_not_rollback_scheduled_snapshot_success(
    qtbot, monkeypatch, tmp_path
):
    now = datetime.now(timezone.utc)
    schedule_path = tmp_path / "network_intelligence_schedule.json"
    automatic_dir = tmp_path / "reports" / "scheduled"
    previous = automatic_dir / "previous.json"
    schedule = ScheduleConfig(
        enabled=True,
        scope=SCOPE,
        interval_minutes=60,
        next_run_at=now + timedelta(hours=1),
        last_started_at=now,
        last_success_at=now - timedelta(hours=1),
        last_snapshot=str(previous),
    )
    save_schedule(schedule_path, schedule)

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

    tool = scheduler_window.Tool()
    qtbot.addWidget(tool)
    tool.schedule_timer.stop()
    monkeypatch.setattr(scheduler_window.HistoryTool, "_scan_finished", lambda self, result: True)
    monkeypatch.setattr(tool.inventory, "list_assets", lambda **kwargs: [])
    monkeypatch.setattr(tool.relationship_store, "list", lambda **kwargs: [])
    monkeypatch.setattr(tool.inventory, "list_events", lambda **kwargs: [])
    current = automatic_dir / "current.json"
    monkeypatch.setattr(
        scheduler_window,
        "create_automatic_snapshot",
        lambda *args, **kwargs: AutomaticSnapshotResult(path=current, pruned_count=0),
    )
    monkeypatch.setattr(
        tool,
        "_automatic_snapshot_published",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("notification failure")),
    )
    warnings = []
    monkeypatch.setattr(
        scheduler_window,
        "show_warning",
        lambda *args, **kwargs: warnings.append((args, kwargs)),
    )
    tool._scheduled_scan_active = True

    tool._scan_finished({"devices": []})

    persisted = load_schedule(schedule_path)
    assert persisted.last_success_at is not None
    assert persisted.last_snapshot == str(current)
    assert warnings
    assert "procesamiento posterior no disponible" in tool.status_label.text()
