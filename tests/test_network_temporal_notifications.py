from __future__ import annotations

from pythonkni.network_intelligence.notifications import load_notification_inbox
from pythonkni.network_intelligence.temporal_notifications import (
    MONITOR_SOURCE_DETAIL,
    is_monitor_notification,
    load_monitor_notifications,
    monitor_event_to_notification,
    publish_monitor_events,
)
from pythonkni.network_monitor.models import EventSeverity, MonitorEvent


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


def test_occurrence_id_deduplicates_replay_but_not_later_occurrence():
    first = monitor_event_to_notification(event(timestamp=1000.0))
    replay = monitor_event_to_notification(event(timestamp=1000.0))
    later = monitor_event_to_notification(event(timestamp=1001.0))
    assert first.event_id == replay.event_id
    assert first.event_id != later.event_id


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


def test_empty_publish_is_a_noop(tmp_path):
    merged, added = publish_monitor_events(tmp_path / "missing.json", ())
    assert merged == ()
    assert added == 0
