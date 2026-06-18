from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from pathlib import Path

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QMainWindow,
)

from tools.theme_manager import ThemeManager


@dataclass
class DiskItem:
    path: str
    name: str
    item_type: str
    size: int


def format_bytes(num_bytes: int | float) -> str:
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.2f} {unit}"
        value /= 1024
    return f"{value:.2f} TB"


def directory_size(path: Path) -> int:
    total = 0
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if not Path(root, d).is_symlink()]
        for file_name in files:
            try:
                file_path = Path(root) / file_name
                if not file_path.is_symlink():
                    total += file_path.stat().st_size
            except OSError:
                continue
    return total


def analyze_directory(path: Path, limit: int = 100) -> list[DiskItem]:
    items: list[DiskItem] = []

    with os.scandir(path) as entries:
        for entry in entries:
            try:
                entry_path = Path(entry.path)
                if entry.is_symlink():
                    continue

                if entry.is_dir(follow_symlinks=False):
                    size = directory_size(entry_path)
                    item_type = "Carpeta"
                elif entry.is_file(follow_symlinks=False):
                    size = entry.stat(follow_symlinks=False).st_size
                    item_type = "Archivo"
                else:
                    continue

                items.append(
                    DiskItem(
                        path=str(entry_path),
                        name=entry.name,
                        item_type=item_type,
                        size=size,
                    )
                )
            except (PermissionError, OSError):
                continue

    return sorted(items, key=lambda item: item.size, reverse=True)[:limit]


class DiskAnalyzerWorker(QThread):
    finished = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, folder: str, limit: int = 100):
        super().__init__()
        self.folder = folder
        self.limit = limit

    def run(self) -> None:
        try:
            self.finished.emit(analyze_directory(Path(self.folder), self.limit))
        except Exception as error:
            self.failed.emit(str(error))


class Tool(QMainWindow):
    name = "Analizador de Disco"

    def __init__(self):
        super().__init__()
        self.setWindowTitle(self.name)
        self.setGeometry(250, 250, 1050, 650)
        ThemeManager.apply_theme(self)

        self.current_folder: str | None = None
        self.items: list[DiskItem] = []

        layout = QVBoxLayout()
        layout.addWidget(QLabel("Analiza una carpeta y muestra los archivos/carpetas que más espacio ocupan."))

        top_layout = QHBoxLayout()
        self.folder_label = QLabel("Carpeta: no seleccionada")
        top_layout.addWidget(self.folder_label)

        btn_select = QPushButton("Seleccionar carpeta")
        btn_select.clicked.connect(self.select_folder)
        top_layout.addWidget(btn_select)

        self.btn_analyze = QPushButton("Analizar")
        self.btn_analyze.clicked.connect(self.start_analysis)
        self.btn_analyze.setEnabled(False)
        top_layout.addWidget(self.btn_analyze)

        self.btn_export = QPushButton("Exportar CSV")
        self.btn_export.clicked.connect(self.export_csv)
        self.btn_export.setEnabled(False)
        top_layout.addWidget(self.btn_export)

        layout.addLayout(top_layout)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)

        self.summary_label = QLabel("Selecciona una carpeta para empezar.")
        layout.addWidget(self.summary_label)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Nombre", "Tipo", "Tamaño", "Bytes", "Ruta"])
        self.table.setSortingEnabled(True)
        layout.addWidget(self.table)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    def select_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta")
        if not folder:
            return
        self.current_folder = folder
        self.folder_label.setText(f"Carpeta: {folder}")
        self.btn_analyze.setEnabled(True)

    def start_analysis(self) -> None:
        if not self.current_folder:
            QMessageBox.warning(self, "Analizador", "Selecciona una carpeta primero.")
            return

        self.table.setRowCount(0)
        self.progress.show()
        self.btn_analyze.setEnabled(False)
        self.btn_export.setEnabled(False)
        self.summary_label.setText("Analizando. Puede tardar si la carpeta es grande...")

        self.worker = DiskAnalyzerWorker(self.current_folder)
        self.worker.finished.connect(self.on_analysis_finished)
        self.worker.failed.connect(self.on_analysis_failed)
        self.worker.start()

    def on_analysis_finished(self, items: list[DiskItem]) -> None:
        self.items = items
        self.progress.hide()
        self.btn_analyze.setEnabled(True)
        self.btn_export.setEnabled(bool(items))
        total = sum(item.size for item in items)
        self.summary_label.setText(f"Elementos mostrados: {len(items)} | Tamaño acumulado mostrado: {format_bytes(total)}")
        self.fill_table(items)

    def on_analysis_failed(self, message: str) -> None:
        self.progress.hide()
        self.btn_analyze.setEnabled(True)
        QMessageBox.critical(self, "Error", f"No se pudo analizar la carpeta:\n{message}")

    def fill_table(self, items: list[DiskItem]) -> None:
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(items))
        for row, item in enumerate(items):
            self.table.setItem(row, 0, QTableWidgetItem(item.name))
            self.table.setItem(row, 1, QTableWidgetItem(item.item_type))
            self.table.setItem(row, 2, QTableWidgetItem(format_bytes(item.size)))

            bytes_item = QTableWidgetItem()
            bytes_item.setData(0, item.size)
            self.table.setItem(row, 3, bytes_item)

            self.table.setItem(row, 4, QTableWidgetItem(item.path))
        self.table.resizeColumnsToContents()
        self.table.setSortingEnabled(True)

    def export_csv(self) -> None:
        if not self.items:
            QMessageBox.warning(self, "Exportar", "No hay resultados para exportar.")
            return

        file_path, _ = QFileDialog.getSaveFileName(self, "Guardar CSV", "analisis_disco.csv", "CSV (*.csv)")
        if not file_path:
            return

        with open(file_path, "w", newline="", encoding="utf-8-sig") as csv_file:
            writer = csv.writer(csv_file, delimiter=";")
            writer.writerow(["Nombre", "Tipo", "Tamaño", "Bytes", "Ruta"])
            for item in self.items:
                writer.writerow([item.name, item.item_type, format_bytes(item.size), item.size, item.path])

        QMessageBox.information(self, "Exportado", "CSV generado correctamente.")
