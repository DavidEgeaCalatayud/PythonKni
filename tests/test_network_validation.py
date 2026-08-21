import socket
import threading
import time
from types import SimpleNamespace

import pytest

from tools import network_tool as network


def test_validate_port_range_accepts_valid_range():
    assert network.validate_port_range("20-80") == (20, 80)


@pytest.mark.parametrize("value", ["", "abc", "80", "90-20", "0-10", "1-70000"])
def test_validate_port_range_rejects_invalid_ranges(value):
    with pytest.raises(ValueError):
        network.validate_port_range(value)


def test_parse_network_cidr_uses_real_prefix_instead_of_assuming_24():
    parsed = network.parse_network_cidr("10.42.17.23/20")

    assert parsed.with_prefixlen == "10.42.16.0/20"


def test_parse_network_cidr_rejects_huge_or_ipv6_networks():
    with pytest.raises(ValueError, match="máximo"):
        network.parse_network_cidr("10.0.0.0/8")
    with pytest.raises(ValueError, match="IPv4"):
        network.parse_network_cidr("2001:db8::/120")


def test_get_ipv4_interfaces_uses_real_netmasks(monkeypatch):
    addresses = {
        "Ethernet": [
            SimpleNamespace(
                family=socket.AF_INET,
                address="192.168.50.17",
                netmask="255.255.255.0",
            )
        ],
        "VPN": [
            SimpleNamespace(
                family=socket.AF_INET,
                address="10.33.9.14",
                netmask="255.255.252.0",
            )
        ],
        "Loopback": [
            SimpleNamespace(
                family=socket.AF_INET,
                address="127.0.0.1",
                netmask="255.0.0.0",
            )
        ],
    }
    stats = {
        "Ethernet": SimpleNamespace(isup=True),
        "VPN": SimpleNamespace(isup=True),
        "Loopback": SimpleNamespace(isup=True),
    }
    monkeypatch.setattr(network.psutil, "net_if_addrs", lambda: addresses)
    monkeypatch.setattr(network.psutil, "net_if_stats", lambda: stats)

    interfaces = network.get_ipv4_interfaces()

    assert [(item.name, item.cidr) for item in interfaces] == [
        ("Ethernet", "192.168.50.0/24"),
        ("VPN", "10.33.8.0/22"),
    ]


def test_detect_default_network_uses_os_route_address(monkeypatch):
    interfaces = [
        network.NetworkInterface("Ethernet", "192.168.1.20", "255.255.255.0", "192.168.1.0/24"),
        network.NetworkInterface("VPN", "10.20.5.7", "255.255.252.0", "10.20.4.0/22"),
    ]
    monkeypatch.setattr(network, "get_default_route_address", lambda: "10.20.5.7")

    assert network.detect_default_network(interfaces) == interfaces[1]


def test_ping_success_requires_actual_reply_marker():
    assert network._ping_succeeded("Reply from 192.0.2.1: time=3ms TTL=64")
    assert network._ping_succeeded("Respuesta desde 192.0.2.1: tiempo=3ms TTL=64")
    assert not network._ping_succeeded("Reply from 192.0.2.254: Destination host unreachable.")
    assert not network._ping_succeeded("Tiempo de espera agotado para esta solicitud.")


def test_probe_host_rejects_unreachable_even_with_zero_returncode(monkeypatch):
    monkeypatch.setattr(
        network.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout="Reply from 192.0.2.254: Destination host unreachable.",
        ),
    )

    assert network._probe_host("192.0.2.1", threading.Event()) is None


def test_parse_arp_mac_matches_exact_ip_not_substring():
    output = """
      192.168.1.10          aa-bb-cc-dd-ee-10     dynamic
      192.168.1.1           aa-bb-cc-dd-ee-01     dynamic
    """

    assert network._parse_arp_mac(output, "192.168.1.1") == "aa-bb-cc-dd-ee-01"
    assert network._parse_arp_mac(output, "192.168.1.2") == "No disponible"


def test_parse_arp_mac_supports_linux_style_output():
    output = "gateway (192.168.1.1) at aa:bb:cc:dd:ee:ff [ether] on eth0"

    assert network._parse_arp_mac(output, "192.168.1.1") == "aa:bb:cc:dd:ee:ff"


def test_reverse_dns_has_a_real_timeout(monkeypatch):
    def slow_lookup(_ip):
        time.sleep(0.2)
        return ("late.example", [], [])

    monkeypatch.setattr(network.socket, "gethostbyaddr", slow_lookup)
    started = time.monotonic()

    result = network.reverse_dns_name("192.0.2.5", timeout=0.02)

    assert result == "No resuelto"
    assert time.monotonic() - started < 0.15


def test_network_scan_uses_limited_concurrency():
    lock = threading.Lock()
    active = 0
    peak = 0

    def probe(ip, stop_event):
        nonlocal active, peak
        assert not stop_event.is_set()
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.03)
        with lock:
            active -= 1
        if ip.endswith(".1") or ip.endswith(".2"):
            return network.DiscoveredHost(ip, "host", "aa-bb-cc-dd-ee-ff")
        return None

    found = network.scan_network_hosts(
        "192.168.5.0/29",
        max_workers=2,
        probe_func=probe,
    )

    assert [host.ip for host in found] == ["192.168.5.1", "192.168.5.2"]
    assert 1 < peak <= 2


def test_port_scan_returns_only_open_ports_with_service_names(monkeypatch):
    monkeypatch.setattr(network.socket, "gethostbyname", lambda target: "192.0.2.10")
    monkeypatch.setattr(network, "known_service_name", lambda port: {22: "ssh", 443: "https"}[port])

    def probe(ip, port, timeout):
        assert ip == "192.0.2.10"
        assert timeout > 0
        return port in {22, 443}

    results = network.scan_open_ports(
        "example.test",
        20,
        450,
        max_workers=8,
        probe_func=probe,
    )

    assert results == [
        network.OpenPort(22, "ssh"),
        network.OpenPort(443, "https"),
    ]


def test_port_scan_keeps_only_a_bounded_future_window(monkeypatch):
    original_executor = network.ThreadPoolExecutor
    gate = threading.Event()
    submitted = []

    class TrackingExecutor(original_executor):
        def submit(self, fn, *args, **kwargs):
            submitted.append(args)
            return super().submit(fn, *args, **kwargs)

    monkeypatch.setattr(network, "ThreadPoolExecutor", TrackingExecutor)
    monkeypatch.setattr(network.socket, "gethostbyname", lambda target: "192.0.2.10")

    def probe(_ip, _port, _timeout):
        gate.wait(1)
        return False

    scan_thread = threading.Thread(
        target=lambda: network.scan_open_ports(
            "example.test",
            1,
            200,
            max_workers=2,
            max_pending=4,
            probe_func=probe,
        )
    )
    scan_thread.start()
    time.sleep(0.05)

    assert 2 <= len(submitted) <= 4

    gate.set()
    scan_thread.join(2)
    assert not scan_thread.is_alive()
    assert len(submitted) == 200


def test_port_scan_cancellation_does_not_drain_queued_range(monkeypatch):
    monkeypatch.setattr(network.socket, "gethostbyname", lambda target: "192.0.2.10")
    stop_event = threading.Event()
    checked = []

    def probe(_ip, port, _timeout):
        if port == 1:
            stop_event.set()
        time.sleep(0.01)
        return False

    network.scan_open_ports(
        "example.test",
        1,
        500,
        stop_event=stop_event,
        max_workers=2,
        max_pending=4,
        probe_func=probe,
        on_checked=checked.append,
    )

    assert len(checked) < 500


def test_known_service_name_has_fallback_for_common_ports(monkeypatch):
    def unknown_service(*args):
        raise OSError

    monkeypatch.setattr(network.socket, "getservbyport", unknown_service)

    assert network.known_service_name(3306) == "mysql"
    assert network.known_service_name(65000) == "desconocido"
