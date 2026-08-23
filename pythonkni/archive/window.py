from __future__ import annotations

import sys as _sys
import types as _types
from pathlib import Path

from PyQt5.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from tools.base_tool import BaseTool
from tools.theme_manager import ThemeManager
from tools.worker import Worker
from tools.zip_7zip_utils import (
    _default_extract_path,
)

from . import service as _service
from .service import (
    _archive_input_size as _archive_input_size,
)
from .service import (
    _CancellableReader as _CancellableReader,
)
from .service import (
    _publish_file as _publish_file,
)
from .service import (
    _report as _report,
)
from .service import (
    _SevenZipFactory as _SevenZipFactory,
)
from .service import (
    _SevenZipWriter as _SevenZipWriter,
)
from .service import (
    _temporary_output as _temporary_output,
)
from .service import (
    create_7z_task as create_7z_task,
)
from .service import (
    create_zip_task as create_zip_task,
)
from .service import (
    extract_7z_task as extract_7z_task,
)
from .service import (
    extract_zip_task as extract_zip_task,
)
from .service import (
    logger as logger,
)


class Tool(BaseTool):
    name = "Gestor de Archivos (ZIP/7Z)"
    description = "Comprime y extrae archivos ZIP y 7Z."
    category = "Archivos"

    def setup_ui(self):
        self.setWindowTitle(self.name)
        self.setGeometry(150, 150, 440, 280)
        self.worker: Worker | None = None
        self._action_buttons: list[QPushButton] = []

        layout = QVBoxLayout()

        actions = (
            ("Extraer ZIP", self.extract_zip_action),
            ("Crear ZIP", self.create_zip_action),
            ("Extraer 7z", self.extract_7z_action),
            ("Crear 7z", self.create_7z_action),
        )
        for text, callback in actions:
            button = QPushButton(text)
            button.clicked.connect(callback)
            self._action_buttons.append(button)
            layout.addWidget(button)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        status_row = QHBoxLayout()
        self.status = QLabel("")
        status_row.addWidget(self.status)
        status_row.addStretch()
        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.cancel_operation)
        status_row.addWidget(self.btn_cancel)
        layout.addLayout(status_row)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        ThemeManager.apply_theme(self)

    def _operation_active(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    def _set_busy(self, busy: bool, label: str = "") -> None:
        for button in self._action_buttons:
            button.setEnabled(not busy)
        self.btn_cancel.setEnabled(busy)
        self.progress.setVisible(busy)
        if busy:
            self.progress.setValue(0)
            self.status.setText(label)

    def _start_task(self, task, args: tuple, label: str, success_message: str) -> bool:
        if self._operation_active():
            QMessageBox.information(self, "Archivo", "Ya hay una operación en curso.")
            return False

        worker = Worker(task, *args, parent=self)
        worker.progress.connect(self._on_progress)
        worker.result.connect(
            lambda _result: QMessageBox.information(self, "Éxito", success_message)
        )
        worker.error.connect(self._on_error)
        worker.cancelled.connect(self._on_cancelled)
        worker.finished.connect(lambda worker=worker: self._on_finished(worker))
        self.worker = worker
        self._set_busy(True, label)
        self.start_managed_worker(worker, cancel=worker.cancel)
        return True

    def _on_progress(self, progress) -> None:
        if isinstance(progress, dict):
            self.status.setText(str(progress.get("message", "Procesando...")))
            percent = progress.get("percent")
            if percent is not None:
                self.progress.setValue(int(percent))
        else:
            self.status.setText(str(progress))

    def _on_error(self, error) -> None:
        logger.warning("Archive operation failed: %s", error)
        self.status.setText("Operación fallida")
        QMessageBox.critical(self, "Error", f"No se pudo completar la operación:\n{error}")

    def _on_cancelled(self) -> None:
        self.status.setText("Operación cancelada")

    def _on_finished(self, worker: Worker) -> None:
        if self.worker is not worker:
            return
        self.worker = None
        for button in self._action_buttons:
            button.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.progress.setVisible(False)

    def cancel_operation(self) -> None:
        worker = self.worker
        if worker is None or not worker.isRunning():
            return
        worker.cancel()
        self.btn_cancel.setEnabled(False)
        self.status.setText("Cancelando...")

    def extract_zip_action(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar archivo ZIP", "", "Zip Files (*.zip)"
        )
        if not file_path:
            return
        destination = _default_extract_path(file_path)
        self._start_task(
            extract_zip_task,
            (file_path, destination),
            "Preparando extracción ZIP...",
            f"Archivos extraídos en:\n{destination}",
        )

    def create_zip_action(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Seleccionar archivos para comprimir")
        if not files:
            return
        save_path, _ = QFileDialog.getSaveFileName(self, "Guardar ZIP", "", "Zip Files (*.zip)")
        if not save_path:
            return
        self._start_task(
            create_zip_task,
            (files, Path(save_path)),
            "Creando ZIP...",
            f"ZIP creado en:\n{save_path}",
        )

    def extract_7z_action(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar archivo 7z", "", "7z Files (*.7z)"
        )
        if not file_path:
            return
        destination = _default_extract_path(file_path)
        self._start_task(
            extract_7z_task,
            (file_path, destination),
            "Preparando extracción 7Z...",
            f"Archivos extraídos en:\n{destination}",
        )

    def create_7z_action(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Seleccionar archivos para comprimir")
        if not files:
            return
        save_path, _ = QFileDialog.getSaveFileName(self, "Guardar 7z", "", "7z Files (*.7z)")
        if not save_path:
            return
        self._start_task(
            create_7z_task,
            (files, Path(save_path)),
            "Creando 7Z...",
            f"7Z creado en:\n{save_path}",
        )


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
