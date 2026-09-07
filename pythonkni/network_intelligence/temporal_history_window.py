from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pythonkni.infrastructure.paths import (
    NETWORK_INTELLIGENCE_AUTOMATIC_SNAPSHOTS_DIR,
    NETWORK_INTELLIGENCE_NOTIFICATIONS_FILE,
    NETWORK_INTELLIGENCE_RETENTION_FILE,
)
from tools.ui_feedback import show_error

from .automatic_snapshot import AutomaticSnapshotResult
from .history_center_window import HistoryCenterDialog
from .history_center_window import Tool as HistoryCenterTool
from .notification_window import ChangeNotificationDialog
from .notifications import ChangeNotification, load_notification_inbox
from .retention import RetentionPolicy
from .temporal_notifications import (
    MONITOR_SOURCE_DETAIL,
    PATH_SOURCE_DETAIL,
    load_temporal_notifications,
    mark_notification_ids_read,
    notification_inbox_lock,
)

NOTIFICATION_REFRESH_MS = 2000


def _source_label(notification: ChangeNotification) -> str:
    for detail in notification.details:
        if detail.startswith("Source: "):
            return detail.removeprefix("Source: ")
    return "Temporal telemetry"


class TemporalHistoryCenterDialog(HistoryCenterDialog):
    """History Center extended with first-party temporal network observations."""

    def __init__(
        self,
        directory: Path,
        policy_path: Path,
        policy: RetentionPolicy,
        parent: QWidget | None = None,
        *,
        notification_path: Path = NETWORK_INTELLIGENCE_NOTIFICATIONS_FILE,
    ) -> None:
        self.notification_path = Path(notification_path)
        super().__init__(directory, policy_path, policy, parent)

        temporal_group = QGroupBox("Telemetría temporal")
        temporal_layout = QVBoxLayout(temporal_group)
        self.temporal_status = QLabel()
        self.temporal_status.setWordWrap(True)
        temporal_layout.addWidget(self.temporal_status)

        self.temporal_table = QTableWidget(0, 7)
        self.temporal_table.setHorizontalHeaderLabels(
            ["Detected", "Source", "Severity", "Event", "Subject", "Scope", "Message"]
        )
        self.temporal_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.temporal_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.temporal_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.temporal_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.temporal_table.horizontalHeader().setStretchLastSection(True)
        self.temporal_table.setMaximumHeight(230)
        temporal_layout.addWidget(self.temporal_table)

        layout = self.layout()
        assert layout is not None
        layout.insertWidget(max(0, layout.count() - 1), temporal_group)
        self._refresh_temporal_events()

    def _refresh_view(self, _index: int = -1) -> None:
        super()._refresh_view(_index)
        if hasattr(self, "temporal_table"):
            self._refresh_temporal_events()

    def _refresh_temporal_events(self) -> None:
        try:
            notifications = load_temporal_notifications(self.notification_path)
        except Exception as error:
            self.temporal_table.setRowCount(0)
            self.temporal_status.setText(f"Telemetría temporal no disponible: {error}")
            return

        days = self.time_filter.currentData()
        since = None
        if days is not None:
            since = datetime.now(timezone.utc) - timedelta(days=int(days))
        filtered = tuple(
            item for item in notifications if since is None or item.detected_at >= since
        )
        unread = sum(not item.read for item in filtered)
        monitor_count = sum(MONITOR_SOURCE_DETAIL in item.details for item in filtered)
        path_count = sum(PATH_SOURCE_DETAIL in item.details for item in filtered)
        self.temporal_status.setText(
            f"{len(filtered)} evento(s) temporal(es) · {unread} sin leer · "
            f"Traffic Monitor {monitor_count} · Path Analyzer {path_count}. "
            "El filtro temporal del History Center también se aplica aquí; estos scopes son "
            "orígenes de observación y no snapshots sintéticos."
        )

        self.temporal_table.setRowCount(len(filtered))
        for row, item in enumerate(filtered):
            values = (
                item.detected_at.astimezone().strftime("%d/%m/%Y %H:%M:%S"),
                _source_label(item),
                item.severity.value,
                item.category,
                item.subject_id or "—",
                item.scope,
                item.message,
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                cell.setData(Qt.UserRole, item.event_id)
                self.temporal_table.setItem(row, column, cell)


class Tool(HistoryCenterTool):
    """Network Intelligence with live temporal-notification and History Center integration."""

    def setup_ui(self) -> None:
        super().setup_ui()
        self._temporal_notification_timer = QTimer(self)
        self._temporal_notification_timer.timeout.connect(self._refresh_temporal_notifications)
        self._temporal_notification_timer.start(NOTIFICATION_REFRESH_MS)

    def _refresh_temporal_notifications(self) -> None:
        try:
            latest = load_notification_inbox(NETWORK_INTELLIGENCE_NOTIFICATIONS_FILE)
        except Exception:
            return
        if latest == self.notifications:
            return
        self.notifications = latest
        self._sync_notification_controls()

    def _open_notifications(self) -> None:
        self._refresh_temporal_notifications()
        if not self.notifications:
            return

        presented = self.notifications
        dialog = ChangeNotificationDialog(presented, self)
        dialog.exec_()
        try:
            self.notifications = mark_notification_ids_read(
                NETWORK_INTELLIGENCE_NOTIFICATIONS_FILE,
                (item.event_id for item in presented),
            )
        except Exception as error:
            show_error(
                self,
                self.name,
                "No se pudieron marcar como leídos los cambios de Network Intelligence.",
                error=error,
            )
            return
        self._sync_notification_controls()

    def _automatic_snapshot_published(
        self,
        *,
        previous_snapshot: Path | None,
        snapshot: AutomaticSnapshotResult,
        generated_at: datetime,
    ) -> str:
        with notification_inbox_lock():
            return super()._automatic_snapshot_published(
                previous_snapshot=previous_snapshot,
                snapshot=snapshot,
                generated_at=generated_at,
            )

    def _open_history_center(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        dialog = TemporalHistoryCenterDialog(
            NETWORK_INTELLIGENCE_AUTOMATIC_SNAPSHOTS_DIR,
            NETWORK_INTELLIGENCE_RETENTION_FILE,
            self.retention_policy,
            self,
        )
        dialog.exec_()
        self.retention_policy = dialog.policy
        self._sync_history_center_controls()
