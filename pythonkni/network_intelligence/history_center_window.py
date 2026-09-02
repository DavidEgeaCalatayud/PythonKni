from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPainter, QPen
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pythonkni.infrastructure.paths import (
    NETWORK_INTELLIGENCE_AUTOMATIC_SNAPSHOTS_DIR,
    NETWORK_INTELLIGENCE_RETENTION_FILE,
    ensure_app_dirs,
)
from tools.ui_feedback import show_error, show_warning

from .comparison import compare_network_reports, load_network_report
from .comparison_window import SnapshotComparisonDialog
from .notification_window import Tool as NotificationTool
from .retention import (
    DEFAULT_KEEP_PER_SCOPE,
    MAX_KEEP_PER_SCOPE,
    MAX_RETENTION_DAYS,
    MIN_KEEP_PER_SCOPE,
    RetentionPolicy,
    SnapshotCatalog,
    SnapshotCatalogEntry,
    apply_retention_policy,
    filter_snapshot_entries,
    load_retention_policy,
    load_snapshot_catalog,
    previous_snapshot_for,
    retention_candidates,
    save_retention_policy,
    summarize_trend,
)

TIME_FILTERS = (
    (None, "Todo el histórico"),
    (1, "Últimas 24 h"),
    (7, "Últimos 7 días"),
    (30, "Últimos 30 días"),
    (90, "Últimos 90 días"),
    (365, "Último año"),
)


def _format_bytes(value: int) -> str:
    if value < 1024:
        return f"{value} B"
    if value < 1024 * 1024:
        return f"{value / 1024:.1f} KiB"
    return f"{value / (1024 * 1024):.1f} MiB"


def _entry_details(entry: SnapshotCatalogEntry) -> str:
    lines = [
        f"Snapshot: {entry.generated_at_text}",
        f"Scope: {entry.scope}",
        f"Archivo: {entry.path}",
        f"Schema: v{entry.schema_version}",
        f"Tamaño: {_format_bytes(entry.size_bytes)}",
        "",
        f"Security Score: {entry.score}/100",
        f"Dispositivos: {entry.total_devices}",
        (
            f"Riesgo: High {entry.high_risk} · Medium {entry.medium_risk} · "
            f"Low {entry.low_risk} · Unknown {entry.unknown_devices}"
        ),
        "",
        "Findings",
    ]
    if entry.findings:
        lines.extend(f"• {finding}" for finding in entry.findings)
    else:
        lines.append("• Ninguno")
    return "\n".join(lines)


class SnapshotTrendChart(QWidget):
    """Small dependency-free chart for score and high-risk evolution."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.entries: tuple[SnapshotCatalogEntry, ...] = ()
        self.empty_message = "Sin snapshots para el filtro actual"
        self.setMinimumHeight(190)

    def set_entries(self, entries: tuple[SnapshotCatalogEntry, ...]) -> None:
        self.entries = entries
        self.update()

    def set_empty_message(self, message: str) -> None:
        self.empty_message = message
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API name
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        palette = self.palette()
        painter.fillRect(self.rect(), palette.base())

        if not self.entries:
            painter.setPen(palette.text().color())
            painter.drawText(self.rect(), Qt.AlignCenter, self.empty_message)
            return

        plot = self.rect().adjusted(48, 24, -24, -38)
        painter.setPen(QPen(palette.mid().color(), 1))
        painter.drawRect(plot)
        painter.drawText(4, plot.top() + 5, "100")
        painter.drawText(14, plot.bottom(), "0")

        count = len(self.entries)
        x_step = plot.width() / max(1, count - 1)

        def x_at(index: int) -> int:
            return int(plot.left() + index * x_step)

        def score_y(score: int) -> int:
            bounded = max(0, min(100, score))
            return int(plot.bottom() - (bounded / 100) * plot.height())

        score_pen = QPen(palette.highlight().color(), 2)
        painter.setPen(score_pen)
        score_points = [(x_at(index), score_y(entry.score)) for index, entry in enumerate(self.entries)]
        for index in range(1, len(score_points)):
            painter.drawLine(
                score_points[index - 1][0],
                score_points[index - 1][1],
                score_points[index][0],
                score_points[index][1],
            )
        for x, y in score_points:
            painter.drawEllipse(x - 2, y - 2, 4, 4)

        max_high = max(entry.high_risk for entry in self.entries)
        if max_high > 0:
            high_pen = QPen(palette.link().color(), 2, Qt.DashLine)
            painter.setPen(high_pen)

            def high_y(value: int) -> int:
                return int(plot.bottom() - (value / max_high) * plot.height())

            high_points = [
                (x_at(index), high_y(entry.high_risk))
                for index, entry in enumerate(self.entries)
            ]
            for index in range(1, len(high_points)):
                painter.drawLine(
                    high_points[index - 1][0],
                    high_points[index - 1][1],
                    high_points[index][0],
                    high_points[index][1],
                )

        painter.setPen(palette.text().color())
        first = self.entries[0].generated_at.astimezone().strftime("%d/%m %H:%M")
        latest = self.entries[-1].generated_at.astimezone().strftime("%d/%m %H:%M")
        painter.drawText(plot.left(), self.height() - 12, first)
        painter.drawText(plot.right() - 95, self.height() - 12, latest)
        painter.drawText(plot.left(), 16, "Security Score")
        if max_high > 0:
            painter.drawText(plot.left() + 125, 16, f"High risk (máx. {max_high})")


class HistoryCenterDialog(QDialog):
    def __init__(self, directory: Path, policy_path: Path, policy: RetentionPolicy, parent=None):
        super().__init__(parent)
        self.directory = Path(directory)
        self.policy_path = Path(policy_path)
        self.policy = policy
        self.catalog = SnapshotCatalog(entries=())
        self.filtered_entries: tuple[SnapshotCatalogEntry, ...] = ()

        self.setWindowTitle("Network Intelligence · History Center")
        self.resize(1180, 780)
        layout = QVBoxLayout(self)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Scope:"))
        self.scope_filter = QComboBox()
        self.scope_filter.currentIndexChanged.connect(self._refresh_view)
        filter_row.addWidget(self.scope_filter)
        filter_row.addWidget(QLabel("Periodo:"))
        self.time_filter = QComboBox()
        for days, label in TIME_FILTERS:
            self.time_filter.addItem(label, days)
        self.time_filter.currentIndexChanged.connect(self._refresh_view)
        filter_row.addWidget(self.time_filter)
        filter_row.addStretch(1)
        layout.addLayout(filter_row)

        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        self.chart = SnapshotTrendChart(self)
        layout.addWidget(self.chart)

        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(
            [
                "Generated",
                "Scope",
                "Score",
                "Devices",
                "High",
                "Medium",
                "Unknown",
                "Size",
                "Snapshot",
            ]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)

        nav_row = QHBoxLayout()
        self.previous_button = QPushButton("← Anterior")
        self.previous_button.clicked.connect(lambda: self._move_selection(-1))
        nav_row.addWidget(self.previous_button)
        self.next_button = QPushButton("Siguiente →")
        self.next_button.clicked.connect(lambda: self._move_selection(1))
        nav_row.addWidget(self.next_button)
        self.compare_previous_button = QPushButton("Comparar con anterior del mismo scope")
        self.compare_previous_button.clicked.connect(self._compare_previous)
        nav_row.addWidget(self.compare_previous_button)
        nav_row.addStretch(1)
        layout.addLayout(nav_row)

        self.detail_area = QPlainTextEdit()
        self.detail_area.setReadOnly(True)
        self.detail_area.setMaximumHeight(180)
        layout.addWidget(self.detail_area)

        retention_group = QGroupBox("Retención automática")
        retention_row = QHBoxLayout(retention_group)
        retention_row.addWidget(QLabel("Máximo por scope:"))
        self.keep_spin = QSpinBox()
        self.keep_spin.setRange(MIN_KEEP_PER_SCOPE, MAX_KEEP_PER_SCOPE)
        self.keep_spin.setValue(policy.keep_per_scope)
        retention_row.addWidget(self.keep_spin)
        retention_row.addWidget(QLabel("Edad máxima (días):"))
        self.age_spin = QSpinBox()
        self.age_spin.setRange(0, MAX_RETENTION_DAYS)
        self.age_spin.setSpecialValueText("Sin límite")
        self.age_spin.setValue(policy.max_age_days or 0)
        retention_row.addWidget(self.age_spin)
        self.save_policy_button = QPushButton("Guardar política")
        self.save_policy_button.clicked.connect(self._save_policy)
        retention_row.addWidget(self.save_policy_button)
        self.clean_button = QPushButton("Limpiar ahora")
        self.clean_button.clicked.connect(self._clean_now)
        retention_row.addWidget(self.clean_button)
        layout.addWidget(retention_group)

        self.catalog_status = QLabel()
        self.catalog_status.setWordWrap(True)
        layout.addWidget(self.catalog_status)

        close_button = QPushButton("Cerrar")
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button)

        self._reload_catalog()

    def _reload_catalog(self) -> None:
        self.catalog = load_snapshot_catalog(self.directory)
        previous_scope = self.scope_filter.currentData()
        self.scope_filter.blockSignals(True)
        self.scope_filter.clear()
        self.scope_filter.addItem("Todos los scopes", None)
        for scope in self.catalog.scopes:
            self.scope_filter.addItem(scope, scope)
        if previous_scope is not None:
            index = self.scope_filter.findData(previous_scope)
            if index >= 0:
                self.scope_filter.setCurrentIndex(index)
        self.scope_filter.blockSignals(False)

        notes = [
            f"{len(self.catalog.entries)} snapshot(s) válidos · "
            f"{_format_bytes(self.catalog.total_size_bytes)} indexados"
        ]
        if self.catalog.skipped:
            notes.append(
                f"{len(self.catalog.skipped)} archivo(s) inválidos preservados y excluidos"
            )
        if self.catalog.truncated_count:
            notes.append(
                f"catálogo limitado: {self.catalog.truncated_count} archivo(s) más antiguos no indexados"
            )
        self.catalog_status.setText(" · ".join(notes))
        self._refresh_view()

    def _selected_scope(self) -> str | None:
        value = self.scope_filter.currentData()
        return str(value) if value else None

    def _refresh_view(self, _index: int = -1) -> None:
        days = self.time_filter.currentData()
        since = None
        if days is not None:
            since = datetime.now(timezone.utc) - timedelta(days=int(days))
        selected_scope = self._selected_scope()
        self.filtered_entries = filter_snapshot_entries(
            self.catalog.entries,
            scope=selected_scope,
            since=since,
        )

        scopes = {entry.scope for entry in self.filtered_entries}
        if not self.filtered_entries:
            self.summary_label.setText("Sin snapshots para el filtro actual.")
            self.chart.set_empty_message("Sin snapshots para el filtro actual")
            self.chart.set_entries(())
        elif selected_scope is None and len(scopes) > 1:
            self.summary_label.setText(
                f"{len(self.filtered_entries)} snapshot(s) en {len(scopes)} scopes · "
                "selecciona un scope para calcular una tendencia comparable."
            )
            self.chart.set_empty_message(
                "Selecciona un scope para visualizar una tendencia comparable"
            )
            self.chart.set_entries(())
        else:
            trend = summarize_trend(self.filtered_entries)
            assert trend is not None
            self.summary_label.setText(
                f"{trend.points} snapshot(s) · Score {trend.first_score} → {trend.latest_score} "
                f"({trend.score_delta:+d}) · rango {trend.lowest_score}–{trend.highest_score} · "
                f"devices {trend.devices_delta:+d} · high risk {trend.high_risk_delta:+d} · "
                f"medium risk {trend.medium_risk_delta:+d} · unknown {trend.unknown_delta:+d}"
            )
            self.chart.set_empty_message("Sin snapshots para el filtro actual")
            self.chart.set_entries(self.filtered_entries)

        self.table.setRowCount(len(self.filtered_entries))
        for row, entry in enumerate(self.filtered_entries):
            values = (
                entry.generated_at.astimezone().strftime("%d/%m/%Y %H:%M:%S"),
                entry.scope,
                f"{entry.score}/100",
                entry.total_devices,
                entry.high_risk,
                entry.medium_risk,
                entry.unknown_devices,
                _format_bytes(entry.size_bytes),
                entry.path.name,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.UserRole, row)
                self.table.setItem(row, column, item)

        if self.filtered_entries:
            self.table.selectRow(len(self.filtered_entries) - 1)
        else:
            self.detail_area.clear()
            self._sync_navigation()

    def _selected_row(self) -> int | None:
        selected = self.table.selectedItems()
        if not selected:
            return None
        row = selected[0].row()
        if not 0 <= row < len(self.filtered_entries):
            return None
        return row

    def _selected_entry(self) -> SnapshotCatalogEntry | None:
        row = self._selected_row()
        return self.filtered_entries[row] if row is not None else None

    def _selection_changed(self) -> None:
        entry = self._selected_entry()
        self.detail_area.setPlainText(_entry_details(entry) if entry is not None else "")
        self._sync_navigation()

    def _sync_navigation(self) -> None:
        row = self._selected_row()
        if row is None:
            self.previous_button.setEnabled(False)
            self.next_button.setEnabled(False)
            self.compare_previous_button.setEnabled(False)
            return
        self.previous_button.setEnabled(row > 0)
        self.next_button.setEnabled(row < len(self.filtered_entries) - 1)
        entry = self.filtered_entries[row]
        self.compare_previous_button.setEnabled(
            previous_snapshot_for(self.filtered_entries, entry) is not None
        )

    def _move_selection(self, offset: int) -> None:
        row = self._selected_row()
        if row is None:
            return
        target = row + offset
        if 0 <= target < len(self.filtered_entries):
            self.table.selectRow(target)
            self.table.scrollToItem(self.table.item(target, 0))

    def _compare_previous(self) -> None:
        current = self._selected_entry()
        if current is None:
            return
        previous = previous_snapshot_for(self.filtered_entries, current)
        if previous is None:
            return
        try:
            comparison = compare_network_reports(
                load_network_report(previous.path),
                load_network_report(current.path),
            )
        except Exception as error:
            show_error(
                self,
                "Network Intelligence",
                "No se pudieron comparar los snapshots seleccionados del histórico.",
                error=error,
            )
            return
        SnapshotComparisonDialog(comparison, self).exec_()

    def _candidate_policy(self) -> RetentionPolicy:
        age = self.age_spin.value()
        return RetentionPolicy(
            keep_per_scope=self.keep_spin.value(),
            max_age_days=age if age > 0 else None,
        )

    def _save_policy(self) -> None:
        candidate = self._candidate_policy()
        try:
            save_retention_policy(self.policy_path, candidate)
        except Exception as error:
            show_error(
                self,
                "Network Intelligence",
                "No se pudo guardar la política de retención de snapshots.",
                error=error,
            )
            return
        self.policy = candidate
        age = (
            "sin límite de edad"
            if candidate.max_age_days is None
            else f"{candidate.max_age_days} días"
        )
        self.catalog_status.setText(
            f"Política guardada: máximo {candidate.keep_per_scope} por scope · {age}."
        )

    def _clean_now(self) -> None:
        candidate = self._candidate_policy()
        scope = self._selected_scope()
        now = datetime.now(timezone.utc)
        removable = retention_candidates(
            self.catalog.entries,
            candidate,
            now=now,
            scope=scope,
        )
        if not removable:
            self.catalog_status.setText("La política actual no tiene snapshots válidos que eliminar.")
            return

        reclaim = sum(entry.size_bytes for entry in removable)
        scope_text = scope or "todos los scopes"
        answer = QMessageBox.question(
            self,
            "Limpiar histórico automático",
            (
                f"Se eliminarán {len(removable)} snapshot(s) programados válidos de {scope_text} "
                f"y se recuperarán aproximadamente {_format_bytes(reclaim)}.\n\n"
                "Se conservarán siempre los dos snapshots válidos más recientes por scope para "
                "mantener el baseline de comparación. Los reportes manuales y archivos inválidos "
                "no se tocarán. ¿Continuar?"
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        try:
            cleanup = apply_retention_policy(
                self.directory,
                candidate,
                now=now,
                scope=scope,
            )
        except Exception as error:
            show_error(
                self,
                "Network Intelligence",
                "No se pudo completar la limpieza del histórico automático.",
                error=error,
            )
            return

        self.policy = candidate
        try:
            save_retention_policy(self.policy_path, candidate)
        except Exception as error:
            show_warning(
                self,
                "Network Intelligence",
                "La limpieza terminó, pero no se pudo persistir la política utilizada.",
                details=str(error),
            )
        self._reload_catalog()
        self.catalog_status.setText(
            f"Limpieza completada: {len(cleanup.removed)} snapshot(s) eliminados · "
            f"{_format_bytes(cleanup.bytes_reclaimed)} recuperados."
        )


class Tool(NotificationTool):
    """Network Intelligence with automatic history catalog, trends and retention controls."""

    def setup_ui(self) -> None:
        super().setup_ui()
        ensure_app_dirs()
        self.retention_policy = self._load_retention_policy()

        history_center_row = QHBoxLayout()
        self.history_center_status = QLabel()
        self.history_center_status.setWordWrap(True)
        history_center_row.addWidget(self.history_center_status, 1)
        self.history_center_button = QPushButton("History Center")
        self.history_center_button.clicked.connect(self._open_history_center)
        history_center_row.addWidget(self.history_center_button)

        layout = self.centralWidget().layout()
        layout.insertLayout(min(9, layout.count()), history_center_row)
        self._sync_history_center_controls()

    def _load_retention_policy(self) -> RetentionPolicy:
        try:
            return load_retention_policy(NETWORK_INTELLIGENCE_RETENTION_FILE)
        except Exception as error:
            show_warning(
                self,
                self.name,
                "La configuración local de retención no es válida y no se modificará automáticamente.",
                details=str(error),
            )
            return RetentionPolicy()

    def _automatic_snapshot_retention_policy(self) -> RetentionPolicy:
        return self.retention_policy

    def _sync_history_center_controls(self) -> None:
        if not hasattr(self, "history_center_status"):
            return
        age = (
            "sin límite de edad"
            if self.retention_policy.max_age_days is None
            else f"máx. {self.retention_policy.max_age_days} días"
        )
        self.history_center_status.setText(
            f"Histórico automático: máximo {self.retention_policy.keep_per_scope} por scope · {age}"
        )
        running = self.worker is not None and self.worker.isRunning()
        self.history_center_button.setEnabled(not running)

    def _open_history_center(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        dialog = HistoryCenterDialog(
            NETWORK_INTELLIGENCE_AUTOMATIC_SNAPSHOTS_DIR,
            NETWORK_INTELLIGENCE_RETENTION_FILE,
            self.retention_policy,
            self,
        )
        dialog.exec_()
        self.retention_policy = dialog.policy
        self._sync_history_center_controls()

    def _set_running(self, running: bool) -> None:
        super()._set_running(running)
        if hasattr(self, "history_center_button"):
            self.history_center_button.setEnabled(not running)
