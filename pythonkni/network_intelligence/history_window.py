from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from tools.ui_feedback import show_error, show_warning

from .history import ScoreHistory, ScoreHistoryPoint, load_score_history
from .risk_window import Tool as RiskTool


def _point_details(point: ScoreHistoryPoint) -> str:
    delta = "Baseline" if point.score_delta is None else f"{point.score_delta:+d} points"
    lines = [
        f"Snapshot: {point.generated_at_text}",
        f"Source: {point.source}",
        f"Schema: v{point.schema_version}",
        f"Score: {point.score}/100 · {delta}",
        f"Devices: {point.total_devices}",
        f"Risk: High {point.high_risk} · Medium {point.medium_risk} · Low {point.low_risk}",
        f"Unknown: {point.unknown_devices}",
        "",
        "Current findings",
    ]
    lines.extend(f"• {finding}" for finding in point.findings)
    if not point.findings:
        lines.append("• None")
    if point.findings_added:
        lines.extend(["", "New since previous snapshot"])
        lines.extend(f"+ {finding}" for finding in point.findings_added)
    if point.findings_resolved:
        lines.extend(["", "Resolved since previous snapshot"])
        lines.extend(f"- {finding}" for finding in point.findings_resolved)
    return "\n".join(lines)


class ScoreHistoryDialog(QDialog):
    def __init__(self, history: ScoreHistory, parent=None):
        super().__init__(parent)
        self.history = history
        self.setWindowTitle("Network Intelligence Security Score History")
        self.resize(980, 650)

        layout = QVBoxLayout(self)
        self.summary_label = QLabel(
            f"Scope {history.scope} · {len(history.points)} snapshots · "
            f"Score {history.first_score} → {history.latest_score} ({history.total_delta:+d}) · "
            f"Range {history.lowest_score}–{history.highest_score}"
        )
        layout.addWidget(self.summary_label)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["Generated", "Score", "Delta", "Devices", "High", "Medium", "Unknown", "Source"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        layout.addWidget(self.table)

        self.detail_area = QPlainTextEdit()
        self.detail_area.setReadOnly(True)
        layout.addWidget(self.detail_area)

        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button)

        self._populate()

    def _populate(self) -> None:
        self.table.setRowCount(len(self.history.points))
        for row, point in enumerate(self.history.points):
            values = (
                point.generated_at_text,
                f"{point.score}/100",
                "—" if point.score_delta is None else f"{point.score_delta:+d}",
                point.total_devices,
                point.high_risk,
                point.medium_risk,
                point.unknown_devices,
                point.source.name,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.UserRole, row)
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents()
        if self.history.points:
            self.table.selectRow(len(self.history.points) - 1)
            self.detail_area.setPlainText(_point_details(self.history.points[-1]))

    def _selection_changed(self) -> None:
        selected = self.table.selectedItems()
        if not selected:
            return
        row = int(selected[0].data(Qt.UserRole))
        self.detail_area.setPlainText(_point_details(self.history.points[row]))


class Tool(RiskTool):
    """Network Intelligence window with offline Security Score History."""

    def setup_ui(self) -> None:
        super().setup_ui()
        history_row = QHBoxLayout()
        self.score_history_button = QPushButton("Security Score History")
        self.score_history_button.clicked.connect(self.open_score_history)
        history_row.addWidget(self.score_history_button)
        history_row.addStretch(1)
        layout = self.centralWidget().layout()
        layout.insertLayout(min(6, layout.count()), history_row)

    def _set_running(self, running: bool) -> None:
        super()._set_running(running)
        if hasattr(self, "score_history_button"):
            self.score_history_button.setEnabled(not running)

    def open_score_history(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            return

        paths, _selected_filter = QFileDialog.getOpenFileNames(
            self,
            "Select Network Intelligence snapshots",
            "",
            "Network Intelligence snapshots (*.json *.zip)",
        )
        if not paths:
            return
        if len(paths) < 2:
            show_warning(
                self,
                self.name,
                "Selecciona al menos dos snapshots para construir el histórico.",
            )
            return

        try:
            history = load_score_history(paths)
        except Exception as error:
            show_error(
                self,
                self.name,
                "No se pudo construir el histórico del Network Security Score.",
                error=error,
            )
            return

        dialog = ScoreHistoryDialog(history, self)
        dialog.exec_()
        self.status_label.setText(
            f"Histórico offline: {len(history.points)} snapshots · "
            f"Score {history.first_score} → {history.latest_score} ({history.total_delta:+d}) · "
            f"rango {history.lowest_score}–{history.highest_score}."
        )
