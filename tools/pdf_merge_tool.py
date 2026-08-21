from __future__ import annotations

from tools.base_tool import BaseTool

import os

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from tools.pdf_tasks import (
    extract_pages_task,
    extract_text_task,
    load_reorder_task,
    merge_pdfs_task,
    parse_page_list,
    parse_page_spec,
    preview_text_task,
    reorder_pdf_task,
    require_pypdf_available,
    split_pdf_task,
)
from tools.worker import Worker


class Tool(BaseTool):
    name = "PDF Toolkit"
    description = "Divide, combina, reordena y extrae contenido de PDF."
    category = "PDF"

    def setup_ui(self):
        self.setWindowTitle(self.name)
        self.setGeometry(150, 150, 900, 600)
        self._worker = None
        self._close_when_worker_finishes = False
        self._merge_paths = []
        self._init_ui()

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._tab_extract_text(), "Extraer texto")
        self.tabs.addTab(self._tab_split(), "Dividir")
        self.tabs.addTab(self._tab_extract_pages(), "Extraer páginas")
        self.tabs.addTab(self._tab_reorder(), "Reordenar")
        self.tabs.addTab(self._tab_merge(), "Combinar")
        root.addWidget(self.tabs)

        task_row = QHBoxLayout()
        self.task_status = QLabel("")
        task_row.addWidget(self.task_status)
        task_row.addStretch()
        self.btn_cancel_task = QPushButton("Cancelar tarea")
        self.btn_cancel_task.setEnabled(False)
        self.btn_cancel_task.clicked.connect(self._cancel_task)
        task_row.addWidget(self.btn_cancel_task)
        root.addLayout(task_row)

        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(160)
        root.addWidget(QLabel("Log"))
        root.addWidget(self.log_box)

    def log(self, msg: str):
        self.log_box.appendPlainText(msg)

    def require_pypdf(self) -> bool:
        if require_pypdf_available():
            return True
        QMessageBox.critical(
            self,
            "Falta dependencia",
            "No se encuentra PyPDF2.\nInstale con:\npython -m pip install PyPDF2",
        )
        return False

    def pick_pdf(self, title="Seleccionar PDF"):
        path, _ = QFileDialog.getOpenFileName(self, title, "", "PDF Files (*.pdf)")
        return path or None

    def _start_task(self, label, task, result_handler, *args):
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(
                self,
                "Tarea en curso",
                "Ya hay una operación PDF en curso. Cancélela o espere a que finalice.",
            )
            return False

        worker = Worker(task, *args, parent=self)
        self._worker = worker
        self.tabs.setEnabled(False)
        self.btn_cancel_task.setEnabled(True)
        self.task_status.setText(label)
        worker.progress.connect(self._task_progress)
        worker.result.connect(result_handler)
        worker.error.connect(lambda error: self._task_error(label, error))
        worker.cancelled.connect(self._task_cancelled)
        worker.finished.connect(lambda: self._task_finished(worker))
        worker.start()
        return True

    def _task_progress(self, progress):
        if isinstance(progress, dict):
            message = str(progress.get("message", "Procesando..."))
            percent = progress.get("percent")
            if percent is not None and "%" not in message:
                message = f"{message} ({percent}%)"
            self.task_status.setText(message)
        else:
            self.task_status.setText(str(progress))

    def _task_error(self, label, error):
        self.log(f"[{label}][ERROR] {error}")
        QMessageBox.critical(self, "Error", str(error))

    def _task_cancelled(self):
        self.log("[Tarea] Operación cancelada por el usuario.")
        self.task_status.setText("Operación cancelada")

    def _cancel_task(self):
        worker = self._worker
        if worker is not None and worker.isRunning():
            worker.cancel()
            self.btn_cancel_task.setEnabled(False)
            self.task_status.setText("Cancelando...")

    def _task_finished(self, worker):
        if self._worker is worker:
            self._worker = None
            self.tabs.setEnabled(True)
            self.btn_cancel_task.setEnabled(False)
            if self.task_status.text() != "Operación cancelada":
                self.task_status.setText("")
        worker.deleteLater()
        if self._close_when_worker_finishes:
            self._close_when_worker_finishes = False
            QTimer.singleShot(0, self.close)

    def closeEvent(self, event):
        worker = self._worker
        if worker is not None and worker.isRunning():
            worker.cancel()
            self._close_when_worker_finishes = True
            self.task_status.setText("Cancelando antes de cerrar...")
            event.ignore()
            return
        super().closeEvent(event)

    # ---------- TAB: DIVIDIR ----------
    def _tab_split(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.split_path = QLineEdit()
        self.split_path.setReadOnly(True)
        btn_pick = QPushButton("Seleccionar PDF...")
        btn_pick.clicked.connect(self._split_pick)
        row = QHBoxLayout()
        row.addWidget(QLabel("Archivo:"))
        row.addWidget(self.split_path)
        row.addWidget(btn_pick)
        layout.addLayout(row)

        self.split_mode = QLineEdit("individual")
        self.split_mode.setReadOnly(True)
        mode_row = QHBoxLayout()
        btn_individual = QPushButton("Modo: 1 PDF por página")
        btn_individual.clicked.connect(lambda: self._set_split_mode("individual"))
        btn_ranges = QPushButton("Modo: rangos (ej: 1-3,5,8-10)")
        btn_ranges.clicked.connect(lambda: self._set_split_mode("rangos"))
        mode_row.addWidget(btn_individual)
        mode_row.addWidget(btn_ranges)
        layout.addLayout(mode_row)

        self.split_ranges = QLineEdit()
        self.split_ranges.setPlaceholderText("Ej: 1-3,5,8-10 (solo en modo rangos)")
        layout.addWidget(self.split_ranges)

        btn_run = QPushButton("Dividir y guardar...")
        btn_run.clicked.connect(self._split_run)
        layout.addWidget(btn_run)
        layout.addStretch(1)
        return widget

    def _set_split_mode(self, mode):
        self.split_mode.setText(mode)
        self.log(f"[Dividir] Modo cambiado a: {mode}")

    def _split_pick(self):
        path = self.pick_pdf("Seleccionar PDF a dividir")
        if path:
            self.split_path.setText(path)
            self.log(f"[Dividir] PDF seleccionado: {path}")

    def _split_run(self):
        if not self.require_pypdf():
            return
        src = self.split_path.text().strip()
        if not src or not os.path.exists(src):
            QMessageBox.warning(self, "Aviso", "Seleccione un PDF válido.")
            return
        out_dir = QFileDialog.getExistingDirectory(self, "Seleccione carpeta de salida")
        if not out_dir:
            return
        self._start_task(
            "Dividiendo PDF...",
            split_pdf_task,
            self._split_done,
            src,
            out_dir,
            self.split_mode.text().strip(),
            self.split_ranges.text().strip(),
        )

    def _split_done(self, result):
        count = len(result["outputs"])
        self.log(f"[Dividir] Generados {count} PDFs en: {result['out_dir']}")
        QMessageBox.information(self, "OK", f"Generados {count} PDFs.")

    # ---------- TAB: EXTRAER TEXTO ----------
    def _tab_extract_text(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.text_src = QLineEdit()
        self.text_src.setReadOnly(True)
        btn_pick = QPushButton("Seleccionar PDF...")
        btn_pick.clicked.connect(self._text_pick)
        row = QHBoxLayout()
        row.addWidget(QLabel("Archivo:"))
        row.addWidget(self.text_src)
        row.addWidget(btn_pick)
        layout.addLayout(row)

        self.text_pages_spec = QLineEdit()
        self.text_pages_spec.setPlaceholderText("Páginas (opcional): ej 1,3,5-7 | vacío = todas")
        layout.addWidget(self.text_pages_spec)

        output_row = QHBoxLayout()
        self.chk_one_file_per_page = QPushButton("Un archivo por página: NO")
        self.chk_one_file_per_page.setCheckable(True)
        self.chk_one_file_per_page.toggled.connect(
            lambda value: self.chk_one_file_per_page.setText(
                f"Un archivo por página: {'SÍ' if value else 'NO'}"
            )
        )
        output_row.addWidget(self.chk_one_file_per_page)

        self.chk_include_headers = QPushButton("Incluir cabecera por página: SÍ")
        self.chk_include_headers.setCheckable(True)
        self.chk_include_headers.setChecked(True)
        self.chk_include_headers.toggled.connect(
            lambda value: self.chk_include_headers.setText(
                f"Incluir cabecera por página: {'SÍ' if value else 'NO'}"
            )
        )
        output_row.addWidget(self.chk_include_headers)
        layout.addLayout(output_row)

        scan_row = QHBoxLayout()
        scan_row.addWidget(QLabel("Umbral 'probablemente escaneado' (% páginas vacías):"))
        self.scan_threshold = QSpinBox()
        self.scan_threshold.setRange(10, 100)
        self.scan_threshold.setValue(60)
        scan_row.addWidget(self.scan_threshold)
        scan_row.addWidget(QLabel("%"))
        layout.addLayout(scan_row)

        ocr_row = QHBoxLayout()
        self.chk_ocr = QPushButton("OCR: NO")
        self.chk_ocr.setCheckable(True)
        self.chk_ocr.toggled.connect(
            lambda value: self.chk_ocr.setText(f"OCR: {'SÍ' if value else 'NO'}")
        )
        ocr_row.addWidget(self.chk_ocr)

        self.chk_ocr_only_empty = QPushButton("OCR solo en páginas vacías: SÍ")
        self.chk_ocr_only_empty.setCheckable(True)
        self.chk_ocr_only_empty.setChecked(True)
        self.chk_ocr_only_empty.toggled.connect(
            lambda value: self.chk_ocr_only_empty.setText(
                f"OCR solo en páginas vacías: {'SÍ' if value else 'NO'}"
            )
        )
        ocr_row.addWidget(self.chk_ocr_only_empty)
        layout.addLayout(ocr_row)

        btn_preview = QPushButton("Vista previa (primeras 2 páginas)")
        btn_preview.clicked.connect(self._text_preview)
        layout.addWidget(btn_preview)

        btn_run = QPushButton("Extraer y guardar como Markdown (.md)...")
        btn_run.clicked.connect(self._text_run_md)
        layout.addWidget(btn_run)
        layout.addStretch(1)
        return widget

    def _text_pick(self):
        if not self.require_pypdf():
            return
        path = self.pick_pdf("Seleccionar PDF para extraer texto")
        if path:
            self.text_src.setText(path)
            self.log(f"[Texto] PDF seleccionado: {path}")

    def _text_preview(self):
        if not self.require_pypdf():
            return
        src = self.text_src.text().strip()
        if not src or not os.path.exists(src):
            QMessageBox.warning(self, "Aviso", "Seleccione un PDF válido.")
            return
        self._start_task(
            "Generando vista previa...",
            preview_text_task,
            self._text_preview_done,
            src,
            2,
        )

    def _text_preview_done(self, result):
        QMessageBox.information(self, "Vista previa", result["preview"][:2500])
        self.log(f"[Texto] Vista previa generada (1-{result['pages']}).")

    def _text_run_md(self):
        if not self.require_pypdf():
            return
        src = self.text_src.text().strip()
        if not src or not os.path.exists(src):
            QMessageBox.warning(self, "Aviso", "Seleccione un PDF válido.")
            return

        one_per_page = self.chk_one_file_per_page.isChecked()
        out_dir = None
        save_path = None
        if one_per_page:
            out_dir = QFileDialog.getExistingDirectory(self, "Seleccione carpeta de salida")
            if not out_dir:
                return
        else:
            save_path, _ = QFileDialog.getSaveFileName(
                self,
                "Guardar Markdown",
                "texto_extraido.md",
                "Markdown Files (*.md)",
            )
            if not save_path:
                return
            if not save_path.lower().endswith(".md"):
                save_path += ".md"

        self._start_task(
            "Extrayendo texto...",
            extract_text_task,
            self._text_extract_done,
            src,
            self.text_pages_spec.text().strip(),
            one_per_page,
            self.chk_include_headers.isChecked(),
            self.chk_ocr.isChecked(),
            self.chk_ocr_only_empty.isChecked(),
            self.scan_threshold.value(),
            out_dir,
            save_path,
        )

    def _text_extract_done(self, result):
        for message in result["logs"]:
            self.log(message)

        if result["ocr_warning"]:
            QMessageBox.warning(
                self,
                "OCR no disponible",
                result["ocr_warning"] + "\n\nLa extracción se ha completado sin OCR.",
            )

        empty_ratio = result["empty_ratio"]
        if empty_ratio >= result["threshold"]:
            message = (
                f"Se detectó un {empty_ratio:.0f}% de páginas sin texto.\n"
                "Este PDF probablemente es escaneado (imagen).\n"
                "Active OCR y asegúrese de tener Tesseract/Poppler para mejores resultados."
            )
            self.log(f"[Texto][Aviso] Probablemente escaneado: {empty_ratio:.0f}% páginas vacías.")
            QMessageBox.warning(self, "Aviso", message)
        else:
            self.log(
                f"[Texto] Páginas vacías: {result['empty_pages']}/{result['total']} "
                f"({empty_ratio:.0f}%)."
            )
        QMessageBox.information(self, "OK", "Extracción finalizada.")

    # ---------- TAB: EXTRAER PÁGINAS ----------
    def _tab_extract_pages(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.extract_path = QLineEdit()
        self.extract_path.setReadOnly(True)
        btn_pick = QPushButton("Seleccionar PDF...")
        btn_pick.clicked.connect(self._extract_pick)
        row = QHBoxLayout()
        row.addWidget(QLabel("Archivo:"))
        row.addWidget(self.extract_path)
        row.addWidget(btn_pick)
        layout.addLayout(row)

        self.extract_spec = QLineEdit()
        self.extract_spec.setPlaceholderText("Páginas a extraer: ej 1,3,5-7")
        layout.addWidget(self.extract_spec)
        btn_run = QPushButton("Extraer y guardar como...")
        btn_run.clicked.connect(self._extract_run)
        layout.addWidget(btn_run)
        layout.addStretch(1)
        return widget

    def _extract_pick(self):
        path = self.pick_pdf("Seleccionar PDF para extraer páginas")
        if path:
            self.extract_path.setText(path)
            self.log(f"[Extraer] PDF seleccionado: {path}")

    def _extract_run(self):
        if not self.require_pypdf():
            return
        src = self.extract_path.text().strip()
        spec = self.extract_spec.text().strip()
        if not src or not os.path.exists(src):
            QMessageBox.warning(self, "Aviso", "Seleccione un PDF válido.")
            return
        if not spec:
            QMessageBox.warning(self, "Aviso", "Indique páginas. Ej: 1,3,5-7")
            return
        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar PDF extraído",
            "extraido.pdf",
            "PDF Files (*.pdf)",
        )
        if not save_path:
            return
        if not save_path.lower().endswith(".pdf"):
            save_path += ".pdf"
        self._start_task(
            "Extrayendo páginas...",
            extract_pages_task,
            self._extract_done,
            src,
            spec,
            save_path,
        )

    def _extract_done(self, result):
        self.log(f"[Extraer] Guardado: {result['save_path']} (páginas: {result['page_count']})")
        QMessageBox.information(self, "OK", "PDF extraído correctamente.")

    # ---------- TAB: REORDENAR ----------
    def _tab_reorder(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.reorder_src = QLineEdit()
        self.reorder_src.setReadOnly(True)
        btn_pick = QPushButton("Seleccionar PDF...")
        btn_pick.clicked.connect(self._reorder_pick)
        row = QHBoxLayout()
        row.addWidget(QLabel("Archivo:"))
        row.addWidget(self.reorder_src)
        row.addWidget(btn_pick)
        layout.addLayout(row)

        self.page_list = QListWidget()
        self.page_list.setDragDropMode(QListWidget.InternalMove)
        layout.addWidget(QLabel("Arrastre para reordenar páginas:"))
        layout.addWidget(self.page_list)
        btn_save = QPushButton("Guardar PDF reordenado como...")
        btn_save.clicked.connect(self._reorder_save)
        layout.addWidget(btn_save)
        layout.addStretch(1)
        return widget

    def _reorder_pick(self):
        if not self.require_pypdf():
            return
        path = self.pick_pdf("Seleccionar PDF para reordenar")
        if not path:
            return
        self.reorder_src.setText(path)
        self.page_list.clear()
        self._start_task(
            "Leyendo páginas...",
            load_reorder_task,
            self._reorder_loaded,
            path,
        )

    def _reorder_loaded(self, result):
        for index in range(result["page_count"]):
            self.page_list.addItem(f"Página {index + 1}")
        self.log(f"[Reordenar] Cargado {result['src']} con {result['page_count']} páginas.")

    def _reorder_save(self):
        if not self.require_pypdf():
            return
        src = self.reorder_src.text().strip()
        if not src or not os.path.exists(src):
            QMessageBox.warning(self, "Aviso", "Seleccione un PDF válido.")
            return
        if self.page_list.count() == 0:
            QMessageBox.warning(self, "Aviso", "No hay páginas cargadas.")
            return
        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar PDF reordenado",
            "reordenado.pdf",
            "PDF Files (*.pdf)",
        )
        if not save_path:
            return
        if not save_path.lower().endswith(".pdf"):
            save_path += ".pdf"

        order = []
        for index in range(self.page_list.count()):
            order.append(int(self.page_list.item(index).text().split()[-1]))
        self._start_task(
            "Guardando PDF reordenado...",
            reorder_pdf_task,
            self._reorder_done,
            src,
            order,
            save_path,
        )

    def _reorder_done(self, result):
        self.log(f"[Reordenar] Guardado: {result['save_path']}")
        QMessageBox.information(self, "OK", "PDF reordenado correctamente.")

    # ---------- TAB: COMBINAR ----------
    def _tab_merge(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.merge_list = QListWidget()
        layout.addWidget(QLabel("Orden de combinación:"))
        layout.addWidget(self.merge_list)

        btn_row = QHBoxLayout()
        btn_add = QPushButton("Añadir PDFs...")
        btn_add.clicked.connect(self._merge_add)
        btn_up = QPushButton("Subir")
        btn_up.clicked.connect(lambda: self._move_item(self.merge_list, -1))
        btn_down = QPushButton("Bajar")
        btn_down.clicked.connect(lambda: self._move_item(self.merge_list, 1))
        btn_remove = QPushButton("Quitar")
        btn_remove.clicked.connect(self._merge_remove)
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_up)
        btn_row.addWidget(btn_down)
        btn_row.addWidget(btn_remove)
        layout.addLayout(btn_row)

        btn_run = QPushButton("Crear PDF combinado...")
        btn_run.clicked.connect(self._merge_run)
        layout.addWidget(btn_run)
        layout.addStretch(1)
        return widget

    def _merge_add(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Seleccionar PDFs",
            "",
            "PDF Files (*.pdf)",
        )
        if not files:
            return
        for path in files:
            if path not in self._merge_paths:
                self._merge_paths.append(path)
        self._merge_refresh()
        self.log(f"[Combinar] Añadidos: {len(files)}")

    def _merge_refresh(self):
        self.merge_list.clear()
        for index, path in enumerate(self._merge_paths, start=1):
            self.merge_list.addItem(f"{index}. {os.path.basename(path)}")

    def _merge_remove(self):
        row = self.merge_list.currentRow()
        if row < 0:
            return
        self._merge_paths.pop(row)
        self._merge_refresh()

    def _merge_run(self):
        if not self.require_pypdf():
            return
        if len(self._merge_paths) < 2:
            QMessageBox.warning(self, "Aviso", "Añada al menos 2 PDFs.")
            return
        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar PDF combinado",
            "combinado.pdf",
            "PDF Files (*.pdf)",
        )
        if not save_path:
            return
        if not save_path.lower().endswith(".pdf"):
            save_path += ".pdf"
        self._start_task(
            "Combinando PDFs...",
            merge_pdfs_task,
            self._merge_done,
            list(self._merge_paths),
            save_path,
        )

    def _merge_done(self, result):
        self.log(f"[Combinar] Guardado: {result['save_path']}")
        QMessageBox.information(self, "OK", "PDF combinado correctamente.")

    def _move_item(self, list_widget: QListWidget, delta: int):
        row = list_widget.currentRow()
        if row < 0:
            return
        new_row = row + delta
        if new_row < 0 or new_row >= list_widget.count():
            return
        item = list_widget.takeItem(row)
        list_widget.insertItem(new_row, item)
        list_widget.setCurrentRow(new_row)
        if list_widget is self.merge_list:
            self._merge_paths[row], self._merge_paths[new_row] = (
                self._merge_paths[new_row],
                self._merge_paths[row],
            )


__all__ = ["Tool", "parse_page_list", "parse_page_spec"]
