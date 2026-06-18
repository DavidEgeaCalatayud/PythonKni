from __future__ import annotations

import csv
import getpass
import html
import json
import os
import platform
import socket
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import psutil
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QMainWindow,
)

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from tools.app_paths import DATA_DIR, ensure_app_dirs
from tools.theme_manager import ThemeManager


@dataclass
class ReportData:
    generated_at: str
    system_rows: list[tuple[str, str]]
    disk_rows: list[tuple[str, str, str, str]]
    network_rows: list[tuple[str, str]]
    top_cpu: list[tuple[int, str, float, float]]
    top_memory: list[tuple[int, str, float, float]]
    temp_summary: list[tuple[str, str]]
    event_summary: list[tuple[str, str, str, str, str, str]] = field(default_factory=list)


def format_bytes(num_bytes: int | float) -> str:
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.2f} {unit}"
        value /= 1024
    return f"{value:.2f} TB"


def safe_gethostbyname(hostname: str) -> str:
    try:
        return socket.gethostbyname(hostname)
    except OSError:
        return "No disponible"


def get_default_gateway_windows() -> str:
    if platform.system() != "Windows":
        return "Solo disponible en Windows"

    try:
        result = subprocess.run(
            ["ipconfig"],
            capture_output=True,
            text=True,
            timeout=8,
            encoding="cp850",
            errors="ignore",
        )
        for line in result.stdout.splitlines():
            clean = line.strip()
            if "Puerta de enlace predeterminada" in clean or "Default Gateway" in clean:
                value = clean.split(":", 1)[-1].strip()
                if value:
                    return value
    except Exception:
        pass
    return "No disponible"


def ping_host(host: str = "8.8.8.8") -> str:
    parameter = "-n" if platform.system() == "Windows" else "-c"
    try:
        result = subprocess.run(
            ["ping", parameter, "1", host],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return "Correcto" if result.returncode == 0 else "Fallido"
    except Exception:
        return "Fallido"


def folder_size(path: Path, max_items: int = 30000) -> int:
    total = 0
    checked = 0
    if not path.exists():
        return 0

    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if not Path(root, d).is_symlink()]
        for file_name in files:
            if checked >= max_items:
                return total
            try:
                file_path = Path(root) / file_name
                if not file_path.is_symlink():
                    total += file_path.stat().st_size
                checked += 1
            except OSError:
                continue
    return total


def get_temp_locations() -> list[Path]:
    paths = [Path(tempfile.gettempdir())]
    if platform.system() == "Windows":
        local_app_data = os.getenv("LOCALAPPDATA")
        user_profile = os.getenv("USERPROFILE")
        if local_app_data:
            paths.extend(
                [
                    Path(local_app_data) / "Google" / "Chrome" / "User Data" / "Default" / "Cache",
                    Path(local_app_data) / "Microsoft" / "Edge" / "User Data" / "Default" / "Cache",
                ]
            )
        if user_profile:
            paths.append(Path(user_profile) / "AppData" / "Roaming" / "Mozilla" / "Firefox" / "Profiles")
        paths.append(Path("C:/Windows/Temp"))
    return list(dict.fromkeys(paths))


def collect_processes() -> tuple[list[tuple[int, str, float, float]], list[tuple[int, str, float, float]]]:
    """Obtiene procesos destacados evitando valores falsos del primer muestreo.

    psutil.cpu_percent() necesita una primera llamada de inicialización. Si se mide
    proceso por proceso con intervalos muy pequeños, Windows puede devolver valores
    irreales, especialmente para System Idle Process. Por eso hacemos dos pasadas.
    """
    processes = []
    for proc in psutil.process_iter(["pid", "name", "memory_percent"]):
        try:
            proc.cpu_percent(interval=None)
            processes.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    time.sleep(0.35)

    rows: list[tuple[int, str, float, float]] = []
    for proc in processes:
        try:
            pid = int(proc.info.get("pid") or 0)
            name = proc.info.get("name") or "Desconocido"
            if pid == 0 or name.lower() == "system idle process":
                continue
            cpu = round(float(proc.cpu_percent(interval=None)), 1)
            mem = round(float(proc.info.get("memory_percent") or 0), 2)
            rows.append((pid, name, cpu, mem))
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    top_cpu = sorted(rows, key=lambda item: item[2], reverse=True)[:10]
    top_memory = sorted(rows, key=lambda item: item[3], reverse=True)[:10]
    return top_cpu, top_memory


def load_event_snapshot(max_events: int = 10) -> list[tuple[str, str, str, str, str, str]]:
    """Carga eventos guardados desde el Visor de eventos de Windows.

    El botón "Añadir al informe técnico" del módulo event_viewer_tool.py guarda un
    snapshot en DATA_DIR. Si no existe, el informe técnico se genera igual, sin esta
    sección.
    """
    try:
        ensure_app_dirs()
        snapshot_file = DATA_DIR / "event_report_snapshot.json"
        if not snapshot_file.exists():
            return []

        payload = json.loads(snapshot_file.read_text(encoding="utf-8"))
        events = payload.get("events", [])
        rows: list[tuple[str, str, str, str, str, str]] = []
        for event in events[:max_events]:
            rows.append(
                (
                    str(event.get("date", "")),
                    str(event.get("level", "")),
                    str(event.get("provider", "")),
                    str(event.get("event_id", "")),
                    str(event.get("risk", "")),
                    str(event.get("interpretation", "")),
                )
            )
        return rows
    except Exception:
        return []

def collect_report() -> ReportData:
    boot_time = datetime.fromtimestamp(psutil.boot_time()).strftime("%d/%m/%Y %H:%M:%S")
    virtual_memory = psutil.virtual_memory()
    swap_memory = psutil.swap_memory()

    system_rows = [
        ("Fecha del informe", datetime.now().strftime("%d/%m/%Y %H:%M:%S")),
        ("Equipo", platform.node()),
        ("Usuario", getpass.getuser()),
        ("Sistema operativo", f"{platform.system()} {platform.release()}"),
        ("Versión", platform.version()),
        ("Arquitectura", platform.machine()),
        ("Procesador", platform.processor() or "No disponible"),
        ("Núcleos físicos", str(psutil.cpu_count(logical=False) or "No disponible")),
        ("Núcleos lógicos", str(psutil.cpu_count(logical=True) or "No disponible")),
        ("Uso CPU actual", f"{psutil.cpu_percent(interval=0.3):.1f}%"),
        ("RAM total", format_bytes(virtual_memory.total)),
        ("RAM usada", f"{format_bytes(virtual_memory.used)} ({virtual_memory.percent:.1f}%)"),
        ("Swap total", format_bytes(swap_memory.total)),
        ("Inicio del sistema", boot_time),
    ]

    disk_rows: list[tuple[str, str, str, str]] = []
    for partition in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(partition.mountpoint)
            disk_rows.append(
                (
                    partition.device or partition.mountpoint,
                    partition.mountpoint,
                    format_bytes(usage.total),
                    f"{format_bytes(usage.free)} libres ({100 - usage.percent:.1f}%)",
                )
            )
        except (PermissionError, OSError):
            continue

    hostname = socket.gethostname()
    network_rows = [
        ("Hostname", hostname),
        ("IP local", safe_gethostbyname(hostname)),
        ("Puerta de enlace", get_default_gateway_windows()),
        ("Ping a internet", ping_host()),
    ]

    try:
        addresses = psutil.net_if_addrs()
        for adapter, values in addresses.items():
            ips = []
            for address in values:
                if getattr(address, "family", None) == socket.AF_INET:
                    ips.append(address.address)
            if ips:
                network_rows.append((f"Adaptador: {adapter}", ", ".join(ips)))
    except Exception:
        network_rows.append(("Adaptadores", "No disponible"))

    top_cpu, top_memory = collect_processes()

    temp_summary = []
    for path in get_temp_locations():
        size = folder_size(path)
        temp_summary.append((str(path), format_bytes(size) if path.exists() else "No existe"))

    return ReportData(
        generated_at=datetime.now().strftime("%Y-%m-%d_%H-%M-%S"),
        system_rows=system_rows,
        disk_rows=disk_rows,
        network_rows=network_rows,
        top_cpu=top_cpu,
        top_memory=top_memory,
        temp_summary=temp_summary,
        event_summary=load_event_snapshot(),
    )


def rows_to_text(title: str, rows: list[tuple[str, str]]) -> str:
    output = [title, "=" * len(title)]
    output.extend(f"{key}: {value}" for key, value in rows)
    return "\n".join(output)


def report_to_text(data: ReportData) -> str:
    blocks = [rows_to_text("Sistema", data.system_rows)]

    blocks.append("\nDiscos\n======")
    for device, mountpoint, total, free in data.disk_rows:
        blocks.append(f"{device} | {mountpoint} | Total: {total} | {free}")

    blocks.append("\nRed\n===")
    blocks.extend(f"{key}: {value}" for key, value in data.network_rows)

    blocks.append("\nProcesos con más CPU\n====================")
    blocks.extend(f"PID {pid} | {name} | CPU {cpu:.1f}% | RAM {mem:.2f}%" for pid, name, cpu, mem in data.top_cpu)

    blocks.append("\nProcesos con más RAM\n====================")
    blocks.extend(f"PID {pid} | {name} | CPU {cpu:.1f}% | RAM {mem:.2f}%" for pid, name, cpu, mem in data.top_memory)

    blocks.append("\nTemporales y cachés\n==================")
    blocks.extend(f"{path}: {size}" for path, size in data.temp_summary)

    if data.event_summary:
        blocks.append("\nEventos recientes de Windows\n============================")
        blocks.extend(
            f"{date} | {level} | {provider} | ID {event_id} | Riesgo {risk} | {interpretation}"
            for date, level, provider, event_id, risk, interpretation in data.event_summary
        )

    return "\n".join(blocks)


def table_html(headers: list[str], rows: list[list[str] | tuple]) -> str:
    header_html = "".join(f"<th>{html.escape(str(header))}</th>" for header in headers)
    body = []
    for row in rows:
        body.append("<tr>" + "".join(f"<td>{html.escape(str(cell))}</td>" for cell in row) + "</tr>")
    return f"<table><thead><tr>{header_html}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def report_to_html(data: ReportData) -> str:
    return f"""
<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Informe técnico del equipo</title>
<style>
body {{ font-family: Arial, sans-serif; margin: 32px; color: #222; }}
h1 {{ border-bottom: 2px solid #333; padding-bottom: 8px; }}
h2 {{ margin-top: 28px; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
th, td {{ border: 1px solid #ccc; padding: 7px; text-align: left; font-size: 12px; }}
th {{ background: #eee; }}
.small {{ color: #666; font-size: 12px; }}
</style>
</head>
<body>
<h1>Informe técnico del equipo</h1>
<p class="small">Generado: {html.escape(data.generated_at)}</p>
<h2>Sistema</h2>
{table_html(["Campo", "Valor"], data.system_rows)}
<h2>Discos</h2>
{table_html(["Dispositivo", "Punto de montaje", "Total", "Libre"], data.disk_rows)}
<h2>Red</h2>
{table_html(["Campo", "Valor"], data.network_rows)}
<h2>Procesos con más CPU</h2>
{table_html(["PID", "Nombre", "CPU %", "RAM %"], data.top_cpu)}
<h2>Procesos con más RAM</h2>
{table_html(["PID", "Nombre", "CPU %", "RAM %"], data.top_memory)}
<h2>Temporales y cachés</h2>
{table_html(["Ruta", "Tamaño estimado"], data.temp_summary)}
{f"<h2>Eventos recientes de Windows</h2>{table_html(["Fecha", "Nivel", "Origen", "ID Evento", "Riesgo", "Interpretación"], data.event_summary)}" if data.event_summary else ""}
</body>
</html>
""".strip()


def _pdf_paragraph(value: object, style: ParagraphStyle) -> Paragraph:
    """Crea un Paragraph seguro para ReportLab escapando caracteres especiales."""
    return Paragraph(html.escape(str(value)), style)


def _add_pdf_table(
    story: list,
    title: str,
    headers: list[str],
    rows: list[tuple] | list[list],
    col_widths: list[float],
    styles: dict[str, ParagraphStyle],
) -> None:
    story.append(Paragraph(html.escape(title), styles["heading2"]))
    story.append(Spacer(1, 0.12 * cm))

    table_data = [
        [_pdf_paragraph(header, styles["table_header"]) for header in headers]
    ]
    for row in rows:
        table_data.append([_pdf_paragraph(cell, styles["table_cell"]) for cell in row])

    table = Table(table_data, colWidths=col_widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EDEDED")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#111111")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("LEADING", (0, 0), (-1, -1), 10),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#BDBDBD")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 0.45 * cm))


def _draw_pdf_footer(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#666666"))
    canvas.drawRightString(doc.pagesize[0] - doc.rightMargin, 0.7 * cm, f"Página {doc.page}")
    canvas.restoreState()


def report_to_pdf(data: ReportData, file_path: str | Path) -> None:
    """Exporta el informe a PDF con ReportLab.

    Se evita QTextDocument/QPrinter porque en algunos equipos genera tablas con texto
    microscópico o casi invisible al usar QPrinter.HighResolution.
    """
    file_path = str(file_path)
    doc = SimpleDocTemplate(
        file_path,
        pagesize=landscape(A4),
        leftMargin=1.2 * cm,
        rightMargin=1.2 * cm,
        topMargin=1.1 * cm,
        bottomMargin=1.1 * cm,
        title="Informe técnico del equipo",
        author="PythonKni",
    )

    base_styles = getSampleStyleSheet()
    styles = {
        "title": ParagraphStyle(
            "ReportTitle",
            parent=base_styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            textColor=colors.HexColor("#111111"),
            alignment=TA_LEFT,
            spaceAfter=6,
        ),
        "small": ParagraphStyle(
            "ReportSmall",
            parent=base_styles["Normal"],
            fontName="Helvetica",
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#555555"),
            spaceAfter=10,
        ),
        "heading2": ParagraphStyle(
            "ReportHeading2",
            parent=base_styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=15,
            textColor=colors.HexColor("#111111"),
            spaceBefore=4,
            spaceAfter=2,
        ),
        "table_header": ParagraphStyle(
            "ReportTableHeader",
            parent=base_styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#111111"),
        ),
        "table_cell": ParagraphStyle(
            "ReportTableCell",
            parent=base_styles["Normal"],
            fontName="Helvetica",
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#222222"),
            wordWrap="CJK",
        ),
    }

    story: list = []
    story.append(Paragraph("Informe técnico del equipo", styles["title"]))
    story.append(Paragraph(f"Generado: {html.escape(data.generated_at)}", styles["small"]))

    _add_pdf_table(
        story,
        "Sistema",
        ["Campo", "Valor"],
        data.system_rows,
        [5.0 * cm, 20.0 * cm],
        styles,
    )
    _add_pdf_table(
        story,
        "Discos",
        ["Dispositivo", "Punto de montaje", "Total", "Libre"],
        data.disk_rows,
        [5.0 * cm, 5.0 * cm, 5.0 * cm, 9.5 * cm],
        styles,
    )
    _add_pdf_table(
        story,
        "Red",
        ["Campo", "Valor"],
        data.network_rows,
        [7.0 * cm, 18.0 * cm],
        styles,
    )
    _add_pdf_table(
        story,
        "Procesos con más CPU",
        ["PID", "Nombre", "CPU %", "RAM %"],
        data.top_cpu,
        [2.5 * cm, 14.0 * cm, 3.0 * cm, 3.0 * cm],
        styles,
    )
    _add_pdf_table(
        story,
        "Procesos con más RAM",
        ["PID", "Nombre", "CPU %", "RAM %"],
        data.top_memory,
        [2.5 * cm, 14.0 * cm, 3.0 * cm, 3.0 * cm],
        styles,
    )
    _add_pdf_table(
        story,
        "Temporales y cachés",
        ["Ruta", "Tamaño estimado"],
        data.temp_summary,
        [20.0 * cm, 5.0 * cm],
        styles,
    )

    if data.event_summary:
        _add_pdf_table(
            story,
            "Eventos recientes de Windows",
            ["Fecha", "Nivel", "Origen", "ID Evento", "Riesgo", "Interpretación"],
            data.event_summary,
            [3.6 * cm, 2.8 * cm, 5.0 * cm, 2.4 * cm, 2.5 * cm, 8.7 * cm],
            styles,
        )

    doc.build(story, onFirstPage=_draw_pdf_footer, onLaterPages=_draw_pdf_footer)


class ReportWorker(QThread):
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def run(self) -> None:
        try:
            self.finished.emit(collect_report())
        except Exception as error:
            self.failed.emit(str(error))


class Tool(QMainWindow):
    name = "Informe Técnico del Equipo"

    def __init__(self):
        super().__init__()
        self.setWindowTitle(self.name)
        self.setGeometry(200, 200, 1100, 700)
        ThemeManager.apply_theme(self)

        self.report_data: ReportData | None = None

        layout = QVBoxLayout()
        layout.addWidget(QLabel("Genera un informe técnico con sistema, discos, red, procesos y temporales."))

        button_layout = QHBoxLayout()
        self.btn_generate = QPushButton("Generar informe")
        self.btn_generate.clicked.connect(self.generate_report)
        button_layout.addWidget(self.btn_generate)

        self.btn_html = QPushButton("Exportar HTML")
        self.btn_html.clicked.connect(self.export_html)
        self.btn_html.setEnabled(False)
        button_layout.addWidget(self.btn_html)

        self.btn_pdf = QPushButton("Exportar PDF")
        self.btn_pdf.clicked.connect(self.export_pdf)
        self.btn_pdf.setEnabled(False)
        button_layout.addWidget(self.btn_pdf)

        self.btn_txt = QPushButton("Exportar TXT")
        self.btn_txt.clicked.connect(self.export_txt)
        self.btn_txt.setEnabled(False)
        button_layout.addWidget(self.btn_txt)
        layout.addLayout(button_layout)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)

        self.tabs = QTabWidget()
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.tabs.addTab(self.preview, "Resumen")

        self.system_table = QTableWidget()
        self.tabs.addTab(self.system_table, "Sistema")

        self.disk_table = QTableWidget()
        self.tabs.addTab(self.disk_table, "Discos")

        self.network_table = QTableWidget()
        self.tabs.addTab(self.network_table, "Red")

        self.cpu_table = QTableWidget()
        self.tabs.addTab(self.cpu_table, "Top CPU")

        self.memory_table = QTableWidget()
        self.tabs.addTab(self.memory_table, "Top RAM")

        self.temp_table = QTableWidget()
        self.tabs.addTab(self.temp_table, "Temporales")

        layout.addWidget(self.tabs)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    def generate_report(self) -> None:
        self.btn_generate.setEnabled(False)
        self.progress.show()
        self.worker = ReportWorker()
        self.worker.finished.connect(self.on_report_ready)
        self.worker.failed.connect(self.on_report_failed)
        self.worker.start()

    def on_report_ready(self, data: ReportData) -> None:
        self.report_data = data
        self.preview.setPlainText(report_to_text(data))
        self.fill_table(self.system_table, ["Campo", "Valor"], data.system_rows)
        self.fill_table(self.disk_table, ["Dispositivo", "Punto de montaje", "Total", "Libre"], data.disk_rows)
        self.fill_table(self.network_table, ["Campo", "Valor"], data.network_rows)
        self.fill_table(self.cpu_table, ["PID", "Nombre", "CPU %", "RAM %"], data.top_cpu)
        self.fill_table(self.memory_table, ["PID", "Nombre", "CPU %", "RAM %"], data.top_memory)
        self.fill_table(self.temp_table, ["Ruta", "Tamaño estimado"], data.temp_summary)
        self.progress.hide()
        self.btn_generate.setEnabled(True)
        self.btn_html.setEnabled(True)
        self.btn_pdf.setEnabled(True)
        self.btn_txt.setEnabled(True)

    def on_report_failed(self, message: str) -> None:
        self.progress.hide()
        self.btn_generate.setEnabled(True)
        QMessageBox.critical(self, "Error", f"No se pudo generar el informe:\n{message}")

    def fill_table(self, table: QTableWidget, headers: list[str], rows: list[tuple]) -> None:
        table.clear()
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for col_index, value in enumerate(row):
                table.setItem(row_index, col_index, QTableWidgetItem(str(value)))
        table.resizeColumnsToContents()

    def require_report(self) -> ReportData | None:
        if not self.report_data:
            QMessageBox.warning(self, "Informe", "Primero genera el informe.")
            return None
        return self.report_data

    def default_filename(self, extension: str) -> str:
        suffix = self.report_data.generated_at if self.report_data else datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        return f"informe_tecnico_{suffix}.{extension}"

    def export_html(self) -> None:
        data = self.require_report()
        if not data:
            return
        file_path, _ = QFileDialog.getSaveFileName(self, "Guardar HTML", self.default_filename("html"), "HTML (*.html)")
        if not file_path:
            return
        Path(file_path).write_text(report_to_html(data), encoding="utf-8")
        QMessageBox.information(self, "Exportado", "Informe HTML generado correctamente.")

    def export_txt(self) -> None:
        data = self.require_report()
        if not data:
            return
        file_path, _ = QFileDialog.getSaveFileName(self, "Guardar TXT", self.default_filename("txt"), "Texto (*.txt)")
        if not file_path:
            return
        Path(file_path).write_text(report_to_text(data), encoding="utf-8")
        QMessageBox.information(self, "Exportado", "Informe TXT generado correctamente.")

    def export_pdf(self) -> None:
        data = self.require_report()
        if not data:
            return
        file_path, _ = QFileDialog.getSaveFileName(self, "Guardar PDF", self.default_filename("pdf"), "PDF (*.pdf)")
        if not file_path:
            return

        try:
            report_to_pdf(data, file_path)
        except Exception as error:
            QMessageBox.critical(self, "Error", f"No se pudo exportar el PDF:\n{error}")
            return

        QMessageBox.information(self, "Exportado", "Informe PDF generado correctamente.")
