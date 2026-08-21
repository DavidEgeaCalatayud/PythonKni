from types import SimpleNamespace

from tools import network_tool as network


class HistoryStub:
    def __init__(self):
        self.entries = []

    def append_to_history(self, entry):
        self.entries.append(entry)


def test_network_scanner_populates_detected_interfaces_and_cidr(qtbot, monkeypatch):
    interfaces = [
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
    monkeypatch.setattr(network, "get_ipv4_interfaces", lambda: interfaces)

    scanner = network.NetworkScanner(HistoryStub())
    qtbot.addWidget(scanner)
    scanner.show()

    assert scanner.interface_combo.count() == 2
    assert scanner.cidr_input.text() == "192.168.10.0/24"

    scanner.interface_combo.setCurrentIndex(1)
    assert scanner.cidr_input.text() == "10.20.4.0/22"


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

    def fake_scan(cidr, stop_event=None, max_workers=32, probe_func=None, on_found=None):
        assert cidr == "192.168.1.0/30"
        on_found(host)
        return [host]

    monkeypatch.setattr(network, "scan_network_hosts", fake_scan)
    worker = network.NetworkScanWorker("192.168.1.0/30")

    with qtbot.waitSignal(worker.finished_summary, timeout=2000) as result:
        worker.start()

    worker.wait()
    assert "192.168.1.2" in result.args[0]
    assert "printer" in result.args[0]
