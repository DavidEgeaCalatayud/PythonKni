from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

from pythonkni.network_intelligence import reporting_window, scheduler_window
from pythonkni.network_intelligence import window as base_window
from pythonkni.network_intelligence.fingerprint_policy import (
    FingerprintPolicy,
    ScheduledFingerprintResult,
)
from pythonkni.network_intelligence.scheduler import ScheduleConfig, load_schedule, save_schedule

SCOPE = "192.168.1.0/24"


class _Signal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)


class _FakeWorker:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.progress = _Signal()
        self.result = _Signal()
        self.error = _Signal()
        self.cancelled = _Signal()
        self.finished = _Signal()
        self.cancel_event = threading.Event()
        self.cancel_calls = 0

    def cancel(self):
        self.cancel_calls += 1
        self.cancel_event.set()

    def isRunning(self):
        return False


def _make_tool(qtbot, monkeypatch, tmp_path, *, policy=FingerprintPolicy.MANUAL):
    schedule_path = tmp_path / "network_intelligence_schedule.json"
    automatic_dir = tmp_path / "reports" / "scheduled"
    now = datetime.now(timezone.utc)
    schedule = ScheduleConfig(
        enabled=True,
        scope=SCOPE,
        interval_minutes=60,
        next_run_at=now + timedelta(hours=1),
        last_started_at=now,
        last_success_at=now - timedelta(hours=1),
        fingerprint_policy=policy,
    )
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
    return tool, schedule_path


def test_policy_combo_persists_automatic_choice(qtbot, monkeypatch, tmp_path):
    tool, schedule_path = _make_tool(qtbot, monkeypatch, tmp_path)
    index = tool.fingerprint_policy_combo.findData(
        FingerprintPolicy.AUTOMATIC_AFTER_DISCOVERY.value
    )

    tool.fingerprint_policy_combo.setCurrentIndex(index)

    saved = load_schedule(schedule_path)
    assert saved.fingerprint_policy is FingerprintPolicy.AUTOMATIC_AFTER_DISCOVERY
    assert "exclusivamente manuales" in tool.status_label.text()


def test_automatic_scan_defers_snapshot_until_fingerprinting(qtbot, monkeypatch, tmp_path):
    tool, _schedule_path = _make_tool(
        qtbot,
        monkeypatch,
        tmp_path,
        policy=FingerprintPolicy.AUTOMATIC_AFTER_DISCOVERY,
    )
    monkeypatch.setattr(scheduler_window.HistoryTool, "_scan_finished", lambda self, result: True)
    snapshots = []
    monkeypatch.setattr(tool, "_publish_scheduled_snapshot", lambda *args: snapshots.append(args))
    tool._scheduled_scan_active = True

    tool._scan_finished({"devices": []})

    assert tool._scheduled_postscan_pending
    assert snapshots == []
    assert "fingerprinting TCP acotado" in tool.status_label.text()


def test_worker_finished_launches_automatic_fingerprinting(qtbot, monkeypatch, tmp_path):
    tool, _schedule_path = _make_tool(
        qtbot,
        monkeypatch,
        tmp_path,
        policy=FingerprintPolicy.CHANGED_SERVICES_ONLY,
    )
    monkeypatch.setattr(scheduler_window.HistoryTool, "_worker_finished", lambda self: None)
    started = []
    monkeypatch.setattr(tool, "_start_scheduled_fingerprinting", lambda: started.append(True))
    tool._scheduled_scan_active = True
    tool._scheduled_postscan_pending = True

    tool._worker_finished()

    assert started == [True]
    assert tool._scheduled_scan_active


def test_start_scheduled_fingerprinting_manual_falls_back_to_snapshot(qtbot, monkeypatch, tmp_path):
    tool, _schedule_path = _make_tool(qtbot, monkeypatch, tmp_path)
    published = []
    monkeypatch.setattr(tool, "_publish_scheduled_snapshot", lambda *args: published.append(args))

    tool._start_scheduled_fingerprinting()

    assert published == [()]


def test_start_scheduled_fingerprinting_builds_managed_worker(qtbot, monkeypatch, tmp_path):
    tool, _schedule_path = _make_tool(
        qtbot,
        monkeypatch,
        tmp_path,
        policy=FingerprintPolicy.AUTOMATIC_AFTER_DISCOVERY,
    )
    created = []

    def fake_worker(*args, **kwargs):
        worker = _FakeWorker(*args, **kwargs)
        created.append(worker)
        return worker

    managed = []
    running = []
    monkeypatch.setattr(scheduler_window, "Worker", fake_worker)
    monkeypatch.setattr(
        tool,
        "start_managed_worker",
        lambda worker, cancel=None: managed.append((worker, cancel)),
    )
    monkeypatch.setattr(tool, "_set_running", lambda value: running.append(value))

    tool._start_scheduled_fingerprinting()

    assert len(created) == 1
    worker = created[0]
    assert worker.args[0] is scheduler_window._run_scheduled_fingerprint_worker
    assert worker.args[1] is tool.inventory
    assert worker.args[2] == SCOPE
    assert worker.args[3] is FingerprintPolicy.AUTOMATIC_AFTER_DISCOVERY
    assert worker.args[4] == tool.schedule_config.last_success_at
    assert tool.worker is worker
    assert tool._scheduled_fingerprint_worker_active
    assert running == [True]
    assert managed[0][0] is worker
    assert managed[0][1] == worker.cancel
    assert worker.progress.callbacks == [tool._scheduled_fingerprint_progress]
    assert worker.result.callbacks == [tool._scheduled_fingerprint_finished]
    assert worker.error.callbacks == [tool._scheduled_fingerprint_failed]
    assert worker.cancelled.callbacks == [tool._scheduled_fingerprint_cancelled]
    assert worker.finished.callbacks == [tool._worker_finished]


def test_worker_adapter_forwards_cancel_event_and_progress(monkeypatch):
    worker = _FakeWorker()
    progress = []
    worker.report_progress = progress.append
    expected = ScheduledFingerprintResult(
        policy=FingerprintPolicy.AUTOMATIC_AFTER_DISCOVERY,
        selected_assets=1,
        attempted_assets=1,
        fingerprinted_assets=1,
        fingerprints=2,
    )
    calls = []

    def fake_run(inventory, scope, policy, **kwargs):
        calls.append((inventory, scope, policy, kwargs))
        kwargs["on_progress"]("checking host")
        return expected

    monkeypatch.setattr(scheduler_window, "run_scheduled_fingerprinting", fake_run)
    inventory = object()
    changed_since = datetime.now(timezone.utc)

    result = scheduler_window._run_scheduled_fingerprint_worker(
        worker,
        inventory,
        SCOPE,
        FingerprintPolicy.AUTOMATIC_AFTER_DISCOVERY,
        changed_since,
    )

    assert result is expected
    assert calls[0][0] is inventory
    assert calls[0][1] == SCOPE
    assert calls[0][2] is FingerprintPolicy.AUTOMATIC_AFTER_DISCOVERY
    assert calls[0][3]["stop_event"] is worker.cancel_event
    assert calls[0][3]["changed_since"] == changed_since
    assert progress == [{"message": "checking host"}]


def test_scheduled_fingerprint_progress_ignores_nonmessages(qtbot, monkeypatch, tmp_path):
    tool, _schedule_path = _make_tool(qtbot, monkeypatch, tmp_path)
    original = tool.status_label.text()

    tool._scheduled_fingerprint_progress("not a mapping")
    tool._scheduled_fingerprint_progress({})
    assert tool.status_label.text() == original

    tool._scheduled_fingerprint_progress({"message": "fingerprinting host"})
    assert tool.status_label.text() == "fingerprinting host"


def test_scheduled_fingerprint_success_refreshes_and_publishes_summary(
    qtbot, monkeypatch, tmp_path
):
    tool, _schedule_path = _make_tool(
        qtbot,
        monkeypatch,
        tmp_path,
        policy=FingerprintPolicy.AUTOMATIC_AFTER_DISCOVERY,
    )
    result = ScheduledFingerprintResult(
        policy=FingerprintPolicy.AUTOMATIC_AFTER_DISCOVERY,
        selected_assets=3,
        attempted_assets=2,
        fingerprinted_assets=2,
        fingerprints=5,
    )
    refreshed = []
    published = []
    monkeypatch.setattr(tool, "refresh_inventory", lambda **kwargs: refreshed.append(kwargs))
    monkeypatch.setattr(tool, "_publish_scheduled_snapshot", published.append)

    tool._scheduled_fingerprint_finished(result)

    assert refreshed == [{"keep_status": True}]
    assert len(published) == 1
    assert "2/2 activos" in published[0]
    assert "5 servicios" in published[0]


def test_scheduled_fingerprint_partial_errors_warn_but_publish(qtbot, monkeypatch, tmp_path):
    tool, _schedule_path = _make_tool(
        qtbot,
        monkeypatch,
        tmp_path,
        policy=FingerprintPolicy.AUTOMATIC_AFTER_DISCOVERY,
    )
    result = ScheduledFingerprintResult(
        policy=FingerprintPolicy.AUTOMATIC_AFTER_DISCOVERY,
        selected_assets=2,
        attempted_assets=2,
        fingerprinted_assets=1,
        fingerprints=1,
        errors=("192.168.1.20: timeout", "192.168.1.21: unavailable"),
    )
    warnings = []
    published = []
    monkeypatch.setattr(
        scheduler_window,
        "show_warning",
        lambda *args, **kwargs: warnings.append((args, kwargs)),
    )
    monkeypatch.setattr(tool, "refresh_inventory", lambda **kwargs: None)
    monkeypatch.setattr(tool, "_publish_scheduled_snapshot", published.append)

    tool._scheduled_fingerprint_finished(result)

    assert warnings
    assert "timeout" in warnings[0][1]["details"]
    assert "2 error(es)" in published[0]


def test_scheduled_fingerprint_invalid_result_uses_degraded_snapshot(qtbot, monkeypatch, tmp_path):
    tool, _schedule_path = _make_tool(qtbot, monkeypatch, tmp_path)
    published = []
    monkeypatch.setattr(tool, "_publish_scheduled_snapshot", published.append)

    tool._scheduled_fingerprint_finished(object())

    assert published == [" · fingerprinting automático sin resumen"]


def test_scheduled_fingerprint_failure_warns_and_preserves_valid_snapshot(
    qtbot, monkeypatch, tmp_path
):
    tool, _schedule_path = _make_tool(qtbot, monkeypatch, tmp_path)
    warnings = []
    published = []
    monkeypatch.setattr(
        scheduler_window,
        "show_warning",
        lambda *args, **kwargs: warnings.append((args, kwargs)),
    )
    monkeypatch.setattr(tool, "_publish_scheduled_snapshot", published.append)

    tool._scheduled_fingerprint_failed(RuntimeError("nerva failed"))

    assert warnings
    assert warnings[0][1]["details"] == "nerva failed"
    assert published == [" · fingerprinting automático no disponible"]


def test_scheduled_fingerprint_cancel_prevents_snapshot(qtbot, monkeypatch, tmp_path):
    tool, _schedule_path = _make_tool(qtbot, monkeypatch, tmp_path)
    tool._scheduled_postscan_pending = True

    tool._scheduled_fingerprint_cancelled()

    assert not tool._scheduled_postscan_pending
    assert "no se publicó snapshot" in tool.status_label.text()


def test_finishing_fingerprint_worker_resets_scheduler_flags(qtbot, monkeypatch, tmp_path):
    tool, _schedule_path = _make_tool(qtbot, monkeypatch, tmp_path)
    monkeypatch.setattr(scheduler_window.HistoryTool, "_worker_finished", lambda self: None)
    synced = []
    monkeypatch.setattr(tool, "_sync_schedule_controls", lambda: synced.append(True))
    tool._scheduled_scan_active = True
    tool._scheduled_fingerprint_worker_active = True

    tool._worker_finished()

    assert not tool._scheduled_scan_active
    assert not tool._scheduled_fingerprint_worker_active
    assert synced == [True]
