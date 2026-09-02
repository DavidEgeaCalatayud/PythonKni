from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PyQt5.QtWidgets import QMessageBox

from pythonkni.network_intelligence import history_center_window
from pythonkni.network_intelligence.retention import RetentionPolicy, SnapshotCatalogEntry

SCOPE = "192.168.1.0/24"
NOW = datetime(2026, 9, 2, 8, 0, tzinfo=timezone.utc)


def _entry(
    tmp_path: Path,
    name: str,
    generated_at: datetime,
    *,
    score: int = 90,
    high: int = 0,
    findings: tuple[str, ...] = (),
) -> SnapshotCatalogEntry:
    path = tmp_path / name
    path.write_text("{}", encoding="utf-8")
    return SnapshotCatalogEntry(
        path=path,
        generated_at=generated_at,
        generated_at_text=generated_at.isoformat().replace("+00:00", "Z"),
        scope=SCOPE,
        schema_version=2,
        score=score,
        total_devices=4,
        high_risk=high,
        medium_risk=1,
        low_risk=3 - high,
        unknown_devices=0,
        findings=findings,
        size_bytes=path.stat().st_size,
    )


def _report(generated_at: datetime, *, score: int = 90) -> dict:
    return {
        "schema_version": 2,
        "generated_at": generated_at.isoformat().replace("+00:00", "Z"),
        "scope": SCOPE,
        "summary": {},
        "security_score": {
            "score": score,
            "total_devices": 2,
            "unknown_devices": 0,
            "high_risk": 0,
            "medium_risk": 1,
            "low_risk": 1,
            "findings": [],
        },
        "assets": [],
        "relationships": [],
        "timeline": [],
    }


def _write_snapshot(directory: Path, name: str, generated_at: datetime, *, score: int = 90) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(json.dumps(_report(generated_at, score=score)), encoding="utf-8")
    return path


def test_format_bytes_and_entry_details_cover_empty_and_populated_findings(tmp_path):
    assert history_center_window._format_bytes(512) == "512 B"
    assert history_center_window._format_bytes(2048) == "2.0 KiB"
    assert history_center_window._format_bytes(2 * 1024 * 1024) == "2.0 MiB"

    empty = _entry(tmp_path, "empty.json", NOW)
    risky = _entry(
        tmp_path,
        "risky.json",
        NOW,
        score=70,
        high=1,
        findings=("Puerto administrativo expuesto",),
    )

    assert "• Ninguno" in history_center_window._entry_details(empty)
    details = history_center_window._entry_details(risky)
    assert "Security Score: 70/100" in details
    assert "Puerto administrativo expuesto" in details


def test_trend_chart_renders_empty_zero_risk_and_high_risk_series(qtbot, tmp_path):
    chart = history_center_window.SnapshotTrendChart()
    qtbot.addWidget(chart)
    chart.resize(640, 240)
    chart.show()

    chart.set_empty_message("No comparable trend")
    empty_pixmap = chart.grab()
    assert not empty_pixmap.isNull()

    first = _entry(tmp_path, "first.json", NOW - timedelta(hours=2), score=95)
    second = _entry(tmp_path, "second.json", NOW - timedelta(hours=1), score=90)
    chart.set_entries((first, second))
    zero_risk_pixmap = chart.grab()
    assert not zero_risk_pixmap.isNull()

    third = _entry(tmp_path, "third.json", NOW, score=82, high=2)
    chart.set_entries((first, second, third))
    high_risk_pixmap = chart.grab()
    assert not high_risk_pixmap.isNull()


def test_dialog_empty_history_and_cleanup_with_no_candidates(qtbot, tmp_path):
    dialog = history_center_window.HistoryCenterDialog(
        tmp_path / "scheduled",
        tmp_path / "retention.json",
        RetentionPolicy(),
    )
    qtbot.addWidget(dialog)

    assert dialog.table.rowCount() == 0
    assert "Sin snapshots" in dialog.summary_label.text()
    assert not dialog.previous_button.isEnabled()
    assert not dialog.next_button.isEnabled()
    assert not dialog.compare_previous_button.isEnabled()

    dialog._move_selection(-1)
    dialog._compare_previous()
    dialog._clean_now()
    assert "no tiene snapshots válidos" in dialog.catalog_status.text()


def test_cleanup_cancellation_preserves_snapshot_files(qtbot, monkeypatch, tmp_path):
    directory = tmp_path / "scheduled"
    old = _write_snapshot(directory, "scheduled_old.json", NOW - timedelta(days=3))
    previous = _write_snapshot(directory, "scheduled_previous.json", NOW - timedelta(days=1))
    latest = _write_snapshot(directory, "scheduled_latest.json", NOW)
    dialog = history_center_window.HistoryCenterDialog(
        directory,
        tmp_path / "retention.json",
        RetentionPolicy(),
    )
    qtbot.addWidget(dialog)
    dialog.keep_spin.setValue(2)
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.No)

    dialog._clean_now()

    assert old.exists()
    assert previous.exists()
    assert latest.exists()


def test_save_policy_failure_is_reported_without_mutating_policy(qtbot, monkeypatch, tmp_path):
    errors = []
    dialog = history_center_window.HistoryCenterDialog(
        tmp_path / "scheduled",
        tmp_path / "retention.json",
        RetentionPolicy(keep_per_scope=120),
    )
    qtbot.addWidget(dialog)
    dialog.keep_spin.setValue(40)
    monkeypatch.setattr(
        history_center_window,
        "save_retention_policy",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )
    monkeypatch.setattr(
        history_center_window,
        "show_error",
        lambda *args, **kwargs: errors.append((args, kwargs)),
    )

    dialog._save_policy()

    assert errors
    assert dialog.policy == RetentionPolicy(keep_per_scope=120)


def test_cleanup_failure_is_reported_and_does_not_claim_success(qtbot, monkeypatch, tmp_path):
    directory = tmp_path / "scheduled"
    old = _write_snapshot(directory, "scheduled_old.json", NOW - timedelta(days=3))
    _write_snapshot(directory, "scheduled_previous.json", NOW - timedelta(days=1))
    _write_snapshot(directory, "scheduled_latest.json", NOW)
    errors = []
    dialog = history_center_window.HistoryCenterDialog(
        directory,
        tmp_path / "retention.json",
        RetentionPolicy(),
    )
    qtbot.addWidget(dialog)
    dialog.keep_spin.setValue(2)
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes)
    monkeypatch.setattr(
        history_center_window,
        "apply_retention_policy",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("locked")),
    )
    monkeypatch.setattr(
        history_center_window,
        "show_error",
        lambda *args, **kwargs: errors.append((args, kwargs)),
    )

    dialog._clean_now()

    assert errors
    assert old.exists()


def test_cleanup_success_survives_policy_persistence_failure(qtbot, monkeypatch, tmp_path):
    directory = tmp_path / "scheduled"
    old = _write_snapshot(directory, "scheduled_old.json", NOW - timedelta(days=3))
    previous = _write_snapshot(directory, "scheduled_previous.json", NOW - timedelta(days=1))
    latest = _write_snapshot(directory, "scheduled_latest.json", NOW)
    warnings = []
    dialog = history_center_window.HistoryCenterDialog(
        directory,
        tmp_path / "retention.json",
        RetentionPolicy(),
    )
    qtbot.addWidget(dialog)
    dialog.keep_spin.setValue(2)
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes)
    monkeypatch.setattr(
        history_center_window,
        "save_retention_policy",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("readonly")),
    )
    monkeypatch.setattr(
        history_center_window,
        "show_warning",
        lambda *args, **kwargs: warnings.append((args, kwargs)),
    )

    dialog._clean_now()

    assert warnings
    assert not old.exists()
    assert previous.exists()
    assert latest.exists()
    assert dialog.policy.keep_per_scope == 2


def test_tool_does_not_open_history_center_while_worker_is_running(monkeypatch):
    tool = object.__new__(history_center_window.Tool)

    class Worker:
        @staticmethod
        def isRunning():
            return True

    tool.worker = Worker()
    monkeypatch.setattr(
        history_center_window,
        "HistoryCenterDialog",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("dialog must not open")),
    )

    history_center_window.Tool._open_history_center(tool)
