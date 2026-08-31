import builtins

from pythonkni.disk_analyzer import window as disk_window
from pythonkni.disk_analyzer.models import DiskItem


def _tool(qtbot):
    tool = disk_window.Tool()
    qtbot.addWidget(tool)
    return tool


def test_select_folder_cancel_and_success(qtbot, monkeypatch):
    tool = _tool(qtbot)
    responses = iter(["", "C:/Data"])
    monkeypatch.setattr(
        disk_window.QFileDialog,
        "getExistingDirectory",
        lambda *args, **kwargs: next(responses),
    )

    tool.select_folder()
    assert tool.current_folder is None
    assert not tool.btn_analyze.isEnabled()

    tool.select_folder()
    assert tool.current_folder == "C:/Data"
    assert tool.folder_label.text() == "Carpeta: C:/Data"
    assert tool.btn_analyze.isEnabled()


def test_start_analysis_requires_folder(qtbot, monkeypatch):
    tool = _tool(qtbot)
    warnings = []
    monkeypatch.setattr(
        disk_window.QMessageBox,
        "warning",
        lambda *args: warnings.append(args),
    )

    tool.start_analysis()

    assert warnings[-1][1:] == ("Analizador", "Selecciona una carpeta primero.")


def test_analysis_failed_plain_diagnostic(qtbot, monkeypatch):
    tool = _tool(qtbot)
    tool.btn_analyze.setEnabled(False)
    tool.progress.show()
    feedback = []
    monkeypatch.setattr(
        disk_window,
        "show_error",
        lambda *args, **kwargs: feedback.append((args, kwargs)),
    )

    tool.on_analysis_failed("plain diagnostic")

    assert tool.progress.isHidden()
    assert tool.btn_analyze.isEnabled()
    assert feedback[-1][1]["details"] == "plain diagnostic"


def test_analysis_finished_empty_result_disables_export(qtbot):
    tool = _tool(qtbot)
    tool.progress.show()

    tool.on_analysis_finished([])

    assert tool.items == []
    assert tool.progress.isHidden()
    assert tool.btn_analyze.isEnabled()
    assert not tool.btn_export.isEnabled()
    assert "Elementos mostrados: 0" in tool.summary_label.text()
    assert tool.table.rowCount() == 0


def test_export_requires_results_and_honours_cancel(qtbot, monkeypatch):
    tool = _tool(qtbot)
    warnings = []
    monkeypatch.setattr(
        disk_window.QMessageBox,
        "warning",
        lambda *args: warnings.append(args),
    )

    tool.export_csv()
    assert warnings[-1][1] == "Exportar"

    tool.items = [DiskItem("C:/a.txt", "a.txt", "Archivo", 10)]
    monkeypatch.setattr(
        disk_window.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: ("", ""),
    )
    tool.export_csv()
    assert len(warnings) == 1


def test_export_csv_success_uses_safe_values(qtbot, monkeypatch, tmp_path):
    tool = _tool(qtbot)
    tool.items = [DiskItem("C:/formula.txt", "=SUM(A1:A2)", "Archivo", 1024)]
    output = tmp_path / "disk.csv"
    monkeypatch.setattr(
        disk_window.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(output), ""),
    )
    info = []
    monkeypatch.setattr(
        disk_window.QMessageBox,
        "information",
        lambda *args: info.append(args),
    )

    tool.export_csv()

    text = output.read_text(encoding="utf-8-sig")
    assert "'=SUM(A1:A2)" in text
    assert "1.00 KB" in text
    assert info[-1][1:] == ("Exportado", "CSV generado correctamente.")


def test_export_csv_failure_reports_error(qtbot, monkeypatch, tmp_path):
    tool = _tool(qtbot)
    tool.items = [DiskItem("C:/a.txt", "a.txt", "Archivo", 10)]
    output = tmp_path / "disk.csv"
    monkeypatch.setattr(
        disk_window.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(output), ""),
    )
    error = OSError("disk full")
    real_open = builtins.open

    def fail_open(path, *args, **kwargs):
        if str(path) == str(output):
            raise error
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", fail_open)
    feedback = []
    monkeypatch.setattr(
        disk_window,
        "show_error",
        lambda *args, **kwargs: feedback.append((args, kwargs)),
    )

    tool.export_csv()

    assert feedback[-1][0][1] == "Exportación CSV"
    assert feedback[-1][1]["error"] is error
