from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel

from pythonkni.infrastructure.paths import (
    NETWORK_INTELLIGENCE_AUTOMATIC_SNAPSHOTS_DIR,
    NETWORK_INTELLIGENCE_SCHEDULE_FILE,
    ensure_app_dirs,
)
from tools.ui_feedback import show_error, show_warning

from .automatic_snapshot import create_automatic_snapshot
from .history_window import Tool as HistoryTool
from .scheduler import (
    DEFAULT_INTERVAL_MINUTES,
    ScheduleConfig,
    change_schedule_interval,
    create_schedule,
    disable_schedule,
    disabled_schedule,
    load_schedule,
    mark_schedule_started,
    mark_schedule_success,
    save_schedule,
    schedule_due,
)

SCHEDULE_POLL_MS = 30_000
INTERVAL_OPTIONS = (
    (15, "15 min"),
    (30, "30 min"),
    (60, "1 h"),
    (180, "3 h"),
    (360, "6 h"),
    (720, "12 h"),
    (1440, "24 h"),
)


def _local_time(value: datetime | None) -> str:
    if value is None:
        return "—"
    return value.astimezone().strftime("%d/%m/%Y %H:%M:%S")


class Tool(HistoryTool):
    """Network Intelligence with opt-in in-app scheduling and automatic snapshots."""

    def setup_ui(self) -> None:
        super().setup_ui()
        ensure_app_dirs()
        self._scheduled_scan_active = False
        self._scheduler_closing = False
        self.schedule_config = self._load_schedule()

        schedule_row = QHBoxLayout()
        self.schedule_checkbox = QCheckBox("Monitorización programada")
        self.schedule_checkbox.toggled.connect(self._schedule_toggled)
        schedule_row.addWidget(self.schedule_checkbox)
        schedule_row.addWidget(QLabel("Cada:"))
        self.schedule_interval = QComboBox()
        for minutes, label in INTERVAL_OPTIONS:
            self.schedule_interval.addItem(label, minutes)
        self.schedule_interval.currentIndexChanged.connect(self._schedule_interval_changed)
        schedule_row.addWidget(self.schedule_interval)
        self.schedule_status = QLabel()
        self.schedule_status.setWordWrap(True)
        schedule_row.addWidget(self.schedule_status, 1)

        layout = self.centralWidget().layout()
        layout.insertLayout(min(7, layout.count()), schedule_row)

        if self.schedule_config.enabled:
            self.scope_input.setText(self.schedule_config.scope)
        self._sync_schedule_controls()

        self.schedule_timer = QTimer(self)
        self.schedule_timer.setInterval(SCHEDULE_POLL_MS)
        self.schedule_timer.timeout.connect(self._check_schedule)
        self.schedule_timer.start()
        QTimer.singleShot(1000, self._check_schedule)

    def _load_schedule(self) -> ScheduleConfig:
        try:
            return load_schedule(NETWORK_INTELLIGENCE_SCHEDULE_FILE)
        except Exception as error:
            show_warning(
                self,
                self.name,
                "La configuración de monitorización programada no es válida y se ignorará.",
                details=str(error),
            )
            return disabled_schedule()

    def _selected_interval(self) -> int:
        value = self.schedule_interval.currentData()
        return int(value) if value is not None else DEFAULT_INTERVAL_MINUTES

    def _set_interval_control(self, minutes: int) -> None:
        index = self.schedule_interval.findData(minutes)
        if index < 0:
            index = self.schedule_interval.findData(DEFAULT_INTERVAL_MINUTES)
        self.schedule_interval.setCurrentIndex(max(0, index))

    def _schedule_summary(self) -> str:
        config = self.schedule_config
        if not config.enabled:
            return "Desactivada · no se ejecutan scans automáticos con esta ventana cerrada."
        summary = (
            f"Scope {config.scope} · próxima {_local_time(config.next_run_at)} · "
            f"último éxito {_local_time(config.last_success_at)}"
        )
        if config.last_snapshot:
            summary += f" · snapshot {Path(config.last_snapshot).name}"
        return summary

    def _sync_schedule_controls(self) -> None:
        if not hasattr(self, "schedule_checkbox"):
            return
        self.schedule_checkbox.blockSignals(True)
        self.schedule_interval.blockSignals(True)
        self.schedule_checkbox.setChecked(self.schedule_config.enabled)
        self._set_interval_control(self.schedule_config.interval_minutes)
        self.schedule_checkbox.blockSignals(False)
        self.schedule_interval.blockSignals(False)
        self.schedule_status.setText(self._schedule_summary())

        running = self.worker is not None and self.worker.isRunning()
        self.schedule_checkbox.setEnabled(not running)
        self.schedule_interval.setEnabled(not running)
        self.scope_input.setEnabled(not running and not self.schedule_config.enabled)

    def _save_schedule_candidate(self, candidate: ScheduleConfig) -> bool:
        try:
            save_schedule(NETWORK_INTELLIGENCE_SCHEDULE_FILE, candidate)
        except Exception as error:
            show_error(
                self,
                self.name,
                "No se pudo guardar la configuración de monitorización programada.",
                error=error,
            )
            return False
        self.schedule_config = candidate
        self._sync_schedule_controls()
        return True

    def _schedule_toggled(self, enabled: bool) -> None:
        if enabled:
            try:
                candidate = create_schedule(
                    self._active_scope(),
                    self._selected_interval(),
                    now=datetime.now(timezone.utc),
                )
            except ValueError as error:
                show_warning(self, self.name, str(error))
                self._sync_schedule_controls()
                return
            if self._save_schedule_candidate(candidate):
                self.scope_input.setText(candidate.scope)
                self.status_label.setText(
                    "Monitorización programada activada. PythonKni ejecutará el scope autorizado "
                    "mientras esta ventana de Network Intelligence permanezca abierta y guardará "
                    "un snapshot JSON tras cada ejecución programada completada."
                )
            return

        candidate = disable_schedule(self.schedule_config)
        if self._save_schedule_candidate(candidate):
            self.status_label.setText("Monitorización programada desactivada.")

    def _schedule_interval_changed(self, _index: int) -> None:
        if not self.schedule_config.enabled:
            return
        try:
            candidate = change_schedule_interval(
                self.schedule_config,
                self._selected_interval(),
                now=datetime.now(timezone.utc),
            )
        except ValueError as error:
            show_warning(self, self.name, str(error))
            self._sync_schedule_controls()
            return
        if self._save_schedule_candidate(candidate):
            self.status_label.setText(
                f"Intervalo programado actualizado. Próxima ejecución: "
                f"{_local_time(candidate.next_run_at)}."
            )

    def _check_schedule(self) -> None:
        if self._scheduler_closing or not self.schedule_config.enabled:
            return
        if self.worker is not None and self.worker.isRunning():
            return

        now = datetime.now(timezone.utc)
        if not schedule_due(self.schedule_config, now=now):
            return

        candidate = mark_schedule_started(self.schedule_config, now=now)
        if not self._save_schedule_candidate(candidate):
            self.schedule_config = disable_schedule(self.schedule_config)
            self._sync_schedule_controls()
            self.status_label.setText(
                "La monitorización programada se ha desactivado para esta sesión porque no se "
                "pudo persistir el siguiente horario de ejecución."
            )
            return

        self.scope_input.setText(candidate.scope)
        self._scheduled_scan_active = True
        self.status_label.setText(
            f"Ejecución programada iniciada para {candidate.scope}. Próxima ventana: "
            f"{_local_time(candidate.next_run_at)}."
        )
        super().start_scan()
        if self.worker is None:
            self._scheduled_scan_active = False

    def start_scan(self) -> None:
        self._scheduled_scan_active = False
        super().start_scan()

    def _scan_finished(self, result) -> None:
        scheduled = self._scheduled_scan_active
        super()._scan_finished(result)
        if not scheduled:
            return

        generated_at = datetime.now(timezone.utc)
        scope = self.schedule_config.scope or self._active_scope()
        try:
            assets = self.inventory.list_assets(scope=scope)
            relationships = self.relationship_store.list(scope=scope)
            events = self.inventory.list_events(scope=scope, limit=1000)
            snapshot = create_automatic_snapshot(
                NETWORK_INTELLIGENCE_AUTOMATIC_SNAPSHOTS_DIR,
                scope,
                assets,
                relationships,
                events,
                generated_at=generated_at,
            )
        except Exception as error:
            show_error(
                self,
                self.name,
                "El scan programado terminó, pero no se pudo publicar su snapshot automático.",
                error=error,
            )
            self.schedule_status.setText(self._schedule_summary())
            return

        candidate = mark_schedule_success(
            self.schedule_config,
            now=generated_at,
            snapshot=snapshot.path,
        )
        if not self._save_schedule_candidate(candidate):
            self.schedule_config = candidate
            self._sync_schedule_controls()

        retention = (
            f" · {snapshot.pruned_count} snapshot(s) antiguo(s) eliminado(s)"
            if snapshot.pruned_count
            else ""
        )
        self.status_label.setText(
            f"Ejecución programada completada · snapshot automático {snapshot.path}{retention} · "
            f"próxima {_local_time(self.schedule_config.next_run_at)}."
        )

    def _scan_failed(self, error) -> None:
        scheduled = self._scheduled_scan_active
        super()._scan_failed(error)
        if scheduled:
            self.status_label.setText(
                "La ejecución programada falló; no se creó snapshot automático. "
                f"Próximo intento: {_local_time(self.schedule_config.next_run_at)}."
            )

    def _scan_cancelled(self) -> None:
        scheduled = self._scheduled_scan_active
        super()._scan_cancelled()
        if scheduled:
            self.status_label.setText(
                "La ejecución programada fue cancelada; no se creó snapshot automático y no se "
                "marcaron desapariciones. "
                f"Próximo intento: {_local_time(self.schedule_config.next_run_at)}."
            )

    def _worker_finished(self) -> None:
        super()._worker_finished()
        self._scheduled_scan_active = False
        self._sync_schedule_controls()

    def _set_running(self, running: bool) -> None:
        super()._set_running(running)
        if hasattr(self, "schedule_checkbox"):
            self.schedule_checkbox.setEnabled(not running)
            self.schedule_interval.setEnabled(not running)
            self.scope_input.setEnabled(not running and not self.schedule_config.enabled)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API name
        self._scheduler_closing = True
        if hasattr(self, "schedule_timer"):
            self.schedule_timer.stop()
        super().closeEvent(event)
