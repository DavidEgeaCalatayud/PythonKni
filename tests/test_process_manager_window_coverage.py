from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import QMessageBox

from pythonkni.process_manager import window as process_window


class FakeWorker(QThread):
    progress = pyqtSignal(object)
    result = pyqtSignal(object)
    error = pyqtSignal(object)
    cancelled = pyqtSignal()

    instances = []

    def __init__(self, *args, parent=None, **kwargs):
        super().__init__(parent)
        self.args = args
        self.kwargs = kwargs
        self.running = False
        self.cancel_requested = False
        self.deleted = False
        self.__class__.instances.append(self)

    def start(self):
        self.running = True

    def isRunning(self):
        return self.running

    def cancel(self):
        self.cancel_requested = True

    def deleteLater(self):
        self.deleted = True


def _tool(qtbot, monkeypatch):
    monkeypatch.setattr(process_window.Tool, "load_processes", lambda self: None)
    tool = process_window.Tool()
    qtbot.addWidget(tool)
    return tool


def _details(pid=1234, name="demo.exe", username="David"):
    return process_window.ProcessDetails(
        pid=pid,
        name=name,
        exe_path=f"C:/Apps/{name}",
        username=username,
        create_time=10.0,
    )


def test_process_load_callbacks_ignore_stale_worker_and_update_current(qtbot, monkeypatch):
    tool = _tool(qtbot, monkeypatch)
    current = FakeWorker(parent=tool)
    stale = FakeWorker(parent=tool)
    tool._process_worker = current
    populated = []
    monkeypatch.setattr(tool, "populate_table", lambda rows: populated.append(rows))
    feedback = []
    monkeypatch.setattr(
        process_window,
        "show_error",
        lambda *args, **kwargs: feedback.append((args, kwargs)),
    )

    tool._process_load_result(stale, [(1, "stale", 0.0, 0.0)])
    tool._process_load_error(stale, RuntimeError("stale"))
    tool._process_load_cancelled(stale)
    assert populated == []
    assert feedback == []

    rows = [(2, "current", 1.0, 2.0)]
    tool._process_load_result(current, rows)
    assert populated == [rows]

    error = PermissionError("blocked")
    tool._process_load_error(current, error)
    assert feedback[-1][1]["error"] is error

    tool._process_load_cancelled(current)
    assert tool.loading_text.text() == "Actualización cancelada"


def test_process_load_finished_current_and_stale(qtbot, monkeypatch):
    tool = _tool(qtbot, monkeypatch)
    current = FakeWorker(parent=tool)
    stale = FakeWorker(parent=tool)
    tool._process_worker = current
    tool.loading_widget.show()
    tool.loading_movie.start()

    tool._process_load_finished(stale)
    assert tool._process_worker is current
    assert stale.deleted

    tool._process_load_finished(current)
    assert tool._process_worker is None
    assert tool.loading_widget.isHidden()
    assert current.deleted


def test_populate_table_formats_rows_and_analyze_button(qtbot, monkeypatch):
    tool = _tool(qtbot, monkeypatch)
    analyzed = []
    monkeypatch.setattr(tool, "analyze_process", analyzed.append)

    tool.populate_table([(42, "demo.exe", 12.34, 5.67)])

    assert tool.table.rowCount() == 1
    assert tool.table.item(0, 0).text() == "42"
    assert tool.table.item(0, 1).text() == "demo.exe"
    assert tool.table.item(0, 2).text() == "12.3"
    assert tool.table.item(0, 3).text() == "5.7"
    button = tool.table.cellWidget(0, 4)
    assert button.text() == "Analizar"
    button.click()
    assert analyzed == [42]


def test_kill_process_requires_selection(qtbot, monkeypatch):
    tool = _tool(qtbot, monkeypatch)
    warnings = []
    monkeypatch.setattr(
        process_window.QMessageBox,
        "warning",
        lambda *args: warnings.append(args),
    )

    tool.kill_process()

    assert warnings[-1][1:] == ("Error", "Selecciona un proceso primero.")


def test_kill_process_handles_unavailable_target(qtbot, monkeypatch):
    tool = _tool(qtbot, monkeypatch)
    tool.populate_table([(123, "gone.exe", 0.0, 0.0)])
    tool.table.selectRow(0)
    monkeypatch.setattr(
        process_window,
        "get_termination_target",
        lambda _pid: (_ for _ in ()).throw(process_window.ProcessUnavailableError("gone")),
    )
    warnings = []
    monkeypatch.setattr(
        process_window.QMessageBox,
        "warning",
        lambda *args: warnings.append(args),
    )

    tool.kill_process()

    assert warnings[-1][1] == "Proceso no disponible"
    assert "gone" in warnings[-1][2]


def test_kill_process_system_confirmation_and_success(qtbot, monkeypatch):
    tool = _tool(qtbot, monkeypatch)
    details = _details(name="svchost.exe", username=r"NT AUTHORITY\SYSTEM")
    tool.populate_table([(details.pid, details.name, 0.0, 0.0)])
    tool.table.selectRow(0)
    monkeypatch.setattr(process_window, "get_termination_target", lambda _pid: details)
    monkeypatch.setattr(process_window, "is_system_process", lambda _details: True)
    questions = []
    monkeypatch.setattr(
        process_window.QMessageBox,
        "question",
        lambda *args: questions.append(args) or QMessageBox.Yes,
    )
    terminated = []
    monkeypatch.setattr(process_window, "terminate_process", terminated.append)
    info = []
    monkeypatch.setattr(
        process_window.QMessageBox,
        "information",
        lambda *args: info.append(args),
    )
    reloaded = []
    monkeypatch.setattr(tool, "load_processes", lambda: reloaded.append(True))

    tool.kill_process()

    assert len(questions) == 2
    assert details.username in questions[-1][2]
    assert terminated == [details]
    assert info[-1][1] == "Éxito"
    assert reloaded == [True]


def test_kill_process_handles_termination_domain_errors(qtbot, monkeypatch):
    tool = _tool(qtbot, monkeypatch)
    details = _details()
    tool.populate_table([(details.pid, details.name, 0.0, 0.0)])
    tool.table.selectRow(0)
    monkeypatch.setattr(process_window, "get_termination_target", lambda _pid: details)
    monkeypatch.setattr(process_window, "is_system_process", lambda _details: False)
    monkeypatch.setattr(
        process_window.QMessageBox,
        "question",
        lambda *args: QMessageBox.Yes,
    )
    warnings = []
    critical = []
    monkeypatch.setattr(
        process_window.QMessageBox,
        "warning",
        lambda *args: warnings.append(args),
    )
    monkeypatch.setattr(
        process_window.QMessageBox,
        "critical",
        lambda *args: critical.append(args),
    )

    monkeypatch.setattr(
        process_window,
        "terminate_process",
        lambda _details: (_ for _ in ()).throw(process_window.OwnProcessTerminationError("self")),
    )
    tool.kill_process()
    assert warnings[-1][1] == "Proceso protegido"

    monkeypatch.setattr(
        process_window,
        "terminate_process",
        lambda _details: (_ for _ in ()).throw(process_window.ProcessUnavailableError("gone")),
    )
    tool.kill_process()
    assert critical[-1][1] == "Error"
    assert "gone" in critical[-1][2]


def test_analyze_process_requires_key_and_rejects_overlap(qtbot, monkeypatch):
    tool = _tool(qtbot, monkeypatch)
    warnings = []
    info = []
    monkeypatch.setattr(
        process_window.QMessageBox,
        "warning",
        lambda *args: warnings.append(args),
    )
    monkeypatch.setattr(
        process_window.QMessageBox,
        "information",
        lambda *args: info.append(args),
    )

    monkeypatch.setattr(process_window, "get_vt_api_key", lambda: "")
    tool.analyze_process(1)
    assert warnings[-1][1] == "VirusTotal"

    monkeypatch.setattr(process_window, "get_vt_api_key", lambda: "key")
    worker = FakeWorker(parent=tool)
    worker.running = True
    tool._analysis_worker = worker
    tool.analyze_process(2)
    assert info[-1][1] == "VirusTotal"
    assert "curso" in info[-1][2]
    worker.running = False
    tool._analysis_worker = None


def test_analyze_process_wires_worker_and_cancel(qtbot, monkeypatch):
    FakeWorker.instances.clear()
    tool = _tool(qtbot, monkeypatch)
    monkeypatch.setattr(process_window, "Worker", FakeWorker)
    monkeypatch.setattr(process_window, "get_vt_api_key", lambda: "key")

    tool.analyze_process(77)

    worker = FakeWorker.instances[-1]
    assert worker.args[0] is process_window.analyze_process_task
    assert worker.args[1:] == (77, "key")
    assert worker.running
    assert tool._analysis_worker is worker
    assert tool.analysis_status.text() == "Analizando PID 77..."
    assert tool.btn_cancel_analysis.isEnabled()

    tool.cancel_analysis()
    assert worker.cancel_requested
    assert tool.analysis_status.text() == "Cancelando análisis..."
    assert not tool.btn_cancel_analysis.isEnabled()
    worker.running = False
    tool._analysis_worker = None


def test_cancel_analysis_is_noop_without_running_worker(qtbot, monkeypatch):
    tool = _tool(qtbot, monkeypatch)
    tool.cancel_analysis()
    worker = FakeWorker(parent=tool)
    tool._analysis_worker = worker
    worker.running = False
    tool.cancel_analysis()
    assert not worker.cancel_requested
    tool._analysis_worker = None


def test_analysis_progress_variants(qtbot, monkeypatch):
    tool = _tool(qtbot, monkeypatch)

    tool._analysis_progress({"message": "Hashing"})
    assert tool.analysis_status.text() == "Hashing"
    tool._analysis_progress({})
    assert tool.analysis_status.text() == "Analizando..."
    tool._analysis_progress("Uploading hash")
    assert tool.analysis_status.text() == "Uploading hash"


def test_analysis_results_not_found_and_http_error(qtbot, monkeypatch):
    tool = _tool(qtbot, monkeypatch)
    warnings = []
    monkeypatch.setattr(
        process_window.QMessageBox,
        "warning",
        lambda *args: warnings.append(args),
    )

    tool._analysis_result(process_window.VirusTotalResult("not_found", "demo.exe", "abc"))
    assert warnings[-1][1] == "VirusTotal"
    assert "abc" in warnings[-1][2]

    tool._analysis_result(
        process_window.VirusTotalResult(
            "http_error", "demo.exe", "abc", response_text="maintenance"
        )
    )
    assert warnings[-1][1] == "Error"
    assert "maintenance" in warnings[-1][2]


def test_analysis_result_found_with_many_and_no_detections(qtbot, monkeypatch):
    tool = _tool(qtbot, monkeypatch)
    info = []
    monkeypatch.setattr(
        process_window.QMessageBox,
        "information",
        lambda *args: info.append(args),
    )
    detections = tuple(f"Engine{i}: Trojan" for i in range(17))

    tool._analysis_result(
        process_window.VirusTotalResult(
            "found", "demo.exe", "abc", positives=17, total=70, detections=detections
        )
    )
    text = info[-1][2]
    assert "17/70" in text
    assert "Engine0" in text
    assert "2 más" in text

    tool._analysis_result(
        process_window.VirusTotalResult("found", "clean.exe", "def", positives=0, total=70)
    )
    assert "Sin detecciones específicas" in info[-1][2]


def test_analysis_cancelled_and_finished_current_stale(qtbot, monkeypatch):
    tool = _tool(qtbot, monkeypatch)
    current = FakeWorker(parent=tool)
    stale = FakeWorker(parent=tool)
    tool._analysis_worker = current
    tool.btn_cancel_analysis.setEnabled(True)

    tool._analysis_cancelled()
    assert tool.analysis_status.text() == "Análisis cancelado"

    tool._analysis_finished(stale)
    assert tool._analysis_worker is current
    assert stale.deleted

    tool._analysis_finished(current)
    assert tool._analysis_worker is None
    assert not tool.btn_cancel_analysis.isEnabled()
    assert tool.analysis_status.text() == "Análisis cancelado"
    assert current.deleted


def test_analysis_finished_clears_non_cancelled_status(qtbot, monkeypatch):
    tool = _tool(qtbot, monkeypatch)
    worker = FakeWorker(parent=tool)
    tool._analysis_worker = worker
    tool.analysis_status.setText("Done")

    tool._analysis_finished(worker)

    assert tool._analysis_worker is None
    assert tool.analysis_status.text() == ""
