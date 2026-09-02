from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from pythonkni.network_intelligence import automatic_snapshot, retention
from pythonkni.network_intelligence.automatic_snapshot import create_automatic_snapshot
from pythonkni.network_intelligence.retention import (
    RetentionPolicy,
    apply_retention_policy,
    filter_snapshot_entries,
    load_retention_policy,
    load_snapshot_catalog,
    previous_snapshot_for,
    retention_candidates,
    save_retention_policy,
    summarize_trend,
    validate_retention_policy,
)

NOW = datetime(2026, 9, 2, 8, 0, tzinfo=timezone.utc)
SCOPE = "192.168.1.0/24"
OTHER_SCOPE = "10.0.0.0/24"


def _report(
    generated_at: datetime,
    *,
    scope: str = SCOPE,
    score: int = 90,
    devices: int = 2,
    high: int = 0,
    medium: int = 1,
    unknown: int = 0,
) -> dict:
    return {
        "schema_version": 2,
        "generated_at": generated_at.isoformat().replace("+00:00", "Z"),
        "scope": scope,
        "summary": {},
        "security_score": {
            "score": score,
            "total_devices": devices,
            "unknown_devices": unknown,
            "high_risk": high,
            "medium_risk": medium,
            "low_risk": max(0, devices - high - medium),
            "findings": ["finding"] if score < 100 else [],
        },
        "assets": [],
        "relationships": [],
        "timeline": [],
    }


def _write_snapshot(
    directory: Path,
    name: str,
    generated_at: datetime,
    **kwargs,
) -> Path:
    path = directory / name
    path.write_text(json.dumps(_report(generated_at, **kwargs)), encoding="utf-8")
    return path


def test_retention_policy_round_trip_and_validation(tmp_path):
    path = tmp_path / "retention.json"
    policy = RetentionPolicy(keep_per_scope=75, max_age_days=45)

    save_retention_policy(path, policy)

    assert load_retention_policy(path) == policy
    with pytest.raises(ValueError, match="between 2 and 1000"):
        validate_retention_policy(RetentionPolicy(keep_per_scope=1))
    with pytest.raises(ValueError, match="between 1 and 3650"):
        validate_retention_policy(RetentionPolicy(max_age_days=0))
    with pytest.raises(ValueError, match="integer"):
        validate_retention_policy(RetentionPolicy(keep_per_scope=True))


def test_retention_load_rejects_bad_schema_and_non_object(tmp_path):
    path = tmp_path / "retention.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        load_retention_policy(path)

    path.write_text('{"schema_version": 99}', encoding="utf-8")
    with pytest.raises(ValueError, match="schema version"):
        load_retention_policy(path)


def test_retention_atomic_save_preserves_previous_file(tmp_path, monkeypatch):
    path = tmp_path / "retention.json"
    original = RetentionPolicy(keep_per_scope=120)
    save_retention_policy(path, original)

    def fail_replace(_source, _destination):
        raise OSError("replace failed")

    monkeypatch.setattr(retention.os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        save_retention_policy(path, RetentionPolicy(keep_per_scope=50, max_age_days=30))

    assert load_retention_policy(path) == original
    assert not list(tmp_path.glob(".retention.json.*.tmp"))


def test_catalog_indexes_valid_scheduled_snapshots_and_preserves_invalid_files(tmp_path):
    newest = _write_snapshot(
        tmp_path,
        "scheduled_192.168.1.0_24_20260902T080000.000000Z.json",
        NOW,
        score=82,
        high=1,
    )
    older = _write_snapshot(
        tmp_path,
        "scheduled_192.168.1.0_24_20260901T080000.000000Z.json",
        NOW - timedelta(days=1),
        score=90,
    )
    invalid = tmp_path / "scheduled_192.168.1.0_24_broken.json"
    invalid.write_text("not-json", encoding="utf-8")
    manual = tmp_path / "network_intelligence_report.json"
    manual.write_text("not-a-scheduled-snapshot", encoding="utf-8")

    catalog = load_snapshot_catalog(tmp_path)

    assert [entry.path for entry in catalog.entries] == [older, newest]
    assert catalog.entries[-1].score == 82
    assert catalog.entries[-1].high_risk == 1
    assert catalog.skipped[0][0] == invalid
    assert manual.exists()


def test_catalog_limit_reports_truncation(tmp_path):
    for index in range(3):
        _write_snapshot(
            tmp_path,
            f"scheduled_192.168.1.0_24_20260902T08000{index}.000000Z.json",
            NOW + timedelta(seconds=index),
        )

    catalog = load_snapshot_catalog(tmp_path, max_files=2)

    assert len(catalog.entries) == 2
    assert catalog.truncated_count == 1
    with pytest.raises(ValueError, match="positive integer"):
        load_snapshot_catalog(tmp_path, max_files=0)


def test_filter_trend_and_previous_snapshot_are_scope_and_time_aware(tmp_path):
    first = _write_snapshot(
        tmp_path,
        "scheduled_192.168.1.0_24_a.json",
        NOW - timedelta(days=10),
        score=95,
        devices=2,
    )
    middle = _write_snapshot(
        tmp_path,
        "scheduled_192.168.1.0_24_b.json",
        NOW - timedelta(days=3),
        score=85,
        devices=3,
        high=1,
        medium=1,
        unknown=1,
    )
    latest = _write_snapshot(
        tmp_path,
        "scheduled_192.168.1.0_24_c.json",
        NOW,
        score=88,
        devices=4,
        high=1,
        medium=2,
        unknown=0,
    )
    _write_snapshot(
        tmp_path,
        "scheduled_10.0.0.0_24_d.json",
        NOW - timedelta(days=1),
        scope=OTHER_SCOPE,
        score=99,
    )

    catalog = load_snapshot_catalog(tmp_path)
    selected = filter_snapshot_entries(
        catalog.entries,
        scope=SCOPE,
        since=NOW - timedelta(days=7),
    )
    trend = summarize_trend(selected)

    assert [entry.path for entry in selected] == [middle, latest]
    assert trend is not None
    assert trend.points == 2
    assert trend.score_delta == 3
    assert trend.devices_delta == 1
    assert trend.high_risk_delta == 0
    assert trend.medium_risk_delta == 1
    assert trend.unknown_delta == -1
    latest_entry = next(entry for entry in catalog.entries if entry.path == latest)
    assert previous_snapshot_for(catalog.entries, latest_entry).path == middle
    first_entry = next(entry for entry in catalog.entries if entry.path == first)
    assert previous_snapshot_for(catalog.entries, first_entry) is None

    with pytest.raises(ValueError, match="start"):
        filter_snapshot_entries(catalog.entries, since=NOW, until=NOW - timedelta(days=1))


def test_retention_candidates_combine_count_and_age_but_preserve_latest_pair(tmp_path):
    times = [
        NOW - timedelta(days=10),
        NOW - timedelta(days=8),
        NOW - timedelta(days=6),
        NOW - timedelta(days=3),
        NOW,
    ]
    paths = [
        _write_snapshot(tmp_path, f"scheduled_192.168.1.0_24_{index}.json", value)
        for index, value in enumerate(times)
    ]
    catalog = load_snapshot_catalog(tmp_path)

    removable = retention_candidates(
        catalog.entries,
        RetentionPolicy(keep_per_scope=3, max_age_days=1),
        now=NOW,
        scope=SCOPE,
    )

    assert [entry.path for entry in removable] == paths[:3]
    assert paths[-2] not in {entry.path for entry in removable}
    assert paths[-1] not in {entry.path for entry in removable}


def test_apply_retention_only_deletes_valid_scheduler_owned_snapshots(tmp_path):
    old = _write_snapshot(
        tmp_path,
        "scheduled_192.168.1.0_24_old.json",
        NOW - timedelta(days=30),
    )
    previous = _write_snapshot(
        tmp_path,
        "scheduled_192.168.1.0_24_previous.json",
        NOW - timedelta(days=1),
    )
    latest = _write_snapshot(tmp_path, "scheduled_192.168.1.0_24_latest.json", NOW)
    other_scope = _write_snapshot(
        tmp_path,
        "scheduled_10.0.0.0_24_other.json",
        NOW - timedelta(days=30),
        scope=OTHER_SCOPE,
    )
    invalid = tmp_path / "scheduled_192.168.1.0_24_corrupt.json"
    invalid.write_text("corrupt", encoding="utf-8")
    manual = tmp_path / "manual.json"
    manual.write_text("manual", encoding="utf-8")

    cleanup = apply_retention_policy(
        tmp_path,
        RetentionPolicy(keep_per_scope=2),
        now=NOW,
        scope=SCOPE,
    )

    assert cleanup.removed == (old,)
    assert cleanup.bytes_reclaimed > 0
    assert previous.exists()
    assert latest.exists()
    assert other_scope.exists()
    assert invalid.exists()
    assert manual.exists()


def test_automatic_snapshot_uses_configurable_retention_policy(tmp_path):
    manual = tmp_path / "manual.json"
    manual.write_text("manual", encoding="utf-8")

    for index in range(4):
        create_automatic_snapshot(
            tmp_path,
            SCOPE,
            [],
            [],
            [],
            generated_at=NOW + timedelta(minutes=index),
            retention_policy=RetentionPolicy(keep_per_scope=2),
        )

    snapshots = sorted(tmp_path.glob("scheduled_*.json"))
    assert len(snapshots) == 2
    assert manual.exists()


def test_automatic_snapshot_age_cleanup_preserves_previous_change_baseline(tmp_path):
    for index in range(3):
        create_automatic_snapshot(
            tmp_path,
            SCOPE,
            [],
            [],
            [],
            generated_at=NOW + timedelta(minutes=index),
            retention_policy=RetentionPolicy(keep_per_scope=120, max_age_days=1),
        )

    result = create_automatic_snapshot(
        tmp_path,
        SCOPE,
        [],
        [],
        [],
        generated_at=NOW + timedelta(days=10),
        retention_policy=RetentionPolicy(keep_per_scope=2, max_age_days=1),
    )

    snapshots = sorted(tmp_path.glob("scheduled_*.json"))
    assert len(snapshots) == 2
    assert result.path == snapshots[-1]
    assert snapshots[-2].exists()


def test_retention_failure_does_not_unpublish_successful_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(
        automatic_snapshot,
        "apply_retention_policy",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("cleanup failed")),
    )

    result = create_automatic_snapshot(
        tmp_path,
        SCOPE,
        [],
        [],
        [],
        generated_at=NOW,
        retention_policy=RetentionPolicy(keep_per_scope=2),
    )

    assert result.path.exists()
    assert result.pruned_count == 0
    assert result.retention_error == "cleanup failed"
