from PyQt5.QtCore import QThread, pyqtSignal

from pythonkni.wifi_auditor import window
from pythonkni.wifi_auditor.models import AccessPoint, AuditFinding, AuditReport


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
    return AuditReport(
        "fixed",
        96,
        (point,),
        (finding,),
        ("Limitación de prueba",),
        "a" * 64,
    )


def test_tool_metadata_and_initial_state(qtbot):
    tool = window.Tool()
    qtbot.addWidget(tool)
    assert tool.name == "WiFi Auditor"
    assert tool.category == "Red"
    assert tool.table.columnCount() == 8
    assert tool.score_label.text() == "Score: —"
    assert tool.btn_scan.isEnabled()
    assert not tool.btn_cancel.isEnabled()
    assert not tool.btn_export.isEnabled()
    assert "No captura credenciales" in tool.scope_label.text()


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
    assert tool.btn_cancel.isEnabled()
    assert "analizando" in tool.score_label.text()
    assert not tool.start_audit()

    tool.cancel_audit()
    assert worker.cancel_requested
    assert not tool.btn_cancel.isEnabled()
    worker.running = False
    tool.worker = None


def test_cancel_audit_is_noop_without_active_worker(qtbot):
    tool = window.Tool()
    qtbot.addWidget(tool)
    tool.cancel_audit()
    assert tool.worker is None


def test_audit_result_populates_table_findings_and_digest(qtbot):
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
    assert "SHA-256 evidencia" in text
    assert "Limitación de prueba" in text
    assert tool.btn_export.isEnabled()


def test_audit_result_handles_missing_optional_radio_values(qtbot):
    tool = window.Tool()
    qtbot.addWidget(tool)
    point = AccessPoint("Hidden", "aa", "Unknown", "Unknown")
    report = AuditReport("fixed", 100, (point,), (), (), "b" * 64)
    tool.on_audit_result(report)
    assert tool.table.item(0, 3).text() == ""
    assert tool.table.item(0, 4).text() == ""
    assert tool.table.item(0, 7).text() == "Unknown"


def test_audit_cancelled_updates_state(qtbot):
    tool = window.Tool()
    qtbot.addWidget(tool)
    tool.on_audit_cancelled()
    assert tool.score_label.text() == "Score: cancelado"
    assert "cancelada" in tool.findings.toPlainText().lower()


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
    monkeypatch.setattr(window, "export_report", lambda path, report: (_ for _ in ()).throw(failure))
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
    assert tool.btn_export.isEnabled()
