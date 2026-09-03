from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from pythonkni.network_intelligence.fingerprint_policy import FingerprintPolicy
from pythonkni.network_intelligence.scheduler import (
    ScheduleConfig,
    change_fingerprint_policy,
    create_schedule,
    load_schedule,
    save_schedule,
)

NOW = datetime(2026, 9, 3, 9, 0, tzinfo=timezone.utc)
SCOPE = "192.168.1.0/24"


def test_new_schedule_defaults_to_manual_fingerprint_policy():
    config = create_schedule(SCOPE, 60, now=NOW)
    assert config.fingerprint_policy is FingerprintPolicy.MANUAL


def test_schedule_v1_migrates_to_manual_policy_without_losing_state(tmp_path):
    path = tmp_path / "schedule.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "enabled": True,
                "scope": SCOPE,
                "interval_minutes": 60,
                "next_run_at": "2026-09-03T10:00:00Z",
                "last_started_at": "2026-09-03T09:00:00Z",
                "last_success_at": "2026-09-03T08:00:00Z",
                "last_snapshot": "scheduled.json",
            }
        ),
        encoding="utf-8",
    )

    loaded = load_schedule(path)

    assert loaded.enabled
    assert loaded.fingerprint_policy is FingerprintPolicy.MANUAL
    assert loaded.last_snapshot == "scheduled.json"


def test_schedule_v2_round_trips_automatic_policy(tmp_path):
    path = tmp_path / "schedule.json"
    config = create_schedule(
        SCOPE,
        30,
        now=NOW,
        fingerprint_policy=FingerprintPolicy.AUTOMATIC_AFTER_DISCOVERY,
    )

    save_schedule(path, config)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["schema_version"] == 2
    assert payload["fingerprint_policy"] == "automatic_after_discovery"
    assert load_schedule(path) == config


def test_change_fingerprint_policy_preserves_schedule_timing_and_history():
    config = ScheduleConfig(
        enabled=True,
        scope=SCOPE,
        interval_minutes=60,
        next_run_at=NOW + timedelta(hours=1),
        last_started_at=NOW - timedelta(minutes=1),
        last_success_at=NOW - timedelta(hours=1),
        last_snapshot="previous.json",
    )

    changed = change_fingerprint_policy(config, FingerprintPolicy.CHANGED_SERVICES_ONLY)

    assert changed.fingerprint_policy is FingerprintPolicy.CHANGED_SERVICES_ONLY
    assert changed.next_run_at == config.next_run_at
    assert changed.last_started_at == config.last_started_at
    assert changed.last_success_at == config.last_success_at
    assert changed.last_snapshot == config.last_snapshot


def test_invalid_fingerprint_policy_is_rejected_on_load(tmp_path):
    path = tmp_path / "schedule.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "enabled": False,
                "scope": "",
                "interval_minutes": 60,
                "next_run_at": None,
                "fingerprint_policy": "exploit_everything",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="fingerprint policy"):
        load_schedule(path)
