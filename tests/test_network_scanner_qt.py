import time

from tools import network_tool as network


class HistoryStub:
    def __init__(self):
        self.entries = []

    def append_to_history(self, entry):
        self.entries.append(entry)


def sample_interfaces():
    return [
        network.NetworkInterface(
            name="Ethernet",
            address="192.168.10.23",
            netmask="255.255.255.0",
            cidr="192.168.10.0/24",
        ),
        network.NetworkInterface(
            name="VPN",
            address="10.20.5.7",
            netmask="255.255.252.0",
            cidr="10.20.4.0/22",
        ),
    ]


def test_network_scanner_populates_detected_interfaces_and_uses_default_route(qtbot, monkeypatch):
    interfaces = sample_interfaces()
    monkeypatch.setattr(network, "get_ipv4_interfaces", lambda: interfaces)
    monkeypatch.setattr(network, "get_default_route_address", lambda: "10.20.5.7")

    scanner = network.NetworkScanner(HistoryStub())
    qtbot.addWidget(scanner)
    scanner.show()

    assert scanner.interface_combo.count() == 2
    assert scanner.interface_combo.currentIndex() == 1
    assert scanner.cidr_input.text() == "10.20.4.0/22"

    scanner.interface_combo.setCurrentIndex(0)
    assert scanner.cidr_input.text() == "192.168.10.0/24"


def test_network_scanner_accepts_manual_cidr_and_rejects_invalid_input(qtbot, monkeypatch):
    monkeypatch.setattr(network, "get_ipv4_interfaces", lambda: [])
    scanner = network.NetworkScanner(HistoryStub())
    qtbot.addWidget(scanner)
    scanner.show()

    scanner.cidr_input.setText("not-a-network")
    scanner.scan_network()

    assert "Error:" in scanner.result_area.toPlainText()
    assert scanner.worker is None


def test_port_scanner_validates_range_before_starting_worker(qtbot):
    scanner = network.PortScanner(HistoryStub())
    qtbot.addWidget(scanner)
    scanner.show()

    scanner.ip_input.setText("192.0.2.1")
    scanner.port_range_input.setText("100-20")
    scanner.scan_ports()

    assert "Error:" in scanner.result_area.toPlainText()
    assert scanner.worker is None


def test_network_worker_reports_found_hosts(monkeypatch, qtbot):
    host = network.DiscoveredHost("192.168.1.2", "printer", "aa-bb-cc-dd-ee-ff")

    def fake_scan(
        cidr,
        stop_event=None,
        max_workers=32,
        probe_func=None,
        on_found=None,
        on_checked=None,
        max_pending=None,
    ):
        assert cidr == "192.168.1.0/30"
        on_checked(host.ip)
        on_found(host)
        return [host]

    monkeypatch.setattr(network, "scan_network_hosts", fake_scan)
    worker = network.NetworkScanWorker("192.168.1.0/30")

    with qtbot.waitSignal(worker.finished_summary, timeout=2000) as result:
        worker.start()

    worker.wait()
    assert "192.168.1.2" in result.args[0]
    assert "printer" in result.args[0]
    assert "CANCELADO" not in result.args[0]


def test_network_worker_marks_cancelled_results_as_partial(monkeypatch, qtbot):
    host = network.DiscoveredHost("192.168.1.2", "printer", "No disponible")

    def fake_scan(cidr, stop_event=None, on_found=None, on_checked=None, **kwargs):
        on_checked(host.ip)
        on_found(host)
        stop_event.set()
        return [host]

    monkeypatch.setattr(network, "scan_network_hosts", fake_scan)
    worker = network.NetworkScanWorker("192.168.1.0/30")

    with qtbot.waitSignal(worker.finished_summary, timeout=2000) as result:
        worker.start()

    worker.wait()
    assert result.args[0].startswith("[CANCELADO]")
    assert "Resultados parciales" in result.args[0]
    assert "1 hosts comprobados" in result.args[0]


def test_port_worker_marks_cancelled_results_as_partial(monkeypatch, qtbot):
    open_port = network.OpenPort(22, "ssh")

    def fake_scan(target, start_port, end_port, stop_event=None, on_open=None, on_checked=None, **kwargs):
        on_checked(22)
        on_open(open_port)
        stop_event.set()
        return [open_port]

    monkeypatch.setattr(network, "scan_open_ports", fake_scan)
    worker = network.PortScanWorker("example.test", 1, 100)

    with qtbot.waitSignal(worker.finished_summary, timeout=2000) as result:
        worker.start()

    worker.wait()
    assert result.args[0].startswith("[CANCELADO]")
    assert "1 de 100 puertos comprobados" in result.args[0]
    assert "22/tcp abierto (ssh)" in result.args[0]


def test_tool_close_cancels_and_waits_for_both_network_threads(qtbot, monkeypatch, tmp_path):
    interfaces = sample_interfaces()[:1]
    monkeypatch.setattr(network, "SCAN_HISTORY_FILE", tmp_path / "network_history.txt")
    monkeypatch.setattr(network, "get_ipv4_interfaces", lambda: interfaces)
    monkeypatch.setattr(network, "get_default_route_address", lambda: interfaces[0].address)

    def slow_network_scan(cidr, stop_event=None, **kwargs):
        while not stop_event.is_set():
            time.sleep(0.005)
        return []

    def slow_port_scan(target, start_port, end_port, stop_event=None, **kwargs):
        while not stop_event.is_set():
            time.sleep(0.005)
        return []

    monkeypatch.setattr(network, "scan_network_hosts", slow_network_scan)
    monkeypatch.setattr(network, "scan_open_ports", slow_port_scan)

    tool = network.Tool()
    qtbot.addWidget(tool)
    tool.show()

    tool.network_scanner.scan_network()
    tool.port_scanner.ip_input.setText("192.0.2.1")
    tool.port_scanner.port_range_input.setText("1-100")
    tool.port_scanner.scan_ports()

    qtbot.waitUntil(
        lambda: tool.network_scanner.worker.isRunning() and tool.port_scanner.worker.isRunning(),
        timeout=2000,
    )

    tool.close()

    assert not tool.network_scanner.worker.isRunning()
    assert not tool.port_scanner.worker.isRunning()
    assert not tool.isVisible()
