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
)

from pythonkni.infrastructure.paths import (
    NETWORK_INTELLIGENCE_AUTOMATIC_SNAPSHOTS_DIR,
    NETWORK_INTELLIGENCE_NOTIFICATIONS_FILE,
    NETWORK_INTELLIGENCE_RETENTION_FILE,
)

from .history_center_window import HistoryCenterDialog, Tool as HistoryCenterTool
from .notifications import load_notification_inbox
from .temporal_notifications import load_monitor_notifications

NOTIFICATION_REFRESH_MS = 2000


class TemporalHistoryCenterDialog(HistoryCenterDialog):
    """History Center extended with passive Network Traffic Monitor events."""

    def __init__(
        self,
        directory: Path,
        policy_path: Path,
        policy,
        parent=None,
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

        self.temporal_table = QTableWidget(0, 6)
        self.temporal_table.setHorizontalHeaderLabels(
            ["Detected", "Severity", "Event", "Subject", "Scope", "Message"]
        )
        self.temporal_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.temporal_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.temporal_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.temporal_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.temporal_table.horizontalHeader().setStretchLastSection(True)
        self.temporal_table.setMaximumHeight(210)
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
            notifications = load_monitor_notifications(self.notification_path)
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
        self.temporal_status.setText(
            f"{len(filtered)} evento(s) del Network Traffic Monitor · {unread} sin leer. "
            "El filtro temporal del History Center también se aplica a esta telemetría; "
            "el scope mostrado es el origen del monitor, no un snapshot sintético."
        )

        self.temporal_table.setRowCount(len(filtered))
        for row, item in enumerate(filtered):
            values = (
                item.detected_at.astimezone().strftime("%d/%m/%Y %H:%M:%S"),
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
