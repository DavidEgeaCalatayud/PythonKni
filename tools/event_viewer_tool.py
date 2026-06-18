from __future__ import annotations

import csv
import html
import json
import platform
import re
import subprocess
import threading
import time
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from PyQt5.QtCore import QThread, Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QMainWindow,
)

from tools.app_paths import DATA_DIR, ensure_app_dirs
from tools.theme_manager import ThemeManager

try:
    from reportlab.lib import colors as rl_colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    _REPORTLAB_AVAILABLE = True
except ImportError:
    _REPORTLAB_AVAILABLE = False


EVENT_SNAPSHOT_FILE = DATA_DIR / "event_report_snapshot.json"

LEVEL_NAMES = {
    1: "Crítico",
    2: "Error",
    3: "Advertencia",
    4: "Información",
    5: "Verbose",
}

RISK_ORDER = {
    "Alto": 3,
    "Medio": 2,
    "Bajo": 1,
    "Normal": 0,
}

RISK_COLORS = {
    "Alto": QColor("#ffcccc"),
    "Medio": QColor("#ffe5b4"),
    "Bajo": QColor("#fff7cc"),
    "Normal": QColor("#d9f2d9"),
}

SUPPORTED_LOGS = ["Application", "System", "Security"]


@dataclass
class EventItem:
    date: str
    level: str
    level_number: int
    provider: str
    event_id: str
    category: str
    message: str
    risk: str
    interpretation: str
    log_name: str
    record_id: str
    computer: str
    process_id: str
    thread_id: str
    raw_xml: str = ""
    timestamp_sort: str = ""

    def detail_text(self) -> str:
        return (
            f"Fecha: {self.date}\n"
            f"Nivel: {self.level}\n"
            f"Registro: {self.log_name}\n"
            f"Origen: {self.provider}\n"
            f"ID Evento: {self.event_id}\n"
            f"Categoría: {self.category}\n"
            f"Equipo: {self.computer}\n"
            f"Record ID: {self.record_id}\n"
            f"Proceso: {self.process_id}\n"
            f"Hilo: {self.thread_id}\n"
            f"Riesgo: {self.risk}\n"
            f"Interpretación: {self.interpretation}\n\n"
            f"Mensaje:\n{self.message}"
        )


@dataclass
class EventResult:
    events: list[EventItem]
    warnings: list[str]


# ---------------------------------------------------------------------------
# Utilidades de lectura y diagnóstico
# ---------------------------------------------------------------------------


def is_windows() -> bool:
    return platform.system().lower() == "windows"


def clean_text(value: object, max_len: int | None = None) -> str:
    text = "" if value is None else str(value)
    text = re.sub(r"\s+", " ", text).strip()
    if max_len and len(text) > max_len:
        return text[: max_len - 3].rstrip() + "..."
    return text


def first_child(element: ET.Element | None, name: str) -> ET.Element | None:
    if element is None:
        return None
    for child in list(element):
        if child.tag.split("}")[-1] == name:
            return child
    return None


def find_child(element: ET.Element | None, name: str) -> ET.Element | None:
    if element is None:
        return None
    for child in element.iter():
        if child.tag.split("}")[-1] == name:
            return child
    return None


def child_text(element: ET.Element | None, name: str, default: str = "") -> str:
    child = first_child(element, name)
    if child is None or child.text is None:
        return default
    return clean_text(child.text)


def child_attr(element: ET.Element | None, name: str, attr: str, default: str = "") -> str:
    child = first_child(element, name)
    if child is None:
        return default
    return clean_text(child.attrib.get(attr, default))


def parse_windows_time(value: str) -> tuple[str, str]:
    """Returns (display_date, sort_key)."""
    if not value:
        return "No disponible", ""

    raw = value.strip().replace("Z", "+00:00")
    if "." in raw:
        prefix, suffix = raw.split(".", 1)
        tz = ""
        if "+" in suffix:
            frac, tz = suffix.split("+", 1)
            tz = "+" + tz
        elif "-" in suffix:
            frac, tz = suffix.split("-", 1)
            tz = "-" + tz
        else:
            frac = suffix
        raw = f"{prefix}.{frac[:6]}{tz}"

    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is not None:
            dt = dt.astimezone()
        return dt.strftime("%d/%m/%Y %H:%M:%S"), dt.strftime("%Y%m%d%H%M%S")
    except ValueError:
        return value, ""


def decode_process_output(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode(errors="ignore")


def build_event_query(hours: int, include_info: bool = False) -> str:
    levels = "Level=1 or Level=2 or Level=3"
    if include_info:
        levels = f"{levels} or Level=4"

    time_filter = ""
    if hours > 0:
        milliseconds = hours * 60 * 60 * 1000
        time_filter = f" and TimeCreated[timediff(@SystemTime) <= {milliseconds}]"

    return f"*[System[({levels}){time_filter}]]"


def run_wevtutil(
    log_name: str,
    hours: int,
    max_events: int,
    include_info: bool,
    cancel_event: threading.Event | None = None,
) -> tuple[str, str]:
    query = build_event_query(hours=hours, include_info=include_info)
    command = [
        "wevtutil", "qe", log_name,
        f"/q:{query}", f"/c:{max_events}", "/rd:true", "/f:RenderedXml",
    ]

    try:
        proc = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
        )
    except Exception as error:
        return "", f"No se pudo ejecutar wevtutil para {log_name}: {error}"

    deadline = time.monotonic() + 25.0
    while proc.poll() is None:
        if cancel_event is not None and cancel_event.is_set():
            proc.kill()
            return "", "Cancelado por el usuario."
        if time.monotonic() > deadline:
            proc.kill()
            return "", (
                f"Tiempo agotado leyendo {log_name}. "
                "Prueba con menos eventos o un filtro temporal menor."
            )
        time.sleep(0.2)

    stdout_bytes = proc.stdout.read() if proc.stdout else b""
    stderr_bytes = proc.stderr.read() if proc.stderr else b""
    stdout = decode_process_output(stdout_bytes)
    stderr = decode_process_output(stderr_bytes)

    if proc.returncode != 0:
        combined = f"{stdout}\n{stderr}".strip()
        if "No events were found" in combined or "No se encontraron eventos" in combined:
            return "", ""
        return "", combined or f"No se pudo leer el registro {log_name}."

    return stdout, ""


def normalize_xml_output(output: str) -> str:
    cleaned = output.strip()
    cleaned = re.sub(r"<\?xml[^>]*\?>", "", cleaned, flags=re.IGNORECASE).strip()
    if not cleaned:
        return "<Events />"
    if cleaned.startswith("<Events"):
        return cleaned
    return f"<Events>{cleaned}</Events>"


def rendered_message(event: ET.Element) -> str:
    rendering = find_child(event, "RenderingInfo")
    message = child_text(rendering, "Message", "")
    if message:
        return message

    eventdata = find_child(event, "EventData")
    if eventdata is not None:
        parts = []
        for data in list(eventdata):
            if data.text:
                name = data.attrib.get("Name", "Dato")
                parts.append(f"{name}: {clean_text(data.text)}")
        if parts:
            return " | ".join(parts)

    userdata = find_child(event, "UserData")
    if userdata is not None:
        parts = [clean_text(node.text) for node in userdata.iter() if node.text and clean_text(node.text)]
        if parts:
            return " | ".join(parts)

    return "Mensaje no disponible. Puede requerir permisos o componentes de Windows para renderizarse."


def interpret_event(provider: str, event_id: str, level_number: int, message: str) -> str:
    provider_low = provider.lower()
    msg_low = message.lower()
    event_id_int = int(event_id) if str(event_id).isdigit() else -1

    if "kernel-power" in provider_low and event_id_int == 41:
        return "El equipo se apagó o reinició de forma inesperada. Puede deberse a corte eléctrico, bloqueo, botón físico o pantallazo."
    if provider_low in {"disk", "microsoft-windows-disk"} or "disk" == provider_low:
        if event_id_int in {7, 11, 15, 51, 129, 153, 157}:
            return "Posible problema de disco, controlador o comunicación con la unidad. Conviene revisar SMART, cableado/controlador y salud del disco."
        return "Evento relacionado con almacenamiento. Revisar si coincide con lentitud, errores de E/S o desconexiones."
    if "ntfs" in provider_low and event_id_int in {55, 98, 137}:
        return "Posible incidencia del sistema de archivos. Conviene ejecutar comprobación de disco y revisar apagados bruscos."
    if "whea-logger" in provider_low:
        return "Windows ha detectado un error de hardware. Puede estar relacionado con CPU, RAM, placa, energía o drivers."
    if "bugcheck" in provider_low or event_id_int == 1001 and "bugcheck" in msg_low:
        return "El equipo tuvo un pantallazo o reinicio por error crítico. Revisar minidumps, drivers y cambios recientes."
    if "service control manager" in provider_low:
        if 7000 <= event_id_int <= 7034:
            return "Un servicio de Windows no pudo iniciar, se detuvo o falló. Revisar nombre del servicio y dependencia indicada."
        return "Evento relacionado con servicios de Windows. Revisar si afecta a una aplicación o servicio concreto."
    if "application error" in provider_low and event_id_int == 1000:
        return "Una aplicación se cerró inesperadamente. Revisar el ejecutable, módulo con error y hora del fallo."
    if "application hang" in provider_low:
        return "Una aplicación dejó de responder. Puede deberse a bloqueo, espera de red, disco lento o fallo interno."
    if "dns client events" in provider_low and event_id_int == 1014:
        return "Problema temporal de resolución DNS. Revisar DNS configurado, red, VPN o conectividad."
    if "windowsupdateclient" in provider_low or "windows update" in provider_low:
        return "Evento relacionado con Windows Update. Revisar conectividad, espacio en disco y estado del servicio de actualización."
    if "eventlog" in provider_low and event_id_int == 6008:
        return "Windows detectó un apagado inesperado anterior. Revisar si hubo corte, bloqueo o reinicio forzado."
    if "security-auditing" in provider_low and event_id_int in {4625, 4771, 4776}:
        return "Intento de inicio de sesión fallido. Revisar usuario, origen y frecuencia si se repite."
    if level_number == 1:
        return "Evento crítico. Revisar prioridad alta, especialmente si coincide con reinicios, bloqueos o pérdida de datos."
    if level_number == 2:
        return "Error de sistema o aplicación. Conviene revisar si se repite y si coincide con una incidencia real."
    if level_number == 3:
        return "Advertencia. No siempre implica fallo grave, pero puede anticipar problemas si se repite."
    return "Evento informativo. Normalmente no requiere acción salvo que esté relacionado con una incidencia concreta."


def classify_risk(provider: str, event_id: str, level_number: int, message: str) -> str:
    provider_low = provider.lower()
    msg_low = message.lower()
    event_id_int = int(event_id) if str(event_id).isdigit() else -1

    if level_number == 1:
        return "Alto"
    if "kernel-power" in provider_low and event_id_int == 41:
        return "Alto"
    if "disk" in provider_low and event_id_int in {7, 11, 15, 51, 129, 153, 157}:
        return "Alto"
    if "ntfs" in provider_low and event_id_int in {55, 98, 137}:
        return "Alto"
    if "whea-logger" in provider_low:
        return "Alto"
    if "bugcheck" in provider_low or "pantallazo" in msg_low or "blue screen" in msg_low:
        return "Alto"
    if "eventlog" in provider_low and event_id_int == 6008:
        return "Alto"

    if level_number == 2:
        return "Medio"
    if "service control manager" in provider_low and 7000 <= event_id_int <= 7034:
        return "Medio"
    if "dns client events" in provider_low and event_id_int == 1014:
        return "Medio"
    if "windowsupdateclient" in provider_low:
        return "Medio"
    if "security-auditing" in provider_low and event_id_int in {4625, 4771, 4776}:
        return "Medio"

    if level_number == 3:
        return "Bajo"
    return "Normal"


def parse_events_xml(output: str, fallback_log_name: str) -> list[EventItem]:
    xml_text = normalize_xml_output(output)
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as error:
        raise RuntimeError(f"No se pudo interpretar la salida XML de {fallback_log_name}: {error}") from error

    if root.tag.split("}")[-1] == "Event":
        event_nodes = [root]
    else:
        event_nodes = [node for node in root.iter() if node.tag.split("}")[-1] == "Event"]

    items: list[EventItem] = []
    for event in event_nodes:
        system = first_child(event, "System")
        rendering = first_child(event, "RenderingInfo")
        provider_node = first_child(system, "Provider")
        event_id_node = first_child(system, "EventID")
        execution_node = first_child(system, "Execution")

        provider = clean_text(provider_node.attrib.get("Name", "Desconocido") if provider_node is not None else "Desconocido")
        event_id = clean_text(event_id_node.text if event_id_node is not None else "") or "-"
        level_number_raw = child_text(system, "Level", "0")
        try:
            level_number = int(level_number_raw)
        except ValueError:
            level_number = 0

        rendered_level = child_text(rendering, "Level", "")
        level = rendered_level or LEVEL_NAMES.get(level_number, level_number_raw or "Desconocido")
        category = child_text(rendering, "Task", "") or child_text(system, "Task", "-")
        log_name = child_text(system, "Channel", fallback_log_name) or fallback_log_name
        computer = child_text(system, "Computer", "-")
        record_id = child_text(system, "EventRecordID", "-")
        system_time = child_attr(system, "TimeCreated", "SystemTime", "")
        date, timestamp_sort = parse_windows_time(system_time)
        process_id = execution_node.attrib.get("ProcessID", "-") if execution_node is not None else "-"
        thread_id = execution_node.attrib.get("ThreadID", "-") if execution_node is not None else "-"
        message = rendered_message(event)
        risk = classify_risk(provider, event_id, level_number, message)
        interpretation = interpret_event(provider, event_id, level_number, message)

        try:
            raw_xml = ET.tostring(event, encoding="unicode")
        except Exception:
            raw_xml = ""

        items.append(
            EventItem(
                date=date,
                level=level,
                level_number=level_number,
                provider=provider,
                event_id=event_id,
                category=category,
                message=message,
                risk=risk,
                interpretation=interpretation,
                log_name=log_name,
                record_id=record_id,
                computer=computer,
                process_id=process_id,
                thread_id=thread_id,
                raw_xml=raw_xml,
                timestamp_sort=timestamp_sort,
            )
        )

    return items


def collect_events(
    logs: Iterable[str],
    hours: int,
    max_events: int,
    include_info: bool = False,
    cancel_event: threading.Event | None = None,
) -> EventResult:
    if not is_windows():
        raise RuntimeError("El Visor de eventos solo está disponible en Windows.")

    all_events: list[EventItem] = []
    warnings: list[str] = []
    per_log_limit = max(10, max_events)

    for log_name in logs:
        if cancel_event is not None and cancel_event.is_set():
            break
        if log_name not in SUPPORTED_LOGS:
            continue
        output, warning = run_wevtutil(
            log_name,
            hours=hours,
            max_events=per_log_limit,
            include_info=include_info,
            cancel_event=cancel_event,
        )
        if warning == "Cancelado por el usuario.":
            break
        if warning:
            warnings.append(f"{log_name}: {warning}")
            continue
        if not output.strip():
            continue
        try:
            all_events.extend(parse_events_xml(output, fallback_log_name=log_name))
        except RuntimeError as error:
            warnings.append(str(error))

    all_events.sort(
        key=lambda item: (RISK_ORDER.get(item.risk, 0), item.timestamp_sort),
        reverse=True,
    )
    return EventResult(events=all_events[:max_events], warnings=warnings)


def events_to_html(events: list[EventItem], title: str = "Diagnóstico de eventos de Windows") -> str:
    rows = []
    for item in events:
        rows.append(
            "<tr>"
            f"<td>{html.escape(item.date)}</td>"
            f"<td>{html.escape(item.level)}</td>"
            f"<td>{html.escape(item.log_name)}</td>"
            f"<td>{html.escape(item.provider)}</td>"
            f"<td>{html.escape(item.event_id)}</td>"
            f"<td>{html.escape(item.risk)}</td>"
            f"<td>{html.escape(clean_text(item.message, 300))}</td>"
            f"<td>{html.escape(item.interpretation)}</td>"
            "</tr>"
        )

    return f"""
<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>
body {{ font-family: Arial, sans-serif; margin: 32px; color: #222; }}
h1 {{ border-bottom: 2px solid #333; padding-bottom: 8px; }}
table {{ border-collapse: collapse; width: 100%; margin-top: 16px; }}
th, td {{ border: 1px solid #ccc; padding: 7px; font-size: 12px; vertical-align: top; }}
th {{ background: #eee; text-align: left; }}
.small {{ color: #666; font-size: 12px; }}
</style>
</head>
<body>
<h1>{html.escape(title)}</h1>
<p class="small">Generado: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}</p>
<table>
<thead>
<tr>
<th>Fecha</th><th>Nivel</th><th>Registro</th><th>Origen</th><th>ID Evento</th><th>Riesgo</th><th>Mensaje resumido</th><th>Interpretación</th>
</tr>
</thead>
<tbody>
{''.join(rows)}
</tbody>
</table>
</body>
</html>
""".strip()


def events_to_pdf(events: list[EventItem], summary: str, path: str) -> None:
    if not _REPORTLAB_AVAILABLE:
        raise RuntimeError("ReportLab no está instalado. Instala con: pip install reportlab")

    doc = SimpleDocTemplate(
        path,
        pagesize=A4,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )
    styles = getSampleStyleSheet()
    small = styles["Normal"].clone("EventSmall")
    small.fontSize = 7
    small.leading = 9
    story = []

    story.append(Paragraph("Diagnóstico de eventos de Windows", styles["Title"]))
    story.append(Paragraph(f"Generado: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}", styles["Normal"]))
    story.append(Spacer(1, 0.4 * cm))

    story.append(Paragraph("Resumen ejecutivo", styles["Heading2"]))
    for part in summary.split("|"):
        part = part.strip()
        if part:
            story.append(Paragraph(f"• {html.escape(part)}", styles["Normal"]))
    story.append(Spacer(1, 0.4 * cm))

    limit = min(len(events), 100)
    story.append(Paragraph(f"Eventos relevantes (primeros {limit})", styles["Heading2"]))

    risk_pdf_colors = {
        "Alto": rl_colors.HexColor("#ffcccc"),
        "Medio": rl_colors.HexColor("#ffe5b4"),
        "Bajo": rl_colors.HexColor("#fff7cc"),
        "Normal": rl_colors.HexColor("#d9f2d9"),
    }

    table_data: list[list] = [["Fecha", "Nivel", "Origen", "ID", "Riesgo", "Interpretación"]]
    row_bg: list = [
        ("BACKGROUND", (0, 0), (-1, 0), rl_colors.HexColor("#dddddd")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("GRID", (0, 0), (-1, -1), 0.3, rl_colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]

    for i, item in enumerate(events[:100], start=1):
        table_data.append([
            Paragraph(html.escape(item.date), small),
            Paragraph(html.escape(item.level), small),
            Paragraph(html.escape(clean_text(item.provider, 35)), small),
            Paragraph(html.escape(item.event_id), small),
            Paragraph(html.escape(item.risk), small),
            Paragraph(html.escape(clean_text(item.interpretation, 120)), small),
        ])
        color = risk_pdf_colors.get(item.risk)
        if color:
            row_bg.append(("BACKGROUND", (0, i), (-1, i), color))

    # A4[0] is in points; subtract left+right margins to get usable width
    avail = A4[0] - 3 * cm
    col_widths = [3.2 * cm, 1.8 * cm, 3.5 * cm, 1.2 * cm, 1.5 * cm, avail - 11.2 * cm]

    tbl = Table(table_data, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(TableStyle(row_bg))
    story.append(tbl)
    story.append(Spacer(1, 0.5 * cm))

    story.append(Paragraph("Orígenes más frecuentes", styles["Heading2"]))
    provider_counts = Counter(item.provider for item in events)
    for provider, count in provider_counts.most_common(10):
        story.append(Paragraph(f"• {html.escape(provider)}: {count} evento(s)", styles["Normal"]))

    doc.build(story)


def save_events_snapshot(events: list[EventItem], summary: dict | None = None) -> Path:
    ensure_app_dirs()
    payload = {
        "generated_at": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "source": "Visor de eventos de Windows",
        "summary": summary or {},
        "events": [asdict(item) for item in events],
    }
    EVENT_SNAPSHOT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return EVENT_SNAPSHOT_FILE


# ---------------------------------------------------------------------------
# Hilo de carga
# ---------------------------------------------------------------------------


class EventWorker(QThread):
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, logs: list[str], hours: int, max_events: int, include_info: bool):
        super().__init__()
        self.logs = logs
        self.hours = hours
        self.max_events = max_events
        self.include_info = include_info
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        try:
            result = collect_events(
                self.logs,
                self.hours,
                self.max_events,
                self.include_info,
                cancel_event=self._cancel_event,
            )
            self.finished.emit(result)
        except Exception as error:
            self.failed.emit(str(error))


# ---------------------------------------------------------------------------
# Interfaz gráfica
# ---------------------------------------------------------------------------


class EventDetailDialog(QDialog):
    def __init__(self, item: EventItem, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"Detalle del evento {item.event_id}")
        self.resize(850, 600)

        layout = QVBoxLayout()
        editor = QPlainTextEdit()
        editor.setReadOnly(True)
        editor.setPlainText(item.detail_text())
        layout.addWidget(editor)

        btn_copy = QPushButton("Copiar detalle")
        btn_copy.clicked.connect(lambda: QApplication.clipboard().setText(item.detail_text()))
        layout.addWidget(btn_copy)

        self.setLayout(layout)


class Tool(QMainWindow):
    name = "Visor de eventos de Windows"

    def __init__(self):
        super().__init__()
        self.setWindowTitle(self.name)
        self.resize(1350, 780)
        self.events: list[EventItem] = []
        self.visible_events: list[EventItem] = []
        self.worker: EventWorker | None = None
        self.setup_ui()
        ThemeManager.apply_theme(QApplication.instance())

    def setup_ui(self) -> None:
        root = QWidget()
        main_layout = QVBoxLayout()

        title = QLabel("Visor de eventos de Windows simplificado")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        main_layout.addWidget(title)

        description = QLabel(
            "Lee eventos reales de Windows, clasifica el riesgo y añade una interpretación útil para soporte técnico."
        )
        description.setWordWrap(True)
        main_layout.addWidget(description)

        # --- Filtros de registros y periodo ---
        filters = QGridLayout()

        self.chk_application = QCheckBox("Application")
        self.chk_application.setChecked(True)
        self.chk_system = QCheckBox("System")
        self.chk_system.setChecked(True)
        self.chk_security = QCheckBox("Security")
        self.chk_security.setToolTip("Puede requerir permisos de administrador.")

        filters.addWidget(QLabel("Registros:"), 0, 0)
        filters.addWidget(self.chk_application, 0, 1)
        filters.addWidget(self.chk_system, 0, 2)
        filters.addWidget(self.chk_security, 0, 3)

        self.cmb_period = QComboBox()
        self.cmb_period.addItem("Últimas 24 horas", 24)
        self.cmb_period.addItem("Últimos 7 días", 24 * 7)
        self.cmb_period.addItem("Últimos 30 días", 24 * 30)
        self.cmb_period.addItem("Sin filtro temporal", 0)
        filters.addWidget(QLabel("Periodo:"), 1, 0)
        filters.addWidget(self.cmb_period, 1, 1)

        self.spn_max = QSpinBox()
        self.spn_max.setRange(10, 1000)
        self.spn_max.setValue(150)
        self.spn_max.setSingleStep(10)
        filters.addWidget(QLabel("Máx. eventos:"), 1, 2)
        filters.addWidget(self.spn_max, 1, 3)

        self.chk_info = QCheckBox("Incluir información")
        self.chk_info.setToolTip("Normalmente no hace falta. Puede devolver demasiados eventos.")
        filters.addWidget(self.chk_info, 1, 4)

        main_layout.addLayout(filters)

        # --- Filtros de nivel y riesgo ---
        filter_row = QHBoxLayout()

        self.cmb_filter_level = QComboBox()
        self.cmb_filter_level.addItem("Todos los niveles", "")
        self.cmb_filter_level.addItem("Crítico", "Crítico")
        self.cmb_filter_level.addItem("Error", "Error")
        self.cmb_filter_level.addItem("Advertencia", "Advertencia")
        self.cmb_filter_level.addItem("Información", "Información")
        self.cmb_filter_level.currentIndexChanged.connect(self.populate_table)

        self.cmb_filter_risk = QComboBox()
        self.cmb_filter_risk.addItem("Todos los riesgos", "")
        self.cmb_filter_risk.addItem("Alto", "Alto")
        self.cmb_filter_risk.addItem("Medio", "Medio")
        self.cmb_filter_risk.addItem("Bajo", "Bajo")
        self.cmb_filter_risk.addItem("Normal", "Normal")
        self.cmb_filter_risk.currentIndexChanged.connect(self.populate_table)

        filter_row.addWidget(QLabel("Nivel:"))
        filter_row.addWidget(self.cmb_filter_level)
        filter_row.addWidget(QLabel("Riesgo:"))
        filter_row.addWidget(self.cmb_filter_risk)
        filter_row.addStretch()
        main_layout.addLayout(filter_row)

        # --- Buscador ---
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("Buscar por origen, ID, mensaje o interpretación...")
        self.txt_search.textChanged.connect(self.populate_table)
        main_layout.addWidget(self.txt_search)

        # --- Botones fila 1 ---
        btn_layout1 = QHBoxLayout()

        self.btn_refresh = QPushButton("Actualizar")
        self.btn_refresh.clicked.connect(self.refresh_events)
        btn_layout1.addWidget(self.btn_refresh)

        self.btn_cancel = QPushButton("Cancelar lectura")
        self.btn_cancel.clicked.connect(self.cancel_loading)
        self.btn_cancel.setVisible(False)
        btn_layout1.addWidget(self.btn_cancel)

        self.btn_24h = QPushButton("Filtrar últimas 24h")
        self.btn_24h.clicked.connect(lambda: self.set_period_and_refresh(24))
        btn_layout1.addWidget(self.btn_24h)

        self.btn_7d = QPushButton("Filtrar últimos 7 días")
        self.btn_7d.clicked.connect(lambda: self.set_period_and_refresh(24 * 7))
        btn_layout1.addWidget(self.btn_7d)

        self.btn_detail = QPushButton("Ver detalle")
        self.btn_detail.clicked.connect(self.show_detail)
        btn_layout1.addWidget(self.btn_detail)

        self.btn_copy = QPushButton("Copiar evento")
        self.btn_copy.clicked.connect(self.copy_selected_event)
        btn_layout1.addWidget(self.btn_copy)

        main_layout.addLayout(btn_layout1)

        # --- Botones fila 2 ---
        btn_layout2 = QHBoxLayout()

        self.btn_csv = QPushButton("Exportar CSV")
        self.btn_csv.clicked.connect(self.export_csv)
        btn_layout2.addWidget(self.btn_csv)

        self.btn_html = QPushButton("Exportar HTML")
        self.btn_html.clicked.connect(self.export_html)
        btn_layout2.addWidget(self.btn_html)

        self.btn_pdf = QPushButton("Exportar PDF")
        self.btn_pdf.clicked.connect(self.export_pdf)
        btn_layout2.addWidget(self.btn_pdf)

        self.btn_open_viewer = QPushButton("Abrir Visor de eventos")
        self.btn_open_viewer.clicked.connect(self.open_windows_event_viewer)
        btn_layout2.addWidget(self.btn_open_viewer)

        self.btn_report = QPushButton("Añadir al informe técnico")
        self.btn_report.clicked.connect(self.add_to_technical_report)
        btn_layout2.addWidget(self.btn_report)

        main_layout.addLayout(btn_layout2)

        # --- Resumen ejecutivo ---
        self.lbl_summary = QLabel("Pulsa Actualizar para cargar eventos.")
        self.lbl_summary.setWordWrap(True)
        self.lbl_summary.setStyleSheet("font-weight: bold; padding: 4px;")
        main_layout.addWidget(self.lbl_summary)

        # --- Tabla ---
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels([
            "Fecha", "Nivel", "Origen", "ID Evento",
            "Registro", "Categoría", "Mensaje resumido", "Riesgo", "Interpretación",
        ])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.doubleClicked.connect(self.show_detail)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.Stretch)
        header.setSectionResizeMode(7, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(8, QHeaderView.Stretch)
        main_layout.addWidget(self.table)

        # --- Barra de estado ---
        self.status = QLabel("Pulsa Actualizar para leer los eventos.")
        self.status.setWordWrap(True)
        main_layout.addWidget(self.status)

        root.setLayout(main_layout)
        self.setCentralWidget(root)

    def selected_logs(self) -> list[str]:
        logs = []
        if self.chk_application.isChecked():
            logs.append("Application")
        if self.chk_system.isChecked():
            logs.append("System")
        if self.chk_security.isChecked():
            logs.append("Security")
        return logs

    def set_period_and_refresh(self, hours: int) -> None:
        for index in range(self.cmb_period.count()):
            if self.cmb_period.itemData(index) == hours:
                self.cmb_period.setCurrentIndex(index)
                break
        self.refresh_events()

    def refresh_events(self) -> None:
        logs = self.selected_logs()
        if not logs:
            QMessageBox.warning(self, "Sin registros", "Selecciona al menos un registro de eventos.")
            return

        hours = int(self.cmb_period.currentData())
        max_events = int(self.spn_max.value())
        include_info = self.chk_info.isChecked()

        self.set_buttons_enabled(False)
        self.btn_cancel.setVisible(True)
        self.status.setText("Leyendo eventos de Windows...")
        self.lbl_summary.setText("Cargando...")
        self.table.setRowCount(0)

        self.worker = EventWorker(logs=logs, hours=hours, max_events=max_events, include_info=include_info)
        self.worker.finished.connect(self.on_events_loaded)
        self.worker.failed.connect(self.on_events_failed)
        self.worker.start()

    def cancel_loading(self) -> None:
        if self.worker is not None:
            self.worker.cancel()
        self.btn_cancel.setVisible(False)
        self.status.setText("Cancelando lectura...")

    def set_buttons_enabled(self, enabled: bool) -> None:
        for button in (
            self.btn_refresh,
            self.btn_24h,
            self.btn_7d,
            self.btn_detail,
            self.btn_copy,
            self.btn_csv,
            self.btn_html,
            self.btn_pdf,
            self.btn_open_viewer,
            self.btn_report,
        ):
            button.setEnabled(enabled)

    def on_events_loaded(self, result: EventResult) -> None:
        self.events = result.events
        self.populate_table()
        self.set_buttons_enabled(True)
        self.btn_cancel.setVisible(False)

        summary = self.build_summary()
        self.lbl_summary.setText(summary)

        if result.warnings:
            warning_text = " | Avisos: " + " | ".join(
                clean_text(w, 160) for w in result.warnings[:3]
            )
            if len(result.warnings) > 3:
                warning_text += f" | {len(result.warnings) - 3} avisos más."
            self.status.setText(summary + warning_text)
        else:
            self.status.setText(summary)

    def on_events_failed(self, error: str) -> None:
        self.events = []
        self.visible_events = []
        self.table.setRowCount(0)
        self.set_buttons_enabled(True)
        self.btn_cancel.setVisible(False)
        self.lbl_summary.setText("Error al cargar eventos.")
        self.status.setText("No se pudieron leer los eventos.")
        QMessageBox.critical(self, "Error", error)

    def populate_table(self) -> None:
        search = self.txt_search.text().strip().lower()
        filter_level = self.cmb_filter_level.currentData()
        filter_risk = self.cmb_filter_risk.currentData()

        filtered: list[EventItem] = []
        for item in self.events:
            if filter_level and item.level != filter_level:
                continue
            if filter_risk and item.risk != filter_risk:
                continue
            if search:
                haystack = " ".join([
                    item.date, item.level, item.provider, item.event_id,
                    item.log_name, item.category, item.message, item.risk,
                    item.interpretation,
                ]).lower()
                if search not in haystack:
                    continue
            filtered.append(item)

        self.visible_events = filtered
        self.table.setRowCount(len(self.visible_events))

        for row, item in enumerate(self.visible_events):
            values = [
                item.date,
                item.level,
                item.provider,
                item.event_id,
                item.log_name,
                item.category,
                clean_text(item.message, 260),
                item.risk,
                item.interpretation,
            ]
            for col, value in enumerate(values):
                table_item = QTableWidgetItem(str(value))
                if col in {3, 7}:
                    table_item.setTextAlignment(Qt.AlignCenter)
                if col == 7:
                    self.apply_risk_style(table_item, item.risk)
                self.table.setItem(row, col, table_item)

        if self.events:
            self.lbl_summary.setText(self.build_summary())

    def apply_risk_style(self, table_item: QTableWidgetItem, risk: str) -> None:
        color = RISK_COLORS.get(risk)
        if color:
            table_item.setBackground(color)

    def build_summary(self) -> str:
        total = len(self.events)
        if total == 0:
            return "Sin eventos cargados."
        high = sum(1 for e in self.events if e.risk == "Alto")
        medium = sum(1 for e in self.events if e.risk == "Medio")
        low = sum(1 for e in self.events if e.risk == "Bajo")
        critical = sum(1 for e in self.events if e.level_number == 1)
        errors = sum(1 for e in self.events if e.level_number == 2)
        warnings_count = sum(1 for e in self.events if e.level_number == 3)
        visible = len(self.visible_events)
        shown = f" (mostrando {visible})" if visible != total else ""
        return (
            f"Eventos: {total}{shown} | "
            f"Críticos: {critical} | Errores: {errors} | Advertencias: {warnings_count} | "
            f"Riesgo alto: {high} | Riesgo medio: {medium} | Riesgo bajo: {low}"
        )

    def selected_event(self) -> EventItem | None:
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            return None
        row = selected[0].row()
        if row < 0 or row >= len(self.visible_events):
            return None
        return self.visible_events[row]

    def show_detail(self) -> None:
        item = self.selected_event()
        if item is None:
            QMessageBox.information(self, "Sin selección", "Selecciona un evento para ver el detalle.")
            return
        dialog = EventDetailDialog(item, self)
        dialog.exec_()

    def copy_selected_event(self) -> None:
        item = self.selected_event()
        if item is None:
            QMessageBox.information(self, "Sin selección", "Selecciona un evento para copiarlo.")
            return
        QApplication.clipboard().setText(item.detail_text())
        self.status.setText("Evento copiado al portapapeles.")

    def export_csv(self) -> None:
        if not self.events:
            QMessageBox.information(self, "Sin datos", "No hay eventos para exportar.")
            return
        default_name = f"eventos_windows_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.csv"
        file_path, _ = QFileDialog.getSaveFileName(self, "Exportar CSV", default_name, "CSV (*.csv)")
        if not file_path:
            return

        with open(file_path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow([
                "Fecha", "Nivel", "Origen", "ID Evento", "Registro",
                "Categoría", "Mensaje", "Riesgo", "Interpretación",
                "Equipo", "Record ID",
            ])
            for item in self.events:
                writer.writerow([
                    item.date, item.level, item.provider, item.event_id, item.log_name,
                    item.category, item.message, item.risk, item.interpretation,
                    item.computer, item.record_id,
                ])
        QMessageBox.information(self, "Exportado", "Eventos exportados correctamente en CSV.")

    def export_html(self) -> None:
        if not self.events:
            QMessageBox.information(self, "Sin datos", "No hay eventos para exportar.")
            return
        default_name = f"eventos_windows_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.html"
        file_path, _ = QFileDialog.getSaveFileName(self, "Exportar HTML", default_name, "HTML (*.html)")
        if not file_path:
            return

        Path(file_path).write_text(events_to_html(self.events), encoding="utf-8")
        QMessageBox.information(self, "Exportado", "Eventos exportados correctamente en HTML.")

    def export_pdf(self) -> None:
        if not self.events:
            QMessageBox.information(self, "Sin datos", "No hay eventos para exportar.")
            return
        if not _REPORTLAB_AVAILABLE:
            QMessageBox.warning(
                self,
                "ReportLab no disponible",
                "Para exportar PDF instala ReportLab:\n\npip install reportlab",
            )
            return
        default_name = f"eventos_windows_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.pdf"
        file_path, _ = QFileDialog.getSaveFileName(self, "Exportar PDF", default_name, "PDF (*.pdf)")
        if not file_path:
            return
        try:
            events_to_pdf(self.events, self.build_summary(), file_path)
            QMessageBox.information(self, "Exportado", "Eventos exportados correctamente en PDF.")
        except Exception as error:
            QMessageBox.critical(self, "Error al exportar PDF", str(error))

    def open_windows_event_viewer(self) -> None:
        try:
            subprocess.Popen(["eventvwr.msc"], shell=True)
        except Exception as error:
            QMessageBox.critical(self, "Error", f"No se pudo abrir el Visor de eventos:\n{error}")

    def add_to_technical_report(self) -> None:
        if not self.events:
            QMessageBox.information(self, "Sin datos", "No hay eventos para añadir al informe técnico.")
            return

        selected_events = sorted(
            self.events,
            key=lambda e: (RISK_ORDER.get(e.risk, 0), e.level_number in {1, 2}),
            reverse=True,
        )[:25]

        provider_counts = Counter(item.provider for item in self.events)
        top_providers = [{"provider": p, "count": c} for p, c in provider_counts.most_common(5)]

        summary_data = {
            "total": len(self.events),
            "critical": sum(1 for e in self.events if e.level_number == 1),
            "errors": sum(1 for e in self.events if e.level_number == 2),
            "warnings": sum(1 for e in self.events if e.level_number == 3),
            "high_risk": sum(1 for e in self.events if e.risk == "Alto"),
            "medium_risk": sum(1 for e in self.events if e.risk == "Medio"),
            "top_providers": top_providers,
        }

        snapshot_path = save_events_snapshot(selected_events, summary_data)
        QMessageBox.information(
            self,
            "Añadido al informe técnico",
            "Se ha guardado un resumen de eventos para el Informe Técnico del Equipo.\n\n"
            "Vuelve a generar el informe técnico y aparecerá una sección de eventos recientes.\n\n"
            f"Archivo interno:\n{snapshot_path}",
        )
