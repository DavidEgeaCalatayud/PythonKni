from __future__ import annotations

import hashlib
import threading
from collections.abc import Iterable
from dataclasses import replace
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
    from pythonkni.network_path.models import PathEvent

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
PATH_NOTIFICATION_CATEGORIES = frozenset(
    {
        "route_changed",
        "latency_spike",
        "packet_loss",
        "hop_added",
        "hop_removed",
        "destination_unreachable",
    }
)
MONITOR_SOURCE_DETAIL = "Source: Network Traffic Monitor"
PATH_SOURCE_DETAIL = "Source: Network Path Analyzer"
_INBOX_LOCK = threading.RLock()


def notification_inbox_lock() -> threading.RLock:
    """Return the process-local lock shared by temporal and snapshot inbox writers."""
    return _INBOX_LOCK


def _utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _occurrence_id(source: str, event_id: str, timestamp: float) -> str:
    """Return a replay-stable id without suppressing later temporal occurrences."""
    payload = f"{source}|{event_id}|{timestamp:.6f}"
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
        event_id=_occurrence_id("network-monitor-notification", event.event_id, event.timestamp),
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


def path_event_to_notification(
    event: PathEvent,
    *,
    scope: str = "network-path",
) -> ChangeNotification:
    detected_at = datetime.fromtimestamp(event.timestamp, tz=timezone.utc)
    generated_at = _utc_iso(detected_at)
    details = [PATH_SOURCE_DETAIL, f"Target: {event.target}"]
    if event.hop_ttl is not None:
        details.append(f"Hop TTL: {event.hop_ttl}")
    if event.hop_ip:
        details.append(f"Hop IP: {event.hop_ip}")

    subject_id = event.hop_ip or (
        f"{event.target}#ttl-{event.hop_ttl}" if event.hop_ttl is not None else event.target
    )
    return ChangeNotification(
        event_id=_occurrence_id("network-path-notification", event.event_id, event.timestamp),
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


def is_path_notification(notification: ChangeNotification) -> bool:
    return (
        notification.category in PATH_NOTIFICATION_CATEGORIES
        and PATH_SOURCE_DETAIL in notification.details
    )


def is_temporal_notification(notification: ChangeNotification) -> bool:
    return is_monitor_notification(notification) or is_path_notification(notification)


def load_monitor_notifications(path: str | Path) -> tuple[ChangeNotification, ...]:
    return tuple(
        notification
        for notification in load_notification_inbox(path)
        if is_monitor_notification(notification)
    )


def load_path_notifications(path: str | Path) -> tuple[ChangeNotification, ...]:
    return tuple(
        notification
        for notification in load_notification_inbox(path)
        if is_path_notification(notification)
    )


def load_temporal_notifications(path: str | Path) -> tuple[ChangeNotification, ...]:
    return tuple(
        notification
        for notification in load_notification_inbox(path)
        if is_temporal_notification(notification)
    )


def _publish_notifications(
    path: str | Path,
    incoming: tuple[ChangeNotification, ...],
) -> tuple[tuple[ChangeNotification, ...], int]:
    if not incoming:
        return (), 0
    with _INBOX_LOCK:
        existing = load_notification_inbox(path)
        merged, added = merge_notifications(existing, incoming)
        if added:
            save_notification_inbox(path, merged)
    return merged, added


def publish_monitor_events(
    path: str | Path,
    events: Iterable[MonitorEvent],
    *,
    scope: str = "network-monitor",
) -> tuple[tuple[ChangeNotification, ...], int]:
    """Merge passive monitor events into the canonical Change Notification inbox."""
    incoming = tuple(monitor_event_to_notification(event, scope=scope) for event in events)
    return _publish_notifications(path, incoming)


def publish_path_events(
    path: str | Path,
    events: Iterable[PathEvent],
    *,
    scope: str = "network-path",
) -> tuple[tuple[ChangeNotification, ...], int]:
    """Merge Network Path Analyzer events into the canonical notification inbox."""
    incoming = tuple(path_event_to_notification(event, scope=scope) for event in events)
    return _publish_notifications(path, incoming)


def mark_notification_ids_read(
    path: str | Path,
    event_ids: Iterable[str],
) -> tuple[ChangeNotification, ...]:
    """Mark only notifications actually presented to the user as read."""
    ids = frozenset(event_ids)
    with _INBOX_LOCK:
        current = load_notification_inbox(path)
        updated = tuple(
            replace(item, read=True) if item.event_id in ids and not item.read else item
            for item in current
        )
        if updated != current:
            save_notification_inbox(path, updated)
    return updated
