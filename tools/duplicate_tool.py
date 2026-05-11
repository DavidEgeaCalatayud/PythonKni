from __future__ import annotations

import os
import hashlib
import logging
import shutil
from pathlib import Path


logger = logging.getLogger(__name__)


def hash_file(file_path: str | Path) -> str | None:
    """Devuelve el hash MD5 de un archivo."""
    hasher = hashlib.md5()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hasher.update(chunk)
    except (PermissionError, FileNotFoundError):
        return None
    return hasher.hexdigest()


def find_duplicates(folder_path: str | Path) -> dict[str, list[str]]:
    """Busca archivos duplicados en una carpeta y devuelve un diccionario {hash: [archivos]}"""
    duplicates = {}
    for root, _, files in os.walk(folder_path):
        for filename in files:
            file_path = os.path.join(root, filename)
            file_hash = hash_file(file_path)
            if file_hash:
                duplicates.setdefault(file_hash, []).append(file_path)
    # Filtrar solo los hashes con más de un archivo (duplicados reales)
    return {h: paths for h, paths in duplicates.items() if len(paths) > 1}


def move_duplicates(duplicates, base_folder):
    """
    Mueve los archivos duplicados a una subcarpeta "DuplicadosEncontrados".
    Mantiene un original y mueve los demás.
    Devuelve la cantidad de archivos movidos.
    """
    target_folder = os.path.join(base_folder, "DuplicadosEncontrados")
    os.makedirs(target_folder, exist_ok=True)

    moved_count = 0

    for paths in duplicates.values():
        # Mantener el primer archivo como "original"
        for file_path in paths[1:]:
            try:
                filename = os.path.basename(file_path)
                dest_path = os.path.join(target_folder, filename)

                # Evitar sobrescribir si ya existe
                base, ext = os.path.splitext(filename)
                counter = 1
                while os.path.exists(dest_path):
                    dest_path = os.path.join(target_folder, f"{base}_{counter}{ext}")
                    counter += 1

                shutil.move(file_path, dest_path)
                moved_count += 1
            except Exception:
                logger.warning("No se pudo mover %s", file_path, exc_info=True)

    return moved_count


from PyQt5.QtWidgets import (
    QMainWindow,
    QVBoxLayout,
    QWidget,
    QPushButton,
    QFileDialog,
    QTextEdit,
    QMessageBox,
)
from PyQt5.QtCore import QThread, pyqtSignal


class DuplicateFinderThread(QThread):
    finished = pyqtSignal(dict)

    def __init__(self, folder_path):
        super().__init__()
        self.folder_path = folder_path

    def run(self):
        duplicates = find_duplicates(self.folder_path)
        self.finished.emit(duplicates)


class Tool(QMainWindow):
    name = "Buscador de Archivos Duplicados"

    def __init__(self):
        super().__init__()
        self.setWindowTitle(self.name)
        self.setGeometry(200, 200, 600, 400)

        self.folder_path = None
        self.duplicates = {}

        layout = QVBoxLayout()

        self.result_box = QTextEdit()
        self.result_box.setReadOnly(True)
        layout.addWidget(self.result_box)

        btn_select_folder = QPushButton("Seleccionar Carpeta")
        btn_select_folder.clicked.connect(self.select_folder)
        layout.addWidget(btn_select_folder)

        self.btn_move = QPushButton("Mover duplicados a subcarpeta")
        self.btn_move.setEnabled(False)
        self.btn_move.clicked.connect(self.move_duplicates_action)
        layout.addWidget(self.btn_move)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    def select_folder(self):
        folder_path = QFileDialog.getExistingDirectory(self, "Seleccionar Carpeta")
        if not folder_path:
            return

        self.folder_path = folder_path
        self.result_box.clear()
        self.result_box.setPlainText("Buscando duplicados, por favor espere...")

        self.thread = DuplicateFinderThread(folder_path)
        self.thread.finished.connect(self.on_duplicates_found)
        self.thread.start()

    def on_duplicates_found(self, duplicates):
        self.duplicates = duplicates

        if not self.duplicates:
            QMessageBox.information(self, "Resultado", "No se encontraron archivos duplicados.")
            self.btn_move.setEnabled(False)
            self.result_box.clear()
            return

        result_text = "Archivos duplicados encontrados:\n\n"
        for h, paths in self.duplicates.items():
            result_text += f"Hash {h}:\n"
            for p in paths:
                result_text += f"   - {p}\n"
            result_text += "\n"

        self.result_box.setPlainText(result_text)
        self.btn_move.setEnabled(True)

    def move_duplicates_action(self):
        if not self.duplicates or not self.folder_path:
            return
        moved_count = move_duplicates(self.duplicates, self.folder_path)
        QMessageBox.information(
            self,
            "Duplicados movidos",
            f"Se han movido {moved_count} archivos duplicados "
            f"a la carpeta 'DuplicadosEncontrados'.",
        )
        self.btn_move.setEnabled(False)
