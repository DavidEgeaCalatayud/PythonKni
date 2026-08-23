from __future__ import annotations

import html
import json
import platform
import re
import subprocess
import threading
import time
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Iterable

from tools.app_paths import DATA_DIR, ensure_app_dirs

from .models import EventItem, EventResult

try:
    from reportlab.lib import colors as rl_colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

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

SUPPORTED_LOGS = ["Application", "System", "Security"]
WEVTUTIL_TIMEOUT_SECONDS = 25.0
WEVTUTIL_COMMUNICATE_SLICE_SECONDS = 0.2
WEVTUTIL_REAP_TIMEOUT_SECONDS = 5.0


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


def _kill_and_drain_process(proc: subprocess.Popen) -> tuple[bytes, bytes]:
    """Kill a child process if needed, drain both pipes, and always reap it."""
    try:
        if proc.poll() is None:
            proc.kill()
    except OSError:
        pass

    try:
        stdout_bytes, stderr_bytes = proc.communicate(timeout=WEVTUTIL_REAP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except OSError:
            pass
        stdout_bytes, stderr_bytes = proc.communicate()

    return stdout_bytes or b"", stderr_bytes or b""


def run_wevtutil(
    log_name: str,
    hours: int,
    max_events: int,
    include_info: bool,
    cancel_event: threading.Event | None = None,
) -> tuple[str, str]:
    query = build_event_query(hours=hours, include_info=include_info)
    command = [
        "wevtutil",
        "qe",
        log_name,
        f"/q:{query}",
        f"/c:{max_events}",
        "/rd:true",
        "/f:RenderedXml",
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

    deadline = time.monotonic() + WEVTUTIL_TIMEOUT_SECONDS
    stdout_bytes = b""
    stderr_bytes = b""

    while True:
        if cancel_event is not None and cancel_event.is_set():
            _kill_and_drain_process(proc)
            return "", "Cancelado por el usuario."

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _kill_and_drain_process(proc)
            return "", (
                f"Tiempo agotado leyendo {log_name}. "
                "Prueba con menos eventos o un filtro temporal menor."
            )

        try:
            stdout_bytes, stderr_bytes = proc.communicate(
                timeout=min(WEVTUTIL_COMMUNICATE_SLICE_SECONDS, remaining)
            )
            break
        except subprocess.TimeoutExpired:
            # communicate() keeps draining stdout/stderr while the child is alive.
            # Retrying after TimeoutExpired is explicitly supported and does not
            # lose output already read from either pipe.
            continue
        except Exception as error:
            _kill_and_drain_process(proc)
            return "", f"No se pudo leer la salida de wevtutil para {log_name}: {error}"

    stdout = decode_process_output(stdout_bytes or b"")
    stderr = decode_process_output(stderr_bytes or b"")

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
        parts = [
            clean_text(node.text) for node in userdata.iter() if node.text and clean_text(node.text)
        ]
        if parts:
            return " | ".join(parts)

    return (
        "Mensaje no disponible. Puede requerir permisos o componentes de Windows para renderizarse."
    )


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
        return (
            "Problema temporal de resolución DNS. Revisar DNS configurado, red, VPN o conectividad."
        )
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
        raise RuntimeError(
            f"No se pudo interpretar la salida XML de {fallback_log_name}: {error}"
        ) from error

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

        provider = clean_text(
            provider_node.attrib.get("Name", "Desconocido")
            if provider_node is not None
            else "Desconocido"
        )
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
        process_id = (
            execution_node.attrib.get("ProcessID", "-") if execution_node is not None else "-"
        )
        thread_id = (
            execution_node.attrib.get("ThreadID", "-") if execution_node is not None else "-"
        )
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


def events_to_html(
    events: list[EventItem], title: str = "Diagnóstico de eventos de Windows"
) -> str:
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
<p class="small">Generado: {datetime.now().strftime("%d/%m/%Y %H:%M:%S")}</p>
<table>
<thead>
<tr>
<th>Fecha</th><th>Nivel</th><th>Registro</th><th>Origen</th><th>ID Evento</th><th>Riesgo</th><th>Mensaje resumido</th><th>Interpretación</th>
</tr>
</thead>
<tbody>
{"".join(rows)}
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
    story.append(
        Paragraph(f"Generado: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}", styles["Normal"])
    )
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
        table_data.append(
            [
                Paragraph(html.escape(item.date), small),
                Paragraph(html.escape(item.level), small),
                Paragraph(html.escape(clean_text(item.provider, 35)), small),
                Paragraph(html.escape(item.event_id), small),
                Paragraph(html.escape(item.risk), small),
                Paragraph(html.escape(clean_text(item.interpretation, 120)), small),
            ]
        )
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
    EVENT_SNAPSHOT_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return EVENT_SNAPSHOT_FILE
