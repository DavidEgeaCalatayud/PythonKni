from __future__ import annotations

import sys as _sys
import types as _types

from PyQt5.QtWidgets import (
    QFileDialog,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from pythonkni.core.tasks import WorkerCancelled
from tools.base_tool import BaseTool
from tools.worker import Worker

from . import service as _service
from .service import (
    DUPLICATES_DIR_NAME as DUPLICATES_DIR_NAME,
)
from .service import (
    HASH_CHUNK_SIZE as HASH_CHUNK_SIZE,
)
from .service import (
    QUICK_SAMPLE_SIZE as QUICK_SAMPLE_SIZE,
)
from .service import (
    RESTORE_MANIFEST_PREFIX as RESTORE_MANIFEST_PREFIX,
)
from .service import (
    DuplicateOperationCancelled as DuplicateOperationCancelled,
)
from .service import (
    _check_cancel as _check_cancel,
)
from .service import (
    _finish_cancelled_manifest as _finish_cancelled_manifest,
)
from .service import (
    _group_readable_files_by_size as _group_readable_files_by_size,
)
from .service import (
    _is_inside as _is_inside,
)
from .service import (
    _iter_scan_files as _iter_scan_files,
)
from .service import (
    _new_manifest_path as _new_manifest_path,
)
from .service import (
    _physical_identity as _physical_identity,
)
from .service import (
    _same_physical_file as _same_physical_file,
)
from .service import (
    _unique_destination as _unique_destination,
)
from .service import (
    _verified_byte_groups as _verified_byte_groups,
)
from .service import (
    _write_manifest_atomic as _write_manifest_atomic,
)
from .service import (
    files_equal as files_equal,
)
from .service import (
    find_duplicates as find_duplicates,
)
from .service import (
    hash_file as hash_file,
)
from .service import (
    logger as logger,
)
from .service import (
    move_duplicates as move_duplicates,
)
from .service import (
    quick_hash_file as quick_hash_file,
)


def _scan_duplicates_task(worker: Worker, folder_path: str):
    try:
        return find_duplicates(folder_path, cancel_event=worker.cancel_event)
    except DuplicateOperationCancelled as error:
        raise WorkerCancelled() from error


def _move_duplicates_task(worker: Worker, duplicates, base_folder: str):
    try:
        return move_duplicates(duplicates, base_folder, cancel_event=worker.cancel_event)
    except DuplicateOperationCancelled as error:
        raise WorkerCancelled() from error


class Tool(BaseTool):
    name = "Buscador de Archivos Duplicados"
    description = "Localiza y gestiona archivos duplicados."
    category = "Archivos"

    def setup_ui(self):
        self.setWindowTitle(self.name)
        self.setGeometry(200, 200, 600, 400)

        self.folder_path = None
        self.duplicates = {}
        self.worker: Worker | None = None
        self._operation_kind: str | None = None

        layout = QVBoxLayout()

        self.result_box = QTextEdit()
        self.result_box.setReadOnly(True)
        layout.addWidget(self.result_box)

        self.btn_select_folder = QPushButton("Seleccionar Carpeta")
        self.btn_select_folder.clicked.connect(self.select_folder)
        layout.addWidget(self.btn_select_folder)

        self.btn_move = QPushButton("Mover duplicados a subcarpeta")
        self.btn_move.setEnabled(False)
        self.btn_move.clicked.connect(self.move_duplicates_action)
        layout.addWidget(self.btn_move)

        self.btn_cancel = QPushButton("Cancelar operación")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.cancel_current_operation)
        layout.addWidget(self.btn_cancel)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    def _operation_active(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    def _set_busy(self, busy: bool) -> None:
        self.btn_select_folder.setEnabled(not busy)
        self.btn_cancel.setEnabled(busy)
        self.btn_move.setEnabled(not busy and bool(self.duplicates))

    def _bind_worker(self, worker: Worker) -> None:
        worker.error.connect(lambda error: self.on_operation_failed(str(error)))
        worker.finished.connect(lambda worker=worker: self._on_operation_thread_finished(worker))
        self.worker = worker
        self._set_busy(True)
        self.start_managed_worker(worker, cancel=worker.cancel)

    def _start_scan(self, folder_path: str) -> bool:
        if self._operation_active():
            return False

        self.folder_path = folder_path
        self.duplicates = {}
        self.result_box.clear()
        self.result_box.setPlainText("Buscando duplicados, por favor espere...")
        self._operation_kind = "scan"

        worker = Worker(_scan_duplicates_task, folder_path)
        worker.result.connect(self.on_duplicates_found)
        worker.cancelled.connect(self.on_scan_cancelled)
        self._bind_worker(worker)
        return True

    def select_folder(self):
        if self._operation_active():
            return
        folder_path = QFileDialog.getExistingDirectory(self, "Seleccionar Carpeta")
        if not folder_path:
            return
        self._start_scan(folder_path)

    def on_duplicates_found(self, duplicates):
        self.duplicates = duplicates

        if not self.duplicates:
            QMessageBox.information(self, "Resultado", "No se encontraron archivos duplicados.")
            self.result_box.clear()
            return

        result_text = "Archivos duplicados encontrados:\n\n"
        for secure_hash, paths in self.duplicates.items():
            result_text += f"SHA-256 {secure_hash}:\n"
            for path in paths:
                result_text += f"   - {path}\n"
            result_text += "\n"

        self.result_box.setPlainText(result_text)

    def on_scan_cancelled(self):
        self.duplicates = {}
        self.result_box.setPlainText("Búsqueda de duplicados cancelada.")

    def _start_move(self) -> bool:
        if self._operation_active() or not self.duplicates or not self.folder_path:
            return False

        self._operation_kind = "move"
        self.result_box.append("\nRevalidando y moviendo duplicados, por favor espere...")
        worker = Worker(_move_duplicates_task, dict(self.duplicates), self.folder_path)
        worker.result.connect(self.on_move_finished)
        worker.cancelled.connect(self.on_move_cancelled)
        self._bind_worker(worker)
        return True

    def move_duplicates_action(self):
        self._start_move()

    def on_move_finished(self, moved_count: int):
        self.duplicates = {}
        QMessageBox.information(
            self,
            "Duplicados movidos",
            f"Se han movido {moved_count} archivos duplicados a la carpeta "
            f"'{DUPLICATES_DIR_NAME}'. Se ha creado un manifiesto JSON de restauración.",
        )
        self.result_box.append(
            f"\nOperación completada: {moved_count} archivo(s) movido(s). "
            "Vuelve a escanear para actualizar los resultados."
        )

    def on_move_cancelled(self):
        self.duplicates = {}
        self.result_box.append(
            "\nMovimiento cancelado. Puede haber archivos ya movidos; el manifiesto de "
            "restauración conserva el estado parcial y se ha marcado como cancelado. "
            "Vuelve a escanear para actualizar los resultados."
        )

    def on_operation_failed(self, message: str):
        self.duplicates = {}
        self.result_box.append(f"\nLa operación falló: {message}")
        QMessageBox.critical(self, "Error", f"No se pudo completar la operación:\n{message}")

    def cancel_current_operation(self):
        worker = self.worker
        if worker is None or not worker.isRunning():
            return
        worker.cancel()
        self.btn_cancel.setEnabled(False)
        self.result_box.append("\nCancelando operación...")

    def _on_operation_thread_finished(self, worker: Worker) -> None:
        if self.worker is not worker:
            return
        self.worker = None
        self._operation_kind = None
        self._set_busy(False)


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
