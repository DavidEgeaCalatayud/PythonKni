from __future__ import annotations

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from PIL import Image
from docx import Document
import os
import logging
import fitz  # PyMuPDF (para PDF → imágenes)
from xml.dom.minidom import Document as XMLDocument

logger = logging.getLogger(__name__)


def validate_extension(file_path: str, allowed_extensions: set[str]) -> bool:
    return os.path.splitext(file_path)[1].lower() in allowed_extensions


# ---------------- IMÁGENES ----------------
def images_to_pdf(image_files, output_file):
    """Convierte una lista de imágenes en un PDF."""
    c = canvas.Canvas(output_file, pagesize=A4)
    width, height = A4

    for img_path in image_files:
        try:
            img = Image.open(img_path)
            img_width, img_height = img.size
            aspect = img_height / img_width
            new_width = width
            new_height = width * aspect
            if new_height > height:
                new_height = height
                new_width = height / aspect
            c.drawImage(img_path, 0, height - new_height, new_width, new_height)
            c.showPage()
        except Exception:
            logger.warning("No se pudo añadir la imagen %s al PDF", img_path, exc_info=True)
    c.save()


def pdf_to_images(pdf_file, output_folder):
    """Convierte un PDF en imágenes (PNG)."""
    doc = fitz.open(pdf_file)
    saved_files = []
    for i, page in enumerate(doc):
        pix = page.get_pixmap()
        output_path = os.path.join(output_folder, f"page_{i + 1}.png")
        pix.save(output_path)
        saved_files.append(output_path)
    return saved_files


# ---------------- TEXTO Y WORD ----------------
def text_to_docx(text_file, output_file):
    """Convierte un archivo TXT en DOCX."""
    doc = Document()
    with open(text_file, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            doc.add_paragraph(line.strip())
    doc.save(output_file)


def docx_to_text(docx_file, output_file):
    """Convierte un archivo DOCX en TXT."""
    doc = Document(docx_file)
    with open(output_file, "w", encoding="utf-8") as f:
        for para in doc.paragraphs:
            f.write(para.text + "\n")


def docx_to_pdf(docx_file, output_file):
    """Convierte un DOCX en PDF (simplificado como texto plano)."""
    doc = Document(docx_file)
    c = canvas.Canvas(output_file, pagesize=A4)
    width, height = A4
    y = height - 50

    for para in doc.paragraphs:
        text = para.text
        c.drawString(50, y, text)
        y -= 15
        if y < 50:
            c.showPage()
            y = height - 50
    c.save()


# ---------------- TXT Y KML ----------------
def text_to_kml(txt_file, output_file):
    """Convierte un archivo TXT (lat,lon,nombre opcional) a KML."""
    doc = XMLDocument()
    kml = doc.createElement("kml")
    kml.setAttribute("xmlns", "http://www.opengis.net/kml/2.2")
    doc.appendChild(kml)

    document = doc.createElement("Document")
    kml.appendChild(document)

    with open(txt_file, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            parts = line.strip().replace("\t", ",").replace(";", ",").split(",")
            if len(parts) >= 2:
                lat, lon = parts[0].strip(), parts[1].strip()
                name = parts[2].strip() if len(parts) > 2 else f"Punto ({lat},{lon})"
                placemark = doc.createElement("Placemark")
                pname = doc.createElement("name")
                pname.appendChild(doc.createTextNode(name))
                placemark.appendChild(pname)
                point = doc.createElement("Point")
                coords = doc.createElement("coordinates")
                coords.appendChild(doc.createTextNode(f"{lon},{lat},0"))
                point.appendChild(coords)
                placemark.appendChild(point)
                document.appendChild(placemark)

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(doc.toprettyxml(indent="  "))


def kml_to_text(kml_file, output_file):
    """Convierte un archivo KML a TXT (lat,lon,nombre)."""
    from xml.dom import minidom

    xmldoc = minidom.parse(kml_file)
    placemarks = xmldoc.getElementsByTagName("Placemark")
    with open(output_file, "w", encoding="utf-8") as f:
        for p in placemarks:
            name = (
                p.getElementsByTagName("name")[0].firstChild.nodeValue
                if p.getElementsByTagName("name")
                else ""
            )
            coords = p.getElementsByTagName("coordinates")[0].firstChild.nodeValue.strip()
            lon, lat, *_ = coords.split(",")
            f.write(f"{lat},{lon},{name}\n")


# ---------------- INTERFAZ ----------------
from PyQt5.QtWidgets import QMainWindow, QVBoxLayout, QWidget, QPushButton, QFileDialog, QMessageBox


class Tool(QMainWindow):
    name = "Convertidor de Archivos"

    def __init__(self):
        super().__init__()
        self.setWindowTitle(self.name)
        self.setGeometry(200, 200, 400, 400)

        layout = QVBoxLayout()

        # Opciones de conversión
        btn_img_pdf = QPushButton("Imágenes → PDF")
        btn_img_pdf.clicked.connect(self.convert_images_to_pdf)
        layout.addWidget(btn_img_pdf)

        btn_pdf_img = QPushButton("PDF → Imágenes")
        btn_pdf_img.clicked.connect(self.convert_pdf_to_images)
        layout.addWidget(btn_pdf_img)

        btn_txt_docx = QPushButton("TXT → DOCX")
        btn_txt_docx.clicked.connect(self.convert_text_to_docx)
        layout.addWidget(btn_txt_docx)

        btn_docx_txt = QPushButton("DOCX → TXT")
        btn_docx_txt.clicked.connect(self.convert_docx_to_text)
        layout.addWidget(btn_docx_txt)

        btn_docx_pdf = QPushButton("DOCX → PDF")
        btn_docx_pdf.clicked.connect(self.convert_docx_to_pdf)
        layout.addWidget(btn_docx_pdf)

        # --- Nuevas opciones TXT/KML ---
        btn_txt_kml = QPushButton("TXT → KML (archivos o carpeta)")
        btn_txt_kml.clicked.connect(self.convert_text_to_kml)
        layout.addWidget(btn_txt_kml)

        btn_kml_txt = QPushButton("KML → TXT (archivos o carpeta)")
        btn_kml_txt.clicked.connect(self.convert_kml_to_text)
        layout.addWidget(btn_kml_txt)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    # ---------------- FUNCIONES ----------------
    def convert_images_to_pdf(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Seleccionar imágenes", "", "Imágenes (*.png *.jpg *.jpeg *.bmp)"
        )
        if not files:
            return
        save_path, _ = QFileDialog.getSaveFileName(self, "Guardar PDF", "", "PDF (*.pdf)")
        if not save_path:
            return
        images_to_pdf(files, save_path)
        QMessageBox.information(self, "Conversión completada", f"PDF creado en:\n{save_path}")

    def convert_pdf_to_images(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Seleccionar PDF", "", "PDF (*.pdf)")
        if not file_path:
            return
        folder = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta de destino")
        if not folder:
            return
        saved_files = pdf_to_images(file_path, folder)
        QMessageBox.information(
            self,
            "Conversión completada",
            f"Se han guardado {len(saved_files)} imágenes en:\n{folder}",
        )

    def convert_text_to_docx(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Seleccionar TXT", "", "Texto (*.txt)")
        if not file_path:
            return
        save_path, _ = QFileDialog.getSaveFileName(self, "Guardar DOCX", "", "Word (*.docx)")
        if not save_path:
            return
        text_to_docx(file_path, save_path)
        QMessageBox.information(self, "Conversión completada", f"DOCX creado en:\n{save_path}")

    def convert_docx_to_text(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Seleccionar DOCX", "", "Word (*.docx)")
        if not file_path:
            return
        save_path, _ = QFileDialog.getSaveFileName(self, "Guardar TXT", "", "Texto (*.txt)")
        if not save_path:
            return
        docx_to_text(file_path, save_path)
        QMessageBox.information(self, "Conversión completada", f"TXT creado en:\n{save_path}")

    def convert_docx_to_pdf(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Seleccionar DOCX", "", "Word (*.docx)")
        if not file_path:
            return
        save_path, _ = QFileDialog.getSaveFileName(self, "Guardar PDF", "", "PDF (*.pdf)")
        if not save_path:
            return
        docx_to_pdf(file_path, save_path)
        QMessageBox.information(self, "Conversión completada", f"PDF creado en:\n{save_path}")

    # --- Nuevas funciones ---
    def convert_text_to_kml(self):
        path = QFileDialog.getExistingDirectory(
            self, "Seleccionar carpeta con TXT o archivo individual"
        )
        if path:
            # Carpeta seleccionada
            txt_files = [
                os.path.join(path, f) for f in os.listdir(path) if f.lower().endswith(".txt")
            ]
            if not txt_files:
                QMessageBox.warning(
                    self,
                    "Sin archivos",
                    "No se encontraron archivos .txt en la carpeta seleccionada.",
                )
                return
            output_dir = QFileDialog.getExistingDirectory(
                self, "Seleccionar carpeta de destino para KML"
            )
            if not output_dir:
                return
            for txt in txt_files:
                name = os.path.splitext(os.path.basename(txt))[0]
                output_path = os.path.join(output_dir, f"{name}.kml")
                text_to_kml(txt, output_path)
            QMessageBox.information(
                self, "Conversión completada", f"Se convirtieron {len(txt_files)} archivos a KML."
            )
        else:
            # Archivo individual
            file_path, _ = QFileDialog.getOpenFileName(self, "Seleccionar TXT", "", "Texto (*.txt)")
            if not file_path:
                return
            save_path, _ = QFileDialog.getSaveFileName(self, "Guardar KML", "", "KML (*.kml)")
            if not save_path:
                return
            text_to_kml(file_path, save_path)
            QMessageBox.information(self, "Conversión completada", f"KML creado en:\n{save_path}")

    def convert_kml_to_text(self):
        path = QFileDialog.getExistingDirectory(
            self, "Seleccionar carpeta con KML o archivo individual"
        )
        if path:
            kml_files = [
                os.path.join(path, f) for f in os.listdir(path) if f.lower().endswith(".kml")
            ]
            if not kml_files:
                QMessageBox.warning(
                    self,
                    "Sin archivos",
                    "No se encontraron archivos .kml en la carpeta seleccionada.",
                )
                return
            output_dir = QFileDialog.getExistingDirectory(
                self, "Seleccionar carpeta de destino para TXT"
            )
            if not output_dir:
                return
            for kml in kml_files:
                name = os.path.splitext(os.path.basename(kml))[0]
                output_path = os.path.join(output_dir, f"{name}.txt")
                kml_to_text(kml, output_path)
            QMessageBox.information(
                self, "Conversión completada", f"Se convirtieron {len(kml_files)} archivos a TXT."
            )
        else:
            file_path, _ = QFileDialog.getOpenFileName(self, "Seleccionar KML", "", "KML (*.kml)")
            if not file_path:
                return
            save_path, _ = QFileDialog.getSaveFileName(self, "Guardar TXT", "", "Texto (*.txt)")
            if not save_path:
                return
            kml_to_text(file_path, save_path)
            QMessageBox.information(self, "Conversión completada", f"TXT creado en:\n{save_path}")
