from __future__ import annotations

from pathlib import Path

from PyQt5.QtWidgets import QFileDialog, QHBoxLayout, QPushButton

from pythonkni.camera_auditor.service import parse_camera_scope
from pythonkni.infrastructure.paths import NETWORK_INTELLIGENCE_REPORTS_DIR, ensure_app_dirs
from tools.ui_feedback import show_error, show_warning

from .reporting import build_network_report, export_network_report
from .window import Tool as NetworkIntelligenceTool


class Tool(NetworkIntelligenceTool):
    """Network Intelligence window with snapshot-report export composition."""

    def setup_ui(self) -> None:
        super().setup_ui()
        ensure_app_dirs()
        NETWORK_INTELLIGENCE_REPORTS_DIR.mkdir(parents=True, exist_ok=True)

        report_row = QHBoxLayout()
        self.export_report_button = QPushButton("Export snapshot report")
        self.export_report_button.clicked.connect(self.export_snapshot_report)
        report_row.addWidget(self.export_report_button)
        report_row.addStretch(1)
        self.centralWidget().layout().insertLayout(4, report_row)

    def _set_running(self, running: bool) -> None:
        super()._set_running(running)
        if hasattr(self, "export_report_button"):
            self.export_report_button.setEnabled(not running)

    def export_snapshot_report(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            return

        scope = self._active_scope()
        try:
            canonical_scope = parse_camera_scope(scope).with_prefixlen
            assets = self.inventory.list_assets(scope=canonical_scope)
            relationships = self.relationship_store.list(scope=canonical_scope)
            events = self.inventory.list_events(scope=canonical_scope, limit=1000)
            report = build_network_report(canonical_scope, assets, relationships, events)
        except Exception as error:
            show_error(
                self,
                self.name,
                "No se pudo preparar el snapshot de Network Intelligence.",
                error=error,
            )
            return

        if not assets and not relationships and not events:
            show_warning(
                self,
                self.name,
                "No hay datos persistidos para el scope seleccionado.",
            )
            return

        suggested = str(NETWORK_INTELLIGENCE_REPORTS_DIR / "network_intelligence_report.json")
        file_path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export Network Intelligence snapshot",
            suggested,
            "JSON report (*.json);;Evidence bundle (*.zip)",
        )
        if not file_path:
            return

        destination = Path(file_path)
        if not destination.suffix:
            destination = destination.with_suffix(".zip" if "bundle" in selected_filter.lower() else ".json")
        try:
            exported = export_network_report(destination, report)
        except Exception as error:
            show_error(
                self,
                self.name,
                "No se pudo exportar el informe de Network Intelligence.",
                error=error,
            )
            return

        self.status_label.setText(
            f"Snapshot exportado: {len(assets)} activo(s), {len(relationships)} relación(es), "
            f"{len(events)} evento(s) → {exported}."
        )
