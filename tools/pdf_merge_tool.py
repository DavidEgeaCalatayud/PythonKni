from __future__ import annotations

import os
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTabWidget,
    QPushButton,
    QListWidget,
    QFileDialog,
    QMessageBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
)

try:
    # PyPDF2 actual
    from PyPDF2 import PdfReader, PdfWriter, PdfMerger
except ImportError:
    PdfReader = PdfWriter = PdfMerger = None


class Tool(QMainWindow):
    name = "PDF Toolkit"

    def __init__(self):
        super().__init__()
        self.setWindowTitle(self.name)
        self.setGeometry(150, 150, 900, 600)

        self._init_ui()

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs)

        # Tabs
        self.tabs.addTab(self._tab_extract_text(), "Extraer texto")
        self.tabs.addTab(self._tab_split(), "Dividir")
        self.tabs.addTab(self._tab_extract_pages(), "Extraer páginas")
        self.tabs.addTab(self._tab_reorder(), "Reordenar")
        self.tabs.addTab(self._tab_merge(), "Combinar")

        # Log
        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(160)
        root.addWidget(QLabel("Log"))
        root.addWidget(self.log_box)

    # ---------- Helpers ----------
    def log(self, msg: str):
        self.log_box.appendPlainText(msg)

    def require_pypdf(self) -> bool:
        if PdfReader is None or PdfWriter is None:
            QMessageBox.critical(
                self,
                "Falta dependencia",
                "No se encuentra PyPDF2.\nInstale con:\npython -m pip install PyPDF2",
            )
            return False
        return True

    def pick_pdf(self, title="Seleccionar PDF"):
        path, _ = QFileDialog.getOpenFileName(self, title, "", "PDF Files (*.pdf)")
        return path or None

    # ---------- TAB: DIVIDIR ----------
    def _tab_split(self):
        w = QWidget()
        layout = QVBoxLayout(w)

        self.split_path = QLineEdit()
        self.split_path.setReadOnly(True)

        btn_pick = QPushButton("Seleccionar PDF...")
        btn_pick.clicked.connect(self._split_pick)

        row = QHBoxLayout()
        row.addWidget(QLabel("Archivo:"))
        row.addWidget(self.split_path)
        row.addWidget(btn_pick)
        layout.addLayout(row)

        # Opciones: dividir por páginas individuales o por rango
        row2 = QHBoxLayout()
        self.split_mode = QLineEdit("individual")  # "individual" o "rango"
        self.split_mode.setReadOnly(True)
        btn_ind = QPushButton("Modo: 1 PDF por página")
        btn_rng = QPushButton("Modo: rangos (ej: 1-3,5,8-10)")
        btn_ind.clicked.connect(lambda: self._set_split_mode("individual"))
        btn_rng.clicked.connect(lambda: self._set_split_mode("rangos"))

        row2.addWidget(btn_ind)
        row2.addWidget(btn_rng)
        layout.addLayout(row2)

        self.split_ranges = QLineEdit()
        self.split_ranges.setPlaceholderText("Ej: 1-3,5,8-10 (solo en modo rangos)")
        layout.addWidget(self.split_ranges)

        btn_run = QPushButton("Dividir y guardar...")
        btn_run.clicked.connect(self._split_run)
        layout.addWidget(btn_run)

        layout.addStretch(1)
        return w

    def _set_split_mode(self, mode):
        self.split_mode.setText(mode)
        self.log(f"[Dividir] Modo cambiado a: {mode}")

    def _split_pick(self):
        p = self.pick_pdf("Seleccionar PDF a dividir")
        if p:
            self.split_path.setText(p)
            self.log(f"[Dividir] PDF seleccionado: {p}")

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

        try:
            reader = PdfReader(src)
            n = len(reader.pages)
            base = os.path.splitext(os.path.basename(src))[0]

            mode = self.split_mode.text().strip()

            if mode == "individual":
                for i in range(n):
                    writer = PdfWriter()
                    writer.add_page(reader.pages[i])
                    out_path = os.path.join(out_dir, f"{base}_p{i + 1}.pdf")
                    with open(out_path, "wb") as f:
                        writer.write(f)
                self.log(f"[Dividir] Generados {n} PDFs en: {out_dir}")
                QMessageBox.information(self, "OK", f"Generados {n} PDFs.")
                return

            # modo rangos
            spec = self.split_ranges.text().strip()
            if not spec:
                QMessageBox.warning(self, "Aviso", "Indique rangos. Ej: 1-3,5,8-10")
                return

            ranges = parse_page_spec(
                spec, max_pages=n
            )  # devuelve lista de listas de índices 0-based
            for idx, group in enumerate(ranges, start=1):
                writer = PdfWriter()
                for p_i in group:
                    writer.add_page(reader.pages[p_i])
                out_path = os.path.join(out_dir, f"{base}_part{idx}.pdf")
                with open(out_path, "wb") as f:
                    writer.write(f)

            self.log(f"[Dividir] Generadas {len(ranges)} partes en: {out_dir}")
            QMessageBox.information(self, "OK", f"Generadas {len(ranges)} partes.")

        except Exception as e:
            self.log(f"[Dividir][ERROR] {e}")
            QMessageBox.critical(self, "Error", str(e))

    # ---------- TAB: EXTRAER TEXTO (MEJORADA) ----------
    def _tab_extract_text(self):
        w = QWidget()
        layout = QVBoxLayout(w)

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

        # Opciones de salida
        out_row = QHBoxLayout()

        self.chk_one_file_per_page = QPushButton("Un archivo por página: NO")
        self.chk_one_file_per_page.setCheckable(True)
        self.chk_one_file_per_page.toggled.connect(
            lambda v: self.chk_one_file_per_page.setText(
                f"Un archivo por página: {'SÍ' if v else 'NO'}"
            )
        )
        out_row.addWidget(self.chk_one_file_per_page)

        self.chk_include_headers = QPushButton("Incluir cabecera por página: SÍ")
        self.chk_include_headers.setCheckable(True)
        self.chk_include_headers.setChecked(True)
        self.chk_include_headers.toggled.connect(
            lambda v: self.chk_include_headers.setText(
                f"Incluir cabecera por página: {'SÍ' if v else 'NO'}"
            )
        )
        out_row.addWidget(self.chk_include_headers)

        layout.addLayout(out_row)

        # Detección de escaneado
        scan_row = QHBoxLayout()
        scan_row.addWidget(QLabel("Umbral 'probablemente escaneado' (% páginas vacías):"))
        self.scan_threshold = QSpinBox()
        self.scan_threshold.setRange(10, 100)
        self.scan_threshold.setValue(60)  # default razonable
        scan_row.addWidget(self.scan_threshold)
        scan_row.addWidget(QLabel("%"))
        layout.addLayout(scan_row)

        # OCR opcional
        ocr_row = QHBoxLayout()

        self.chk_ocr = QPushButton("OCR: NO")
        self.chk_ocr.setCheckable(True)
        self.chk_ocr.toggled.connect(lambda v: self.chk_ocr.setText(f"OCR: {'SÍ' if v else 'NO'}"))
        ocr_row.addWidget(self.chk_ocr)

        self.chk_ocr_only_empty = QPushButton("OCR solo en páginas vacías: SÍ")
        self.chk_ocr_only_empty.setCheckable(True)
        self.chk_ocr_only_empty.setChecked(True)
        self.chk_ocr_only_empty.toggled.connect(
            lambda v: self.chk_ocr_only_empty.setText(
                f"OCR solo en páginas vacías: {'SÍ' if v else 'NO'}"
            )
        )
        ocr_row.addWidget(self.chk_ocr_only_empty)

        layout.addLayout(ocr_row)

        # Botones
        btn_preview = QPushButton("Vista previa (primeras 2 páginas)")
        btn_preview.clicked.connect(self._text_preview)
        layout.addWidget(btn_preview)

        btn_run = QPushButton("Extraer y guardar como Markdown (.md)...")
        btn_run.clicked.connect(self._text_run_md)
        layout.addWidget(btn_run)

        layout.addStretch(1)
        return w

    def _text_pick(self):
        if not self.require_pypdf():
            return
        p = self.pick_pdf("Seleccionar PDF para extraer texto")
        if p:
            self.text_src.setText(p)
            self.log(f"[Texto] PDF seleccionado: {p}")

    def _get_pages_for_text(self, reader):
        n = len(reader.pages)
        spec = self.text_pages_spec.text().strip()
        if not spec:
            return list(range(n))  # todas
        return parse_page_list(spec, max_pages=n)

    def _text_preview(self):
        if not self.require_pypdf():
            return
        src = self.text_src.text().strip()
        if not src or not os.path.exists(src):
            QMessageBox.warning(self, "Aviso", "Seleccione un PDF válido.")
            return

        try:
            reader = PdfReader(src)
            n = len(reader.pages)
            take = min(2, n)
            sample = []
            for i in range(take):
                t = reader.pages[i].extract_text() or ""
                t = t.strip()
                sample.append(f"--- Página {i + 1} ---\n{t}\n")

            preview_text = "\n".join(sample).strip()
            if not preview_text:
                preview_text = "(No se ha detectado texto. Puede ser un PDF escaneado o protegido.)"

            QMessageBox.information(self, "Vista previa", preview_text[:2500])
            self.log(f"[Texto] Vista previa generada (1-{take}).")

        except Exception as e:
            self.log(f"[Texto][ERROR][Preview] {e}")
            QMessageBox.critical(self, "Error", str(e))

    # --- OCR helpers ---
    def _ocr_available(self):
        """
        Devuelve (ok:bool, msg:str, deps:dict) sin romper si faltan dependencias.
        """
        deps = {}
        try:
            import pytesseract  # noqa

            deps["pytesseract"] = True
        except Exception:
            deps["pytesseract"] = False

        try:
            from pdf2image import convert_from_path  # noqa

            deps["pdf2image"] = True
        except Exception:
            deps["pdf2image"] = False

        if not deps["pytesseract"] or not deps["pdf2image"]:
            return (
                False,
                "Faltan librerías Python para OCR: instale pytesseract, pdf2image, pillow.",
                deps,
            )

        # Verificar que Tesseract (ejecutable) está accesible
        try:
            import pytesseract

            _ = pytesseract.get_tesseract_version()
            deps["tesseract_bin"] = True
        except Exception:
            deps["tesseract_bin"] = False
            return False, "Tesseract no está accesible. Instálelo y/o añádalo al PATH.", deps

        return True, "OCR disponible.", deps

    def _ocr_page(self, pdf_path: str, page_number_1based: int):
        """
        OCR de una página concreta (1-based). Requiere poppler para pdf2image.
        """
        import pytesseract
        from pdf2image import convert_from_path

        # Renderiza SOLO esa página
        images = convert_from_path(
            pdf_path, first_page=page_number_1based, last_page=page_number_1based
        )
        if not images:
            return ""

        img = images[0]
        text = pytesseract.image_to_string(img) or ""
        return text.strip()

    def _text_run_md(self):
        if not self.require_pypdf():
            return
        src = self.text_src.text().strip()
        if not src or not os.path.exists(src):
            QMessageBox.warning(self, "Aviso", "Seleccione un PDF válido.")
            return

        # salida: carpeta o archivo según modo
        one_per_page = self.chk_one_file_per_page.isChecked()

        if one_per_page:
            out_dir = QFileDialog.getExistingDirectory(self, "Seleccione carpeta de salida")
            if not out_dir:
                return
        else:
            save_path, _ = QFileDialog.getSaveFileName(
                self, "Guardar Markdown", "texto_extraido.md", "Markdown Files (*.md)"
            )
            if not save_path:
                return
            if not save_path.lower().endswith(".md"):
                save_path += ".md"

        # OCR: comprobar disponibilidad si está activo
        use_ocr = self.chk_ocr.isChecked()
        ocr_only_empty = self.chk_ocr_only_empty.isChecked()

        if use_ocr:
            ok, msg, deps = self._ocr_available()
            if not ok:
                self.log(f"[Texto][OCR] No disponible: {msg}")
                QMessageBox.warning(self, "OCR no disponible", f"{msg}\n\nSe continuará sin OCR.")
                use_ocr = False
            else:
                self.log(f"[Texto][OCR] {msg}")

        try:
            reader = PdfReader(src)

            # PDFs cifrados
            if getattr(reader, "is_encrypted", False):
                try:
                    reader.decrypt("")
                except Exception:
                    raise ValueError(
                        "El PDF parece estar cifrado y no se pudo descifrar sin contraseña."
                    )

            pages = self._get_pages_for_text(reader)
            total = len(pages)

            self.log(f"[Texto] Páginas seleccionadas: {', '.join(str(p + 1) for p in pages)}")
            self.log(
                f"[Texto] Exportación: {'1 archivo por página' if one_per_page else 'archivo único'} (Markdown)"
            )

            empty_pages = 0
            extracted = []  # para archivo único: lista de bloques md

            include_headers = self.chk_include_headers.isChecked()

            base = os.path.splitext(os.path.basename(src))[0]

            for idx0 in pages:
                page_num = idx0 + 1
                page = reader.pages[idx0]

                # Extracción normal
                text = (page.extract_text() or "").strip()

                # Si está vacío, contamos
                is_empty = len(text) == 0
                if is_empty:
                    empty_pages += 1

                # OCR opcional
                if use_ocr:
                    if (not ocr_only_empty) or is_empty:
                        try:
                            self.log(f"[Texto][OCR] Procesando página {page_num}...")
                            ocr_text = self._ocr_page(src, page_num)
                            if ocr_text:
                                text = ocr_text
                                is_empty = False
                        except Exception as e:
                            # Muy habitual: falta Poppler en Windows
                            self.log(f"[Texto][OCR][ERROR] Página {page_num}: {e}")
                            # No abortamos todo, seguimos
                            pass

                # Construir Markdown
                md_block = []
                if include_headers:
                    md_block.append(f"## Página {page_num}\n")
                md_block.append(text if text else "")
                md_content = "\n".join(md_block).strip() + "\n"

                if one_per_page:
                    out_path = os.path.join(out_dir, f"{base}_p{page_num}.md")
                    with open(out_path, "w", encoding="utf-8") as f:
                        f.write(md_content)
                else:
                    extracted.append(md_content)

            # Guardar archivo único si aplica
            if not one_per_page:
                final_md = "\n\n".join(extracted).strip() + "\n"
                with open(save_path, "w", encoding="utf-8") as f:
                    f.write(final_md)

            # Detección “probablemente escaneado”
            empty_ratio = (empty_pages / total) * 100 if total else 0
            threshold = self.scan_threshold.value()

            if empty_ratio >= threshold:
                warn_msg = (
                    f"Se detectó un {empty_ratio:.0f}% de páginas sin texto.\n"
                    "Este PDF probablemente es escaneado (imagen).\n"
                    "Active OCR (y asegúrese de tener Tesseract/Poppler) para mejores resultados."
                )
                self.log(
                    f"[Texto][Aviso] Probablemente escaneado: {empty_ratio:.0f}% páginas vacías."
                )
                QMessageBox.warning(self, "Aviso", warn_msg)
            else:
                self.log(f"[Texto] Páginas vacías: {empty_pages}/{total} ({empty_ratio:.0f}%).")

            QMessageBox.information(self, "OK", "Extracción finalizada.")

        except Exception as e:
            self.log(f"[Texto][ERROR] {e}")
            QMessageBox.critical(self, "Error", str(e))

    # ---------- TAB: EXTRAER PÁGINAS ----------
    def _tab_extract_pages(self):
        w = QWidget()
        layout = QVBoxLayout(w)

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
        return w

    def _extract_pick(self):
        p = self.pick_pdf("Seleccionar PDF para extraer páginas")
        if p:
            self.extract_path.setText(p)
            self.log(f"[Extraer] PDF seleccionado: {p}")

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
            self, "Guardar PDF extraído", "extraido.pdf", "PDF Files (*.pdf)"
        )
        if not save_path:
            return
        if not save_path.lower().endswith(".pdf"):
            save_path += ".pdf"

        try:
            reader = PdfReader(src)
            n = len(reader.pages)
            pages = parse_page_list(spec, max_pages=n)  # lista 0-based

            writer = PdfWriter()
            for p_i in pages:
                writer.add_page(reader.pages[p_i])

            with open(save_path, "wb") as f:
                writer.write(f)

            self.log(f"[Extraer] Guardado: {save_path} (páginas: {len(pages)})")
            QMessageBox.information(self, "OK", "PDF extraído correctamente.")

        except Exception as e:
            self.log(f"[Extraer][ERROR] {e}")
            QMessageBox.critical(self, "Error", str(e))

    # ---------- TAB: REORDENAR ----------
    def _tab_reorder(self):
        w = QWidget()
        layout = QVBoxLayout(w)

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
        self.page_list.setDragDropMode(QListWidget.InternalMove)  # Drag & drop
        layout.addWidget(QLabel("Arrastre para reordenar páginas:"))
        layout.addWidget(self.page_list)

        btn_save = QPushButton("Guardar PDF reordenado como...")
        btn_save.clicked.connect(self._reorder_save)
        layout.addWidget(btn_save)

        layout.addStretch(1)
        return w

    def _reorder_pick(self):
        if not self.require_pypdf():
            return
        p = self.pick_pdf("Seleccionar PDF para reordenar")
        if not p:
            return
        self.reorder_src.setText(p)
        self.page_list.clear()

        try:
            reader = PdfReader(p)
            n = len(reader.pages)
            for i in range(n):
                self.page_list.addItem(f"Página {i + 1}")
            self.log(f"[Reordenar] Cargado {p} con {n} páginas.")
        except Exception as e:
            self.log(f"[Reordenar][ERROR] {e}")
            QMessageBox.critical(self, "Error", str(e))

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
            self, "Guardar PDF reordenado", "reordenado.pdf", "PDF Files (*.pdf)"
        )
        if not save_path:
            return
        if not save_path.lower().endswith(".pdf"):
            save_path += ".pdf"

        try:
            reader = PdfReader(src)
            writer = PdfWriter()

            # El orden está definido por el QListWidget:
            for i in range(self.page_list.count()):
                text = self.page_list.item(i).text()
                # "Página X" -> X
                page_num = int(text.split()[-1])
                writer.add_page(reader.pages[page_num - 1])

            with open(save_path, "wb") as f:
                writer.write(f)

            self.log(f"[Reordenar] Guardado: {save_path}")
            QMessageBox.information(self, "OK", "PDF reordenado correctamente.")
        except Exception as e:
            self.log(f"[Reordenar][ERROR] {e}")
            QMessageBox.critical(self, "Error", str(e))

    # ---------- TAB: COMBINAR ----------
    def _tab_merge(self):
        w = QWidget()
        layout = QVBoxLayout(w)

        self.merge_list = QListWidget()
        layout.addWidget(QLabel("Orden de combinación:"))
        layout.addWidget(self.merge_list)

        btn_row = QHBoxLayout()
        btn_add = QPushButton("Añadir PDFs...")
        btn_add.clicked.connect(self._merge_add)
        btn_up = QPushButton("Subir")
        btn_up.clicked.connect(lambda: self._move_item(self.merge_list, -1))
        btn_down = QPushButton("Bajar")
        btn_down.clicked.connect(lambda: self._move_item(self.merge_list, +1))
        btn_rm = QPushButton("Quitar")
        btn_rm.clicked.connect(self._merge_remove)
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_up)
        btn_row.addWidget(btn_down)
        btn_row.addWidget(btn_rm)
        layout.addLayout(btn_row)

        btn_run = QPushButton("Crear PDF combinado...")
        btn_run.clicked.connect(self._merge_run)
        layout.addWidget(btn_run)

        self._merge_paths = []
        layout.addStretch(1)
        return w

    def _merge_add(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Seleccionar PDFs", "", "PDF Files (*.pdf)")
        if not files:
            return
        for f in files:
            if f not in self._merge_paths:
                self._merge_paths.append(f)
        self._merge_refresh()
        self.log(f"[Combinar] Añadidos: {len(files)}")

    def _merge_refresh(self):
        self.merge_list.clear()
        for i, p in enumerate(self._merge_paths, start=1):
            self.merge_list.addItem(f"{i}. {os.path.basename(p)}")

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
            self, "Guardar PDF combinado", "combinado.pdf", "PDF Files (*.pdf)"
        )
        if not save_path:
            return
        if not save_path.lower().endswith(".pdf"):
            save_path += ".pdf"

        merger = PdfMerger()
        try:
            for p in self._merge_paths:
                merger.append(p)
            merger.write(save_path)
            self.log(f"[Combinar] Guardado: {save_path}")
            QMessageBox.information(self, "OK", "PDF combinado correctamente.")
        except Exception as e:
            self.log(f"[Combinar][ERROR] {e}")
            QMessageBox.critical(self, "Error", str(e))
        finally:
            try:
                merger.close()
            except Exception:
                pass

    def _move_item(self, lw: QListWidget, delta: int):
        row = lw.currentRow()
        if row < 0:
            return
        new_row = row + delta
        if new_row < 0 or new_row >= lw.count():
            return

        # mover en UI
        item = lw.takeItem(row)
        lw.insertItem(new_row, item)
        lw.setCurrentRow(new_row)

        # sincronizar lista de paths si es el merge_list
        if lw is self.merge_list:
            self._merge_paths[row], self._merge_paths[new_row] = (
                self._merge_paths[new_row],
                self._merge_paths[row],
            )


# ---------- Parsers ----------
def parse_page_list(spec: str, max_pages: int) -> list[int]:
    """
    spec: "1,3,5-7"
    devuelve lista de índices 0-based, únicos y ordenados según aparición en spec.
    """
    result = []
    seen = set()

    parts = [p.strip() for p in spec.split(",") if p.strip()]
    for part in parts:
        if "-" in part:
            a, b = part.split("-", 1)
            start = int(a.strip())
            end = int(b.strip())
            if start > end:
                start, end = end, start
            for p in range(start, end + 1):
                idx = p - 1
                if 0 <= idx < max_pages and idx not in seen:
                    result.append(idx)
                    seen.add(idx)
        else:
            p = int(part)
            idx = p - 1
            if 0 <= idx < max_pages and idx not in seen:
                result.append(idx)
                seen.add(idx)

    if not result:
        raise ValueError("No se han podido parsear páginas válidas.")
    return result


def parse_page_spec(spec: str, max_pages: int) -> list[list[int]]:
    """
    spec para dividir en grupos: "1-3,5,8-10"
    Devuelve lista de grupos (cada grupo es lista de páginas 0-based).
    Aquí interpretamos cada coma como “un grupo”.
    """
    groups = []
    parts = [p.strip() for p in spec.split(",") if p.strip()]
    for part in parts:
        group = parse_page_list(part, max_pages=max_pages)
        groups.append(group)
    if not groups:
        raise ValueError("No se han podido parsear rangos válidos.")
    return groups
