from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from pythonkni.infrastructure.paths import NETWORK_INTELLIGENCE_NOTIFICATIONS_FILE, ensure_app_dirs
from tools.ui_feedback import show_error, show_warning

from .automatic_snapshot import AutomaticSnapshotResult
from .notifications import (
    ChangeNotification,
    NotificationSeverity,
    build_change_notifications_from_paths,
    format_notification_inbox,
    load_notification_inbox,
    mark_all_notifications_read,
    merge_notifications,
    notification_counts,
    save_notification_inbox,
)
from .scheduler_window import Tool as SchedulerTool


class ChangeNotificationDialog(QDialog):
    def __init__(self, notifications: tuple[ChangeNotification, ...], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Network Intelligence · Cambios detectados")
        self.resize(820, 560)

        layout = QVBoxLayout(self)
        summary = notification_counts(notifications, unread_only=True)
        unread = sum(summary.values())
        layout.addWidget(
            QLabel(
                f"Sin leer: {unread} · críticos: {summary[NotificationSeverity.CRITICAL]} · "
                f"avisos: {summary[NotificationSeverity.WARNING]} · "
                f"informativos: {summary[NotificationSeverity.INFO]}"
            )
        )

        output = QPlainTextEdit()
        output.setReadOnly(True)
        output.setPlainText(format_notification_inbox(notifications))
        layout.addWidget(output, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)


class Tool(SchedulerTool):
    """Scheduled Network Intelligence with a local, deduplicated change-notification inbox."""

    def setup_ui(self) -> None:
        super().setup_ui()
        ensure_app_dirs()
        self.notifications = self._load_notifications()

        notification_row = QHBoxLayout()
        self.notification_status = QLabel()
        self.notification_status.setWordWrap(True)
        notification_row.addWidget(self.notification_status, 1)
        self.notification_button = QPushButton()
        self.notification_button.clicked.connect(self._open_notifications)
        notification_row.addWidget(self.notification_button)

        layout = self.centralWidget().layout()
        layout.insertLayout(min(8, layout.count()), notification_row)
        self._sync_notification_controls()

    def _load_notifications(self) -> tuple[ChangeNotification, ...]:
        try:
            return load_notification_inbox(NETWORK_INTELLIGENCE_NOTIFICATIONS_FILE)
        except Exception as error:
            show_warning(
                self,
                self.name,
                "La bandeja local de cambios no es válida y no se modificará automáticamente.",
                details=str(error),
            )
            return ()

    def _sync_notification_controls(self) -> None:
        if not hasattr(self, "notification_status"):
            return
        unread_counts = notification_counts(self.notifications, unread_only=True)
        unread = sum(unread_counts.values())
        total = len(self.notifications)
        self.notification_status.setText(
            f"Cambios de red: {unread} sin leer · "
            f"{unread_counts[NotificationSeverity.CRITICAL]} críticos · "
            f"{unread_counts[NotificationSeverity.WARNING]} avisos · {total} guardados"
        )
        self.notification_button.setText(f"Ver cambios ({unread})" if unread else "Ver cambios")
        self.notification_button.setEnabled(bool(self.notifications))

    def _open_notifications(self) -> None:
        if not self.notifications:
            return
        dialog = ChangeNotificationDialog(self.notifications, self)
        dialog.exec_()

        candidate = mark_all_notifications_read(self.notifications)
        try:
            save_notification_inbox(NETWORK_INTELLIGENCE_NOTIFICATIONS_FILE, candidate)
        except Exception as error:
            show_error(
                self,
                self.name,
                "No se pudieron marcar como leídos los cambios de Network Intelligence.",
                error=error,
            )
            return
        self.notifications = candidate
        self._sync_notification_controls()

    def _automatic_snapshot_published(
        self,
        *,
        previous_snapshot: Path | None,
        snapshot: AutomaticSnapshotResult,
        generated_at: datetime,
    ) -> str:
        del generated_at
        if previous_snapshot is None:
            return " · baseline de cambios inicializada"
        if not previous_snapshot.is_file():
            show_warning(
                self,
                self.name,
                "El snapshot automático anterior ya no está disponible; se omite la comparación "
                "de cambios de esta ejecución.",
                details=str(previous_snapshot),
            )
            return " · sin comparación de cambios (baseline no disponible)"

        try:
            batch = build_change_notifications_from_paths(previous_snapshot, snapshot.path)
            existing = load_notification_inbox(NETWORK_INTELLIGENCE_NOTIFICATIONS_FILE)
            merged, added = merge_notifications(existing, batch.notifications)
            if added:
                save_notification_inbox(NETWORK_INTELLIGENCE_NOTIFICATIONS_FILE, merged)
        except Exception as error:
            show_warning(
                self,
                self.name,
                "El snapshot automático se publicó correctamente, pero no se pudieron evaluar o "
                "persistir sus cambios.",
                details=str(error),
            )
            return " · motor de cambios no disponible"

        self.notifications = merged
        self._sync_notification_controls()
        if not batch.notifications:
            return " · sin cambios relevantes"
        if not added:
            return " · cambios ya procesados (sin duplicados)"
        return (
            f" · {added} cambio(s) relevante(s): "
            f"{batch.critical_count} crítico(s), {batch.warning_count} aviso(s)"
        )
