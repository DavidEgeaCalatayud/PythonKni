from __future__ import annotations

from types import SimpleNamespace

import pytest

from pythonkni.network import camera_handoff_window, service_intelligence_window
from pythonkni.network.models import (
    OpenPort,
    SecurityFindingSeverity,
    ServiceFingerprint,
    ServiceSecurityFinding,
    UdpPortState,
    UdpProbeResult,
)


def _scanner(qtbot, monkeypatch, *, sctp=False):
    monkeypatch.setattr(
        service_intelligence_window.fingerprinting,
        "transport_available",
        lambda transport: sctp if transport == "sctp" else True,
    )
    history = camera_handoff_window.HistoryTab()
    scanner = service_intelligence_window.PortScanner(history)
    qtbot.addWidget(history)
    qtbot.addWidget(scanner)
    return scanner


def test_parse_port_list_is_deterministic_and_bounded():
    assert service_intelligence_window._parse_port_list("161, 53,53") == (53, 161)
    assert service_intelligence_window._parse_port_list(
        service_intelligence_window.DEFAULT_UDP_PORTS
    ) == (53, 67, 68, 123, 161, 5353)
    with pytest.raises(ValueError, match="al menos"):
        service_intelligence_window._parse_port_list("  ")
    with pytest.raises(ValueError, match="no válido"):
        service_intelligence_window._parse_port_list("dns")
    with pytest.raises(ValueError, match="fuera de rango"):
        service_intelligence_window._parse_port_list("0")
    excessive = ",".join(str(index) for index in range(1, 34))
    with pytest.raises(ValueError, match="máximo"):
        service_intelligence_window._parse_port_list(excessive)


def test_windows_sctp_controls_are_truthfully_disabled(qtbot, monkeypatch):
    scanner = _scanner(qtbot, monkeypatch, sctp=False)

    assert not scanner.sctp_button.isEnabled()
    assert not scanner.sctp_ports_input.isEnabled()
    assert "Linux" in scanner.sctp_button.toolTip()

    scanner.scan_sctp_services()
    assert "no está disponible" in scanner.result_area.toPlainText()


def test_sctp_action_is_advanced_and_explicit_when_capability_exists(qtbot, monkeypatch):
    scanner = _scanner(qtbot, monkeypatch, sctp=True)
    scanner.ip_input.setText("example.test")
    scanner.sctp_ports_input.setText("3868,2905")
    calls = []
    monkeypatch.setattr(
        scanner,
        "_start_transport_worker",
        lambda **kwargs: calls.append(kwargs),
    )

    scanner.scan_sctp_services()

    assert calls == [{"transport": "sctp", "ports": (2905, 3868)}]
    assert "Service Intelligence SCTP" in scanner.result_area.toPlainText()


def test_misconfigs_requires_confirmed_tcp_ports_and_starts_separate_mode(qtbot, monkeypatch):
    scanner = _scanner(qtbot, monkeypatch)
    scanner.ip_input.setText("example.test")

    scanner.scan_misconfigs()
    assert "No hay puertos TCP confirmados" in scanner.result_area.toPlainText()

    scanner.open_ports = (OpenPort(443, "https"), OpenPort(22, "ssh"))
    calls = []
    monkeypatch.setattr(
        scanner,
        "_start_transport_worker",
        lambda **kwargs: calls.append(kwargs),
    )
    scanner.scan_misconfigs()

    assert calls == [{"transport": "tcp", "ports": (22, 443), "misconfigs": True}]
    assert "--misconfigs" in scanner.result_area.toPlainText()


def test_running_state_controls_new_actions(qtbot, monkeypatch):
    scanner = _scanner(qtbot, monkeypatch, sctp=True)
    scanner.open_ports = (OpenPort(22, "ssh"),)
    scanner._set_running(False)

    assert scanner.udp_button.isEnabled()
    assert scanner.sctp_button.isEnabled()
    assert scanner.misconfigs_button.isEnabled()

    scanner._set_running(True)
    assert not scanner.udp_button.isEnabled()
    assert not scanner.sctp_button.isEnabled()
    assert not scanner.misconfigs_button.isEnabled()


def test_udp_action_validates_target_ports_and_starts_worker(qtbot, monkeypatch):
    scanner = _scanner(qtbot, monkeypatch)
    scanner.udp_ports_input.setText("bad")
    scanner.scan_udp_services()
    assert "Error UDP" in scanner.result_area.toPlainText()

    scanner.result_area.clear()
    scanner.udp_ports_input.setText("53,161")
    scanner.scan_udp_services()
    assert "dirección IP" in scanner.result_area.toPlainText()

    scanner.result_area.clear()
    scanner.ip_input.setText("example.test")
    monkeypatch.setattr(service_intelligence_window.UdpFingerprintWorker, "start", lambda self: None)
    scanner.scan_udp_services()
    assert isinstance(scanner.worker, service_intelligence_window.UdpFingerprintWorker)
    assert scanner.worker.ports == (53, 161)
    assert not scanner.udp_button.isEnabled()


def test_udp_results_preserve_ambiguous_state_and_merge_identified_fingerprint(qtbot, monkeypatch):
    scanner = _scanner(qtbot, monkeypatch)
    fingerprint = ServiceFingerprint(
        host="dns.local",
        ip="192.0.2.10",
        port=53,
        protocol="dns",
        transport="udp",
        product="BIND",
        version="9.20",
    )
    results = (
        UdpProbeResult(
            host="dns.local",
            ip="192.0.2.10",
            port=53,
            state=UdpPortState.OPEN,
            fingerprint=fingerprint,
        ),
        UdpProbeResult(
            host="dns.local",
            ip="192.0.2.10",
            port=161,
            state=UdpPortState.OPEN_FILTERED,
        ),
    )

    scanner._udp_results_ready(results)

    assert scanner.udp_probe_results == results
    assert scanner.fingerprints == (fingerprint,)
    text = scanner.result_area.toPlainText()
    assert "53/udp  open · dns BIND 9.20" in text
    assert "161/udp  open|filtered" in text


def test_transport_results_merge_findings_and_show_severity(qtbot, monkeypatch):
    scanner = _scanner(qtbot, monkeypatch)
    original = ServiceFingerprint(
        host="x",
        ip="192.0.2.10",
        port=22,
        protocol="ssh",
        product="OpenSSH",
        version="9.8",
    )
    scanner._remember_fingerprints((original,))
    finding = ServiceSecurityFinding(
        finding_id="weak-setting",
        severity=SecurityFindingSeverity.MEDIUM,
        description="Weak service setting",
    )
    enriched = ServiceFingerprint(
        host="x",
        ip="192.0.2.10",
        port=443,
        protocol="https",
        product="nginx",
        version="1.27",
        security_findings=(finding,),
    )

    scanner._transport_results_ready((enriched,))

    assert len(scanner.fingerprints) == 2
    assert {item.port for item in scanner.fingerprints} == {22, 443}
    assert "FINDING  [MEDIUM] weak-setting" in scanner.result_area.toPlainText()


def test_workers_delegate_exact_modes_and_report_failures(monkeypatch):
    finding = ServiceSecurityFinding(
        finding_id="x",
        severity=SecurityFindingSeverity.LOW,
        description="test",
    )
    expected = [
        ServiceFingerprint(
            host="x",
            ip="192.0.2.10",
            port=22,
            protocol="ssh",
            security_findings=(finding,),
        )
    ]
    calls = []

    def fake_fingerprint(target, ports, **kwargs):
        calls.append((target, tuple(ports), kwargs))
        return expected

    monkeypatch.setattr(service_intelligence_window.fingerprinting, "fingerprint_open_ports", fake_fingerprint)
    worker = service_intelligence_window.TransportFingerprintWorker(
        "x", (22,), transport="tcp", misconfigs=True
    )
    captured = []
    worker.results_ready.connect(captured.append)
    worker.run()

    assert captured == [expected]
    assert calls[0][2]["transport"] == "tcp"
    assert calls[0][2]["misconfigs"] is True

    def fail(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(service_intelligence_window.fingerprinting, "fingerprint_open_ports", fail)
    failed_worker = service_intelligence_window.TransportFingerprintWorker(
        "x", (22,), transport="tcp"
    )
    failures = []
    failed_worker.failed.connect(failures.append)
    failed_worker.run()
    assert isinstance(failures[0], RuntimeError)


def test_udp_worker_delegates_and_supports_stop(monkeypatch):
    expected = [
        UdpProbeResult(
            host="x",
            ip="192.0.2.10",
            port=53,
            state=UdpPortState.OPEN_FILTERED,
        )
    ]
    monkeypatch.setattr(
        service_intelligence_window.fingerprinting,
        "probe_udp_ports",
        lambda *_args, **_kwargs: expected,
    )
    worker = service_intelligence_window.UdpFingerprintWorker("x", (53,))
    captured = []
    worker.results_ready.connect(captured.append)
    worker.run()
    assert captured == [expected]

    worker.stop()
    assert worker._stop_event.is_set()


def test_start_transport_worker_rejects_empty_target_and_running_worker(qtbot, monkeypatch):
    scanner = _scanner(qtbot, monkeypatch)
    scanner._start_transport_worker(transport="tcp", ports=(22,))
    assert "dirección IP" in scanner.result_area.toPlainText()

    scanner.result_area.clear()
    scanner.ip_input.setText("example.test")
    scanner.worker = SimpleNamespace(isRunning=lambda: True)
    scanner._start_transport_worker(transport="tcp", ports=(22,))
    assert scanner.result_area.toPlainText() == ""
