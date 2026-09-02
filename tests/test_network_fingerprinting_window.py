from __future__ import annotations

import builtins
import json
from types import SimpleNamespace

from pythonkni.network import camera_handoff_window as network_window
from pythonkni.network.models import OpenPort, ServiceFingerprint


def _fingerprint(
    port: int = 22,
    protocol: str = "ssh",
    *,
    product: str = "OpenSSH",
    version: str = "9.8",
) -> ServiceFingerprint:
    return ServiceFingerprint(
        host="example.test",
        ip="192.0.2.20",
        port=port,
        protocol=protocol,
        product=product,
        version=version,
    )


def test_fingerprint_label_handles_identity_and_protocol_only():
    assert network_window._fingerprint_label(_fingerprint()) == "ssh — OpenSSH 9.8"
    assert network_window._fingerprint_label(_fingerprint(product="", version="")) == "ssh"


def test_port_worker_exposes_discovered_open_ports(monkeypatch):
    expected = [OpenPort(22, "ssh")]
    monkeypatch.setattr(network_window._base, "scan_open_ports", lambda *_args, **_kwargs: expected)
    worker = network_window.PortScanWorker("example.test", 22, 22)
    captured = []
    worker.results_ready.connect(captured.append)

    worker.run()

    assert captured == [expected]


def test_port_worker_reports_empty_success(monkeypatch):
    monkeypatch.setattr(network_window._base, "scan_open_ports", lambda *_args, **_kwargs: [])
    worker = network_window.PortScanWorker("example.test", 80, 80)
    summaries = []
    worker.finished_summary.connect(summaries.append)

    worker.run()

    assert "no se encontraron puertos abiertos" in summaries[-1]


def test_port_worker_reports_failure(monkeypatch):
    def fail(*_args, **_kwargs):
        raise OSError("blocked")

    monkeypatch.setattr(network_window._base, "scan_open_ports", fail)
    worker = network_window.PortScanWorker("example.test", 22, 22)
    failures = []
    summaries = []
    worker.failed.connect(failures.append)
    worker.finished_summary.connect(summaries.append)

    worker.run()

    assert isinstance(failures[0], OSError)
    assert summaries == ["Escaneo de puertos fallido para example.test."]


def test_port_worker_reports_cancelled_partial_results(monkeypatch):
    worker = network_window.PortScanWorker("example.test", 22, 23)

    def scan(*_args, **kwargs):
        kwargs["on_checked"](22)
        result = OpenPort(22, "ssh")
        kwargs["on_open"](result)
        kwargs["stop_event"].set()
        return [result]

    monkeypatch.setattr(network_window._base, "scan_open_ports", scan)
    cancelled = []
    worker.cancelled.connect(cancelled.append)

    worker.run()

    assert "[CANCELADO]" in cancelled[0]
    assert "1 de 2 puertos comprobados" in cancelled[0]
    assert "22/tcp abierto" in cancelled[0]


def test_fingerprint_worker_uses_only_open_ports_and_emits_normalized_results(monkeypatch):
    expected = [_fingerprint()]
    calls = []

    def fake_fingerprint(target, ports, **kwargs):
        calls.append((target, tuple(ports), kwargs["stop_event"]))
        for item in expected:
            kwargs["on_found"](item)
        return expected

    monkeypatch.setattr(network_window, "fingerprint_open_ports", fake_fingerprint)
    worker = network_window.FingerprintWorker("example.test", [OpenPort(22, "ssh")])
    captured = []
    worker.results_ready.connect(captured.append)

    worker.run()

    assert captured == [expected]
    assert calls[0][0] == "example.test"
    assert calls[0][1] == (OpenPort(22, "ssh"),)


def test_fingerprint_worker_reports_empty_success(monkeypatch):
    monkeypatch.setattr(network_window, "fingerprint_open_ports", lambda *_args, **_kwargs: [])
    worker = network_window.FingerprintWorker("example.test", [OpenPort(443, "https")])
    summaries = []
    worker.finished_summary.connect(summaries.append)

    worker.run()

    assert "no identificó un protocolo compatible" in summaries[-1]


def test_fingerprint_worker_reports_failure(monkeypatch):
    def fail(*_args, **_kwargs):
        raise RuntimeError("engine missing")

    monkeypatch.setattr(network_window, "fingerprint_open_ports", fail)
    worker = network_window.FingerprintWorker("example.test", [OpenPort(22, "ssh")])
    failures = []
    summaries = []
    worker.failed.connect(failures.append)
    worker.finished_summary.connect(summaries.append)

    worker.run()

    assert isinstance(failures[0], RuntimeError)
    assert summaries == ["Fingerprinting de servicios fallido para example.test."]


def test_fingerprint_worker_stop_and_cancelled_partial_results(monkeypatch):
    worker = network_window.FingerprintWorker("example.test", [OpenPort(22, "ssh")])
    assert worker._stop_event.is_set() is False
    worker.stop()
    assert worker._stop_event.is_set() is True

    worker = network_window.FingerprintWorker("example.test", [OpenPort(22, "ssh")])

    def cancelled_fingerprint(*_args, **kwargs):
        result = _fingerprint()
        kwargs["on_found"](result)
        kwargs["stop_event"].set()
        return [result]

    monkeypatch.setattr(network_window, "fingerprint_open_ports", cancelled_fingerprint)
    cancelled = []
    worker.cancelled.connect(cancelled.append)

    worker.run()

    assert "[CANCELADO]" in cancelled[0]
    assert "22/tcp: ssh — OpenSSH 9.8" in cancelled[0]


def test_port_scanner_enables_fingerprinting_only_after_open_port_results(qtbot):
    history = network_window.HistoryTab()
    scanner = network_window.PortScanner(history)
    qtbot.addWidget(history)
    qtbot.addWidget(scanner)

    assert scanner.fingerprint_button.isEnabled() is False
    scanner._remember_open_ports([OpenPort(443, "https")])
    scanner._set_running(False)
    assert scanner.fingerprint_button.isEnabled() is True

    scanner._remember_open_ports([])
    scanner._set_running(False)
    assert scanner.fingerprint_button.isEnabled() is False


def test_port_scanner_remembers_fingerprints_and_emits_signal(qtbot):
    history = network_window.HistoryTab()
    scanner = network_window.PortScanner(history)
    qtbot.addWidget(history)
    qtbot.addWidget(scanner)
    emitted = []
    scanner.fingerprints_ready.connect(emitted.append)
    result = _fingerprint()

    scanner._remember_fingerprints([result])
    scanner._set_running(False)

    assert scanner.fingerprints == (result,)
    assert emitted == [(result,)]
    assert scanner.export_fingerprints_button.isEnabled() is True


def test_port_scanner_fingerprint_error_uses_structured_feedback(qtbot, monkeypatch):
    history = network_window.HistoryTab()
    scanner = network_window.PortScanner(history)
    qtbot.addWidget(history)
    qtbot.addWidget(scanner)
    captured = []
    monkeypatch.setattr(
        network_window._base, "_show_exception", lambda *args: captured.append(args)
    )
    error = RuntimeError("boom")

    scanner._fingerprint_failed(error)

    assert captured[0][-1] is error
    assert captured[0][1] == "Fingerprinting de servicios"


def test_port_scanner_scan_validation_paths(qtbot):
    history = network_window.HistoryTab()
    scanner = network_window.PortScanner(history)
    qtbot.addWidget(history)
    qtbot.addWidget(scanner)

    scanner.scan_ports()
    assert "Debes ingresar una dirección IP" in scanner.result_area.toPlainText()

    scanner.ip_input.setText("example.test")
    scanner.scan_ports()
    assert "Debes ingresar un rango" in scanner.result_area.toPlainText()

    scanner.port_range_input.setText("bad")
    scanner.scan_ports()
    assert "formato 'inicio-fin'" in scanner.result_area.toPlainText()


def test_port_scanner_does_not_start_second_scan_while_worker_running(qtbot):
    history = network_window.HistoryTab()
    scanner = network_window.PortScanner(history)
    qtbot.addWidget(history)
    qtbot.addWidget(scanner)
    scanner.worker = SimpleNamespace(isRunning=lambda: True)
    scanner.ip_input.setText("example.test")
    scanner.port_range_input.setText("22-22")

    scanner.scan_ports()

    assert scanner.result_area.toPlainText() == ""


def test_port_scanner_starts_scan_and_resets_previous_results(qtbot, monkeypatch):
    history = network_window.HistoryTab()
    scanner = network_window.PortScanner(history)
    qtbot.addWidget(history)
    qtbot.addWidget(scanner)
    scanner.ip_input.setText("example.test")
    scanner.port_range_input.setText("22-23")
    scanner.open_ports = (OpenPort(80, "http"),)
    scanner.fingerprints = (_fingerprint(),)
    monkeypatch.setattr(network_window.PortScanWorker, "start", lambda self: None)

    scanner.scan_ports()

    assert scanner.open_ports == ()
    assert scanner.fingerprints == ()
    assert isinstance(scanner.worker, network_window.PortScanWorker)
    assert scanner.scan_button.isEnabled() is False


def test_port_scanner_fingerprint_requires_confirmed_open_ports(qtbot):
    history = network_window.HistoryTab()
    scanner = network_window.PortScanner(history)
    qtbot.addWidget(history)
    qtbot.addWidget(scanner)
    scanner.ip_input.setText("example.test")

    scanner.fingerprint_services()

    assert "No hay puertos abiertos confirmados" in scanner.result_area.toPlainText()


def test_port_scanner_fingerprint_ignores_empty_target_and_running_worker(qtbot):
    history = network_window.HistoryTab()
    scanner = network_window.PortScanner(history)
    qtbot.addWidget(history)
    qtbot.addWidget(scanner)
    scanner.open_ports = (OpenPort(22, "ssh"),)

    scanner.fingerprint_services()
    assert scanner.worker is None

    scanner.worker = SimpleNamespace(isRunning=lambda: True)
    scanner.ip_input.setText("example.test")
    scanner.fingerprint_services()
    assert not isinstance(scanner.worker, network_window.FingerprintWorker)


def test_port_scanner_starts_fingerprint_worker(qtbot, monkeypatch):
    history = network_window.HistoryTab()
    scanner = network_window.PortScanner(history)
    qtbot.addWidget(history)
    qtbot.addWidget(scanner)
    scanner.ip_input.setText("example.test")
    scanner.open_ports = (OpenPort(22, "ssh"),)
    scanner.fingerprints = (_fingerprint(),)
    monkeypatch.setattr(network_window.FingerprintWorker, "start", lambda self: None)

    scanner.fingerprint_services()

    assert scanner.fingerprints == ()
    assert isinstance(scanner.worker, network_window.FingerprintWorker)
    assert scanner.worker.open_ports == (OpenPort(22, "ssh"),)
    assert scanner.scan_button.isEnabled() is False


def test_port_scanner_export_no_results_or_cancelled_dialog_are_noops(qtbot, monkeypatch):
    history = network_window.HistoryTab()
    scanner = network_window.PortScanner(history)
    qtbot.addWidget(history)
    qtbot.addWidget(scanner)

    scanner.export_fingerprints()
    assert scanner.result_area.toPlainText() == ""

    scanner.fingerprints = (_fingerprint(),)
    monkeypatch.setattr(
        network_window.QFileDialog, "getSaveFileName", lambda *_args, **_kwargs: ("", "")
    )
    scanner.export_fingerprints()
    assert scanner.result_area.toPlainText() == ""


def test_port_scanner_exports_fingerprints_as_json(qtbot, monkeypatch, tmp_path):
    history = network_window.HistoryTab()
    scanner = network_window.PortScanner(history)
    qtbot.addWidget(history)
    qtbot.addWidget(scanner)
    scanner.fingerprints = (
        ServiceFingerprint(
            host="server.local",
            ip="192.0.2.5",
            port=22,
            protocol="ssh",
            product="OpenSSH",
            version="9.8",
            metadata={"banner": "SSH-2.0-OpenSSH_9.8"},
        ),
    )
    destination = tmp_path / "fingerprints.json"
    monkeypatch.setattr(
        network_window.QFileDialog,
        "getSaveFileName",
        lambda *_args, **_kwargs: (str(destination), "JSON"),
    )

    scanner.export_fingerprints()

    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert payload[0]["protocol"] == "ssh"
    assert payload[0]["metadata"]["banner"].startswith("SSH-2.0")
    assert "Fingerprints exportados" in scanner.result_area.toPlainText()


def test_port_scanner_export_failure_uses_structured_feedback(qtbot, monkeypatch):
    history = network_window.HistoryTab()
    scanner = network_window.PortScanner(history)
    qtbot.addWidget(history)
    qtbot.addWidget(scanner)
    scanner.fingerprints = (_fingerprint(),)
    monkeypatch.setattr(
        network_window.QFileDialog,
        "getSaveFileName",
        lambda *_args, **_kwargs: ("fingerprints.json", "JSON"),
    )
    captured = []
    monkeypatch.setattr(
        network_window._base, "_show_exception", lambda *args: captured.append(args)
    )

    original_open = builtins.open

    def fail_open(path, *args, **kwargs):
        if path == "fingerprints.json":
            raise OSError("read only")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", fail_open)

    scanner.export_fingerprints()

    assert captured[0][1] == "Exportar fingerprints"
    assert isinstance(captured[0][-1], OSError)
