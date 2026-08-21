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


def test_known_service_name_has_fallback_for_common_ports(monkeypatch):
    def unknown_service(*args):
        raise OSError

    monkeypatch.setattr(network.socket, "getservbyport", unknown_service)

    assert network.known_service_name(3306) == "mysql"
    assert network.known_service_name(65000) == "desconocido"
