from __future__ import annotations

import json

from pythonkni.network import camera_handoff_window as network_window
from pythonkni.network.models import OpenPort, ServiceFingerprint


def test_port_worker_exposes_discovered_open_ports(monkeypatch):
    expected = [OpenPort(22, "ssh")]
    monkeypatch.setattr(network_window._base, "scan_open_ports", lambda *_args, **_kwargs: expected)
    worker = network_window.PortScanWorker("example.test", 22, 22)
    captured = []
    worker.results_ready.connect(captured.append)

    worker.run()

    assert captured == [expected]


def test_fingerprint_worker_uses_only_open_ports_and_emits_normalized_results(monkeypatch):
    expected = [
        ServiceFingerprint(
            host="example.test",
            ip="192.0.2.20",
            port=22,
            protocol="ssh",
            product="OpenSSH",
            version="9.8",
        )
    ]
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
