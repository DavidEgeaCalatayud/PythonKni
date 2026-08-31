from __future__ import annotations

from PyQt5.QtWidgets import (
    QFileDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from tools.base_tool import BaseTool
from tools.ui_feedback import show_error
from tools.worker import Worker

from .models import AuditReport
from .service import export_report, run_audit, security_rating


def _audit_task(worker: Worker) -> AuditReport:
    return run_audit(cancel_event=worker.cancel_event)


class Tool(BaseTool):
    name = "WiFi Auditor"
    description = "Auditoría defensiva de configuración WiFi, canales y evidencias verificables."
    category = "Red"

    def setup_ui(self) -> None:
        self.setWindowTitle(self.name)
        self.setGeometry(100, 100, 1050, 700)
        self.worker: Worker | None = None
        self.report: AuditReport | None = None

        self.scope_label = QLabel(
            "Inventario defensivo de redes visibles. No captura credenciales ni ejecuta cracking."
        )
        self.score_label = QLabel("Score: —")

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["SSID", "BSSID", "Banda", "Canal", "Señal", "Auth", "Cifrado", "Estado"]
        )
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)

        self.findings = QTextEdit()
        self.findings.setReadOnly(True)
        self.findings.setPlaceholderText("Los hallazgos de configuración aparecerán aquí.")

        self.btn_scan = QPushButton("Escanear redes visibles")
        self.btn_scan.clicked.connect(self.start_audit)
        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.cancel_audit)
        self.btn_export = QPushButton("Exportar evidencia JSON")
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self.export_current_report)

        layout = QVBoxLayout()
        layout.addWidget(self.scope_label)
        layout.addWidget(self.score_label)
        layout.addWidget(self.table)
        layout.addWidget(self.findings)
        layout.addWidget(self.btn_scan)
        layout.addWidget(self.btn_cancel)
        layout.addWidget(self.btn_export)
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    def _busy(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    def _set_busy(self, busy: bool) -> None:
        self.btn_scan.setEnabled(not busy)
        self.btn_cancel.setEnabled(busy)
        self.btn_export.setEnabled(not busy and self.report is not None)

    def start_audit(self) -> bool:
        if self._busy():
            return False
        worker = Worker(_audit_task)
        worker.result.connect(self.on_audit_result)
        worker.error.connect(self.on_audit_error)
        worker.cancelled.connect(self.on_audit_cancelled)
        worker.finished.connect(lambda worker=worker: self._on_worker_finished(worker))
        self.worker = worker
        self.report = None
        self.score_label.setText("Score: analizando...")
        self.findings.setPlainText("Enumerando redes visibles mediante Windows...")
        self._set_busy(True)
        self.start_managed_worker(worker, cancel=worker.cancel)
        return True

    def cancel_audit(self) -> None:
        if self._busy():
            self.worker.cancel()
            self.btn_cancel.setEnabled(False)

    def on_audit_cancelled(self) -> None:
        self.score_label.setText("Score: cancelado")
        self.findings.setPlainText("Auditoría cancelada.")

    def on_audit_error(self, error) -> None:
        self.score_label.setText("Score: error")
        if isinstance(error, BaseException):
            show_error(
                self,
                "WiFi Auditor",
                "No se pudo completar el inventario WiFi.",
                error=error,
            )
        else:
            show_error(
                self,
                "WiFi Auditor",
                "No se pudo completar el inventario WiFi.",
                details=str(error),
            )

    def on_audit_result(self, report: AuditReport) -> None:
        self.report = report
        self.score_label.setText(f"Score: {report.score}/100")
        self.table.setRowCount(len(report.access_points))
        for row, point in enumerate(report.access_points):
            values = (
                point.ssid,
                point.bssid,
                point.band,
                "" if point.channel is None else str(point.channel),
                "" if point.signal_percent is None else f"{point.signal_percent}%",
                point.authentication,
                point.encryption,
                security_rating(point),
            )
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))

        lines = []
        for finding in report.findings:
            lines.append(
                f"[{finding.severity.upper()}] {finding.title}\n"
                f"{finding.detail}\nRecomendación: {finding.recommendation}"
            )
        lines.append(f"SHA-256 evidencia: {report.evidence_sha256}")
        lines.append("Limitaciones:\n- " + "\n- ".join(report.limitations))
        self.findings.setPlainText("\n\n".join(lines))
        self.btn_export.setEnabled(True)

    def export_current_report(self) -> None:
        if self.report is None:
            QMessageBox.information(self, "WiFi Auditor", "Ejecute primero una auditoría.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar evidencia",
            "wifi-audit.json",
            "JSON (*.json)",
        )
        if not path:
            return
        try:
            export_report(path, self.report)
        except OSError as error:
            show_error(
                self,
                "WiFi Auditor",
                "No se pudo exportar la evidencia.",
                error=error,
            )
            return
        QMessageBox.information(self, "WiFi Auditor", "Evidencia exportada correctamente.")

    def _on_worker_finished(self, worker: Worker) -> None:
        if self.worker is not worker:
            return
        self.worker = None
        self._set_busy(False)
