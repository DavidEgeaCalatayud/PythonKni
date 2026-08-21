import hashlib
import logging
import os
from dataclasses import dataclass

import psutil
import requests
from PyQt5.QtCore import QThread, Qt, pyqtSignal
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
    return (
        f"PID: {details.pid}\n"
        f"Nombre: {details.name}\n"
        f"Ruta: {details.exe_path}"
    )


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


class LoaderThread(QThread):
    processes_loaded = pyqtSignal(list)

    def __init__(self, cpu_min, mem_min):
        super().__init__()
        self.cpu_min = cpu_min
        self.mem_min = mem_min

    def run(self):
        processes = []
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                cpu = proc.cpu_percent(interval=0.1)
                mem = proc.memory_percent()

                if cpu < self.cpu_min and mem < self.mem_min:
                    continue

                processes.append((proc.pid, proc.info["name"] or "Desconocido", cpu, mem))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        self.processes_loaded.emit(processes)


class Tool(QMainWindow):
    name = "Gestor de Procesos"

    def __init__(self):
        super().__init__()
        self.setWindowTitle(self.name)
        self.setGeometry(250, 250, 1000, 600)

        ThemeManager.apply_theme(self)

        layout = QVBoxLayout()

        # Widget de carga (texto + gif)
        self.loading_widget = QWidget()
        loading_layout = QHBoxLayout()
        loading_layout.setAlignment(Qt.AlignCenter)

        # Texto
        self.loading_text = QLabel("Cargando procesos...")
        self.loading_text.setProperty("class", "loading-text")
        self.loading_text.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        loading_layout.addWidget(self.loading_text)

        # Espaciado fijo
        loading_layout.addSpacing(15)

        # Gif animado
        self.loading_label = QLabel()
        self.loading_label.setFixedSize(48, 48)
        self.loading_label.setAlignment(Qt.AlignCenter)

        gif_path = str(ASSETS_DIR / "spinner.gif")
        self.loading_movie = QMovie(gif_path)
        self.loading_movie.setScaledSize(self.loading_label.size())
        self.loading_label.setMovie(self.loading_movie)
        loading_layout.addWidget(self.loading_label)

        # Estiramiento al final (para que no colapse el texto)
        loading_layout.addStretch()

        self.loading_widget.setLayout(loading_layout)
        layout.addWidget(self.loading_widget)
        self.loading_widget.hide()

        # Tabla de procesos
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

        # Controles de filtrado
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

        # Botones principales
        btn_layout = QHBoxLayout()

        btn_refresh = QPushButton("🔄 Actualizar lista")
        btn_refresh.clicked.connect(self.load_processes)
        btn_layout.addWidget(btn_refresh)

        btn_kill = QPushButton("❌ Terminar proceso seleccionado")
        btn_kill.clicked.connect(self.kill_process)
        btn_layout.addWidget(btn_kill)

        layout.addLayout(btn_layout)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        # Cargar lista al inicio
        self.load_processes()

    def load_processes(self):
        """Carga lista de procesos en la tabla usando un hilo"""
        self.table.setRowCount(0)
        self.loading_widget.show()
        self.loading_movie.start()

        cpu_min = self.cpu_filter.value()
        mem_min = self.mem_filter.value()

        self.loader_thread = LoaderThread(cpu_min, mem_min)
        self.loader_thread.processes_loaded.connect(self.populate_table)
        self.loader_thread.start()

    def populate_table(self, processes):
        """Rellena la tabla con los procesos obtenidos"""
        self.loading_movie.stop()
        self.loading_widget.hide()

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
            "¿Seguro que quieres terminar este proceso?\n\n"
            + format_process_identity(details),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirmation != QMessageBox.Yes:
            return

        if is_system_process(details):
            system_confirmation = QMessageBox.question(
                self,
                "Advertencia: proceso del sistema",
                "Este proceso parece pertenecer a Windows o ejecutarse con una cuenta del sistema.\n"
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
                    "El proceso seleccionado ya no es el mismo. Se ha cancelado la operación por seguridad.",
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
        """Analiza el ejecutable del proceso en VirusTotal"""
        api_key = get_vt_api_key()
        if not api_key:
            QMessageBox.warning(
                self,
                "VirusTotal",
                "Falta la variable de entorno VIRUSTOTAL_API_KEY.",
            )
            return

        try:
            proc = psutil.Process(pid)
            exe_path = proc.exe()

            # Calcular hash SHA256
            sha256_hash = hashlib.sha256()
            with open(exe_path, "rb") as file:
                for chunk in iter(lambda: file.read(4096), b""):
                    sha256_hash.update(chunk)
            file_hash = sha256_hash.hexdigest()

            # Consultar en VirusTotal
            url = f"https://www.virustotal.com/api/v3/files/{file_hash}"
            headers = {"x-apikey": api_key}
            response = requests.get(url, headers=headers, timeout=20)

            if response.status_code == 200:
                data = response.json()
                stats = data["data"]["attributes"]["last_analysis_stats"]
                total = sum(stats.values())
                positives = stats.get("malicious", 0)

                detections = []
                scans = data["data"]["attributes"]["last_analysis_results"]
                for engine, result in scans.items():
                    if result["category"] == "malicious":
                        detections.append(f"{engine}: {result['result']}")

                if detections:
                    detections_text = "\n".join(detections[:15])
                    extra = "\n\n---\nMotores detectando:\n" + detections_text
                    if len(detections) > 15:
                        extra += f"\n...y {len(detections) - 15} más."
                else:
                    extra = "\n\nSin detecciones específicas."

                QMessageBox.information(
                    self,
                    "Resultado VirusTotal",
                    f"Archivo: {exe_path}\n\nDetecciones: {positives}/{total}{extra}",
                )

            elif response.status_code == 404:
                QMessageBox.warning(
                    self,
                    "VirusTotal",
                    f"Archivo no encontrado en VirusTotal.\nHash: {file_hash}",
                )
            else:
                QMessageBox.warning(
                    self,
                    "Error",
                    f"Error al consultar VirusTotal: {response.text}",
                )

        except Exception as error:
            logger.exception("Could not analyze process %s with VirusTotal", pid)
            QMessageBox.critical(
                self,
                "Error",
                f"No se pudo analizar el proceso:\n{error}",
            )
