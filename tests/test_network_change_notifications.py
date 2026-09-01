from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from datetime import datetime

import pytest

from pythonkni.network_intelligence import notifications
from pythonkni.network_intelligence.notifications import (
    MAX_NOTIFICATION_FILE_BYTES,
    MAX_NOTIFICATION_INBOX_ITEMS,
    NOTIFICATION_SCHEMA_VERSION,
    NotificationSeverity,
    build_change_notifications,
    format_notification_inbox,
    load_notification_inbox,
    mark_all_notifications_read,
    merge_notifications,
    save_notification_inbox,
)

SCOPE = "192.168.1.0/24"
BASELINE_TIME = "2026-09-01T20:00:00Z"
CURRENT_TIME = "2026-09-01T21:00:00Z"


def asset(
    asset_id: str,
    ip: str,
    *,
    risk: str = "LOW",
    ports: list[int] | None = None,
    hostname: str = "",
    online: bool = True,
) -> dict:
    return {
        "asset_id": asset_id,
        "ip": ip,
        "mac": "AA:BB:CC:DD:EE:FF",
        "hostname": hostname,
        "vendor": "Example",
        "kind": "PC",
        "risk": risk,
        "open_ports": list(ports or []),
        "services": [],
        "classification_confidence": 70,
        "is_online": online,
        "first_seen": "2026-09-01T19:00:00Z",
        "last_seen": BASELINE_TIME,
        "last_change": BASELINE_TIME,
    }


def relationship(*, confidence: str = "INFERRED", evidence: list[str] | None = None) -> dict:
    return {
        "kind": "Default gateway",
        "source_id": "asset-1",
        "target_id": "gateway",
        "protocol": "",
        "source_port": "",
        "target_port": "",
        "confidence": confidence,
        "evidence": list(evidence or ["gateway"]),
    }


def report(
    generated_at: str,
    assets: list[dict],
    *,
    score: int = 90,
    relationships: list[dict] | None = None,
) -> dict:
    return {
        "schema_version": 2,
        "generated_at": generated_at,
        "scope": SCOPE,
        "summary": {},
        "security_score": {
            "score": score,
            "total_devices": len(assets),
            "unknown_devices": 0,
            "high_risk": sum(item["risk"] == "HIGH" for item in assets),
            "medium_risk": sum(item["risk"] == "MEDIUM" for item in assets),
            "low_risk": sum(item["risk"] == "LOW" for item in assets),
            "findings": [],
        },
        "assets": assets,
        "relationships": list(relationships or []),
        "timeline": [],
    }


def one_notification():
    device = asset("asset-1", "192.168.1.10", ports=[80])
    opened = asset("asset-1", "192.168.1.10", ports=[80, 443])
    return build_change_notifications(
        report(BASELINE_TIME, [device]),
        report(CURRENT_TIME, [opened]),
    ).notifications[0]


def test_engine_ignores_timestamp_status_and_non_security_discovery_churn():
    before_asset = asset("asset-1", "192.168.1.10", ports=[80, 443], hostname="old")
    after_asset = deepcopy(before_asset)
    after_asset.update(
        {
            "hostname": "new",
            "classification_confidence": 95,
            "is_online": False,
            "last_seen": CURRENT_TIME,
            "last_change": CURRENT_TIME,
            "open_ports": [80],
        }
    )

    batch = build_change_notifications(
        report(BASELINE_TIME, [before_asset]),
        report(CURRENT_TIME, [after_asset]),
    )

    assert batch.notifications == ()


def test_engine_emits_meaningful_changes_with_deterministic_severity():
    before = asset("asset-1", "192.168.1.10", risk="LOW", ports=[80], hostname="server")
    after = asset(
        "asset-1",
        "192.168.1.10",
        risk="HIGH",
        ports=[80, 445],
        hostname="server",
    )
    new = asset("asset-2", "192.168.1.20", risk="LOW", ports=[443], hostname="laptop")

    batch = build_change_notifications(
        report(BASELINE_TIME, [before], score=90),
        report(
            CURRENT_TIME,
            [after, new],
            score=72,
            relationships=[relationship()],
        ),
    )

    by_category = {item.category: item for item in batch.notifications}
    assert set(by_category) == {
        "new_device",
        "risk_changed",
        "ports_opened",
        "security_score_drop",
        "relationships_changed",
    }
    assert by_category["new_device"].severity == NotificationSeverity.WARNING
    assert by_category["risk_changed"].severity == NotificationSeverity.CRITICAL
    assert by_category["ports_opened"].severity == NotificationSeverity.CRITICAL
    assert by_category["security_score_drop"].severity == NotificationSeverity.CRITICAL
    assert by_category["relationships_changed"].severity == NotificationSeverity.WARNING
    assert "445" in by_category["ports_opened"].message
    assert batch.security_score_delta == -18
    assert batch.critical_count == 3
    assert batch.warning_count == 2


def test_high_risk_new_device_is_critical_and_small_score_drop_is_warning():
    before = asset("asset-1", "192.168.1.10")
    new = asset("asset-2", "192.168.1.20", risk="HIGH")

    batch = build_change_notifications(
        report(BASELINE_TIME, [before], score=90),
        report(CURRENT_TIME, [before, new], score=85),
    )
    by_category = {item.category: item for item in batch.notifications}

    assert by_category["new_device"].severity == NotificationSeverity.CRITICAL
    assert by_category["security_score_drop"].severity == NotificationSeverity.WARNING


def test_risk_reduction_and_relationship_removal_are_informational():
    before = asset("asset-1", "192.168.1.10", risk="HIGH")
    after = asset("asset-1", "192.168.1.10", risk="MEDIUM")

    batch = build_change_notifications(
        report(BASELINE_TIME, [before], relationships=[relationship()]),
        report(CURRENT_TIME, [after]),
    )
    by_category = {item.category: item for item in batch.notifications}

    assert by_category["risk_changed"].severity == NotificationSeverity.INFO
    assert by_category["relationships_changed"].severity == NotificationSeverity.INFO
    assert batch.info_count == 2


def test_relationship_evidence_change_is_aggregated_into_one_warning():
    device = asset("asset-1", "192.168.1.10")
    batch = build_change_notifications(
        report(
            BASELINE_TIME,
            [device],
            relationships=[relationship(confidence="INFERRED", evidence=["a"])],
        ),
        report(
            CURRENT_TIME,
            [device],
            relationships=[relationship(confidence="CONFIRMED", evidence=["a", "b"])],
        ),
    )

    relationship_notifications = [
        item for item in batch.notifications if item.category == "relationships_changed"
    ]
    assert len(relationship_notifications) == 1
    assert relationship_notifications[0].severity == NotificationSeverity.WARNING
    assert any("Confidence" in detail for detail in relationship_notifications[0].details)


def test_merge_deduplicates_exact_snapshot_pair_but_keeps_future_recurrence():
    device = asset("asset-1", "192.168.1.10", ports=[80])
    opened = asset("asset-1", "192.168.1.10", ports=[80, 443])
    first = build_change_notifications(
        report(BASELINE_TIME, [device]),
        report(CURRENT_TIME, [opened]),
    )

    merged, added = merge_notifications((), first.notifications)
    replayed, replay_added = merge_notifications(merged, first.notifications)

    assert added == 1
    assert replay_added == 0
    assert replayed == merged

    later = build_change_notifications(
        report("2026-09-01T22:00:00Z", [device]),
        report("2026-09-01T23:00:00Z", [opened]),
    )
    recurrent, recurrent_added = merge_notifications(replayed, later.notifications)
    assert recurrent_added == 1
    assert len(recurrent) == 2
    assert recurrent[0].event_id != recurrent[1].event_id


def test_merge_rejects_invalid_capacity_and_enforces_requested_bound():
    item = one_notification()
    with pytest.raises(ValueError, match="at least 1"):
        merge_notifications((), (item,), max_items=0)

    later = replace(item, event_id="later", detected_at=item.detected_at.replace(hour=22))
    merged, added = merge_notifications((item,), (later,), max_items=1)
    assert added == 1
    assert merged == (later,)


def test_notification_inbox_round_trip_and_mark_read(tmp_path):
    path = tmp_path / "notifications.json"
    item = one_notification()

    save_notification_inbox(path, [item])
    loaded = load_notification_inbox(path)
    assert loaded == (item,)
    assert not loaded[0].read

    marked = mark_all_notifications_read(loaded)
    save_notification_inbox(path, marked)
    assert load_notification_inbox(path)[0].read
    assert "leído" in format_notification_inbox(marked)


def test_empty_notification_inbox_helpers_are_stable(tmp_path):
    assert load_notification_inbox(tmp_path / "missing.json") == ()
    assert format_notification_inbox(()) == "No hay cambios relevantes registrados."


def test_notification_inbox_atomic_save_preserves_previous_file(tmp_path, monkeypatch):
    path = tmp_path / "notifications.json"
    original = (one_notification(),)
    save_notification_inbox(path, original)

    def fail_replace(_source, _destination):
        raise OSError("replace failed")

    monkeypatch.setattr(notifications.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        save_notification_inbox(path, mark_all_notifications_read(original))

    assert load_notification_inbox(path) == original
    assert not list(tmp_path.glob(".notifications.json.*.tmp"))


def test_notification_save_rejects_naive_detected_timestamp(tmp_path):
    item = replace(one_notification(), detected_at=datetime(2026, 9, 1, 21, 0))
    with pytest.raises(ValueError, match="timezone-aware"):
        save_notification_inbox(tmp_path / "notifications.json", [item])


def test_notification_inbox_rejects_invalid_boolean_and_duplicate_ids(tmp_path):
    path = tmp_path / "notifications.json"
    item = one_notification()
    save_notification_inbox(path, [item])

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["notifications"][0]["read"] = "false"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="read must be a boolean"):
        load_notification_inbox(path)

    payload["notifications"][0]["read"] = False
    payload["notifications"].append(deepcopy(payload["notifications"][0]))
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate event_id"):
        load_notification_inbox(path)


def test_notification_inbox_rejects_root_schema_collection_and_size_errors(tmp_path):
    path = tmp_path / "notifications.json"

    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="root must be a JSON object"):
        load_notification_inbox(path)

    path.write_text(json.dumps({"schema_version": 99, "notifications": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="schema version"):
        load_notification_inbox(path)

    path.write_text(
        json.dumps({"schema_version": NOTIFICATION_SCHEMA_VERSION, "notifications": {}}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="JSON array"):
        load_notification_inbox(path)

    path.write_text(
        json.dumps(
            {
                "schema_version": NOTIFICATION_SCHEMA_VERSION,
                "notifications": [None] * (MAX_NOTIFICATION_INBOX_ITEMS + 1),
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="more than"):
        load_notification_inbox(path)

    path.write_bytes(b" " * (MAX_NOTIFICATION_FILE_BYTES + 1))
    with pytest.raises(ValueError, match="2 MiB"):
        load_notification_inbox(path)


def test_notification_inbox_rejects_malformed_json_and_item_shape(tmp_path):
    path = tmp_path / "notifications.json"
    path.write_text("not-json", encoding="utf-8")
    with pytest.raises(ValueError, match="Could not read notification inbox"):
        load_notification_inbox(path)

    path.write_text(
        json.dumps({"schema_version": NOTIFICATION_SCHEMA_VERSION, "notifications": [42]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="must be a JSON object"):
        load_notification_inbox(path)


def test_notification_inbox_rejects_invalid_item_fields(tmp_path):
    path = tmp_path / "notifications.json"
    item = one_notification()
    save_notification_inbox(path, [item])
    valid = json.loads(path.read_text(encoding="utf-8"))

    mutations = (
        ("empty title", lambda payload: payload["notifications"][0].__setitem__("title", ""), "title"),
        (
            "non-string detected_at",
            lambda payload: payload["notifications"][0].__setitem__("detected_at", 5),
            "detected_at must be a string",
        ),
        (
            "invalid detected_at",
            lambda payload: payload["notifications"][0].__setitem__("detected_at", "later"),
            "valid ISO-8601",
        ),
        (
            "naive baseline",
            lambda payload: payload["notifications"][0].__setitem__(
                "baseline_generated_at", "2026-09-01T20:00:00"
            ),
            "include a timezone",
        ),
        (
            "invalid severity",
            lambda payload: payload["notifications"][0].__setitem__("severity", "SEVERE"),
            "severity is invalid",
        ),
        (
            "invalid subject",
            lambda payload: payload["notifications"][0].__setitem__("subject_id", 7),
            "subject_id must be a string",
        ),
        (
            "invalid details",
            lambda payload: payload["notifications"][0].__setitem__("details", ["ok", 7]),
            "details must contain strings only",
        ),
    )

    for _name, mutate, message in mutations:
        payload = deepcopy(valid)
        mutate(payload)
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ValueError, match=message):
            load_notification_inbox(path)
