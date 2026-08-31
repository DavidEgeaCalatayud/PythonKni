from PyQt5.QtCore import QThread, pyqtSignal

from pythonkni.wifi_auditor import window
from pythonkni.wifi_auditor.models import (
    AccessPoint,
    AuditFinding,
    AuditPlanItem,
    AuditReport,
    CaptureInspection,
)


class FakeWorker(QThread):
    result = pyqtSignal(object)
    error = pyqtSignal(object)
    cancelled = pyqtSignal()

    instances = []

    def __init__(self, *args, **kwargs):
        super().__init__()
        self.args = args
        self.kwargs = kwargs
        self.running = False
        self.cancel_requested = False
        self.__class__.instances.append(self)

    def start(self):
        self.running = True

    def isRunning(self):
        return self.running

    def cancel(self):
        self.cancel_requested = True


def _report():
    point = AccessPoint(
        "Office",
        "aa:bb:cc:dd:ee:ff",
        "WPA2-Personal",
        "CCMP",
        87,
        36,
        "802.11ax",
        "5 GHz",
        "Infrastructure",
    )
    finding = AuditFinding(
        "medium",
        "Canal concurrido",
        "Detalle",
        "Revisar planificación",
        4,
    )
    plan = AuditPlanItem(
        50,
        "offline-capture-review",
        "Analizar evidencia offline",
        "Hay un baseline disponible.",
        "Importar una captura autorizada.",
    )
    return AuditReport(
        "fixed",
        96,
        (point,),
        (finding,),
        ("Limitación de prueba",),
        "a" * 64,
        (plan,),
    )


def test_tool_metadata_and_initial_state(qtbot):
    tool = window.Tool()
    qtbot.addWidget(tool)
    assert tool.name == "WiFi Auditor"
    assert tool.category == "Red"
    assert tool.table.columnCount() == 8
    assert tool.score_label.text() == "Score: —"
    assert tool.btn_scan.isEnabled()
    assert tool.btn_import_capture.isEnabled()
    assert not tool.btn_cancel.isEnabled()
    assert not tool.btn_export.isEnabled()
    assert "No captura credenciales" in tool.scope_label.text()
    assert "PCAP" in tool.capture_details.placeholderText()


def test_start_audit_wires_worker_and_rejects_overlap(qtbot, monkeypatch):
    FakeWorker.instances.clear()
    monkeypatch.setattr(window, "Worker", FakeWorker)
    tool = window.Tool()
    qtbot.addWidget(tool)

    assert tool.start_audit()
    worker = FakeWorker.instances[-1]
    assert worker.running
    assert tool.worker is worker
    assert not tool.btn_scan.isEnabled()
    assert not tool.btn_import_capture.isEnabled()
    assert tool.btn_cancel.isEnabled()
    assert "analizando" in tool.score_label.text()
    assert not tool.start_audit()
    assert not tool.start_capture_inspection("capture.pcap")

    tool.cancel_audit()
    assert worker.cancel_requested
    assert not tool.btn_cancel.isEnabled()
    worker.running = False
    tool.worker = None


def test_choose_capture_cancel_and_success(qtbot, monkeypatch):
    FakeWorker.instances.clear()
    monkeypatch.setattr(window, "Worker", FakeWorker)
    tool = window.Tool()
    qtbot.addWidget(tool)

    monkeypatch.setattr(window.QFileDialog, "getOpenFileName", lambda *args: ("", ""))
    assert not tool.choose_capture()
    assert not FakeWorker.instances

    monkeypatch.setattr(
        window.QFileDialog,
        "getOpenFileName",
        lambda *args: ("sample.pcapng", "Capturas WiFi"),
    )
    assert tool.choose_capture()
    worker = FakeWorker.instances[-1]
    assert worker.args[1] == "sample.pcapng"
    assert "Analizando captura" in tool.capture_details.toPlainText()
    assert not tool.btn_import_capture.isEnabled()
    worker.running = False
    tool.worker = None


def test_choose_capture_rejects_when_busy(qtbot):
    tool = window.Tool()
    qtbot.addWidget(tool)
    worker = FakeWorker()
    worker.running = True
    tool.worker = worker
    assert not tool.choose_capture()
    worker.running = False
    tool.worker = None


def test_cancel_audit_is_noop_without_active_worker(qtbot):
    tool = window.Tool()
    qtbot.addWidget(tool)
    tool.cancel_audit()
    assert tool.worker is None


def test_audit_result_populates_table_findings_plan_and_digest(qtbot):
    tool = window.Tool()
    qtbot.addWidget(tool)
    report = _report()

    tool.on_audit_result(report)

    assert tool.report is report
    assert tool.score_label.text() == "Score: 96/100"
    assert tool.table.rowCount() == 1
    assert tool.table.item(0, 0).text() == "Office"
    assert tool.table.item(0, 2).text() == "5 GHz"
    assert tool.table.item(0, 3).text() == "36"
    assert tool.table.item(0, 4).text() == "87%"
    assert tool.table.item(0, 7).text() == "Good"
    text = tool.findings.toPlainText()
    assert "Canal concurrido" in text
    assert "Plan automático defensivo" in text
    assert "Analizar evidencia offline" in text
    assert "SHA-256 evidencia" in text
    assert "Limitación de prueba" in text
    assert tool.btn_export.isEnabled()


def test_audit_result_handles_missing_optional_radio_values_and_empty_plan(qtbot):
    tool = window.Tool()
    qtbot.addWidget(tool)
    point = AccessPoint("Hidden", "aa", "Unknown", "Unknown")
    report = AuditReport("fixed", 100, (point,), (), (), "b" * 64)
    tool.on_audit_result(report)
    assert tool.table.item(0, 3).text() == ""
    assert tool.table.item(0, 4).text() == ""
    assert tool.table.item(0, 7).text() == "Unknown"
    assert "Plan automático defensivo" not in tool.findings.toPlainText()


def test_capture_result_renders_builtin_and_tshark_metadata(qtbot):
    tool = window.Tool()
    qtbot.addWidget(tool)

    builtin = CaptureInspection("sample.pcap", "pcap", 123, "c" * 64)
    tool.on_capture_result(builtin)
    assert tool.capture_inspection is builtin
    text = tool.capture_details.toPlainText()
    assert "pcap" in text
    assert "123 bytes" in text
    assert "no disponible" in text
    assert "No se extraen hashes" in text

    tshark = CaptureInspection("sample.pcapng", "pcapng", 456, "d" * 64, 4, 9, "tshark")
    tool.on_capture_result(tshark)
    text = tool.capture_details.toPlainText()
    assert "Tramas EAPOL observadas: 4" in text
    assert "Tramas RSN observadas: 9" in text
    assert "Analizador: tshark" in text


def test_audit_and_capture_cancelled_update_state(qtbot):
    tool = window.Tool()
    qtbot.addWidget(tool)
    tool.on_audit_cancelled()
    assert tool.score_label.text() == "Score: cancelado"
    assert "cancelada" in tool.findings.toPlainText().lower()

    tool.on_capture_cancelled()
    assert "cancelado" in tool.capture_details.toPlainText().lower()


def test_audit_error_preserves_exception_details(qtbot, monkeypatch):
    tool = window.Tool()
    qtbot.addWidget(tool)
    calls = []
    monkeypatch.setattr(window, "show_error", lambda *args, **kwargs: calls.append((args, kwargs)))
    error = OSError("radio unavailable")
    tool.on_audit_error(error)
    assert tool.score_label.text() == "Score: error"
    assert calls[-1][1]["error"] is error
    assert "radio unavailable" not in calls[-1][0][2]


def test_audit_error_accepts_non_exception_details(qtbot, monkeypatch):
    tool = window.Tool()
    qtbot.addWidget(tool)
    calls = []
    monkeypatch.setattr(window, "show_error", lambda *args, **kwargs: calls.append((args, kwargs)))
    tool.on_audit_error("diagnostic")
    assert calls[-1][1]["details"] == "diagnostic"


def test_capture_error_preserves_exception_or_details(qtbot, monkeypatch):
    tool = window.Tool()
    qtbot.addWidget(tool)
    calls = []
    monkeypatch.setattr(window, "show_error", lambda *args, **kwargs: calls.append((args, kwargs)))

    error = ValueError("bad capture")
    tool.on_capture_error(error)
    assert calls[-1][1]["error"] is error
    assert "bad capture" not in calls[-1][0][2]
    assert "No se pudo" in tool.capture_details.toPlainText()

    tool.on_capture_error("diagnostic")
    assert calls[-1][1]["details"] == "diagnostic"


def test_export_requires_report(qtbot, monkeypatch):
    tool = window.Tool()
    qtbot.addWidget(tool)
    info = []
    monkeypatch.setattr(window.QMessageBox, "information", lambda *args: info.append(args))
    tool.export_current_report()
    assert "primero" in info[-1][2].lower()


def test_export_cancel_is_noop(qtbot, monkeypatch):
    tool = window.Tool()
    qtbot.addWidget(tool)
    tool.report = _report()
    monkeypatch.setattr(window.QFileDialog, "getSaveFileName", lambda *args: ("", ""))
    exported = []
    monkeypatch.setattr(window, "export_report", lambda *args: exported.append(args))
    tool.export_current_report()
    assert exported == []


def test_export_success_and_failure(qtbot, monkeypatch):
    tool = window.Tool()
    qtbot.addWidget(tool)
    tool.report = _report()
    monkeypatch.setattr(window.QFileDialog, "getSaveFileName", lambda *args: ("audit.json", "JSON"))
    info = []
    errors = []
    monkeypatch.setattr(window.QMessageBox, "information", lambda *args: info.append(args))
    monkeypatch.setattr(window, "show_error", lambda *args, **kwargs: errors.append((args, kwargs)))

    monkeypatch.setattr(window, "export_report", lambda path, report: path)
    tool.export_current_report()
    assert "correctamente" in info[-1][2].lower()

    failure = OSError("disk full")
    monkeypatch.setattr(
        window, "export_report", lambda path, report: (_ for _ in ()).throw(failure)
    )
    tool.export_current_report()
    assert errors[-1][1]["error"] is failure


def test_worker_finished_ignores_stale_and_clears_current(qtbot):
    tool = window.Tool()
    qtbot.addWidget(tool)
    current = FakeWorker()
    stale = FakeWorker()
    tool.worker = current
    tool.report = _report()

    tool._on_worker_finished(stale)
    assert tool.worker is current

    tool._on_worker_finished(current)
    assert tool.worker is None
    assert tool.btn_scan.isEnabled()
    assert tool.btn_import_capture.isEnabled()
    assert tool.btn_export.isEnabled()
