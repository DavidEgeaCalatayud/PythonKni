from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from pythonkni.network_intelligence import reporting_window, scheduler_window
from pythonkni.network_intelligence import window as base_window
from pythonkni.network_intelligence.automatic_snapshot import AutomaticSnapshotResult
from pythonkni.network_intelligence.scheduler import ScheduleConfig, load_schedule, save_schedule

SCOPE = "192.168.1.0/24"


def make_tool(qtbot, monkeypatch, tmp_path, *, schedule: ScheduleConfig | None = None):
    schedule_path = tmp_path / "network_intelligence_schedule.json"
    automatic_dir = tmp_path / "reports" / "scheduled"
    if schedule is not None:
        save_schedule(schedule_path, schedule)

    monkeypatch.setattr(base_window, "_default_scope", lambda: SCOPE)
    monkeypatch.setattr(base_window, "NETWORK_INTELLIGENCE_DB", tmp_path / "network.sqlite3")
    monkeypatch.setattr(reporting_window, "ensure_app_dirs", lambda: None)
    monkeypatch.setattr(
        reporting_window,
        "NETWORK_INTELLIGENCE_REPORTS_DIR",
        tmp_path / "reports",
    )
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
    return tool, schedule_path, automatic_dir


def test_scheduler_composition_is_opt_in_and_does_not_lock_scope_by_default(
    qtbot, monkeypatch, tmp_path
):
    tool, _schedule_path, _automatic_dir = make_tool(qtbot, monkeypatch, tmp_path)

    assert not tool.schedule_checkbox.isChecked()
    assert tool.scope_input.isEnabled()
    assert tool.schedule_interval.isEnabled()
    assert "Desactivada" in tool.schedule_status.text()


def test_enabling_scheduler_persists_canonical_scope_and_locks_it(qtbot, monkeypatch, tmp_path):
    tool, schedule_path, _automatic_dir = make_tool(qtbot, monkeypatch, tmp_path)
    tool.scope_input.setText("192.168.1.44/24")
    tool.schedule_interval.setCurrentIndex(tool.schedule_interval.findData(30))

    tool.schedule_checkbox.setChecked(True)

    saved = load_schedule(schedule_path)
    assert saved.enabled
    assert saved.scope == SCOPE
    assert saved.interval_minutes == 30
    assert saved.next_run_at is not None
    assert not tool.scope_input.isEnabled()
    assert "Monitorización programada activada" in tool.status_label.text()

    tool.schedule_checkbox.setChecked(False)
    assert not load_schedule(schedule_path).enabled
    assert tool.scope_input.isEnabled()


def test_scheduler_rejects_public_scope_without_enabling(qtbot, monkeypatch, tmp_path):
    tool, _schedule_path, _automatic_dir = make_tool(qtbot, monkeypatch, tmp_path)
    warnings = []
    monkeypatch.setattr(
        scheduler_window,
        "show_warning",
        lambda *args, **kwargs: warnings.append((args, kwargs)),
    )
    tool.scope_input.setText("8.8.8.0/24")

    tool.schedule_checkbox.setChecked(True)

    assert warnings
    assert not tool.schedule_config.enabled
    assert not tool.schedule_checkbox.isChecked()


def test_due_schedule_advances_persistence_before_starting_worker(qtbot, monkeypatch, tmp_path):
    now = datetime.now(timezone.utc)
    schedule = ScheduleConfig(
        enabled=True,
        scope=SCOPE,
        interval_minutes=60,
        next_run_at=now - timedelta(minutes=1),
    )
    tool, schedule_path, _automatic_dir = make_tool(
        qtbot, monkeypatch, tmp_path, schedule=schedule
    )
    calls = []

    class FakeWorker:
        @staticmethod
        def isRunning():
            return True

    def fake_start(fake_tool):
        persisted = load_schedule(schedule_path)
        calls.append(persisted)
        assert persisted.last_started_at is not None
        assert persisted.next_run_at is not None
        assert persisted.next_run_at > datetime.now(timezone.utc)
        fake_tool.worker = FakeWorker()

    monkeypatch.setattr(scheduler_window.HistoryTool, "start_scan", fake_start)

    tool._check_schedule()
    tool._check_schedule()

    assert len(calls) == 1
    assert tool._scheduled_scan_active


def test_scheduled_success_publishes_snapshot_and_records_success(qtbot, monkeypatch, tmp_path):
    now = datetime.now(timezone.utc)
    schedule = ScheduleConfig(
        enabled=True,
        scope=SCOPE,
        interval_minutes=60,
        next_run_at=now + timedelta(hours=1),
        last_started_at=now,
    )
    tool, schedule_path, automatic_dir = make_tool(
        qtbot, monkeypatch, tmp_path, schedule=schedule
    )
    monkeypatch.setattr(scheduler_window.HistoryTool, "_scan_finished", lambda self, result: None)
    monkeypatch.setattr(tool.inventory, "list_assets", lambda **kwargs: [])
    monkeypatch.setattr(tool.relationship_store, "list", lambda **kwargs: [])
    monkeypatch.setattr(tool.inventory, "list_events", lambda **kwargs: [])
    created = []

    def fake_snapshot(directory, scope, assets, relationships, events, *, generated_at):
        created.append((Path(directory), scope, tuple(assets), tuple(relationships), tuple(events)))
        return AutomaticSnapshotResult(
            path=automatic_dir / "scheduled_192.168.1.0_24_test.json",
            pruned_count=2,
        )

    monkeypatch.setattr(scheduler_window, "create_automatic_snapshot", fake_snapshot)
    tool._scheduled_scan_active = True

    tool._scan_finished({"devices": []})

    assert created == [(automatic_dir, SCOPE, (), (), ())]
    saved = load_schedule(schedule_path)
    assert saved.last_success_at is not None
    assert saved.last_snapshot.endswith("scheduled_192.168.1.0_24_test.json")
    assert "2 snapshot(s) antiguo(s) eliminado(s)" in tool.status_label.text()


def test_manual_success_never_creates_automatic_snapshot(qtbot, monkeypatch, tmp_path):
    tool, _schedule_path, _automatic_dir = make_tool(qtbot, monkeypatch, tmp_path)
    monkeypatch.setattr(scheduler_window.HistoryTool, "_scan_finished", lambda self, result: None)
    monkeypatch.setattr(
        scheduler_window,
        "create_automatic_snapshot",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("manual scans must not create automatic snapshots")
        ),
    )

    tool._scheduled_scan_active = False
    tool._scan_finished({"devices": []})


def test_scheduled_failure_and_cancel_do_not_publish_snapshot(qtbot, monkeypatch, tmp_path):
    now = datetime.now(timezone.utc)
    schedule = ScheduleConfig(
        enabled=True,
        scope=SCOPE,
        interval_minutes=60,
        next_run_at=now + timedelta(hours=1),
        last_started_at=now,
    )
    tool, _schedule_path, _automatic_dir = make_tool(
        qtbot, monkeypatch, tmp_path, schedule=schedule
    )
    monkeypatch.setattr(scheduler_window.HistoryTool, "_scan_failed", lambda self, error: None)
    monkeypatch.setattr(scheduler_window.HistoryTool, "_scan_cancelled", lambda self: None)
    monkeypatch.setattr(
        scheduler_window,
        "create_automatic_snapshot",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("failed/cancelled scans must not snapshot")
        ),
    )
    tool._scheduled_scan_active = True

    tool._scan_failed(RuntimeError("boom"))
    assert "no se creó snapshot automático" in tool.status_label.text()
    tool._scan_cancelled()
    assert "no se creó snapshot automático" in tool.status_label.text()


def test_close_stops_scheduler_timer(qtbot, monkeypatch, tmp_path):
    tool, _schedule_path, _automatic_dir = make_tool(qtbot, monkeypatch, tmp_path)
    tool.schedule_timer.start()

    tool.close()

    assert not tool.schedule_timer.isActive()
