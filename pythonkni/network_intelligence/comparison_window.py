from __future__ import annotations

from pathlib import Path

from PyQt5.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from tools.ui_feedback import show_error, show_warning

from .comparison import (
    SnapshotComparison,
    compare_network_reports,
    format_snapshot_comparison,
    load_network_report,
)
from .confidence_window import Tool as ConfidenceTool


class SnapshotComparisonDialog(QDialog):
    def __init__(self, comparison: SnapshotComparison, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Network Intelligence Snapshot Comparison")
        self.resize(780, 580)

        layout = QVBoxLayout(self)
        self.text_area = QPlainTextEdit()
        self.text_area.setReadOnly(True)
        self.text_area.setPlainText(format_snapshot_comparison(comparison))
        layout.addWidget(self.text_area)

        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button)


class Tool(ConfidenceTool):
    """Network Intelligence window with offline saved-snapshot comparison."""

    def setup_ui(self) -> None:
        super().setup_ui()

        compare_row = QHBoxLayout()
        self.compare_snapshots_button = QPushButton("Compare saved snapshots")
        self.compare_snapshots_button.clicked.connect(self.compare_saved_snapshots)
        compare_row.addWidget(self.compare_snapshots_button)
        compare_row.addStretch(1)

        layout = self.centralWidget().layout()
        layout.insertLayout(min(5, layout.count()), compare_row)

    def _set_running(self, running: bool) -> None:
        super()._set_running(running)
        if hasattr(self, "compare_snapshots_button"):
            self.compare_snapshots_button.setEnabled(not running)

    def _pick_snapshot(self, title: str) -> Path | None:
        file_path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            title,
            "",
            "Network Intelligence snapshots (*.json *.zip)",
        )
        return Path(file_path) if file_path else None

    @staticmethod
    def _same_path(left: Path, right: Path) -> bool:
        try:
            return left.resolve() == right.resolve()
        except OSError:
            return left.absolute() == right.absolute()

    def compare_saved_snapshots(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            return

        baseline_path = self._pick_snapshot("Select baseline snapshot")
        if baseline_path is None:
            return
        current_path = self._pick_snapshot("Select comparison snapshot")
        if current_path is None:
            return
        if self._same_path(baseline_path, current_path):
            show_warning(
                self,
                self.name,
                "Selecciona dos snapshots distintos para realizar la comparación.",
            )
            return

        try:
            baseline = load_network_report(baseline_path)
            current = load_network_report(current_path)
            comparison = compare_network_reports(baseline, current)
        except Exception as error:
            show_error(
                self,
                self.name,
                "No se pudieron comparar los snapshots de Network Intelligence.",
                error=error,
            )
            return

        dialog = SnapshotComparisonDialog(comparison, self)
        dialog.exec_()
        self.status_label.setText(
            "Comparación offline completada: "
            f"+{len(comparison.added_assets)} / -{len(comparison.removed_assets)} / "
            f"{len(comparison.changed_assets)} activo(s) cambiado(s) · "
            f"Score {comparison.security_score_before} → {comparison.security_score_after} "
            f"({comparison.security_score_delta:+d})."
        )
