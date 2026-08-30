from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from tools.base_tool import BaseTool
from tools.theme_manager import ThemeManager
from tools.ui_feedback import show_error

from .models import ReportData as ReportData
from .service import collect_report, report_to_html, report_to_pdf, report_to_text


class ReportWorker(QThread):
    result_ready = pyqtSignal(object)
    failed = pyqtSignal(object)

    def run(self) -> None:
        try:
            self.result_ready.emit(collect_report())
        except Exception as error:
            self.failed.emit(error)


class Tool(BaseTool):
    name = "Informe Técnico del Equipo"
    description = "Genera informes técnicos de hardware y software."
    category = "Sistema"

    def setup_ui(self):
        self.setWindowTitle(self.name)
        self.setGeometry(200, 200, 1100, 700)
        ThemeManager.apply_theme(self)

        self.report_data: ReportData | None = None

        layout = QVBoxLayout()
        layout.addWidget(
            QLabel("Genera un informe técnico con sistema, discos, red, procesos y temporales.")
        )

        button_layout = QHBoxLayout()
        self.btn_generate = QPushButton("Generar informe")
        self.btn_generate.clicked.connect(self.generate_report)
        button_layout.addWidget(self.btn_generate)

        self.btn_html = QPushButton("Exportar HTML")
        self.btn_html.clicked.connect(self.export_html)
        self.btn_html.setEnabled(False)
        button_layout.addWidget(self.btn_html)

        self.btn_pdf = QPushButton("Exportar PDF")
        self.btn_pdf.clicked.connect(self.export_pdf)
        self.btn_pdf.setEnabled(False)
        button_layout.addWidget(self.btn_pdf)

        self.btn_txt = QPushButton("Exportar TXT")
        self.btn_txt.clicked.connect(self.export_txt)
        self.btn_txt.setEnabled(False)
        button_layout.addWidget(self.btn_txt)
        layout.addLayout(button_layout)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)

        self.tabs = QTabWidget()
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.tabs.addTab(self.preview, "Resumen")

        self.system_table = QTableWidget()
        self.tabs.addTab(self.system_table, "Sistema")

        self.disk_table = QTableWidget()
        self.tabs.addTab(self.disk_table, "Discos")

        self.network_table = QTableWidget()
        self.tabs.addTab(self.network_table, "Red")

        self.cpu_table = QTableWidget()
        self.tabs.addTab(self.cpu_table, "Top CPU")

        self.memory_table = QTableWidget()
        self.tabs.addTab(self.memory_table, "Top RAM")

        self.temp_table = QTableWidget()
        self.tabs.addTab(self.temp_table, "Temporales")

        layout.addWidget(self.tabs)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    def generate_report(self) -> None:
        self.btn_generate.setEnabled(False)
        self.progress.show()
        self.worker = ReportWorker()
        self.worker.result_ready.connect(self.on_report_ready)
        self.worker.failed.connect(self.on_report_failed)
        self.worker.start()

    def on_report_ready(self, data: ReportData) -> None:
        self.report_data = data
        self.preview.setPlainText(report_to_text(data))
        self.fill_table(self.system_table, ["Campo", "Valor"], data.system_rows)
        self.fill_table(
            self.disk_table, ["Dispositivo", "Punto de montaje", "Total", "Libre"], data.disk_rows
        )
        self.fill_table(self.network_table, ["Campo", "Valor"], data.network_rows)
        self.fill_table(self.cpu_table, ["PID", "Nombre", "CPU %", "RAM %"], data.top_cpu)
        self.fill_table(self.memory_table, ["PID", "Nombre", "CPU %", "RAM %"], data.top_memory)
        self.fill_table(self.temp_table, ["Ruta", "Tamaño estimado"], data.temp_summary)
        self.progress.hide()
        self.btn_generate.setEnabled(True)
        self.btn_html.setEnabled(True)
        self.btn_pdf.setEnabled(True)
        self.btn_txt.setEnabled(True)

    def on_report_failed(self, error) -> None:
        self.progress.hide()
        self.btn_generate.setEnabled(True)
        if isinstance(error, BaseException):
            show_error(
                self,
                "Informe técnico",
                "No se pudo generar el informe técnico.",
                error=error,
            )
        else:
            show_error(
                self,
                "Informe técnico",
                "No se pudo generar el informe técnico.",
                details=str(error),
            )

    def fill_table(self, table: QTableWidget, headers: list[str], rows: list[tuple]) -> None:
        table.clear()
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for col_index, value in enumerate(row):
                table.setItem(row_index, col_index, QTableWidgetItem(str(value)))
        table.resizeColumnsToContents()

    def require_report(self) -> ReportData | None:
        if not self.report_data:
            QMessageBox.warning(self, "Informe", "Primero genera el informe.")
            return None
        return self.report_data

    def default_filename(self, extension: str) -> str:
        suffix = (
            self.report_data.generated_at
            if self.report_data
            else datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        )
        return f"informe_tecnico_{suffix}.{extension}"

    def _export_text_file(self, file_path: str, content: str, label: str) -> bool:
        try:
            Path(file_path).write_text(content, encoding="utf-8")
        except Exception as error:
            show_error(
                self,
                f"Exportación {label}",
                f"No se pudo exportar el informe {label}.",
                error=error,
            )
            return False
        return True

    def export_html(self) -> None:
        data = self.require_report()
        if not data:
            return
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Guardar HTML", self.default_filename("html"), "HTML (*.html)"
        )
        if not file_path:
            return
        try:
            content = report_to_html(data)
        except Exception as error:
            show_error(
                self,
                "Exportación HTML",
                "No se pudo preparar el informe HTML.",
                error=error,
            )
            return
        if not self._export_text_file(file_path, content, "HTML"):
            return
        QMessageBox.information(self, "Exportado", "Informe HTML generado correctamente.")

    def export_txt(self) -> None:
        data = self.require_report()
        if not data:
            return
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Guardar TXT", self.default_filename("txt"), "Texto (*.txt)"
        )
        if not file_path:
            return
        try:
            content = report_to_text(data)
        except Exception as error:
            show_error(
                self,
                "Exportación TXT",
                "No se pudo preparar el informe TXT.",
                error=error,
            )
            return
        if not self._export_text_file(file_path, content, "TXT"):
            return
        QMessageBox.information(self, "Exportado", "Informe TXT generado correctamente.")

    def export_pdf(self) -> None:
        data = self.require_report()
        if not data:
            return
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Guardar PDF", self.default_filename("pdf"), "PDF (*.pdf)"
        )
        if not file_path:
            return

        try:
            report_to_pdf(data, file_path)
        except Exception as error:
            show_error(
                self,
                "Exportación PDF",
                "No se pudo exportar el informe PDF.",
                error=error,
            )
            return

        QMessageBox.information(self, "Exportado", "Informe PDF generado correctamente.")