from __future__ import annotations

import hashlib
import threading
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from .notifications import (
    ChangeNotification,
    NotificationSeverity,
    load_notification_inbox,
    merge_notifications,
    save_notification_inbox,
)

if TYPE_CHECKING:
    from pythonkni.network_monitor.models import MonitorEvent

MONITOR_NOTIFICATION_CATEGORIES = frozenset(
    {
        "new_external_connection",
        "new_remote_host",
        "new_listening_port",
        "process_network_activity",
        "traffic_spike",
        "known_asset_connection",
        "unusual_destination",
    }
)
MONITOR_SOURCE_DETAIL = "Source: Network Traffic Monitor"
_INBOX_LOCK = threading.RLock()


def _utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _occurrence_id(event: MonitorEvent) -> str:
    """Return a replay-stable id without suppressing later temporal occurrences."""
    payload = f"network-monitor-notification|{event.event_id}|{event.timestamp:.6f}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def monitor_event_to_notification(
    event: MonitorEvent,
    *,
    scope: str = "network-monitor",
) -> ChangeNotification:
    detected_at = datetime.fromtimestamp(event.timestamp, tz=timezone.utc)
    generated_at = _utc_iso(detected_at)
    details = [MONITOR_SOURCE_DETAIL]
    if event.process_name:
        details.append(f"Process: {event.process_name}")
    if event.remote_ip:
        details.append(f"Remote: {event.remote_ip}")
    if event.port is not None:
        details.append(f"Port: {event.port}")
    if event.asset_id:
        details.append(f"Network Intelligence asset: {event.asset_id}")

    subject_id = event.asset_id or event.remote_ip or event.process_name or event.kind
    return ChangeNotification(
        event_id=_occurrence_id(event),
        scope=scope,
        detected_at=detected_at,
        baseline_generated_at=generated_at,
        current_generated_at=generated_at,
        category=event.kind,
        severity=NotificationSeverity(event.severity.value),
        title=event.title,
        message=event.description,
        subject_id=subject_id,
        details=tuple(details),
    )


def is_monitor_notification(notification: ChangeNotification) -> bool:
    return (
        notification.category in MONITOR_NOTIFICATION_CATEGORIES
        and MONITOR_SOURCE_DETAIL in notification.details
    )


def load_monitor_notifications(path: str | Path) -> tuple[ChangeNotification, ...]:
    return tuple(
        notification
        for notification in load_notification_inbox(path)
        if is_monitor_notification(notification)
    )


def publish_monitor_events(
    path: str | Path,
    events: Iterable[MonitorEvent],
    *,
    scope: str = "network-monitor",
) -> tuple[tuple[ChangeNotification, ...], int]:
    """Merge monitor events into the canonical Change Notification inbox.

    Exact replay of the same monitor occurrence is deduplicated. A later occurrence of
    the same logical monitor event receives another occurrence id because its timestamp
    differs, preserving temporal history across monitor sessions.
    """
    incoming = tuple(monitor_event_to_notification(event, scope=scope) for event in events)
    if not incoming:
        return (), 0

    with _INBOX_LOCK:
        existing = load_notification_inbox(path)
        merged, added = merge_notifications(existing, incoming)
        if added:
            save_notification_inbox(path, merged)
    return merged, added
