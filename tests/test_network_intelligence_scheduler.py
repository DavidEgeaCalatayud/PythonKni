from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from pythonkni.network_intelligence import automatic_snapshot, scheduler
from pythonkni.network_intelligence.automatic_snapshot import create_automatic_snapshot
from pythonkni.network_intelligence.scheduler import (
    MAX_AUTOMATIC_SNAPSHOTS_PER_SCOPE,
    change_schedule_interval,
    create_schedule,
    disable_schedule,
    load_schedule,
    mark_schedule_started,
    mark_schedule_success,
    prune_automatic_snapshots,
    save_schedule,
    schedule_due,
)

NOW = datetime(2026, 9, 1, 20, 0, tzinfo=timezone.utc)
SCOPE = "192.168.1.0/24"


def test_schedule_is_canonical_due_and_advances_before_execution():
    config = create_schedule("192.168.1.44/24", 60, now=NOW)

    assert config.enabled
    assert config.scope == SCOPE
    assert config.next_run_at == NOW + timedelta(hours=1)
    assert not schedule_due(config, now=NOW + timedelta(minutes=59))
    assert schedule_due(config, now=NOW + timedelta(hours=1))

    started = mark_schedule_started(config, now=NOW + timedelta(hours=1))
    assert started.last_started_at == NOW + timedelta(hours=1)
    assert started.next_run_at == NOW + timedelta(hours=2)
    assert not schedule_due(started, now=NOW + timedelta(hours=1, seconds=1))


def test_schedule_rejects_unsafe_scope_interval_and_naive_time():
    with pytest.raises(ValueError, match="red local permitida"):
        create_schedule("8.8.8.0/24", 60, now=NOW)
    with pytest.raises(ValueError, match="between 15 and 1440"):
        create_schedule(SCOPE, 5, now=NOW)
    with pytest.raises(ValueError, match="timezone-aware"):
        create_schedule(SCOPE, 60, now=datetime(2026, 9, 1, 20, 0))


def test_schedule_persistence_round_trip_and_disable(tmp_path):
    path = tmp_path / "schedule.json"
    config = create_schedule(SCOPE, 30, now=NOW)
    config = mark_schedule_started(config, now=NOW + timedelta(minutes=30))
    config = mark_schedule_success(
        config,
        now=NOW + timedelta(minutes=31),
        snapshot=tmp_path / "scheduled.json",
    )

    save_schedule(path, config)
    loaded = load_schedule(path)

    assert loaded == config
    disabled = disable_schedule(loaded)
    save_schedule(path, disabled)
    assert not load_schedule(path).enabled
    assert load_schedule(path).next_run_at is None


def test_schedule_load_rejects_invalid_schema_and_enabled_missing_next_run(tmp_path):
    path = tmp_path / "schedule.json"
    path.write_text('{"schema_version": 99}', encoding="utf-8")
    with pytest.raises(ValueError, match="schema version"):
        load_schedule(path)

    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "enabled": True,
                "scope": SCOPE,
                "interval_minutes": 60,
                "next_run_at": None,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="next_run_at"):
        load_schedule(path)


def test_schedule_load_rejects_truthy_non_boolean_enabled(tmp_path):
    path = tmp_path / "schedule.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "enabled": "false",
                "scope": SCOPE,
                "interval_minutes": 60,
                "next_run_at": "2026-09-01T21:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="enabled must be a boolean"):
        load_schedule(path)


def test_schedule_atomic_save_preserves_previous_valid_file(tmp_path, monkeypatch):
    path = tmp_path / "schedule.json"
    original = create_schedule(SCOPE, 60, now=NOW)
    save_schedule(path, original)
    replacement = change_schedule_interval(original, 30, now=NOW)

    def fail_replace(_source, _destination):
        raise OSError("replace failed")

    monkeypatch.setattr(scheduler.os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        save_schedule(path, replacement)

    assert load_schedule(path) == original
    assert not list(tmp_path.glob(".schedule.json.*.tmp"))


def test_interval_change_resets_next_run_without_losing_history():
    config = create_schedule(SCOPE, 60, now=NOW)
    config = mark_schedule_started(config, now=NOW + timedelta(hours=1))
    config = mark_schedule_success(
        config, now=NOW + timedelta(hours=1, minutes=1), snapshot="a.json"
    )

    changed = change_schedule_interval(config, 180, now=NOW + timedelta(hours=2))

    assert changed.interval_minutes == 180
    assert changed.next_run_at == NOW + timedelta(hours=5)
    assert changed.last_started_at == config.last_started_at
    assert changed.last_success_at == config.last_success_at
    assert changed.last_snapshot == "a.json"


def test_automatic_snapshot_is_atomic_valid_report_and_history_compatible(tmp_path):
    result = create_automatic_snapshot(
        tmp_path,
        SCOPE,
        [],
        [],
        [],
        generated_at=NOW,
    )

    payload = json.loads(result.path.read_text(encoding="utf-8"))
    assert payload["scope"] == SCOPE
    assert payload["generated_at"] == "2026-09-01T20:00:00Z"
    assert payload["security_score"]["score"] == 100
    assert result.path.name.startswith("scheduled_192.168.1.0_24_")
    assert not list(tmp_path.glob(".*.json"))


def test_automatic_snapshot_failure_never_publishes_partial_report(tmp_path, monkeypatch):
    def fail_export(path, _report):
        Path(path).write_text("partial", encoding="utf-8")
        raise OSError("serialization failed")

    monkeypatch.setattr(automatic_snapshot, "export_network_report", fail_export)

    with pytest.raises(OSError, match="serialization failed"):
        create_automatic_snapshot(tmp_path, SCOPE, [], [], [], generated_at=NOW)

    assert not list(tmp_path.glob("scheduled_*.json"))
    assert not list(tmp_path.glob(".*.json"))


def test_automatic_snapshot_retention_is_bounded_per_scope(tmp_path):
    total = MAX_AUTOMATIC_SNAPSHOTS_PER_SCOPE + 3
    for index in range(total):
        create_automatic_snapshot(
            tmp_path,
            SCOPE,
            [],
            [],
            [],
            generated_at=NOW + timedelta(seconds=index),
        )

    snapshots = sorted(tmp_path.glob("scheduled_192.168.1.0_24_*.json"))
    assert len(snapshots) == MAX_AUTOMATIC_SNAPSHOTS_PER_SCOPE
    assert "20:00:03" in json.loads(snapshots[0].read_text(encoding="utf-8"))["generated_at"]


def test_prune_does_not_touch_other_scopes_or_manual_reports(tmp_path):
    for index in range(3):
        (tmp_path / f"scheduled_192.168.1.0_24_20260901T00000{index}.json").write_text(
            "{}", encoding="utf-8"
        )
    other = tmp_path / "scheduled_10.0.0.0_24_20260901T000000.json"
    manual = tmp_path / "network_intelligence_report.json"
    other.write_text("{}", encoding="utf-8")
    manual.write_text("{}", encoding="utf-8")

    removed = prune_automatic_snapshots(tmp_path, SCOPE, keep=1)

    assert len(removed) == 2
    assert other.exists()
    assert manual.exists()
