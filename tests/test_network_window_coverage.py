import json

import pytest
from PyQt5.QtCore import QObject, pyqtSignal

from pythonkni.network import window as network_window


class HistoryStub:
    def __init__(self):
        self.entries = []

    def append_to_history(self, entry):
        self.entries.append(entry)


class FakeNetworkWorker(QObject):
    message = pyqtSignal(str)
    finished_summary = pyqtSignal(str)
    cancelled = pyqtSignal(str)
    failed = pyqtSignal(object)
    finished = pyqtSignal()

    instances = []

    def __init__(self, *args, **kwargs):
        super().__init__()
        self.args = args
        self.kwargs = kwargs
        self.running = False
        self.stopped = False
        self.wait_result = True
        self.wait_calls = []
        self.__class__.instances.append(self)

    def start(self):
        self.running = True

    def isRunning(self):
        return self.running

    def stop(self):
        self.stopped = True

    def wait(self, timeout):
        self.wait_calls.append(timeout)
        if self.wait_result:
            self.running = False
        return self.wait_result


class CloseEventStub:
    def __init__(self):
        self.accepted = False
        self.ignored = False

    def accept(self):
        self.accepted = True

    def ignore(self):
        self.ignored = True


def sample_interfaces():
    return [
        network_window.NetworkInterface(
            name="Ethernet",
            address="192.168.10.23",
            netmask="255.255.255.0",
            cidr="192.168.10.0/24",
        ),
        network_window.NetworkInterface(
            name="VPN",
            address="10.20.5.7",
            netmask="255.255.252.0",
            cidr="10.20.4.0/22",
        ),
    ]


def _history(qtbot, monkeypatch, tmp_path):
    monkeypatch.setattr(network_window, "ensure_app_dirs", lambda: None)
    monkeypatch.setattr(network_window, "SCAN_HISTORY_FILE", tmp_path / "network-history.txt")
    history = network_window.HistoryTab()
    qtbot.addWidget(history)
    return history


def test_show_exception_supports_exception_and_plain_diagnostics(monkeypatch):
    calls = []
    monkeypatch.setattr(
        network_window,
        "show_error",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    error = RuntimeError("boom")

    network_window._show_exception(None, "Title", "Message", error)
    network_window._show_exception(None, "Title", "Message", "plain")

    assert calls[0][1]["error"] is error
    assert calls[1][1]["details"] == "plain"


def test_network_worker_empty_success_reports_completion(monkeypatch):
    monkeypatch.setattr(
        network_window,
        "scan_network_hosts",
        lambda *_args, **_kwargs: [],
    )
    worker = network_window.NetworkScanWorker("192.168.1.0/30")
    messages = []
    summaries = []
    worker.message.connect(messages.append)
    worker.finished_summary.connect(summaries.append)

    worker.run()

    assert any("Exploración completada" in message for message in messages)
    assert summaries == ["Escaneo de 192.168.1.0/30: no se encontraron dispositivos."]


def test_port_worker_reports_open_ports_and_empty_success(monkeypatch):
    open_port = network_window.OpenPort(443, "https")

    def with_open(_target, _start, _end, on_open=None, on_checked=None, **_kwargs):
        on_checked(443)
        on_open(open_port)
        return [open_port]

    monkeypatch.setattr(network_window, "scan_open_ports", with_open)
    worker = network_window.PortScanWorker("example.test", 443, 443)
    messages = []
    summaries = []
    worker.message.connect(messages.append)
    worker.finished_summary.connect(summaries.append)
    worker.run()

    assert any("ABIERTO" in message for message in messages)
    assert "443/tcp abierto (https)" in summaries[-1]
    assert any("1 puertos abiertos de 1" in message for message in messages)

    monkeypatch.setattr(
        network_window,
        "scan_open_ports",
        lambda *_args, on_checked=None, **_kwargs: (
            on_checked(1) if on_checked else None,
            [],
        )[1],
    )
    worker = network_window.PortScanWorker("example.test", 1, 1)
    summaries = []
    worker.finished_summary.connect(summaries.append)
    worker.run()
    assert "no se encontraron puertos abiertos" in summaries[-1]


def test_network_scanner_handles_default_detection_failure_and_running_state(qtbot, monkeypatch):
    monkeypatch.setattr(network_window, "get_ipv4_interfaces", sample_interfaces)
    monkeypatch.setattr(
        network_window,
        "detect_default_network",
        lambda _interfaces: (_ for _ in ()).throw(RuntimeError("no route")),
    )
    scanner = network_window.NetworkScanner(HistoryStub())
    qtbot.addWidget(scanner)

    assert scanner.interface_combo.currentIndex() == 0
    assert scanner.cidr_input.text() == "192.168.10.0/24"

    scanner._set_running(True)
    assert not scanner.scan_button.isEnabled()
    assert scanner.stop_button.isEnabled()
    assert not scanner.interface_combo.isEnabled()
    assert not scanner.cidr_input.isEnabled()

    scanner._worker_finished()
    assert scanner.scan_button.isEnabled()
    assert not scanner.stop_button.isEnabled()


def test_network_scanner_starts_stops_and_ignores_overlap(qtbot, monkeypatch):
    FakeNetworkWorker.instances.clear()
    monkeypatch.setattr(network_window, "get_ipv4_interfaces", lambda: [])
    monkeypatch.setattr(network_window, "NetworkScanWorker", FakeNetworkWorker)
    history = HistoryStub()
    scanner = network_window.NetworkScanner(history)
    qtbot.addWidget(scanner)
    scanner.cidr_input.setText("192.168.1.0/30")

    scanner.scan_network()

    worker = FakeNetworkWorker.instances[-1]
    assert worker.args == ("192.168.1.0/30",)
    assert worker.running
    assert not scanner.scan_button.isEnabled()
    assert scanner.stop_button.isEnabled()
    assert scanner.running_worker() is worker

    scanner.scan_network()
    assert len(FakeNetworkWorker.instances) == 1

    worker.message.emit("host found")
    worker.finished_summary.emit("summary")
    assert "host found" in scanner.result_area.toPlainText()
    assert history.entries == ["summary"]

    scanner.stop_scan()
    assert worker.stopped
    assert not scanner.stop_button.isEnabled()
    assert "Cancelando escaneo" in scanner.result_area.toPlainText()

    worker.running = False
    worker.finished.emit()
    assert scanner.scan_button.isEnabled()
    assert scanner.running_worker() is None


def test_port_scanner_validates_empty_fields_then_starts_and_stops(qtbot, monkeypatch):
    FakeNetworkWorker.instances.clear()
    monkeypatch.setattr(network_window, "PortScanWorker", FakeNetworkWorker)
    history = HistoryStub()
    scanner = network_window.PortScanner(history)
    qtbot.addWidget(scanner)

    scanner.scan_ports()
    assert "dirección IP" in scanner.result_area.toPlainText()

    scanner.ip_input.setText("example.test")
    scanner.scan_ports()
    assert "rango de puertos" in scanner.result_area.toPlainText()

    scanner.port_range_input.setText("80-81")
    scanner.scan_ports()
    worker = FakeNetworkWorker.instances[-1]
    assert worker.args == ("example.test", 80, 81)
    assert worker.running
    assert scanner.running_worker() is worker
    assert not scanner.ip_input.isEnabled()
    assert not scanner.port_range_input.isEnabled()

    scanner.scan_ports()
    assert len(FakeNetworkWorker.instances) == 1

    worker.message.emit("80/tcp")
    worker.finished_summary.emit("ports summary")
    assert "80/tcp" in scanner.result_area.toPlainText()
    assert history.entries == ["ports summary"]

    scanner.stop_scan()
    assert worker.stopped
    assert "Cancelando escaneo" in scanner.result_area.toPlainText()
    worker.running = False
    worker.finished.emit()
    assert scanner.scan_button.isEnabled()
    assert scanner.running_worker() is None


def test_history_load_missing_existing_and_failure(qtbot, monkeypatch, tmp_path):
    history = _history(qtbot, monkeypatch, tmp_path)
    assert "No hay historial" in history.history_area.toPlainText()

    history.history_file.write_text("first\nsecond", encoding="utf-8")
    history.load_history()
    assert history.history_area.toPlainText() == "first\nsecond"

    feedback = []
    monkeypatch.setattr(
        network_window,
        "show_error",
        lambda *args, **kwargs: feedback.append((args, kwargs)),
    )
    history.history_file = tmp_path
    history.load_history()
    assert "No se pudo cargar" in history.history_area.toPlainText()
    assert isinstance(feedback[-1][1]["error"], OSError)


def test_history_clear_and_append_persist_successfully(qtbot, monkeypatch, tmp_path):
    history = _history(qtbot, monkeypatch, tmp_path)
    history.history_file.write_text("old", encoding="utf-8")

    history.clear_history()
    assert history.history_file.read_text(encoding="utf-8") == ""
    assert "Historial limpiado" in history.history_area.toPlainText()

    history.append_to_history("scan one")
    history.append_to_history("scan two")
    assert history.history_file.read_text(encoding="utf-8") == "scan one\nscan two\n"
    text = history.history_area.toPlainText()
    assert "scan one" in text and "scan two" in text


def test_history_append_failure_keeps_ui_entry_and_reports_error(qtbot, monkeypatch, tmp_path):
    history = _history(qtbot, monkeypatch, tmp_path)
    feedback = []
    monkeypatch.setattr(
        network_window,
        "show_error",
        lambda *args, **kwargs: feedback.append((args, kwargs)),
    )
    history.history_file = tmp_path

    history.append_to_history("visible entry")

    assert "visible entry" in history.history_area.toPlainText()
    assert isinstance(feedback[-1][1]["error"], OSError)


@pytest.mark.parametrize("suffix", [".txt", ".json", ".csv"])
def test_history_export_supported_formats(qtbot, monkeypatch, tmp_path, suffix):
    history = _history(qtbot, monkeypatch, tmp_path)
    history.history_area.setText("normal\n=formula")
    output = tmp_path / f"export{suffix}"
    monkeypatch.setattr(
        network_window.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(output), ""),
    )

    history.export_history()

    assert output.exists()
    if suffix == ".txt":
        assert output.read_text(encoding="utf-8") == "normal\n=formula"
    elif suffix == ".json":
        assert json.loads(output.read_text(encoding="utf-8")) == ["normal", "=formula"]
    else:
        csv_text = output.read_text(encoding="utf-8")
        assert "normal" in csv_text
        assert "'=formula" in csv_text


def test_history_export_cancel_and_unsupported_format(qtbot, monkeypatch, tmp_path):
    history = _history(qtbot, monkeypatch, tmp_path)
    feedback = []
    monkeypatch.setattr(
        network_window,
        "show_error",
        lambda *args, **kwargs: feedback.append((args, kwargs)),
    )
    monkeypatch.setattr(
        network_window.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: ("", ""),
    )
    history.export_history()
    assert feedback == []

    output = tmp_path / "export.bin"
    monkeypatch.setattr(
        network_window.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(output), ""),
    )
    history.export_history()
    assert isinstance(feedback[-1][1]["error"], ValueError)


@pytest.mark.parametrize(
    ("suffix", "content", "expected"),
    [
        (".txt", "one\ntwo", "one\ntwo"),
        (".json", '["one", "two"]', "one\ntwo"),
        (".csv", "one,two\nthree,four\n", "one,two\nthree,four"),
    ],
)
def test_history_import_supported_formats(qtbot, monkeypatch, tmp_path, suffix, content, expected):
    history = _history(qtbot, monkeypatch, tmp_path)
    source = tmp_path / f"source{suffix}"
    source.write_text(content, encoding="utf-8")
    monkeypatch.setattr(
        network_window.QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: (str(source), ""),
    )

    history.import_history()

    assert history.history_area.toPlainText() == expected
    assert history.history_file.read_text(encoding="utf-8") == expected


def test_history_import_cancel_and_unsupported_format(qtbot, monkeypatch, tmp_path):
    history = _history(qtbot, monkeypatch, tmp_path)
    feedback = []
    monkeypatch.setattr(
        network_window,
        "show_error",
        lambda *args, **kwargs: feedback.append((args, kwargs)),
    )
    monkeypatch.setattr(
        network_window.QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: ("", ""),
    )
    history.import_history()
    assert feedback == []

    source = tmp_path / "source.bin"
    source.write_text("data", encoding="utf-8")
    monkeypatch.setattr(
        network_window.QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: (str(source), ""),
    )
    history.import_history()
    assert isinstance(feedback[-1][1]["error"], ValueError)


def test_tool_running_workers_and_deferred_close(qtbot, monkeypatch, tmp_path):
    monkeypatch.setattr(network_window, "ensure_app_dirs", lambda: None)
    monkeypatch.setattr(network_window, "SCAN_HISTORY_FILE", tmp_path / "history.txt")
    monkeypatch.setattr(network_window, "get_ipv4_interfaces", lambda: [])
    tool = network_window.Tool()
    qtbot.addWidget(tool)

    assert tool._running_workers() == []
    event = CloseEventStub()
    tool.closeEvent(event)
    assert event.accepted

    closed = []
    monkeypatch.setattr(tool, "close", lambda: closed.append(True))
    tool._close_when_workers_finish = True
    tool._retry_deferred_close()
    assert closed == [True]
    assert not tool._close_when_workers_finish


def test_tool_close_waits_and_defers_when_worker_does_not_finish(qtbot, monkeypatch, tmp_path):
    monkeypatch.setattr(network_window, "ensure_app_dirs", lambda: None)
    monkeypatch.setattr(network_window, "SCAN_HISTORY_FILE", tmp_path / "history.txt")
    monkeypatch.setattr(network_window, "get_ipv4_interfaces", lambda: [])
    tool = network_window.Tool()
    qtbot.addWidget(tool)

    worker = FakeNetworkWorker()
    worker.running = True
    worker.wait_result = False
    tool.network_scanner.worker = worker

    event = CloseEventStub()
    tool.closeEvent(event)

    assert worker.stopped
    assert worker.wait_calls
    assert event.ignored
    assert tool._close_when_workers_finish

    closed = []
    monkeypatch.setattr(tool, "close", lambda: closed.append(True))
    worker.running = False
    worker.finished.emit()
    assert closed == [True]


def test_tool_close_accepts_when_running_worker_finishes_during_wait(qtbot, monkeypatch, tmp_path):
    monkeypatch.setattr(network_window, "ensure_app_dirs", lambda: None)
    monkeypatch.setattr(network_window, "SCAN_HISTORY_FILE", tmp_path / "history.txt")
    monkeypatch.setattr(network_window, "get_ipv4_interfaces", lambda: [])
    tool = network_window.Tool()
    qtbot.addWidget(tool)

    worker = FakeNetworkWorker()
    worker.running = True
    worker.wait_result = True
    tool.port_scanner.worker = worker

    event = CloseEventStub()
    tool.closeEvent(event)

    assert worker.stopped
    assert event.accepted
    assert not event.ignored
