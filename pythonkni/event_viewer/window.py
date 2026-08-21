from __future__ import annotations

import csv
import subprocess
import threading
from collections import Counter
from datetime import datetime
from pathlib import Path

from PyQt5.QtCore import QThread, Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tools.base_tool import BaseTool
from tools.theme_manager import ThemeManager

from .models import EventItem, EventResult
from .service import (
    RISK_ORDER,
    _REPORTLAB_AVAILABLE,
    clean_text,
    collect_events,
    events_to_html,
    events_to_pdf,
    save_events_snapshot,
)


RISK_COLORS = {
    "Alto": QColor("#ffcccc"),
    "Medio": QColor("#ffe5b4"),
    "Bajo": QColor("#fff7cc"),
    "Normal": QColor("#d9f2d9"),
}


class EventWorker(QThread):
    result_ready = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, logs: list[str], hours: int, max_events: int, include_info: bool):
        super().__init__()
        self.logs = logs
        self.hours = hours
        self.max_events = max_events
        self.include_info = include_info
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        try:
            result = collect_events(
                self.logs,
                self.hours,
                self.max_events,
                self.include_info,
                cancel_event=self._cancel_event,
            )
            self.result_ready.emit(result)
        except Exception as error:
            self.failed.emit(str(error))


# ---------------------------------------------------------------------------
# Interfaz gráfica
# ---------------------------------------------------------------------------


class EventDetailDialog(QDialog):
    def __init__(self, item: EventItem, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"Detalle del evento {item.event_id}")
        self.resize(850, 600)

        layout = QVBoxLayout()
        editor = QPlainTextEdit()
        editor.setReadOnly(True)
        editor.setPlainText(item.detail_text())
        layout.addWidget(editor)

        btn_copy = QPushButton("Copiar detalle")
        btn_copy.clicked.connect(lambda: QApplication.clipboard().setText(item.detail_text()))
        layout.addWidget(btn_copy)

        self.setLayout(layout)


class Tool(BaseTool):
    name = "Visor de eventos de Windows"
    description = "Consulta y analiza eventos de Windows."
    category = "Sistema"

    def setup_ui(self) -> None:
        self.setWindowTitle(self.name)
        self.resize(1350, 780)
        self.events: list[EventItem] = []
        self.visible_events: list[EventItem] = []
        self.worker: EventWorker | None = None
        ThemeManager.apply_theme(QApplication.instance())

        root = QWidget()
        main_layout = QVBoxLayout()

        title = QLabel("Visor de eventos de Windows simplificado")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        main_layout.addWidget(title)

        description = QLabel(
            "Lee eventos reales de Windows, clasifica el riesgo y añade una interpretación útil para soporte técnico."
        )
        description.setWordWrap(True)
        main_layout.addWidget(description)

        # --- Filtros de registros y periodo ---
        filters = QGridLayout()

        self.chk_application = QCheckBox("Application")
        self.chk_application.setChecked(True)
        self.chk_system = QCheckBox("System")
        self.chk_system.setChecked(True)
        self.chk_security = QCheckBox("Security")
        self.chk_security.setToolTip("Puede requerir permisos de administrador.")

        filters.addWidget(QLabel("Registros:"), 0, 0)
        filters.addWidget(self.chk_application, 0, 1)
        filters.addWidget(self.chk_system, 0, 2)
        filters.addWidget(self.chk_security, 0, 3)

        self.cmb_period = QComboBox()
        self.cmb_period.addItem("Últimas 24 horas", 24)
        self.cmb_period.addItem("Últimos 7 días", 24 * 7)
        self.cmb_period.addItem("Últimos 30 días", 24 * 30)
        self.cmb_period.addItem("Sin filtro temporal", 0)
        filters.addWidget(QLabel("Periodo:"), 1, 0)
        filters.addWidget(self.cmb_period, 1, 1)

        self.spn_max = QSpinBox()
        self.spn_max.setRange(10, 1000)
        self.spn_max.setValue(150)
        self.spn_max.setSingleStep(10)
        filters.addWidget(QLabel("Máx. eventos:"), 1, 2)
        filters.addWidget(self.spn_max, 1, 3)

        self.chk_info = QCheckBox("Incluir información")
        self.chk_info.setToolTip("Normalmente no hace falta. Puede devolver demasiados eventos.")
        filters.addWidget(self.chk_info, 1, 4)

        main_layout.addLayout(filters)

        # --- Filtros de nivel y riesgo ---
        filter_row = QHBoxLayout()

        self.cmb_filter_level = QComboBox()
        self.cmb_filter_level.addItem("Todos los niveles", "")
        self.cmb_filter_level.addItem("Crítico", "Crítico")
        self.cmb_filter_level.addItem("Error", "Error")
        self.cmb_filter_level.addItem("Advertencia", "Advertencia")
        self.cmb_filter_level.addItem("Información", "Información")
        self.cmb_filter_level.currentIndexChanged.connect(self.populate_table)

        self.cmb_filter_risk = QComboBox()
        self.cmb_filter_risk.addItem("Todos los riesgos", "")
        self.cmb_filter_risk.addItem("Alto", "Alto")
        self.cmb_filter_risk.addItem("Medio", "Medio")
        self.cmb_filter_risk.addItem("Bajo", "Bajo")
        self.cmb_filter_risk.addItem("Normal", "Normal")
        self.cmb_filter_risk.currentIndexChanged.connect(self.populate_table)

        filter_row.addWidget(QLabel("Nivel:"))
        filter_row.addWidget(self.cmb_filter_level)
        filter_row.addWidget(QLabel("Riesgo:"))
        filter_row.addWidget(self.cmb_filter_risk)
        filter_row.addStretch()
        main_layout.addLayout(filter_row)

        # --- Buscador ---
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("Buscar por origen, ID, mensaje o interpretación...")
        self.txt_search.textChanged.connect(self.populate_table)
        main_layout.addWidget(self.txt_search)

        # --- Botones fila 1 ---
        btn_layout1 = QHBoxLayout()

        self.btn_refresh = QPushButton("Actualizar")
        self.btn_refresh.clicked.connect(self.refresh_events)
        btn_layout1.addWidget(self.btn_refresh)

        self.btn_cancel = QPushButton("Cancelar lectura")
        self.btn_cancel.clicked.connect(self.cancel_loading)
        self.btn_cancel.setVisible(False)
        btn_layout1.addWidget(self.btn_cancel)

        self.btn_24h = QPushButton("Filtrar últimas 24h")
        self.btn_24h.clicked.connect(lambda: self.set_period_and_refresh(24))
        btn_layout1.addWidget(self.btn_24h)

        self.btn_7d = QPushButton("Filtrar últimos 7 días")
        self.btn_7d.clicked.connect(lambda: self.set_period_and_refresh(24 * 7))
        btn_layout1.addWidget(self.btn_7d)

        self.btn_detail = QPushButton("Ver detalle")
        self.btn_detail.clicked.connect(self.show_detail)
        btn_layout1.addWidget(self.btn_detail)

        self.btn_copy = QPushButton("Copiar evento")
        self.btn_copy.clicked.connect(self.copy_selected_event)
        btn_layout1.addWidget(self.btn_copy)

        main_layout.addLayout(btn_layout1)

        # --- Botones fila 2 ---
        btn_layout2 = QHBoxLayout()

        self.btn_csv = QPushButton("Exportar CSV")
        self.btn_csv.clicked.connect(self.export_csv)
        btn_layout2.addWidget(self.btn_csv)

        self.btn_html = QPushButton("Exportar HTML")
        self.btn_html.clicked.connect(self.export_html)
        btn_layout2.addWidget(self.btn_html)

        self.btn_pdf = QPushButton("Exportar PDF")
        self.btn_pdf.clicked.connect(self.export_pdf)
        btn_layout2.addWidget(self.btn_pdf)

        self.btn_open_viewer = QPushButton("Abrir Visor de eventos")
        self.btn_open_viewer.clicked.connect(self.open_windows_event_viewer)
        btn_layout2.addWidget(self.btn_open_viewer)

        self.btn_report = QPushButton("Añadir al informe técnico")
        self.btn_report.clicked.connect(self.add_to_technical_report)
        btn_layout2.addWidget(self.btn_report)

        main_layout.addLayout(btn_layout2)

        # --- Resumen ejecutivo ---
        self.lbl_summary = QLabel("Pulsa Actualizar para cargar eventos.")
        self.lbl_summary.setWordWrap(True)
        self.lbl_summary.setStyleSheet("font-weight: bold; padding: 4px;")
        main_layout.addWidget(self.lbl_summary)

        # --- Tabla ---
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(
            [
                "Fecha",
                "Nivel",
                "Origen",
                "ID Evento",
                "Registro",
                "Categoría",
                "Mensaje resumido",
                "Riesgo",
                "Interpretación",
            ]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.doubleClicked.connect(self.show_detail)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.Stretch)
        header.setSectionResizeMode(7, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(8, QHeaderView.Stretch)
        main_layout.addWidget(self.table)

        # --- Barra de estado ---
        self.status = QLabel("Pulsa Actualizar para leer los eventos.")
        self.status.setWordWrap(True)
        main_layout.addWidget(self.status)

        root.setLayout(main_layout)
        self.setCentralWidget(root)

    def selected_logs(self) -> list[str]:
        logs = []
        if self.chk_application.isChecked():
            logs.append("Application")
        if self.chk_system.isChecked():
            logs.append("System")
        if self.chk_security.isChecked():
            logs.append("Security")
        return logs

    def set_period_and_refresh(self, hours: int) -> None:
        for index in range(self.cmb_period.count()):
            if self.cmb_period.itemData(index) == hours:
                self.cmb_period.setCurrentIndex(index)
                break
        self.refresh_events()

    def refresh_events(self) -> None:
        logs = self.selected_logs()
        if not logs:
            QMessageBox.warning(
                self, "Sin registros", "Selecciona al menos un registro de eventos."
            )
            return

        hours = int(self.cmb_period.currentData())
        max_events = int(self.spn_max.value())
        include_info = self.chk_info.isChecked()

        self.set_buttons_enabled(False)
        self.btn_cancel.setVisible(True)
        self.status.setText("Leyendo eventos de Windows...")
        self.lbl_summary.setText("Cargando...")
        self.table.setRowCount(0)

        self.worker = EventWorker(
            logs=logs, hours=hours, max_events=max_events, include_info=include_info
        )
        self.worker.result_ready.connect(self.on_events_loaded)
        self.worker.failed.connect(self.on_events_failed)
        self.worker.start()

    def cancel_loading(self) -> None:
        if self.worker is not None:
            self.worker.cancel()
        self.btn_cancel.setVisible(False)
        self.status.setText("Cancelando lectura...")

    def set_buttons_enabled(self, enabled: bool) -> None:
        for button in (
            self.btn_refresh,
            self.btn_24h,
            self.btn_7d,
            self.btn_detail,
            self.btn_copy,
            self.btn_csv,
            self.btn_html,
            self.btn_pdf,
            self.btn_open_viewer,
            self.btn_report,
        ):
            button.setEnabled(enabled)

    def on_events_loaded(self, result: EventResult) -> None:
        self.events = result.events
        self.populate_table()
        self.set_buttons_enabled(True)
        self.btn_cancel.setVisible(False)

        summary = self.build_summary()
        self.lbl_summary.setText(summary)

        if result.warnings:
            warning_text = " | Avisos: " + " | ".join(
                clean_text(w, 160) for w in result.warnings[:3]
            )
            if len(result.warnings) > 3:
                warning_text += f" | {len(result.warnings) - 3} avisos más."
            self.status.setText(summary + warning_text)
        else:
            self.status.setText(summary)

    def on_events_failed(self, error: str) -> None:
        self.events = []
        self.visible_events = []
        self.table.setRowCount(0)
        self.set_buttons_enabled(True)
        self.btn_cancel.setVisible(False)
        self.lbl_summary.setText("Error al cargar eventos.")
        self.status.setText("No se pudieron leer los eventos.")
        QMessageBox.critical(self, "Error", error)

    def populate_table(self) -> None:
        search = self.txt_search.text().strip().lower()
        filter_level = self.cmb_filter_level.currentData()
        filter_risk = self.cmb_filter_risk.currentData()

        filtered: list[EventItem] = []
        for item in self.events:
            if filter_level and item.level != filter_level:
                continue
            if filter_risk and item.risk != filter_risk:
                continue
            if search:
                haystack = " ".join(
                    [
                        item.date,
                        item.level,
                        item.provider,
                        item.event_id,
                        item.log_name,
                        item.category,
                        item.message,
                        item.risk,
                        item.interpretation,
                    ]
                ).lower()
                if search not in haystack:
                    continue
            filtered.append(item)

        self.visible_events = filtered
        self.table.setRowCount(len(self.visible_events))

        for row, item in enumerate(self.visible_events):
            values = [
                item.date,
                item.level,
                item.provider,
                item.event_id,
                item.log_name,
                item.category,
                clean_text(item.message, 260),
                item.risk,
                item.interpretation,
            ]
            for col, value in enumerate(values):
                table_item = QTableWidgetItem(str(value))
                if col in {3, 7}:
                    table_item.setTextAlignment(Qt.AlignCenter)
                if col == 7:
                    self.apply_risk_style(table_item, item.risk)
                self.table.setItem(row, col, table_item)

        if self.events:
            self.lbl_summary.setText(self.build_summary())

    def apply_risk_style(self, table_item: QTableWidgetItem, risk: str) -> None:
        color = RISK_COLORS.get(risk)
        if color:
            table_item.setBackground(color)

    def build_summary(self) -> str:
        total = len(self.events)
        if total == 0:
            return "Sin eventos cargados."
        high = sum(1 for e in self.events if e.risk == "Alto")
        medium = sum(1 for e in self.events if e.risk == "Medio")
        low = sum(1 for e in self.events if e.risk == "Bajo")
        critical = sum(1 for e in self.events if e.level_number == 1)
        errors = sum(1 for e in self.events if e.level_number == 2)
        warnings_count = sum(1 for e in self.events if e.level_number == 3)
        visible = len(self.visible_events)
        shown = f" (mostrando {visible})" if visible != total else ""
        return (
            f"Eventos: {total}{shown} | "
            f"Críticos: {critical} | Errores: {errors} | Advertencias: {warnings_count} | "
            f"Riesgo alto: {high} | Riesgo medio: {medium} | Riesgo bajo: {low}"
        )

    def selected_event(self) -> EventItem | None:
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            return None
        row = selected[0].row()
        if row < 0 or row >= len(self.visible_events):
            return None
        return self.visible_events[row]

    def show_detail(self) -> None:
        item = self.selected_event()
        if item is None:
            QMessageBox.information(
                self, "Sin selección", "Selecciona un evento para ver el detalle."
            )
            return
        dialog = EventDetailDialog(item, self)
        dialog.exec_()

    def copy_selected_event(self) -> None:
        item = self.selected_event()
        if item is None:
            QMessageBox.information(self, "Sin selección", "Selecciona un evento para copiarlo.")
            return
        QApplication.clipboard().setText(item.detail_text())
        self.status.setText("Evento copiado al portapapeles.")

    def export_csv(self) -> None:
        if not self.events:
            QMessageBox.information(self, "Sin datos", "No hay eventos para exportar.")
            return
        default_name = f"eventos_windows_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.csv"
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Exportar CSV", default_name, "CSV (*.csv)"
        )
        if not file_path:
            return

        with open(file_path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow(
                [
                    "Fecha",
                    "Nivel",
                    "Origen",
                    "ID Evento",
                    "Registro",
                    "Categoría",
                    "Mensaje",
                    "Riesgo",
                    "Interpretación",
                    "Equipo",
                    "Record ID",
                ]
            )
            for item in self.events:
                writer.writerow(
                    [
                        item.date,
                        item.level,
                        item.provider,
                        item.event_id,
                        item.log_name,
                        item.category,
                        item.message,
                        item.risk,
                        item.interpretation,
                        item.computer,
                        item.record_id,
                    ]
                )
        QMessageBox.information(self, "Exportado", "Eventos exportados correctamente en CSV.")

    def export_html(self) -> None:
        if not self.events:
            QMessageBox.information(self, "Sin datos", "No hay eventos para exportar.")
            return
        default_name = f"eventos_windows_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.html"
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Exportar HTML", default_name, "HTML (*.html)"
        )
        if not file_path:
            return

        Path(file_path).write_text(events_to_html(self.events), encoding="utf-8")
        QMessageBox.information(self, "Exportado", "Eventos exportados correctamente en HTML.")

    def export_pdf(self) -> None:
        if not self.events:
            QMessageBox.information(self, "Sin datos", "No hay eventos para exportar.")
            return
        if not _REPORTLAB_AVAILABLE:
            QMessageBox.warning(
                self,
                "ReportLab no disponible",
                "Para exportar PDF instala ReportLab:\n\npip install reportlab",
            )
            return
        default_name = f"eventos_windows_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.pdf"
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Exportar PDF", default_name, "PDF (*.pdf)"
        )
        if not file_path:
            return
        try:
            events_to_pdf(self.events, self.build_summary(), file_path)
            QMessageBox.information(self, "Exportado", "Eventos exportados correctamente en PDF.")
        except Exception as error:
            QMessageBox.critical(self, "Error al exportar PDF", str(error))

    def open_windows_event_viewer(self) -> None:
        try:
            subprocess.Popen(["eventvwr.msc"], shell=True)
        except Exception as error:
            QMessageBox.critical(self, "Error", f"No se pudo abrir el Visor de eventos:\n{error}")

    def add_to_technical_report(self) -> None:
        if not self.events:
            QMessageBox.information(
                self, "Sin datos", "No hay eventos para añadir al informe técnico."
            )
            return

        selected_events = sorted(
            self.events,
            key=lambda e: (RISK_ORDER.get(e.risk, 0), e.level_number in {1, 2}),
            reverse=True,
        )[:25]

        provider_counts = Counter(item.provider for item in self.events)
        top_providers = [{"provider": p, "count": c} for p, c in provider_counts.most_common(5)]

        summary_data = {
            "total": len(self.events),
            "critical": sum(1 for e in self.events if e.level_number == 1),
            "errors": sum(1 for e in self.events if e.level_number == 2),
            "warnings": sum(1 for e in self.events if e.level_number == 3),
            "high_risk": sum(1 for e in self.events if e.risk == "Alto"),
            "medium_risk": sum(1 for e in self.events if e.risk == "Medio"),
            "top_providers": top_providers,
        }

        snapshot_path = save_events_snapshot(selected_events, summary_data)
        QMessageBox.information(
            self,
            "Añadido al informe técnico",
            "Se ha guardado un resumen de eventos para el Informe Técnico del Equipo.\n\n"
            "Vuelve a generar el informe técnico y aparecerá una sección de eventos recientes.\n\n"
            f"Archivo interno:\n{snapshot_path}",
        )
