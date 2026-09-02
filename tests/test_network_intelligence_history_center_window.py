from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PyQt5.QtWidgets import QMessageBox

from pythonkni.network_intelligence import (
    history_center_window,
    notification_window,
    reporting_window,
    scheduler_window,
)
from pythonkni.network_intelligence import window as base_window
from pythonkni.network_intelligence.retention import (
    RetentionPolicy,
    load_retention_policy,
    save_retention_policy,
)

SCOPE = "192.168.1.0/24"
OTHER_SCOPE = "10.0.0.0/24"


def _report(generated_at: datetime, *, scope: str = SCOPE, score: int = 90, high: int = 0):
    return {
        "schema_version": 2,
        "generated_at": generated_at.isoformat().replace("+00:00", "Z"),
        "scope": scope,
        "summary": {},
        "security_score": {
            "score": score,
            "total_devices": 2,
            "unknown_devices": 0,
            "high_risk": high,
            "medium_risk": 1,
            "low_risk": max(0, 1 - high),
            "findings": ["finding"] if score < 100 else [],
        },
        "assets": [],
        "relationships": [],
        "timeline": [],
    }


def _write_snapshot(directory: Path, name: str, generated_at: datetime, **kwargs) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(json.dumps(_report(generated_at, **kwargs)), encoding="utf-8")
    return path


def make_tool(qtbot, monkeypatch, tmp_path, *, policy: RetentionPolicy | None = None):
    reports = tmp_path / "reports"
    automatic_dir = reports / "scheduled"
    schedule_path = tmp_path / "network_intelligence_schedule.json"
    notification_path = tmp_path / "network_intelligence_notifications.json"
    retention_path = tmp_path / "network_intelligence_retention.json"
    if policy is not None:
        save_retention_policy(retention_path, policy)

    monkeypatch.setattr(base_window, "_default_scope", lambda: SCOPE)
    monkeypatch.setattr(base_window, "NETWORK_INTELLIGENCE_DB", tmp_path / "network.sqlite3")
    monkeypatch.setattr(reporting_window, "ensure_app_dirs", lambda: None)
    monkeypatch.setattr(reporting_window, "NETWORK_INTELLIGENCE_REPORTS_DIR", reports)
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
    monkeypatch.setattr(history_center_window, "ensure_app_dirs", lambda: None)
    monkeypatch.setattr(
        history_center_window,
        "NETWORK_INTELLIGENCE_AUTOMATIC_SNAPSHOTS_DIR",
        automatic_dir,
    )
    monkeypatch.setattr(
        history_center_window,
        "NETWORK_INTELLIGENCE_RETENTION_FILE",
        retention_path,
    )

    tool = history_center_window.Tool()
    qtbot.addWidget(tool)
    tool.schedule_timer.stop()
    return tool, automatic_dir, retention_path


def test_history_center_tool_loads_policy_and_exposes_scheduler_hook(qtbot, monkeypatch, tmp_path):
    policy = RetentionPolicy(keep_per_scope=45, max_age_days=30)
    tool, _automatic_dir, _retention_path = make_tool(
        qtbot, monkeypatch, tmp_path, policy=policy
    )

    assert tool.retention_policy == policy
    assert tool._automatic_snapshot_retention_policy() == policy
    assert "45 por scope" in tool.history_center_status.text()
    assert "30 días" in tool.history_center_status.text()
    assert tool.history_center_button.isEnabled()


def test_history_center_tool_uses_default_for_corrupt_policy_without_overwriting(
    qtbot, monkeypatch, tmp_path
):
    retention_path = tmp_path / "network_intelligence_retention.json"
    retention_path.write_text("not-json", encoding="utf-8")
    warnings = []
    monkeypatch.setattr(
        history_center_window,
        "show_warning",
        lambda *args, **kwargs: warnings.append((args, kwargs)),
    )

    tool, _automatic_dir, path = make_tool(qtbot, monkeypatch, tmp_path)

    assert warnings
    assert tool.retention_policy == RetentionPolicy()
    assert path.read_text(encoding="utf-8") == "not-json"


def test_history_center_dialog_indexes_filters_and_navigates(qtbot, tmp_path):
    automatic_dir = tmp_path / "scheduled"
    retention_path = tmp_path / "retention.json"
    now = datetime.now(timezone.utc)
    _write_snapshot(automatic_dir, "scheduled_192_a.json", now - timedelta(days=20), score=95)
    second = _write_snapshot(automatic_dir, "scheduled_192_b.json", now - timedelta(days=2), score=88)
    latest = _write_snapshot(automatic_dir, "scheduled_192_c.json", now, score=91, high=1)
    _write_snapshot(
        automatic_dir,
        "scheduled_10_a.json",
        now - timedelta(days=1),
        scope=OTHER_SCOPE,
        score=99,
    )

    dialog = history_center_window.HistoryCenterDialog(
        automatic_dir,
        retention_path,
        RetentionPolicy(),
    )
    qtbot.addWidget(dialog)

    assert dialog.table.rowCount() == 4
    assert "4 snapshot" in dialog.summary_label.text()
    assert "2 scopes" in dialog.summary_label.text()
    assert dialog.chart.entries == ()
    assert "Selecciona un scope" in dialog.chart.empty_message
    assert dialog.keep_spin.minimum() == 2

    scope_index = dialog.scope_filter.findData(SCOPE)
    dialog.scope_filter.setCurrentIndex(scope_index)
    time_index = dialog.time_filter.findData(7)
    dialog.time_filter.setCurrentIndex(time_index)

    assert dialog.table.rowCount() == 2
    assert [entry.path for entry in dialog.filtered_entries] == [second, latest]
    assert "Score 88 → 91" in dialog.summary_label.text()
    assert dialog.chart.entries == dialog.filtered_entries
    assert latest.name in dialog.detail_area.toPlainText()
    assert dialog.previous_button.isEnabled()
    dialog._move_selection(-1)
    assert second.name in dialog.detail_area.toPlainText()
    assert dialog.next_button.isEnabled()


def test_history_center_dialog_saves_retention_policy(qtbot, tmp_path):
    retention_path = tmp_path / "retention.json"
    dialog = history_center_window.HistoryCenterDialog(
        tmp_path / "scheduled",
        retention_path,
        RetentionPolicy(),
    )
    qtbot.addWidget(dialog)
    dialog.keep_spin.setValue(60)
    dialog.age_spin.setValue(90)

    dialog._save_policy()

    assert dialog.policy == RetentionPolicy(keep_per_scope=60, max_age_days=90)
    assert load_retention_policy(retention_path) == dialog.policy
    assert "Política guardada" in dialog.catalog_status.text()


def test_history_center_dialog_cleanup_requires_confirmation_and_preserves_baseline_pair(
    qtbot, monkeypatch, tmp_path
):
    automatic_dir = tmp_path / "scheduled"
    retention_path = tmp_path / "retention.json"
    now = datetime.now(timezone.utc)
    old = _write_snapshot(automatic_dir, "scheduled_192_old.json", now - timedelta(days=10))
    previous = _write_snapshot(
        automatic_dir,
        "scheduled_192_previous.json",
        now - timedelta(days=1),
    )
    latest = _write_snapshot(automatic_dir, "scheduled_192_latest.json", now)
    manual = automatic_dir / "manual.json"
    manual.write_text("manual", encoding="utf-8")

    dialog = history_center_window.HistoryCenterDialog(
        automatic_dir,
        retention_path,
        RetentionPolicy(),
    )
    qtbot.addWidget(dialog)
    dialog.keep_spin.setValue(2)
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes)

    dialog._clean_now()

    assert not old.exists()
    assert previous.exists()
    assert latest.exists()
    assert manual.exists()
    assert load_retention_policy(retention_path).keep_per_scope == 2
    assert "1 snapshot" in dialog.catalog_status.text()


def test_history_center_compare_previous_uses_same_scope(qtbot, monkeypatch, tmp_path):
    automatic_dir = tmp_path / "scheduled"
    now = datetime.now(timezone.utc)
    _write_snapshot(automatic_dir, "scheduled_192_a.json", now - timedelta(hours=2), score=95)
    _write_snapshot(automatic_dir, "scheduled_10_a.json", now - timedelta(hours=1), scope=OTHER_SCOPE)
    _write_snapshot(automatic_dir, "scheduled_192_b.json", now, score=90)

    shown = []
    monkeypatch.setattr(
        history_center_window.SnapshotComparisonDialog,
        "exec_",
        lambda self: shown.append(self.comparison if hasattr(self, "comparison") else True) or 0,
    )
    dialog = history_center_window.HistoryCenterDialog(
        automatic_dir,
        tmp_path / "retention.json",
        RetentionPolicy(),
    )
    qtbot.addWidget(dialog)
    scope_index = dialog.scope_filter.findData(SCOPE)
    dialog.scope_filter.setCurrentIndex(scope_index)
    dialog.table.selectRow(dialog.table.rowCount() - 1)

    dialog._compare_previous()

    assert shown


def test_opening_history_center_adopts_policy_saved_by_dialog(qtbot, monkeypatch, tmp_path):
    tool, _automatic_dir, retention_path = make_tool(qtbot, monkeypatch, tmp_path)
    new_policy = RetentionPolicy(keep_per_scope=25, max_age_days=14)

    class FakeDialog:
        def __init__(self, *args, **kwargs):
            self.policy = new_policy

        def exec_(self):
            save_retention_policy(retention_path, self.policy)
            return 0

    monkeypatch.setattr(history_center_window, "HistoryCenterDialog", FakeDialog)

    tool._open_history_center()

    assert tool.retention_policy == new_policy
    assert tool._automatic_snapshot_retention_policy() == new_policy
    assert "25 por scope" in tool.history_center_status.text()
