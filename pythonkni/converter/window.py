from __future__ import annotations

import os
import sys as _sys
import types as _types

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from tools.base_tool import BaseTool
from tools.ui_feedback import show_error
from tools.worker import Worker

from . import service as _service
from .service import (
    ConversionResult as ConversionResult,
)
from .service import (
    OutputTransaction as OutputTransaction,
)
from .service import (
    _check_worker as _check_worker,
)
from .service import (
    _report as _report,
)
from .service import (
    _single_output_transaction as _single_output_transaction,
)
from .service import (
    batch_conversion_task as batch_conversion_task,
)
from .service import (
    conversion_task as conversion_task,
)
from .service import (
    docx_to_pdf as docx_to_pdf,
)
from .service import (
    docx_to_text as docx_to_text,
)
from .service import (
    images_to_pdf as images_to_pdf,
)
from .service import (
    kml_to_text as kml_to_text,
)
from .service import (
    logger as logger,
)
from .service import (
    pdf_to_images as pdf_to_images,
)
from .service import (
    text_to_docx as text_to_docx,
)
from .service import (
    text_to_kml as text_to_kml,
)
from .service import (
    validate_extension as validate_extension,
)


class Tool(BaseTool):
    name = "Convertidor de Archivos"
    description = "Convierte imágenes, PDF, texto, Word y KML."
    category = "Archivos"

    def setup_ui(self):
        self.setWindowTitle(self.name)
        self.setGeometry(200, 200, 420, 460)
        self._worker = None
        self._close_when_worker_finishes = False

        layout = QVBoxLayout()
        buttons = (
            ("Imágenes → PDF", self.convert_images_to_pdf),
            ("PDF → Imágenes", self.convert_pdf_to_images),
            ("TXT → DOCX", self.convert_text_to_docx),
            ("DOCX → TXT", self.convert_docx_to_text),
            ("DOCX → PDF", self.convert_docx_to_pdf),
            ("TXT → KML (archivos o carpeta)", self.convert_text_to_kml),
            ("KML → TXT (archivos o carpeta)", self.convert_kml_to_text),
        )
        for text, callback in buttons:
            button = QPushButton(text)
            button.clicked.connect(callback)
            layout.addWidget(button)

        task_row = QHBoxLayout()
        self.task_status = QLabel("")
        task_row.addWidget(self.task_status)
        task_row.addStretch()
        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.cancel_conversion)
        task_row.addWidget(self.btn_cancel)
        layout.addLayout(task_row)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    def _start_conversion(self, label, function, args, success_message):
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(self, "Conversión", "Ya hay una conversión en curso.")
            return
        worker = Worker(conversion_task, function, args, parent=self)
        self._start_worker(worker, label, success_message)

    def _start_batch_conversion(self, label, function, jobs, success_message):
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(self, "Conversión", "Ya hay una conversión en curso.")
            return
        worker = Worker(batch_conversion_task, function, jobs, parent=self)
        self._start_worker(worker, label, success_message)

    def _start_worker(self, worker, label, success_message):
        self._worker = worker
        self.task_status.setText(label)
        self.btn_cancel.setEnabled(True)
        worker.progress.connect(self._conversion_progress)
        worker.result.connect(lambda result: self._conversion_done(success_message, result))
        worker.error.connect(self._conversion_error)
        worker.cancelled.connect(self._conversion_cancelled)
        worker.finished.connect(lambda: self._conversion_finished(worker))
        worker.start()

    def _conversion_progress(self, progress):
        if isinstance(progress, dict):
            self.task_status.setText(str(progress.get("message", "Procesando...")))
        else:
            self.task_status.setText(str(progress))

    def _conversion_done(self, success_message, result):
        if not isinstance(result, ConversionResult):
            result = ConversionResult.completed([str(result)])

        if result.success:
            message = (
                success_message(list(result.outputs))
                if callable(success_message)
                else success_message
            )
            if result.warnings:
                message += "\n\nAvisos:\n- " + "\n- ".join(result.warnings)
                QMessageBox.warning(self, "Conversión completada con avisos", message)
            else:
                QMessageBox.information(self, "Conversión completada", message)
            return

        details = []
        if result.failures:
            details.append("Errores:\n- " + "\n- ".join(result.failures))
        if result.warnings:
            details.append("Avisos:\n- " + "\n- ".join(result.warnings))
        show_error(
            self,
            "Conversión fallida",
            "No se pudo completar la conversión. No se publicó ningún resultado incompleto.",
            details="\n\n".join(details) or None,
        )

    def _conversion_error(self, error):
        logger.error("Conversion failed: %s", error)
        if isinstance(error, BaseException):
            show_error(
                self,
                "Conversión fallida",
                "No se pudo completar la conversión.",
                error=error,
            )
        else:
            show_error(
                self,
                "Conversión fallida",
                "No se pudo completar la conversión.",
                details=str(error),
            )

    def _conversion_cancelled(self):
        self.task_status.setText("Conversión cancelada")

    def _conversion_finished(self, worker):
        if self._worker is worker:
            self._worker = None
            self.btn_cancel.setEnabled(False)
            if self.task_status.text() != "Conversión cancelada":
                self.task_status.setText("")
        worker.deleteLater()
        if self._close_when_worker_finishes:
            self._close_when_worker_finishes = False
            QTimer.singleShot(0, self.close)

    def cancel_conversion(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self.btn_cancel.setEnabled(False)
            self.task_status.setText("Cancelando...")

    def closeEvent(self, event):
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._close_when_worker_finishes = True
            self.task_status.setText("Cancelando antes de cerrar...")
            event.ignore()
            return
        super().closeEvent(event)

    def convert_images_to_pdf(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Seleccionar imágenes",
            "",
            "Imágenes (*.png *.jpg *.jpeg *.bmp)",
        )
        if not files:
            return
        save_path, _ = QFileDialog.getSaveFileName(self, "Guardar PDF", "", "PDF (*.pdf)")
        if not save_path:
            return
        self._start_conversion(
            "Creando PDF...",
            images_to_pdf,
            (files, save_path),
            f"PDF creado en:\n{save_path}",
        )

    def convert_pdf_to_images(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Seleccionar PDF", "", "PDF (*.pdf)")
        if not file_path:
            return
        folder = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta de destino")
        if not folder:
            return
        self._start_conversion(
            "Renderizando PDF...",
            pdf_to_images,
            (file_path, folder),
            lambda files: f"Se han guardado {len(files)} imágenes en:\n{folder}",
        )

    def convert_text_to_docx(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Seleccionar TXT", "", "Texto (*.txt)")
        if not file_path:
            return
        save_path, _ = QFileDialog.getSaveFileName(self, "Guardar DOCX", "", "Word (*.docx)")
        if not save_path:
            return
        self._start_conversion(
            "Creando DOCX...",
            text_to_docx,
            (file_path, save_path),
            f"DOCX creado en:\n{save_path}",
        )

    def convert_docx_to_text(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Seleccionar DOCX", "", "Word (*.docx)")
        if not file_path:
            return
        save_path, _ = QFileDialog.getSaveFileName(self, "Guardar TXT", "", "Texto (*.txt)")
        if not save_path:
            return
        self._start_conversion(
            "Extrayendo texto...",
            docx_to_text,
            (file_path, save_path),
            f"TXT creado en:\n{save_path}",
        )

    def convert_docx_to_pdf(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Seleccionar DOCX", "", "Word (*.docx)")
        if not file_path:
            return
        save_path, _ = QFileDialog.getSaveFileName(self, "Guardar PDF", "", "PDF (*.pdf)")
        if not save_path:
            return
        self._start_conversion(
            "Creando PDF...",
            docx_to_pdf,
            (file_path, save_path),
            f"PDF creado en:\n{save_path}",
        )

    def _files_with_extension(self, path, extension):
        try:
            return [
                os.path.join(path, filename)
                for filename in os.listdir(path)
                if filename.lower().endswith(extension)
            ]
        except OSError as error:
            show_error(
                self,
                "Conversión por lotes",
                "No se pudo leer la carpeta seleccionada.",
                error=error,
            )
            return None

    def convert_text_to_kml(self):
        path = QFileDialog.getExistingDirectory(
            self,
            "Seleccionar carpeta con TXT o archivo individual",
        )
        if path:
            txt_files = self._files_with_extension(path, ".txt")
            if txt_files is None:
                return
            if not txt_files:
                QMessageBox.warning(
                    self,
                    "Sin archivos",
                    "No se encontraron archivos .txt en la carpeta seleccionada.",
                )
                return
            output_dir = QFileDialog.getExistingDirectory(
                self,
                "Seleccionar carpeta de destino para KML",
            )
            if not output_dir:
                return
            jobs = []
            for txt_file in txt_files:
                name = os.path.splitext(os.path.basename(txt_file))[0]
                jobs.append((txt_file, os.path.join(output_dir, f"{name}.kml")))
            self._start_batch_conversion(
                "Convirtiendo TXT a KML...",
                text_to_kml,
                jobs,
                lambda outputs: f"Se convirtieron {len(outputs)} archivos a KML.",
            )
            return

        file_path, _ = QFileDialog.getOpenFileName(self, "Seleccionar TXT", "", "Texto (*.txt)")
        if not file_path:
            return
        save_path, _ = QFileDialog.getSaveFileName(self, "Guardar KML", "", "KML (*.kml)")
        if not save_path:
            return
        self._start_conversion(
            "Convirtiendo TXT a KML...",
            text_to_kml,
            (file_path, save_path),
            f"KML creado en:\n{save_path}",
        )

    def convert_kml_to_text(self):
        path = QFileDialog.getExistingDirectory(
            self,
            "Seleccionar carpeta con KML o archivo individual",
        )
        if path:
            kml_files = self._files_with_extension(path, ".kml")
            if kml_files is None:
                return
            if not kml_files:
                QMessageBox.warning(
                    self,
                    "Sin archivos",
                    "No se encontraron archivos .kml en la carpeta seleccionada.",
                )
                return
            output_dir = QFileDialog.getExistingDirectory(
                self,
                "Seleccionar carpeta de destino para TXT",
            )
            if not output_dir:
                return
            jobs = []
            for kml_file in kml_files:
                name = os.path.splitext(os.path.basename(kml_file))[0]
                jobs.append((kml_file, os.path.join(output_dir, f"{name}.txt")))
            self._start_batch_conversion(
                "Convirtiendo KML a TXT...",
                kml_to_text,
                jobs,
                lambda outputs: f"Se convirtieron {len(outputs)} archivos a TXT.",
            )
            return

        file_path, _ = QFileDialog.getOpenFileName(self, "Seleccionar KML", "", "KML (*.kml)")
        if not file_path:
            return
        save_path, _ = QFileDialog.getSaveFileName(self, "Guardar TXT", "", "Texto (*.txt)")
        if not save_path:
            return
        self._start_conversion(
            "Convirtiendo KML a TXT...",
            kml_to_text,
            (file_path, save_path),
            f"TXT creado en:\n{save_path}",
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
