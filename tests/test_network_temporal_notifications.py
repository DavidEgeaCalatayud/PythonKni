from __future__ import annotations

from pythonkni.network_intelligence.notifications import load_notification_inbox
from pythonkni.network_intelligence.temporal_notifications import (
    MONITOR_SOURCE_DETAIL,
    PATH_SOURCE_DETAIL,
    is_monitor_notification,
    is_path_notification,
    load_monitor_notifications,
    load_path_notifications,
    load_temporal_notifications,
    mark_notification_ids_read,
    monitor_event_to_notification,
    notification_inbox_lock,
    path_event_to_notification,
    publish_monitor_events,
    publish_path_events,
)
from pythonkni.network_monitor.models import EventSeverity, MonitorEvent
from pythonkni.network_path.models import PathEvent, PathEventSeverity


def event(*, timestamp: float = 1000.0, event_id: str = "logical-event") -> MonitorEvent:
    return MonitorEvent(
        event_id=event_id,
        kind="new_external_connection",
        severity=EventSeverity.WARNING,
        timestamp=timestamp,
        title="New external connection",
        description="chrome.exe connected to 8.8.8.8:4444/tcp.",
        process_name="chrome.exe",
        remote_ip="8.8.8.8",
        port=4444,
    )


def path_event(*, timestamp: float = 1000.0, event_id: str = "path-event") -> PathEvent:
    return PathEvent(
        event_id=event_id,
        kind="latency_spike",
        severity=PathEventSeverity.WARNING,
        timestamp=timestamp,
        title="Latency spike",
        description="RTT increased toward 8.8.8.8.",
        target="8.8.8.8",
        hop_ttl=3,
        hop_ip="192.0.2.1",
    )


def test_monitor_event_normalizes_to_change_notification():
    notification = monitor_event_to_notification(event(), scope="network-monitor")
    assert notification.category == "new_external_connection"
    assert notification.severity.value == "WARNING"
    assert notification.scope == "network-monitor"
    assert notification.subject_id == "8.8.8.8"
    assert notification.baseline_generated_at == notification.current_generated_at
    assert MONITOR_SOURCE_DETAIL in notification.details
    assert "Process: chrome.exe" in notification.details
    assert "Remote: 8.8.8.8" in notification.details
    assert "Port: 4444" in notification.details
    assert is_monitor_notification(notification) is True
    assert is_path_notification(notification) is False


def test_path_event_normalizes_to_change_notification():
    notification = path_event_to_notification(path_event(), scope="network-path")
    assert notification.category == "latency_spike"
    assert notification.severity.value == "WARNING"
    assert notification.scope == "network-path"
    assert notification.subject_id == "192.0.2.1"
    assert PATH_SOURCE_DETAIL in notification.details
    assert "Target: 8.8.8.8" in notification.details
    assert "Hop TTL: 3" in notification.details
    assert "Hop IP: 192.0.2.1" in notification.details
    assert is_path_notification(notification) is True
    assert is_monitor_notification(notification) is False


def test_path_notification_without_hop_uses_target_subject():
    value = PathEvent(
        "id",
        "destination_unreachable",
        PathEventSeverity.CRITICAL,
        1000.0,
        "Destination unreachable",
        "No response.",
        "example.com",
    )
    notification = path_event_to_notification(value)
    assert notification.subject_id == "example.com"
    assert all(not detail.startswith("Hop TTL:") for detail in notification.details)


def test_occurrence_id_deduplicates_replay_but_not_later_occurrence():
    first = monitor_event_to_notification(event(timestamp=1000.0))
    replay = monitor_event_to_notification(event(timestamp=1000.0))
    later = monitor_event_to_notification(event(timestamp=1001.0))
    assert first.event_id == replay.event_id
    assert first.event_id != later.event_id

    path_first = path_event_to_notification(path_event(timestamp=1000.0))
    path_replay = path_event_to_notification(path_event(timestamp=1000.0))
    path_later = path_event_to_notification(path_event(timestamp=1001.0))
    assert path_first.event_id == path_replay.event_id
    assert path_first.event_id != path_later.event_id
    assert path_first.event_id != first.event_id


def test_publish_monitor_events_uses_canonical_inbox_and_deduplicates(tmp_path):
    inbox = tmp_path / "notifications.json"
    first = event(timestamp=1000.0)

    merged, added = publish_monitor_events(inbox, (first,))
    assert added == 1
    assert len(merged) == 1

    merged, added = publish_monitor_events(inbox, (first,))
    assert added == 0
    assert len(merged) == 1

    merged, added = publish_monitor_events(inbox, (event(timestamp=1001.0),))
    assert added == 1
    assert len(merged) == 2

    loaded = load_notification_inbox(inbox)
    monitor_items = load_monitor_notifications(inbox)
    assert len(loaded) == 2
    assert monitor_items == loaded
    assert all(is_monitor_notification(item) for item in loaded)


def test_publish_path_events_shares_inbox_without_cross_filtering(tmp_path):
    inbox = tmp_path / "notifications.json"
    publish_monitor_events(inbox, (event(),))
    merged, added = publish_path_events(inbox, (path_event(),))
    assert added == 1
    assert len(merged) == 2
    assert len(load_monitor_notifications(inbox)) == 1
    assert len(load_path_notifications(inbox)) == 1
    assert len(load_temporal_notifications(inbox)) == 2

    merged, added = publish_path_events(inbox, (path_event(),))
    assert added == 0
    assert len(merged) == 2


def test_mark_read_updates_only_presented_ids(tmp_path):
    inbox = tmp_path / "notifications.json"
    publish_monitor_events(inbox, (event(timestamp=1000.0), event(timestamp=1001.0)))
    publish_path_events(inbox, (path_event(timestamp=1002.0),))
    before = load_notification_inbox(inbox)
    presented_id = before[-1].event_id

    updated = mark_notification_ids_read(inbox, (presented_id,))
    by_id = {item.event_id: item for item in updated}
    assert by_id[presented_id].read is True
    assert sum(item.read for item in updated) == 1


def test_notification_inbox_lock_is_reentrant():
    lock = notification_inbox_lock()
    with lock:
        with lock:
            assert notification_inbox_lock() is lock


def test_empty_publish_is_a_noop(tmp_path):
    merged, added = publish_monitor_events(tmp_path / "missing.json", ())
    assert merged == ()
    assert added == 0
    merged, added = publish_path_events(tmp_path / "missing.json", ())
    assert merged == ()
    assert added == 0
