from __future__ import annotations

from pythonkni.network import window as network_window


def test_base_network_worker_reports_discovered_host_and_checked_count(monkeypatch):
    host = network_window.DiscoveredHost(
        ip="192.168.1.2",
        hostname="printer.local",
        mac="AA:BB:CC:DD:EE:FF",
    )

    def fake_scan(cidr, stop_event=None, on_found=None, on_checked=None, **_kwargs):
        assert cidr == "192.168.1.0/30"
        on_checked(host.ip)
        on_found(host)
        return [host]

    monkeypatch.setattr(network_window, "scan_network_hosts", fake_scan)
    worker = network_window.NetworkScanWorker("192.168.1.0/30")
    messages = []
    summaries = []
    worker.message.connect(messages.append)
    worker.finished_summary.connect(summaries.append)

    worker.run()

    assert any("Dispositivo: 192.168.1.2" in message for message in messages)
    assert summaries == [
        "Escaneo de 192.168.1.0/30:\n"
        "192.168.1.2 - Hostname: printer.local - MAC: AA:BB:CC:DD:EE:FF"
    ]


def test_base_network_worker_cancellation_keeps_partial_host_evidence(monkeypatch):
    host = network_window.DiscoveredHost(
        ip="192.168.1.2",
        hostname="printer.local",
        mac="AA:BB:CC:DD:EE:FF",
    )

    def fake_scan(_cidr, stop_event=None, on_found=None, on_checked=None, **_kwargs):
        on_checked(host.ip)
        on_found(host)
        stop_event.set()
        return [host]

    monkeypatch.setattr(network_window, "scan_network_hosts", fake_scan)
    worker = network_window.NetworkScanWorker("192.168.1.0/30")
    summaries = []
    cancelled = []
    worker.finished_summary.connect(summaries.append)
    worker.cancelled.connect(cancelled.append)

    worker.run()

    assert summaries[-1].startswith("[CANCELADO]")
    assert "1 hosts comprobados; 1 encontrados" in summaries[-1]
    assert "192.168.1.2" in summaries[-1]
    assert cancelled == summaries
