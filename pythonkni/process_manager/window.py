from __future__ import annotations
from tools.base_tool import BaseTool
import hashlib
import logging
import os
from dataclasses import dataclass
import psutil
import requests
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QMovie
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from tools.app_paths import ASSETS_DIR
from tools.theme_manager import ThemeManager
from tools.worker import Worker
from .service import (
    CPU_SAMPLE_SECONDS,
    ProcessDetails,
    SYSTEM_PROCESS_NAMES,
    SYSTEM_USERNAMES,
    VirusTotalResult,
    _safe_process_value,
    analyze_process_task,
    format_process_identity,
    get_process_details,
    get_vt_api_key,
    is_own_process,
    is_system_process,
    load_processes_task,
    logger,
)
from . import service as _service
import sys as _sys
import types as _types


class Tool(BaseTool):
    name = "Gestor de Procesos"
    description = "Consulta, analiza y administra procesos del sistema."
    category = "Sistema"

    def setup_ui(self):
        self.setWindowTitle(self.name)
        self.setGeometry(250, 250, 1000, 600)
        self._process_worker = None
        self._analysis_worker = None

        ThemeManager.apply_theme(self)

        layout = QVBoxLayout()

        self.loading_widget = QWidget()
        loading_layout = QHBoxLayout()
        loading_layout.setAlignment(Qt.AlignCenter)

        self.loading_text = QLabel("Cargando procesos...")
        self.loading_text.setProperty("class", "loading-text")
        self.loading_text.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        loading_layout.addWidget(self.loading_text)
        loading_layout.addSpacing(15)

        self.loading_label = QLabel()
        self.loading_label.setFixedSize(48, 48)
        self.loading_label.setAlignment(Qt.AlignCenter)
        gif_path = str(ASSETS_DIR / "spinner.gif")
        self.loading_movie = QMovie(gif_path)
        self.loading_movie.setScaledSize(self.loading_label.size())
        self.loading_label.setMovie(self.loading_movie)
        loading_layout.addWidget(self.loading_label)
        loading_layout.addStretch()

        self.loading_widget.setLayout(loading_layout)
        layout.addWidget(self.loading_widget)
        self.loading_widget.hide()

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            ["PID", "Nombre", "CPU (%)", "Memoria (%)", "Acciones"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(self.table.SelectRows)
        self.table.setSortingEnabled(True)
        layout.addWidget(self.table)

        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Filtrar CPU >"))
        self.cpu_filter = QSpinBox()
        self.cpu_filter.setRange(0, 100)
        self.cpu_filter.setValue(0)
        filter_layout.addWidget(self.cpu_filter)

        filter_layout.addWidget(QLabel("Memoria >"))
        self.mem_filter = QSpinBox()
        self.mem_filter.setRange(0, 100)
        self.mem_filter.setValue(0)
        filter_layout.addWidget(self.mem_filter)

        btn_apply_filter = QPushButton("Aplicar Filtro")
        btn_apply_filter.clicked.connect(self.load_processes)
        filter_layout.addWidget(btn_apply_filter)
        layout.addLayout(filter_layout)

        btn_layout = QHBoxLayout()
        btn_refresh = QPushButton("🔄 Actualizar lista")
        btn_refresh.clicked.connect(self.load_processes)
        btn_layout.addWidget(btn_refresh)

        btn_kill = QPushButton("❌ Terminar proceso seleccionado")
        btn_kill.clicked.connect(self.kill_process)
        btn_layout.addWidget(btn_kill)
        layout.addLayout(btn_layout)

        analysis_layout = QHBoxLayout()
        self.analysis_status = QLabel("")
        analysis_layout.addWidget(self.analysis_status)
        analysis_layout.addStretch()
        self.btn_cancel_analysis = QPushButton("Cancelar análisis")
        self.btn_cancel_analysis.setEnabled(False)
        self.btn_cancel_analysis.clicked.connect(self.cancel_analysis)
        analysis_layout.addWidget(self.btn_cancel_analysis)
        layout.addLayout(analysis_layout)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)
        self.load_processes()

    def load_processes(self):
        """Carga la lista mediante workers administrados por BaseTool."""
        previous_worker = self._process_worker
        if previous_worker is not None and previous_worker.isRunning():
            previous_worker.cancel()

        self.table.setRowCount(0)
        self.loading_text.setText("Cargando procesos...")
        self.loading_widget.show()
        self.loading_movie.start()

        worker = Worker(
            load_processes_task,
            self.cpu_filter.value(),
            self.mem_filter.value(),
            parent=self,
        )
        self._process_worker = worker
        worker.result.connect(
            lambda processes, worker=worker: self._process_load_result(worker, processes)
        )
        worker.error.connect(lambda error, worker=worker: self._process_load_error(worker, error))
        worker.cancelled.connect(lambda worker=worker: self._process_load_cancelled(worker))
        worker.finished.connect(lambda: self._process_load_finished(worker))
        self.start_managed_worker(worker, cancel=worker.cancel)

    def _process_load_result(self, worker, processes):
        if self._process_worker is worker:
            self.populate_table(processes)

    def _process_load_error(self, worker, error):
        if self._process_worker is not worker:
            return
        logger.error("Could not load process list: %s", error)
        QMessageBox.critical(self, "Error", f"No se pudo cargar la lista de procesos:\n{error}")

    def _process_load_cancelled(self, worker):
        if self._process_worker is worker:
            self.loading_text.setText("Actualización cancelada")

    def _process_load_finished(self, worker):
        if self._process_worker is worker:
            self._process_worker = None
            self.loading_movie.stop()
            self.loading_widget.hide()
        worker.deleteLater()

    def populate_table(self, processes):
        """Rellena la tabla con los procesos obtenidos."""
        self.table.setSortingEnabled(False)
        for pid, name, cpu, mem in processes:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(str(pid)))
            self.table.setItem(row, 1, QTableWidgetItem(name))
            self.table.setItem(row, 2, QTableWidgetItem(f"{cpu:.1f}"))
            self.table.setItem(row, 3, QTableWidgetItem(f"{mem:.1f}"))

            btn_analyze = QPushButton("Analizar")
            btn_analyze.clicked.connect(lambda checked, pid=pid: self.analyze_process(pid))
            self.table.setCellWidget(row, 4, btn_analyze)
        self.table.setSortingEnabled(True)

    def kill_process(self):
        """Termina el proceso seleccionado aplicando protecciones previas."""
        selected = self.table.currentRow()
        if selected < 0:
            QMessageBox.warning(self, "Error", "Selecciona un proceso primero.")
            return

        pid = int(self.table.item(selected, 0).text())
        if is_own_process(pid):
            QMessageBox.warning(
                self,
                "Proceso protegido",
                "PythonKni no puede terminar su propio proceso desde el Gestor de Procesos.",
            )
            return

        try:
            proc = psutil.Process(pid)
            details = get_process_details(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as error:
            logger.warning("Could not inspect process %s before termination: %s", pid, error)
            QMessageBox.warning(
                self,
                "Proceso no disponible",
                "El proceso ya no existe o no se puede consultar con los permisos actuales.",
            )
            return

        confirmation = QMessageBox.question(
            self,
            "Confirmar finalización",
            "¿Seguro que quieres terminar este proceso?\n\n" + format_process_identity(details),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirmation != QMessageBox.Yes:
            return

        if is_system_process(details):
            system_confirmation = QMessageBox.question(
                self,
                "Advertencia: proceso del sistema",
                "Este proceso parece pertenecer a Windows o ejecutarse con una cuenta "
                "del sistema.\n"
                "Terminarlo puede provocar inestabilidad, cierre de sesión o reinicio.\n\n"
                + format_process_identity(details)
                + f"\nUsuario: {details.username}\n\n¿Quieres continuar de todos modos?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if system_confirmation != QMessageBox.Yes:
                return

        try:
            if not proc.is_running() or proc.create_time() != details.create_time:
                QMessageBox.warning(
                    self,
                    "Proceso cambiado",
                    "El proceso seleccionado ya no es el mismo. "
                    "Se ha cancelado la operación por seguridad.",
                )
                return

            proc.terminate()
            QMessageBox.information(
                self,
                "Éxito",
                f"Proceso {details.name} (PID {pid}) terminado.",
            )
            self.load_processes()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as error:
            logger.exception("Could not terminate process %s", pid)
            QMessageBox.critical(
                self,
                "Error",
                f"No se pudo terminar el proceso:\n{error}",
            )

    def analyze_process(self, pid):
        """Programa el análisis de VirusTotal fuera del hilo de la interfaz."""
        api_key = get_vt_api_key()
        if not api_key:
            QMessageBox.warning(
                self,
                "VirusTotal",
                "Falta la variable de entorno VIRUSTOTAL_API_KEY.",
            )
            return
        if self._analysis_worker is not None and self._analysis_worker.isRunning():
            QMessageBox.information(
                self,
                "VirusTotal",
                "Ya hay un análisis en curso. Cancélelo o espere a que finalice.",
            )
            return

        worker = Worker(analyze_process_task, pid, api_key, parent=self)
        self._analysis_worker = worker
        self.analysis_status.setText(f"Analizando PID {pid}...")
        self.btn_cancel_analysis.setEnabled(True)
        worker.progress.connect(self._analysis_progress)
        worker.result.connect(self._analysis_result)
        worker.error.connect(self._analysis_error)
        worker.cancelled.connect(self._analysis_cancelled)
        worker.finished.connect(lambda: self._analysis_finished(worker))
        self.start_managed_worker(worker, cancel=worker.cancel)

    def cancel_analysis(self):
        worker = self._analysis_worker
        if worker is not None and worker.isRunning():
            worker.cancel()
            self.analysis_status.setText("Cancelando análisis...")
            self.btn_cancel_analysis.setEnabled(False)

    def _analysis_progress(self, progress):
        if isinstance(progress, dict):
            self.analysis_status.setText(str(progress.get("message", "Analizando...")))
        else:
            self.analysis_status.setText(str(progress))

    def _analysis_result(self, result):
        if result.status == "not_found":
            QMessageBox.warning(
                self,
                "VirusTotal",
                f"Archivo no encontrado en VirusTotal.\nHash: {result.file_hash}",
            )
            return
        if result.status == "http_error":
            QMessageBox.warning(
                self,
                "Error",
                f"Error al consultar VirusTotal: {result.response_text}",
            )
            return

        if result.detections:
            detections_text = "\n".join(result.detections[:15])
            extra = "\n\n---\nMotores detectando:\n" + detections_text
            if len(result.detections) > 15:
                extra += f"\n...y {len(result.detections) - 15} más."
        else:
            extra = "\n\nSin detecciones específicas."

        QMessageBox.information(
            self,
            "Resultado VirusTotal",
            f"Archivo: {result.exe_path}\n\nDetecciones: {result.positives}/{result.total}{extra}",
        )

    def _analysis_error(self, error):
        logger.error("Could not analyze process with VirusTotal: %s", error)
        QMessageBox.critical(self, "Error", f"No se pudo analizar el proceso:\n{error}")

    def _analysis_cancelled(self):
        self.analysis_status.setText("Análisis cancelado")

    def _analysis_finished(self, worker):
        if self._analysis_worker is worker:
            self._analysis_worker = None
            self.btn_cancel_analysis.setEnabled(False)
            if self.analysis_status.text() != "Análisis cancelado":
                self.analysis_status.setText("")
        worker.deleteLater()


class _CompatibilityModule(_types.ModuleType):
    """Forward legacy monkeypatches to the separated service module."""

    def __setattr__(self, name, value):
        if hasattr(_service, name):
            setattr(_service, name, value)
        super().__setattr__(name, value)

    def __delattr__(self, name):
        if hasattr(_service, name):
            delattr(_service, name)
        super().__delattr__(name)


_sys.modules[__name__].__class__ = _CompatibilityModule
