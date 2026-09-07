from __future__ import annotations

from datetime import datetime, timezone

from pythonkni.network_intelligence.retention import RetentionPolicy
from pythonkni.network_intelligence.temporal_history_window import TemporalHistoryCenterDialog
from pythonkni.network_intelligence.temporal_notifications import (
    publish_monitor_events,
    publish_path_events,
)
from pythonkni.network_monitor.models import EventSeverity, MonitorEvent
from pythonkni.network_path.models import PathEvent, PathEventSeverity


def monitor_event(timestamp: float) -> MonitorEvent:
    return MonitorEvent(
        event_id="monitor-event",
        kind="unusual_destination",
        severity=EventSeverity.WARNING,
        timestamp=timestamp,
        title="Unusual external destination",
        description="unknown.exe contacted 185.1.2.3:4444/tcp.",
        process_name="unknown.exe",
        remote_ip="185.1.2.3",
        port=4444,
    )


def path_event(timestamp: float) -> PathEvent:
    return PathEvent(
        "path-event",
        "latency_spike",
        PathEventSeverity.WARNING,
        timestamp,
        "Latency spike",
        "RTT increased at hop 3.",
        "8.8.8.8",
        3,
        "192.0.2.1",
    )


def test_history_center_renders_monitor_notifications(qtbot, tmp_path):
    snapshots = tmp_path / "scheduled"
    snapshots.mkdir()
    inbox = tmp_path / "notifications.json"
    publish_monitor_events(inbox, (monitor_event(datetime.now(timezone.utc).timestamp()),))

    dialog = TemporalHistoryCenterDialog(
        snapshots,
        tmp_path / "retention.json",
        RetentionPolicy(),
        notification_path=inbox,
    )
    qtbot.addWidget(dialog)

    assert dialog.temporal_table.rowCount() == 1
    assert dialog.temporal_table.item(0, 1).text() == "Network Traffic Monitor"
    assert dialog.temporal_table.item(0, 2).text() == "WARNING"
    assert dialog.temporal_table.item(0, 3).text() == "unusual_destination"
    assert dialog.temporal_table.item(0, 4).text() == "185.1.2.3"
    assert "1 evento" in dialog.temporal_status.text()
    assert "1 sin leer" in dialog.temporal_status.text()
    assert "Traffic Monitor 1" in dialog.temporal_status.text()


def test_history_center_renders_path_analyzer_notifications(qtbot, tmp_path):
    snapshots = tmp_path / "scheduled"
    snapshots.mkdir()
    inbox = tmp_path / "notifications.json"
    publish_path_events(inbox, (path_event(datetime.now(timezone.utc).timestamp()),))

    dialog = TemporalHistoryCenterDialog(
        snapshots,
        tmp_path / "retention.json",
        RetentionPolicy(),
        notification_path=inbox,
    )
    qtbot.addWidget(dialog)

    assert dialog.temporal_table.rowCount() == 1
    assert dialog.temporal_table.item(0, 1).text() == "Network Path Analyzer"
    assert dialog.temporal_table.item(0, 3).text() == "latency_spike"
    assert dialog.temporal_table.item(0, 4).text() == "192.0.2.1"
    assert "Path Analyzer 1" in dialog.temporal_status.text()


def test_history_center_time_filter_applies_to_all_temporal_events(qtbot, tmp_path):
    snapshots = tmp_path / "scheduled"
    snapshots.mkdir()
    inbox = tmp_path / "notifications.json"
    old_timestamp = datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp()
    publish_monitor_events(inbox, (monitor_event(old_timestamp),))
    publish_path_events(inbox, (path_event(old_timestamp),))

    dialog = TemporalHistoryCenterDialog(
        snapshots,
        tmp_path / "retention.json",
        RetentionPolicy(),
        notification_path=inbox,
    )
    qtbot.addWidget(dialog)
    assert dialog.temporal_table.rowCount() == 2

    dialog.time_filter.setCurrentIndex(1)  # Últimas 24 h
    assert dialog.temporal_table.rowCount() == 0
    assert "0 evento" in dialog.temporal_status.text()
