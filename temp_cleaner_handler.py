import os
import shutil
import tempfile
import platform
import getpass

def delete_folder_contents(folder):
    """Borra todos los archivos y carpetas dentro de una carpeta."""
    deleted_count = 0
    if not os.path.exists(folder):
        return 0

    for root, dirs, files in os.walk(folder, topdown=False):
        for f in files:
            try:
                os.remove(os.path.join(root, f))
                deleted_count += 1
            except Exception:
                pass
        for d in dirs:
            try:
                shutil.rmtree(os.path.join(root, d))
                deleted_count += 1
            except Exception:
                pass
    return deleted_count


def clean_temp():
    """Borra archivos temporales del sistema."""
    system = platform.system()
    temp_dir = os.environ.get("TEMP") if system == "Windows" else tempfile.gettempdir()
    return delete_folder_contents(temp_dir)


def clean_browser_cache():
    """Borra la caché de navegadores comunes."""
    user = getpass.getuser()
    deleted_count = 0
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
        deleted_count += delete_folder_contents(folder)

    return deleted_count


def clean_logs():
    """Borra logs del sistema (Windows/Linux)."""
    deleted_count = 0
    system = platform.system()

    if system == "Windows":
        log_dir = f"C:/Windows/Temp"
    else:
        log_dir = "/var/log"

    deleted_count += delete_folder_contents(log_dir)
    return deleted_count

from PyQt5.QtWidgets import (
    QMainWindow, QVBoxLayout, QWidget, QPushButton,
    QMessageBox, QCheckBox
)
from temp_cleaner_handler import clean_temp, clean_browser_cache, clean_logs

class TempCleanerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Limpieza de Archivos Temporales")
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
        deleted_count = 0

        if self.chk_temp.isChecked():
            deleted_count += clean_temp()

        if self.chk_cache.isChecked():
            deleted_count += clean_browser_cache()

        if self.chk_logs.isChecked():
            deleted_count += clean_logs()

        QMessageBox.information(
            self,
            "Limpieza completada",
            f"Se han eliminado {deleted_count} archivos/carpetas temporales."
        )
