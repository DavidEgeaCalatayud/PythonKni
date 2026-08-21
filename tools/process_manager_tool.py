from __future__ import annotations

from tools.base_tool import BaseTool

import hashlib
import logging
import os
from dataclasses import dataclass

import psutil
import requests
from PyQt5.QtCore import QTimer, Qt
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


logger = logging.getLogger(__name__)

SYSTEM_PROCESS_NAMES = {
    "csrss.exe",
    "fontdrvhost.exe",
    "lsass.exe",
    "registry",
    "services.exe",
    "smss.exe",
    "system",
    "system idle process",
    "svchost.exe",
    "wininit.exe",
    "winlogon.exe",
}
SYSTEM_USERNAMES = {
    "local service",
    "network service",
    "nt authority\\local service",
    "nt authority\\network service",
    "nt authority\\system",
    "system",
}


@dataclass(frozen=True)
class ProcessDetails:
    pid: int
    name: str
    exe_path: str
    username: str
    create_time: float


@dataclass(frozen=True)
class VirusTotalResult:
    status: str
    exe_path: str
    file_hash: str
    positives: int = 0
    total: int = 0
    detections: tuple[str, ...] = ()
    response_text: str = ""


def get_vt_api_key():
    return os.getenv("VIRUSTOTAL_API_KEY")


def is_own_process(pid, app_pid=None):
    """Indica si el PID pertenece a la instancia actual de PythonKni."""
    return pid == (os.getpid() if app_pid is None else app_pid)


def is_system_process(details):
    """Clasifica conservadoramente procesos que requieren una advertencia extra."""
    name = details.name.casefold()
    username = details.username.casefold()
    exe_path = details.exe_path.casefold().replace("/", "\\")

    if details.pid in {0, 4}:
        return True
    if name in SYSTEM_PROCESS_NAMES:
        return True
    if username in SYSTEM_USERNAMES:
        return True
    return "\\windows\\system32\\" in exe_path or "\\windows\\syswow64\\" in exe_path


def format_process_identity(details):
    return f"PID: {details.pid}\nNombre: {details.name}\nRuta: {details.exe_path}"


def _safe_process_value(getter, fallback="No disponible"):
    try:
        value = getter()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return fallback
    return str(value) if value else fallback


def get_process_details(proc):
    """Obtiene una instantánea del proceso sin fallar por campos restringidos."""
    return ProcessDetails(
        pid=proc.pid,
        name=_safe_process_value(proc.name, "Desconocido"),
        exe_path=_safe_process_value(proc.exe),
        username=_safe_process_value(proc.username),
        create_time=proc.create_time(),
    )


def load_processes_task(worker, cpu_min, mem_min):
    """Collect process metrics outside the Qt GUI thread."""
    processes = []
    for proc in psutil.process_iter(["pid", "name"]):
        worker.check_cancelled()
        try:
            cpu = proc.cpu_percent(interval=0.1)
            mem = proc.memory_percent()
            if cpu < cpu_min and mem < mem_min:
                continue
            processes.append((proc.pid, proc.info["name"] or "Desconocido", cpu, mem))
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return processes


def analyze_process_task(worker, pid, api_key):
    """Hash an executable and query VirusTotal without blocking the GUI."""
    worker.report_progress({"message": f"Leyendo proceso {pid}..."})
    proc = psutil.Process(pid)
    exe_path = proc.exe()

    file_size = max(os.path.getsize(exe_path), 1)
    hashed_bytes = 0
    sha256_hash = hashlib.sha256()
    worker.report_progress({"message": "Calculando SHA-256...", "percent": 0})

    with open(exe_path, "rb") as file:
        while True:
            worker.check_cancelled()
            chunk = file.read(1024 * 1024)
            if not chunk:
                break
            sha256_hash.update(chunk)
            hashed_bytes += len(chunk)
            percent = min(100, int((hashed_bytes / file_size) * 100))
            worker.report_progress(
                {"message": f"Calculando SHA-256... {percent}%", "percent": percent}
            )

    file_hash = sha256_hash.hexdigest()
    worker.report_progress({"message": "Consultando VirusTotal..."})
    response = requests.get(
        f"https://www.virustotal.com/api/v3/files/{file_hash}",
        headers={"x-apikey": api_key},
        timeout=20,
    )
    worker.check_cancelled()

    if response.status_code == 404:
        return VirusTotalResult("not_found", exe_path, file_hash)
    if response.status_code != 200:
        return VirusTotalResult(
            "http_error",
            exe_path,
            file_hash,
            response_text=response.text,
        )

    data = response.json()
    attributes = data["data"]["attributes"]
    stats = attributes["last_analysis_stats"]
    scans = attributes["last_analysis_results"]
    detections = tuple(
        f"{engine}: {result['result']}"
        for engine, result in scans.items()
        if result["category"] == "malicious"
    )
    return VirusTotalResult(
        "found",
        exe_path,
        file_hash,
        positives=stats.get("malicious", 0),
        total=sum(stats.values()),
        detections=detections,
    )


class Tool(BaseTool):
    name = "Gestor de Procesos"
    description = "Consulta, analiza y administra procesos del sistema."
    category = "Sistema"

    def setup_ui(self):
        self.setWindowTitle(self.name)
        self.setGeometry(250, 250, 1000, 600)
        self._process_worker = None
        self._analysis_worker = None
        self._close_when_workers_finish = False

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
        """Carga la lista mediante el Worker reutilizable."""
        if self._process_worker is not None and self._process_worker.isRunning():
            self._process_worker.cancel()

        self.table.setRowCount(0)
        self.loading_widget.show()
        self.loading_movie.start()

        worker = Worker(
            load_processes_task,
            self.cpu_filter.value(),
            self.mem_filter.value(),
            parent=self,
        )
        self._process_worker = worker
        worker.result.connect(self.populate_table)
        worker.error.connect(self._process_load_error)
        worker.cancelled.connect(self._process_load_cancelled)
        worker.finished.connect(lambda: self._process_load_finished(worker))
        worker.start()

    def _process_load_error(self, error):
        logger.error("Could not load process list: %s", error)
        QMessageBox.critical(self, "Error", f"No se pudo cargar la lista de procesos:\n{error}")

    def _process_load_cancelled(self):
        self.loading_text.setText("Actualización cancelada")

    def _process_load_finished(self, worker):
        if self._process_worker is worker:
            self._process_worker = None
            self.loading_movie.stop()
            self.loading_widget.hide()
        worker.deleteLater()
        self._maybe_close_after_workers()

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
        worker.start()

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
        self._maybe_close_after_workers()

    def _maybe_close_after_workers(self):
        if not self._close_when_workers_finish:
            return
        process_running = self._process_worker is not None and self._process_worker.isRunning()
        analysis_running = self._analysis_worker is not None and self._analysis_worker.isRunning()
        if not process_running and not analysis_running:
            self._close_when_workers_finish = False
            QTimer.singleShot(0, self.close)

    def closeEvent(self, event):
        running = False
        for worker in (self._process_worker, self._analysis_worker):
            if worker is not None and worker.isRunning():
                worker.cancel()
                running = True
        if running:
            self._close_when_workers_finish = True
            event.ignore()
            return
        super().closeEvent(event)
