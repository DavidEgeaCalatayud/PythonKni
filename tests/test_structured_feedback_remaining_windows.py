from PyQt5.QtWidgets import QMessageBox

from pythonkni.converter import window as converter_window
from pythonkni.disk_analyzer import window as disk_window
from pythonkni.network import window as network_window
from pythonkni.system_report import window as report_window
from pythonkni.system_report.models import ReportData
from pythonkni.temp_cleaner import window as temp_window
from pythonkni.wifi import window as wifi_window


def capture_feedback(monkeypatch, module):
    calls = []
    monkeypatch.setattr(
        module,
        "show_error",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    return calls


def sample_report():
    return ReportData(
        generated_at="2026-08-30_19-00-00",
        system_rows=[("Equipo", "PC")],
        disk_rows=[],
        network_rows=[],
        top_cpu=[],
        top_memory=[],
        temp_summary=[],
    )


def test_converter_failures_keep_diagnostics_out_of_primary_message(qtbot, monkeypatch):
    feedback = capture_feedback(monkeypatch, converter_window)
    monkeypatch.setattr(
        converter_window.QMessageBox,
        "information",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        converter_window.QMessageBox,
        "warning",
        lambda *args, **kwargs: None,
    )
    tool = converter_window.Tool()
    qtbot.addWidget(tool)

    result = converter_window.ConversionResult.failed(
        "codec exploded",
        warnings=["fallback warning"],
    )
    tool._conversion_done("unused", result)

    args, kwargs = feedback[-1]
    assert "codec exploded" not in args[2]
    assert "fallback warning" not in args[2]
    assert "codec exploded" in kwargs["details"]
    assert "fallback warning" in kwargs["details"]

    error = RuntimeError("converter exploded")
    tool._conversion_error(error)
    args, kwargs = feedback[-1]
    assert "converter exploded" not in args[2]
    assert kwargs["error"] is error


def test_converter_batch_folder_read_failure_is_structured(qtbot, monkeypatch):
    feedback = capture_feedback(monkeypatch, converter_window)
    tool = converter_window.Tool()
    qtbot.addWidget(tool)
    error = PermissionError("folder denied")

    def fail_listdir(_path):
        raise error

    monkeypatch.setattr(converter_window.os, "listdir", fail_listdir)

    assert tool._files_with_extension("C:/blocked", ".txt") is None
    args, kwargs = feedback[-1]
    assert "folder denied" not in args[2]
    assert kwargs["error"] is error


def test_disk_analyzer_worker_and_export_failures_are_structured(qtbot, monkeypatch, tmp_path):
    worker_error = PermissionError("disk denied")

    def fail_analysis(*args, **kwargs):
        raise worker_error

    monkeypatch.setattr(disk_window, "analyze_directory", fail_analysis)
    worker = disk_window.DiskAnalyzerWorker(str(tmp_path))
    failures = []
    worker.failed.connect(failures.append)
    worker.run()
    assert failures == [worker_error]

    feedback = capture_feedback(monkeypatch, disk_window)
    monkeypatch.setattr(
        disk_window.QMessageBox,
        "information",
        lambda *args, **kwargs: None,
    )
    tool = disk_window.Tool()
    qtbot.addWidget(tool)
    tool.progress.show()
    tool.btn_analyze.setEnabled(False)
    tool.on_analysis_failed(worker_error)

    args, kwargs = feedback[-1]
    assert not tool.progress.isVisible()
    assert tool.btn_analyze.isEnabled()
    assert "disk denied" not in args[2]
    assert kwargs["error"] is worker_error

    tool.items = [disk_window.DiskItem(str(tmp_path / "a"), "a", "Archivo", 1)]
    monkeypatch.setattr(
        disk_window.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(tmp_path), ""),
    )
    tool.export_csv()
    args, kwargs = feedback[-1]
    assert "IsADirectoryError" not in args[2]
    assert isinstance(kwargs["error"], OSError)


def test_network_workers_emit_sanitized_failure_and_preserve_exception(qtbot, monkeypatch):
    network_error = RuntimeError("socket exploded")

    def fail_network(*args, **kwargs):
        raise network_error

    monkeypatch.setattr(network_window, "scan_network_hosts", fail_network)
    network_worker = network_window.NetworkScanWorker("192.168.1.0/30")
    network_failures = []
    network_summaries = []
    network_worker.failed.connect(network_failures.append)
    network_worker.finished_summary.connect(network_summaries.append)

    with qtbot.waitSignal(network_worker.finished, timeout=2000):
        network_worker.start()

    assert network_failures == [network_error]
    assert network_summaries == ["Escaneo de red fallido."]
    assert "socket exploded" not in network_summaries[0]

    port_error = OSError("resolver exploded")

    def fail_ports(*args, **kwargs):
        raise port_error

    monkeypatch.setattr(network_window, "scan_open_ports", fail_ports)
    port_worker = network_window.PortScanWorker("example.test", 1, 10)
    port_failures = []
    port_summaries = []
    port_worker.failed.connect(port_failures.append)
    port_worker.finished_summary.connect(port_summaries.append)

    with qtbot.waitSignal(port_worker.finished, timeout=2000):
        port_worker.start()

    assert port_failures == [port_error]
    assert port_summaries == ["Escaneo de puertos fallido para example.test."]
    assert "resolver exploded" not in port_summaries[0]


def test_network_scanner_and_history_use_structured_feedback(qtbot, monkeypatch, tmp_path):
    feedback = capture_feedback(monkeypatch, network_window)
    monkeypatch.setattr(network_window, "ensure_app_dirs", lambda: None)
    history_path = tmp_path / "history.txt"
    monkeypatch.setattr(network_window, "SCAN_HISTORY_FILE", history_path)

    history = network_window.HistoryTab()
    qtbot.addWidget(history)
    network_scanner = network_window.NetworkScanner(history)
    qtbot.addWidget(network_scanner)

    error = RuntimeError("adapter vanished")
    network_scanner._scan_failed(error)
    args, kwargs = feedback[-1]
    assert "adapter vanished" not in args[2]
    assert kwargs["error"] is error

    history.history_file = tmp_path
    history.history_area.setText("existing")
    history.clear_history()
    args, kwargs = feedback[-1]
    assert "Historial limpiado" not in history.history_area.toPlainText()
    assert "IsADirectoryError" not in args[2]
    assert isinstance(kwargs["error"], OSError)

    malformed = tmp_path / "bad.json"
    malformed.write_text('{"not": "a list"}', encoding="utf-8")
    history.history_file = history_path
    history.history_area.setText("keep this")
    monkeypatch.setattr(
        network_window.QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: (str(malformed), ""),
    )
    history.import_history()

    args, kwargs = feedback[-1]
    assert history.history_area.toPlainText() == "keep this"
    assert "lista de cadenas" not in args[2]
    assert isinstance(kwargs["error"], ValueError)


def test_system_report_worker_and_exports_preserve_diagnostics(qtbot, monkeypatch, tmp_path):
    worker_error = RuntimeError("collector exploded")

    def fail_collect():
        raise worker_error

    monkeypatch.setattr(report_window, "collect_report", fail_collect)
    worker = report_window.ReportWorker()
    with qtbot.waitSignal(worker.failed, timeout=2000) as signal:
        worker.start()
    assert signal.args == [worker_error]

    feedback = capture_feedback(monkeypatch, report_window)
    monkeypatch.setattr(
        report_window.QMessageBox,
        "information",
        lambda *args, **kwargs: None,
    )
    tool = report_window.Tool()
    qtbot.addWidget(tool)

    tool.progress.show()
    tool.btn_generate.setEnabled(False)
    tool.on_report_failed(worker_error)
    args, kwargs = feedback[-1]
    assert not tool.progress.isVisible()
    assert tool.btn_generate.isEnabled()
    assert "collector exploded" not in args[2]
    assert kwargs["error"] is worker_error

    tool.report_data = sample_report()
    output = tmp_path / "report.pdf"
    monkeypatch.setattr(
        report_window.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(output), ""),
    )
    pdf_error = OSError("pdf write denied")

    def fail_pdf(*args, **kwargs):
        raise pdf_error

    monkeypatch.setattr(report_window, "report_to_pdf", fail_pdf)
    tool.export_pdf()
    args, kwargs = feedback[-1]
    assert "pdf write denied" not in args[2]
    assert kwargs["error"] is pdf_error

    write_error_count = len(feedback)
    assert not tool._export_text_file(str(tmp_path), "content", "TXT")
    assert len(feedback) == write_error_count + 1
    args, kwargs = feedback[-1]
    assert "IsADirectoryError" not in args[2]
    assert isinstance(kwargs["error"], OSError)


def test_temp_cleaner_preview_and_cleanup_failures_are_structured(qtbot, monkeypatch, tmp_path):
    feedback = capture_feedback(monkeypatch, temp_window)
    monkeypatch.setattr(
        temp_window.QMessageBox,
        "information",
        lambda *args, **kwargs: None,
    )
    tool = temp_window.Tool()
    qtbot.addWidget(tool)

    preview_error = RuntimeError("preview exploded")
    monkeypatch.setattr(temp_window, "get_temp_targets", lambda: [])
    monkeypatch.setattr(
        temp_window,
        "build_preview",
        lambda _targets: (_ for _ in ()).throw(preview_error),
    )
    tool.clean_action()
    args, kwargs = feedback[-1]
    assert "preview exploded" not in args[2]
    assert kwargs["error"] is preview_error

    target = temp_window.CleanTarget("Temp", tmp_path)
    preview = temp_window.CleanPreview(targets=[target], items=1, bytes=1)
    monkeypatch.setattr(temp_window, "build_preview", lambda _targets: preview)
    monkeypatch.setattr(
        temp_window.QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.Yes,
    )
    clean_error = OSError("cleanup denied")
    monkeypatch.setattr(
        temp_window,
        "clean_targets",
        lambda _targets: (_ for _ in ()).throw(clean_error),
    )
    tool.clean_action()
    args, kwargs = feedback[-1]
    assert "cleanup denied" not in args[2]
    assert kwargs["error"] is clean_error


def test_wifi_unexpected_worker_failure_is_structured(qtbot, monkeypatch):
    feedback = capture_feedback(monkeypatch, wifi_window)
    monkeypatch.setattr(wifi_window.Tool, "refresh_wifi_data", lambda self: True)
    tool = wifi_window.Tool()
    qtbot.addWidget(tool)

    error = RuntimeError("netsh exploded")
    tool.on_loading_failed(error)

    assert tool.table.item(0, 0).text() == "No se pudieron cargar los perfiles Wi-Fi"
    assert "netsh exploded" not in tool.table.item(0, 1).text()
    args, kwargs = feedback[-1]
    assert "netsh exploded" not in args[2]
    assert kwargs["error"] is error
