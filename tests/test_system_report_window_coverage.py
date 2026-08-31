from datetime import datetime

from PyQt5.QtCore import QObject, pyqtSignal

from pythonkni.system_report import window as report_window
from pythonkni.system_report.models import ReportData


class FakeReportWorker(QObject):
    result_ready = pyqtSignal(object)
    failed = pyqtSignal(object)

    instances = []

    def __init__(self):
        super().__init__()
        self.started = False
        self.__class__.instances.append(self)

    def start(self):
        self.started = True


def sample_report():
    return ReportData(
        generated_at="2026-08-31_12-00-00",
        system_rows=[("Equipo", "PC")],
        disk_rows=[("Disk0", "C:/", "500 GB", "200 GB")],
        network_rows=[("IPv4", "192.0.2.10")],
        top_cpu=[(10, "cpu.exe", 50.0, 2.0)],
        top_memory=[(20, "ram.exe", 3.0, 40.0)],
        temp_summary=[("C:/Temp", "10 MB")],
    )


def _tool(qtbot):
    tool = report_window.Tool()
    qtbot.addWidget(tool)
    return tool


def test_generate_report_wires_worker_and_ready_state(qtbot, monkeypatch):
    FakeReportWorker.instances.clear()
    monkeypatch.setattr(report_window, "ReportWorker", FakeReportWorker)
    monkeypatch.setattr(report_window, "report_to_text", lambda _data: "preview")
    tool = _tool(qtbot)

    tool.generate_report()

    worker = FakeReportWorker.instances[-1]
    assert worker.started
    assert not tool.btn_generate.isEnabled()
    assert not tool.progress.isHidden()

    data = sample_report()
    worker.result_ready.emit(data)

    assert tool.report_data is data
    assert tool.preview.toPlainText() == "preview"
    assert tool.system_table.item(0, 0).text() == "Equipo"
    assert tool.system_table.item(0, 1).text() == "PC"
    assert tool.disk_table.rowCount() == 1
    assert tool.network_table.rowCount() == 1
    assert tool.cpu_table.rowCount() == 1
    assert tool.memory_table.rowCount() == 1
    assert tool.temp_table.rowCount() == 1
    assert tool.progress.isHidden()
    assert tool.btn_generate.isEnabled()
    assert tool.btn_html.isEnabled()
    assert tool.btn_pdf.isEnabled()
    assert tool.btn_txt.isEnabled()


def test_generate_report_failure_signal_restores_state(qtbot, monkeypatch):
    FakeReportWorker.instances.clear()
    monkeypatch.setattr(report_window, "ReportWorker", FakeReportWorker)
    feedback = []
    monkeypatch.setattr(
        report_window,
        "show_error",
        lambda *args, **kwargs: feedback.append((args, kwargs)),
    )
    tool = _tool(qtbot)
    tool.generate_report()

    FakeReportWorker.instances[-1].failed.emit("plain failure")

    assert tool.btn_generate.isEnabled()
    assert tool.progress.isHidden()
    assert feedback[-1][1]["details"] == "plain failure"


def test_require_report_warns_and_default_filename_uses_current_time(qtbot, monkeypatch):
    tool = _tool(qtbot)
    warnings = []
    monkeypatch.setattr(
        report_window.QMessageBox,
        "warning",
        lambda *args: warnings.append(args),
    )

    assert tool.require_report() is None
    assert warnings[-1][2] == "Primero genera el informe."

    class FixedDateTime:
        @classmethod
        def now(cls):
            return datetime(2026, 8, 31, 13, 15, 20)

    monkeypatch.setattr(report_window, "datetime", FixedDateTime)
    assert tool.default_filename("txt") == "informe_tecnico_2026-08-31_13-15-20.txt"

    tool.report_data = sample_report()
    assert tool.require_report() is tool.report_data
    assert tool.default_filename("pdf") == "informe_tecnico_2026-08-31_12-00-00.pdf"


def test_export_text_file_success(qtbot, tmp_path):
    tool = _tool(qtbot)
    output = tmp_path / "report.txt"

    assert tool._export_text_file(str(output), "content", "TXT")
    assert output.read_text(encoding="utf-8") == "content"


def test_export_html_success_cancel_and_prepare_failure(qtbot, monkeypatch, tmp_path):
    tool = _tool(qtbot)
    tool.report_data = sample_report()
    info = []
    feedback = []
    monkeypatch.setattr(
        report_window.QMessageBox,
        "information",
        lambda *args: info.append(args),
    )
    monkeypatch.setattr(
        report_window,
        "show_error",
        lambda *args, **kwargs: feedback.append((args, kwargs)),
    )

    monkeypatch.setattr(
        report_window.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: ("", ""),
    )
    tool.export_html()
    assert info == []

    output = tmp_path / "report.html"
    monkeypatch.setattr(
        report_window.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(output), ""),
    )
    monkeypatch.setattr(report_window, "report_to_html", lambda _data: "<html>ok</html>")
    tool.export_html()
    assert output.read_text(encoding="utf-8") == "<html>ok</html>"
    assert info[-1][2] == "Informe HTML generado correctamente."

    error = RuntimeError("html exploded")
    monkeypatch.setattr(
        report_window,
        "report_to_html",
        lambda _data: (_ for _ in ()).throw(error),
    )
    tool.export_html()
    assert feedback[-1][1]["error"] is error


def test_export_txt_success_and_prepare_failure(qtbot, monkeypatch, tmp_path):
    tool = _tool(qtbot)
    tool.report_data = sample_report()
    output = tmp_path / "report.txt"
    info = []
    feedback = []
    monkeypatch.setattr(
        report_window.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(output), ""),
    )
    monkeypatch.setattr(
        report_window.QMessageBox,
        "information",
        lambda *args: info.append(args),
    )
    monkeypatch.setattr(
        report_window,
        "show_error",
        lambda *args, **kwargs: feedback.append((args, kwargs)),
    )
    monkeypatch.setattr(report_window, "report_to_text", lambda _data: "text report")

    tool.export_txt()
    assert output.read_text(encoding="utf-8") == "text report"
    assert info[-1][2] == "Informe TXT generado correctamente."

    error = ValueError("text exploded")
    monkeypatch.setattr(
        report_window,
        "report_to_text",
        lambda _data: (_ for _ in ()).throw(error),
    )
    tool.export_txt()
    assert feedback[-1][1]["error"] is error


def test_export_pdf_success_and_cancel(qtbot, monkeypatch, tmp_path):
    tool = _tool(qtbot)
    tool.report_data = sample_report()
    info = []
    writes = []
    monkeypatch.setattr(
        report_window.QMessageBox,
        "information",
        lambda *args: info.append(args),
    )
    monkeypatch.setattr(
        report_window.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: ("", ""),
    )
    monkeypatch.setattr(
        report_window,
        "report_to_pdf",
        lambda data, path: writes.append((data, path)),
    )

    tool.export_pdf()
    assert writes == []

    output = tmp_path / "report.pdf"
    monkeypatch.setattr(
        report_window.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(output), ""),
    )
    tool.export_pdf()
    assert writes == [(tool.report_data, str(output))]
    assert info[-1][2] == "Informe PDF generado correctamente."


def test_exports_return_before_dialog_without_report(qtbot, monkeypatch):
    tool = _tool(qtbot)
    warnings = []
    dialogs = []
    monkeypatch.setattr(
        report_window.QMessageBox,
        "warning",
        lambda *args: warnings.append(args),
    )
    monkeypatch.setattr(
        report_window.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: dialogs.append(args) or ("ignored", ""),
    )

    tool.export_html()
    tool.export_txt()
    tool.export_pdf()

    assert len(warnings) == 3
    assert dialogs == []
