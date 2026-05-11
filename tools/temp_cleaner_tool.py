from __future__ import annotations

# tools/temp_cleaner_tool.py
import os
import shutil
import tempfile
import platform
import getpass
import logging
from dataclasses import dataclass, field
from PyQt5.QtWidgets import QMainWindow, QVBoxLayout, QWidget, QPushButton, QMessageBox, QCheckBox


logger = logging.getLogger(__name__)


@dataclass
class CleanResult:
    deleted: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)

    def add(self, other: "CleanResult") -> None:
        self.deleted += other.deleted
        self.failed += other.failed
        self.errors.extend(other.errors)


# ---------------- FUNCIONES DE LIMPIEZA ----------------
def delete_folder_contents(folder) -> CleanResult:
    """Borra todos los archivos y carpetas dentro de una carpeta."""
    result = CleanResult()
    if not os.path.exists(folder):
        return result

    for root, dirs, files in os.walk(folder, topdown=False):
        for f in files:
            try:
                path = os.path.join(root, f)
                os.remove(path)
                result.deleted += 1
            except Exception:
                result.failed += 1
                result.errors.append(os.path.join(root, f))
                logger.warning("No se pudo borrar %s", os.path.join(root, f), exc_info=True)
        for d in dirs:
            try:
                path = os.path.join(root, d)
                shutil.rmtree(path)
                result.deleted += 1
            except Exception:
                result.failed += 1
                result.errors.append(os.path.join(root, d))
                logger.warning("No se pudo borrar %s", os.path.join(root, d), exc_info=True)
    return result


def clean_temp() -> CleanResult:
    """Borra archivos temporales del sistema."""
    system = platform.system()
    temp_dir = os.environ.get("TEMP") if system == "Windows" else tempfile.gettempdir()
    return delete_folder_contents(temp_dir)


def clean_browser_cache() -> CleanResult:
    """Borra la caché de navegadores comunes (Chrome, Edge, Firefox)."""
    user = getpass.getuser()
    result = CleanResult()
    system = platform.system()

    if system == "Windows":
        chrome_cache = f"C:/Users/{user}/AppData/Local/Google/Chrome/User Data/Default/Cache"
        edge_cache = f"C:/Users/{user}/AppData/Local/Microsoft/Edge/User Data/Default/Cache"
        firefox_cache = f"C:/Users/{user}/AppData/Roaming/Mozilla/Firefox/Profiles"
    else:  # Linux/Mac
        home = os.path.expanduser("~")
        chrome_cache = f"{home}/.cache/google-chrome/Default/Cache"
        edge_cache = f"{home}/.cache/microsoft-edge/Default/Cache"
        firefox_cache = f"{home}/.mozilla/firefox"

    for folder in [chrome_cache, edge_cache, firefox_cache]:
        result.add(delete_folder_contents(folder))

    return result


def clean_logs() -> CleanResult:
    """Borra logs del sistema (Windows/Linux)."""
    system = platform.system()

    if system == "Windows":
        log_dir = f"C:/Windows/Temp"
    else:
        log_dir = "/var/log"

    return delete_folder_contents(log_dir)


# ---------------- INTERFAZ GRÁFICA ----------------
class Tool(QMainWindow):
    name = "Limpieza de Temporales"

    def __init__(self):
        super().__init__()
        self.setWindowTitle(self.name)
        self.setGeometry(200, 200, 400, 300)

        layout = QVBoxLayout()

        # Opciones con checkboxes
        self.chk_temp = QCheckBox("Archivos temporales del sistema")
        self.chk_temp.setChecked(True)
        layout.addWidget(self.chk_temp)

        self.chk_cache = QCheckBox("Caché de navegadores (Chrome, Edge, Firefox)")
        layout.addWidget(self.chk_cache)

        self.chk_logs = QCheckBox("Logs del sistema")
        layout.addWidget(self.chk_logs)

        # Botón ejecutar
        btn_clean = QPushButton("Ejecutar limpieza")
        btn_clean.clicked.connect(self.clean_action)
        layout.addWidget(btn_clean)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    def clean_action(self):
        result = CleanResult()

        if self.chk_temp.isChecked():
            result.add(clean_temp())

        if self.chk_cache.isChecked():
            result.add(clean_browser_cache())

        if self.chk_logs.isChecked():
            result.add(clean_logs())

        QMessageBox.information(
            self,
            "Limpieza completada",
            f"Se han eliminado {result.deleted} archivos/carpetas temporales.\n"
            f"No se pudieron eliminar {result.failed} elementos.",
        )
