import json
import subprocess
import threading
import xml.etree.ElementTree as ET

import pytest

from pythonkni.event_viewer import service as events
from pythonkni.event_viewer.models import EventItem


def make_item(**overrides):
    values = {
        "date": "30/08/2026 10:00:00",
        "level": "Error",
        "level_number": 2,
        "provider": "Disk",
        "event_id": "7",
        "category": "Storage",
        "message": "Disk error",
        "risk": "Alto",
        "interpretation": "Check disk",
        "log_name": "System",
        "record_id": "42",
        "computer": "TEST-PC",
        "process_id": "4",
        "thread_id": "8",
        "raw_xml": "<Event />",
        "timestamp_sort": "20260830100000",
    }
    values.update(overrides)
    return EventItem(**values)


def test_is_windows_and_clean_text(monkeypatch):
    monkeypatch.setattr(events.platform, "system", lambda: "Windows")
    assert events.is_windows()
    monkeypatch.setattr(events.platform, "system", lambda: "Linux")
    assert not events.is_windows()

    assert events.clean_text(None) == ""
    assert events.clean_text("  many\n spaces  ") == "many spaces"
    assert events.clean_text("abcdefgh", max_len=6) == "abc..."


def test_xml_child_helpers_handle_namespaces_and_defaults():
    root = ET.fromstring(
        '<Root xmlns="urn:test"><Child attr=" value "> text </Child>'
        "<Nested><Target>x</Target></Nested></Root>"
    )
    child = events.first_child(root, "Child")
    assert child is not None
    assert events.child_text(root, "Child") == "text"
    assert events.child_attr(root, "Child", "attr") == "value"
    assert events.find_child(root, "Target").text == "x"
    assert events.first_child(None, "Child") is None
    assert events.find_child(None, "Child") is None
    assert events.child_text(root, "Missing", "fallback") == "fallback"
    assert events.child_attr(root, "Missing", "attr", "fallback") == "fallback"


@pytest.mark.parametrize(
    ("value", "expected_display", "has_sort"),
    [
        ("", "No disponible", False),
        ("not-a-date", "not-a-date", False),
        ("2026-08-30T08:00:00Z", "30/08/2026", True),
        ("2026-08-30T08:00:00.1234567+00:00", "30/08/2026", True),
    ],
)
def test_parse_windows_time_variants(value, expected_display, has_sort):
    display, sort_key = events.parse_windows_time(value)
    assert expected_display in display
    assert bool(sort_key) is has_sort


def test_decode_process_output_supports_common_encodings():
    assert events.decode_process_output("áé".encode("utf-8-sig")) == "áé"
    assert events.decode_process_output("hello".encode("utf-16")) == "hello"


def test_build_event_query_without_time_or_information():
    query = events.build_event_query(hours=0, include_info=False)
    assert "Level=1" in query
    assert "Level=4" not in query
    assert "TimeCreated" not in query


class FakeProcess:
    def __init__(self, *, returncode=0, stdout=b"", stderr=b"", communicate_error=None):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.communicate_error = communicate_error
        self.killed = False
        self.communicate_calls = 0

    def communicate(self, timeout=None):
        del timeout
        self.communicate_calls += 1
        if self.communicate_error is not None:
            error = self.communicate_error
            self.communicate_error = None
            raise error
        return self.stdout, self.stderr

    def poll(self):
        return None if not self.killed else self.returncode

    def kill(self):
        self.killed = True


def test_run_wevtutil_reports_process_creation_error(monkeypatch):
    def fail(*_args, **_kwargs):
        raise OSError("missing executable")

    monkeypatch.setattr(events.subprocess, "Popen", fail)
    output, warning = events.run_wevtutil("System", 24, 10, False)
    assert output == ""
    assert "No se pudo ejecutar wevtutil" in warning


def test_run_wevtutil_handles_unexpected_communicate_error(monkeypatch):
    proc = FakeProcess(communicate_error=OSError("pipe closed"))
    monkeypatch.setattr(events.subprocess, "Popen", lambda *_args, **_kwargs: proc)
    monkeypatch.setattr(events.time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(events, "WEVTUTIL_TIMEOUT_SECONDS", 10.0)

    output, warning = events.run_wevtutil("System", 24, 10, False)

    assert output == ""
    assert "No se pudo leer la salida" in warning
    assert proc.killed


def test_run_wevtutil_treats_no_events_as_success(monkeypatch):
    proc = FakeProcess(returncode=1, stderr=b"No events were found")
    monkeypatch.setattr(events.subprocess, "Popen", lambda *_args, **_kwargs: proc)
    monkeypatch.setattr(events.time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(events, "WEVTUTIL_TIMEOUT_SECONDS", 10.0)

    output, warning = events.run_wevtutil("System", 24, 10, False)
    assert output == ""
    assert warning == ""


def test_run_wevtutil_uses_generic_failure_when_process_has_no_output(monkeypatch):
    proc = FakeProcess(returncode=2)
    monkeypatch.setattr(events.subprocess, "Popen", lambda *_args, **_kwargs: proc)
    monkeypatch.setattr(events.time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(events, "WEVTUTIL_TIMEOUT_SECONDS", 10.0)

    output, warning = events.run_wevtutil("Application", 24, 10, False)
    assert output == ""
    assert warning == "No se pudo leer el registro Application."


def test_kill_and_drain_retries_after_reap_timeout():
    class SlowProcess(FakeProcess):
        def communicate(self, timeout=None):
            self.communicate_calls += 1
            if self.communicate_calls == 1:
                raise subprocess.TimeoutExpired("wevtutil", timeout)
            return b"out", b"err"

    proc = SlowProcess(returncode=-9)
    stdout, stderr = events._kill_and_drain_process(proc)
    assert (stdout, stderr) == (b"out", b"err")
    assert proc.killed
    assert proc.communicate_calls == 2


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", "<Events />"),
        ("<?xml version='1.0'?><Event><System /></Event>", "<Events><Event>"),
        ("<Events><Event /></Events>", "<Events>"),
    ],
)
def test_normalize_xml_output(raw, expected):
    assert expected in events.normalize_xml_output(raw)


def test_rendered_message_falls_back_to_event_data():
    event = ET.fromstring(
        "<Event><EventData><Data Name='Device'>Disk 0</Data>"
        "<Data>failed</Data></EventData></Event>"
    )
    assert events.rendered_message(event) == "Device: Disk 0 | Dato: failed"


def test_rendered_message_falls_back_to_user_data_and_default():
    user_event = ET.fromstring(
        "<Event><UserData><Root><Value>  value  </Value></Root></UserData></Event>"
    )
    assert "value" in events.rendered_message(user_event)

    empty_event = ET.fromstring("<Event><System /></Event>")
    assert "Mensaje no disponible" in events.rendered_message(empty_event)


@pytest.mark.parametrize(
    ("provider", "event_id", "level", "message", "needle"),
    [
        ("Disk", "7", 2, "I/O", "problema de disco"),
        ("Disk", "1", 4, "info", "almacenamiento"),
        ("Ntfs", "55", 2, "fs", "sistema de archivos"),
        ("Microsoft-Windows-WHEA-Logger", "18", 2, "hardware", "hardware"),
        ("BugCheck", "1001", 2, "bugcheck", "pantallazo"),
        ("Service Control Manager", "7000", 2, "service", "servicio de Windows"),
        ("Service Control Manager", "1", 4, "service", "servicios de Windows"),
        ("Application Error", "1000", 2, "crash", "cerró inesperadamente"),
        ("Application Hang", "1002", 3, "hang", "dejó de responder"),
        ("DNS Client Events", "1014", 3, "dns", "resolución DNS"),
        ("WindowsUpdateClient", "20", 2, "update", "Windows Update"),
        ("EventLog", "6008", 2, "shutdown", "apagado inesperado"),
        (
            "Microsoft-Windows-Security-Auditing",
            "4625",
            2,
            "login",
            "inicio de sesión",
        ),
        ("Other", "1", 1, "critical", "Evento crítico"),
        ("Other", "2", 2, "error", "Error de sistema"),
        ("Other", "3", 3, "warning", "Advertencia"),
        ("Other", "4", 4, "info", "informativo"),
    ],
)
def test_interpret_event_rule_matrix(provider, event_id, level, message, needle):
    assert needle in events.interpret_event(provider, event_id, level, message)


@pytest.mark.parametrize(
    ("provider", "event_id", "level", "message", "expected"),
    [
        ("Other", "1", 1, "critical", "Alto"),
        ("Kernel-Power", "41", 2, "shutdown", "Alto"),
        ("Disk", "129", 3, "disk", "Alto"),
        ("Ntfs", "55", 3, "fs", "Alto"),
        ("WHEA-Logger", "18", 3, "hardware", "Alto"),
        ("Other", "1", 4, "blue screen happened", "Alto"),
        ("EventLog", "6008", 3, "shutdown", "Alto"),
        ("Other", "2", 2, "error", "Medio"),
        ("Service Control Manager", "7001", 4, "service", "Medio"),
        ("DNS Client Events", "1014", 4, "dns", "Medio"),
        ("WindowsUpdateClient", "20", 4, "update", "Medio"),
        ("Security-Auditing", "4776", 4, "login", "Medio"),
        ("Other", "3", 3, "warning", "Bajo"),
        ("Other", "4", 4, "info", "Normal"),
    ],
)
def test_classify_risk_rule_matrix(provider, event_id, level, message, expected):
    assert events.classify_risk(provider, event_id, level, message) == expected


def test_parse_events_xml_rejects_malformed_xml():
    with pytest.raises(RuntimeError, match="No se pudo interpretar"):
        events.parse_events_xml("<Event>", "System")


def test_parse_events_xml_handles_missing_and_invalid_fields():
    xml = """
    <Event>
      <System>
        <Level>not-a-number</Level>
        <TimeCreated SystemTime="invalid" />
      </System>
      <EventData><Data Name="Code">123</Data></EventData>
    </Event>
    """
    result = events.parse_events_xml(xml, "Application")
    assert len(result) == 1
    item = result[0]
    assert item.provider == "Desconocido"
    assert item.event_id == "-"
    assert item.level_number == 0
    assert item.level == "not-a-number"
    assert item.log_name == "Application"
    assert item.date == "invalid"
    assert item.message == "Code: 123"
    assert item.process_id == "-"
    assert item.thread_id == "-"


def test_parse_events_xml_raw_xml_failure_is_non_fatal(monkeypatch):
    xml = (
        "<Event><System><Provider Name='Test'/><EventID>4</EventID>"
        "<Level>4</Level></System></Event>"
    )

    def fail(*_args, **_kwargs):
        raise RuntimeError("serialize")

    monkeypatch.setattr(events.ET, "tostring", fail)
    item = events.parse_events_xml(xml, "System")[0]
    assert item.raw_xml == ""


def test_collect_events_rejects_non_windows(monkeypatch):
    monkeypatch.setattr(events, "is_windows", lambda: False)
    with pytest.raises(RuntimeError, match="Windows"):
        events.collect_events(["System"], 24, 10)


def test_collect_events_skips_unsupported_warnings_empty_and_parse_errors(monkeypatch):
    monkeypatch.setattr(events, "is_windows", lambda: True)
    calls = []

    def fake_run(log_name, **_kwargs):
        calls.append(log_name)
        if log_name == "Application":
            return "", "access denied"
        if log_name == "System":
            return "", ""
        return "<Event>", ""

    monkeypatch.setattr(events, "SUPPORTED_LOGS", ["Application", "System", "Security"])
    monkeypatch.setattr(events, "run_wevtutil", fake_run)

    result = events.collect_events(
        ["Unsupported", "Application", "System", "Security"], hours=24, max_events=10
    )

    assert calls == ["Application", "System", "Security"]
    assert any("Application: access denied" in warning for warning in result.warnings)
    assert any("No se pudo interpretar" in warning for warning in result.warnings)
    assert result.events == []


def test_collect_events_stops_on_cancellation_warning(monkeypatch):
    monkeypatch.setattr(events, "is_windows", lambda: True)
    calls = []

    def fake_run(log_name, **_kwargs):
        calls.append(log_name)
        return "", "Cancelado por el usuario."

    monkeypatch.setattr(events, "run_wevtutil", fake_run)
    result = events.collect_events(["Application", "System"], 24, 10)
    assert calls == ["Application"]
    assert result.events == []
    assert result.warnings == []


def test_collect_events_honours_pre_set_cancel_event(monkeypatch):
    monkeypatch.setattr(events, "is_windows", lambda: True)
    cancel = threading.Event()
    cancel.set()
    calls = []
    monkeypatch.setattr(events, "run_wevtutil", lambda *args, **kwargs: calls.append(args))
    result = events.collect_events(["System"], 24, 10, cancel_event=cancel)
    assert calls == []
    assert result.events == []


def test_events_to_pdf_requires_reportlab(monkeypatch, tmp_path):
    monkeypatch.setattr(events, "_REPORTLAB_AVAILABLE", False)
    with pytest.raises(RuntimeError, match="ReportLab"):
        events.events_to_pdf([], "summary", str(tmp_path / "out.pdf"))


def test_events_to_pdf_generates_document_with_multiple_risks(tmp_path):
    output = tmp_path / "events.pdf"
    sample = [
        make_item(provider="Disk", risk="Alto"),
        make_item(provider="DNS Client Events", event_id="1014", risk="Medio"),
        make_item(provider="Other", event_id="3", risk="Bajo"),
        make_item(provider="Other", event_id="4", risk="Normal"),
    ]

    events.events_to_pdf(sample, "4 eventos | 1 crítico", str(output))

    assert output.exists()
    assert output.stat().st_size > 500
    assert output.read_bytes().startswith(b"%PDF")


def test_save_events_snapshot_serializes_dataclasses(monkeypatch, tmp_path):
    snapshot = tmp_path / "event_report_snapshot.json"
    calls = []
    monkeypatch.setattr(events, "EVENT_SNAPSHOT_FILE", snapshot)
    monkeypatch.setattr(events, "ensure_app_dirs", lambda: calls.append("ensure"))

    result = events.save_events_snapshot([make_item()], summary={"high": 1})

    payload = json.loads(snapshot.read_text(encoding="utf-8"))
    assert result == snapshot
    assert calls == ["ensure"]
    assert payload["source"] == "Visor de eventos de Windows"
    assert payload["summary"] == {"high": 1}
    assert payload["events"][0]["provider"] == "Disk"
