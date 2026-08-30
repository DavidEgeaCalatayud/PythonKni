import socket
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from pythonkni.network import service as network
from pythonkni.network.models import DiscoveredHost, NetworkInterface, OpenPort


def test_get_ipv4_interfaces_skips_down_incomplete_and_invalid_entries(monkeypatch):
    addresses = {
        "Down": [
            SimpleNamespace(
                family=socket.AF_INET,
                address="192.168.1.10",
                netmask="255.255.255.0",
            )
        ],
        "Mixed": [
            SimpleNamespace(family=socket.AF_INET6, address="::1", netmask="ffff::"),
            SimpleNamespace(family=socket.AF_INET, address="", netmask="255.255.255.0"),
            SimpleNamespace(family=socket.AF_INET, address="10.0.0.1", netmask=None),
            SimpleNamespace(family=socket.AF_INET, address="bad-ip", netmask="255.255.255.0"),
            SimpleNamespace(
                family=socket.AF_INET,
                address="0.0.0.0",
                netmask="0.0.0.0",
            ),
            SimpleNamespace(
                family=socket.AF_INET,
                address="10.0.0.20",
                netmask="255.255.255.0",
            ),
        ],
    }
    stats = {
        "Down": SimpleNamespace(isup=False),
        "Mixed": SimpleNamespace(isup=True),
    }
    monkeypatch.setattr(network.psutil, "net_if_addrs", lambda: addresses)
    monkeypatch.setattr(network.psutil, "net_if_stats", lambda: stats)

    result = network.get_ipv4_interfaces()

    assert result == [NetworkInterface("Mixed", "10.0.0.20", "255.255.255.0", "10.0.0.0/24")]


class FakeDatagramSocket:
    def __init__(self, *, error=None):
        self.error = error
        self.connected = None
        self.closed = False

    def connect(self, target):
        self.connected = target
        if self.error:
            raise self.error

    def getsockname(self):
        return ("192.168.50.20", 54321)

    def close(self):
        self.closed = True


def test_get_default_route_address_success_and_failure(monkeypatch):
    success = FakeDatagramSocket()
    monkeypatch.setattr(network.socket, "socket", lambda *_args: success)

    assert network.get_default_route_address() == "192.168.50.20"
    assert success.connected == network.DEFAULT_ROUTE_PROBE
    assert success.closed

    failed = FakeDatagramSocket(error=OSError("no route"))
    monkeypatch.setattr(network.socket, "socket", lambda *_args: failed)

    assert network.get_default_route_address() is None
    assert failed.closed


def test_detect_default_network_rejects_empty_and_uses_deterministic_fallback(monkeypatch):
    with pytest.raises(RuntimeError, match="ninguna interfaz"):
        network.detect_default_network([])

    interfaces = [
        NetworkInterface("Z-public", "8.8.8.8", "255.255.255.0", "8.8.8.0/24"),
        NetworkInterface("Link", "169.254.1.2", "255.255.0.0", "169.254.0.0/16"),
        NetworkInterface("B-private", "192.168.1.2", "255.255.255.0", "192.168.1.0/24"),
        NetworkInterface("A-private", "10.0.0.2", "255.255.255.0", "10.0.0.0/24"),
    ]
    monkeypatch.setattr(network, "get_default_route_address", lambda: "203.0.113.99")

    assert network.detect_default_network(interfaces).name == "A-private"


def test_ping_command_switches_by_platform(monkeypatch):
    monkeypatch.setattr(network.platform, "system", lambda: "Windows")
    assert network._ping_command("192.0.2.1") == [
        "ping",
        "-n",
        "1",
        "-w",
        "800",
        "192.0.2.1",
    ]

    monkeypatch.setattr(network.platform, "system", lambda: "Linux")
    assert network._ping_command("192.0.2.1") == [
        "ping",
        "-c",
        "1",
        "-W",
        "1",
        "192.0.2.1",
    ]


def test_get_mac_address_returns_value_and_handles_failures(monkeypatch):
    monkeypatch.setattr(
        network.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout="192.0.2.1 aa-bb-cc-dd-ee-ff dynamic"),
    )
    assert network.get_mac_address("192.0.2.1") == "aa-bb-cc-dd-ee-ff"

    def fail(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("arp", 2)

    monkeypatch.setattr(network.subprocess, "run", fail)
    assert network.get_mac_address("192.0.2.1") == "No disponible"


def test_reverse_dns_returns_resolved_name_and_handles_lookup_error(monkeypatch):
    monkeypatch.setattr(
        network.socket,
        "gethostbyaddr",
        lambda _ip: ("host.example", [], []),
    )
    assert network.reverse_dns_name("192.0.2.1", timeout=1) == "host.example"

    def fail(_ip):
        raise socket.herror("missing")

    monkeypatch.setattr(network.socket, "gethostbyaddr", fail)
    assert network.reverse_dns_name("192.0.2.1", timeout=1) == "No resuelto"


def test_probe_host_short_circuits_when_stopped(monkeypatch):
    stop = threading.Event()
    stop.set()
    calls = []
    monkeypatch.setattr(network.subprocess, "run", lambda *_args, **_kwargs: calls.append(1))

    assert network._probe_host("192.0.2.1", stop) is None
    assert calls == []


def test_probe_host_success_and_stop_after_ping(monkeypatch):
    monkeypatch.setattr(
        network.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout="Reply: time=1ms TTL=64",
        ),
    )
    monkeypatch.setattr(network, "reverse_dns_name", lambda _ip: "host")
    monkeypatch.setattr(network, "get_mac_address", lambda _ip: "aa-bb-cc-dd-ee-ff")

    assert network._probe_host("192.0.2.1", threading.Event()) == DiscoveredHost(
        "192.0.2.1",
        "host",
        "aa-bb-cc-dd-ee-ff",
    )

    stop = threading.Event()

    def dns_and_stop(_ip):
        stop.set()
        return "host"

    monkeypatch.setattr(network, "reverse_dns_name", dns_and_stop)
    assert network._probe_host("192.0.2.1", stop) is None


def test_probe_host_handles_ping_timeout(monkeypatch):
    def fail(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("ping", 2)

    monkeypatch.setattr(network.subprocess, "run", fail)
    assert network._probe_host("192.0.2.1", threading.Event()) is None


def test_bounded_future_results_honours_minimum_pending_and_stop():
    stop = threading.Event()

    def work(item):
        if item == 1:
            stop.set()
        return item

    with ThreadPoolExecutor(max_workers=1) as executor:
        results = list(
            network._bounded_future_results(
                [1, 2, 3],
                executor,
                work,
                stop,
                max_pending=0,
            )
        )

    assert results
    assert results[0][0] == 1
    assert len(results) < 3


def test_scan_network_hosts_callbacks_and_probe_exception():
    checked = []
    found_callback = []

    def probe(ip, _stop):
        if ip.endswith(".1"):
            return DiscoveredHost(ip, "one", "aa")
        if ip.endswith(".2"):
            raise RuntimeError("probe failed")
        return None

    result = network.scan_network_hosts(
        "192.168.10.0/30",
        max_workers=1,
        probe_func=probe,
        on_checked=checked.append,
        on_found=found_callback.append,
    )

    assert result == [DiscoveredHost("192.168.10.1", "one", "aa")]
    assert set(checked) == {"192.168.10.1", "192.168.10.2"}
    assert found_callback == result


def test_known_service_name_uses_system_database(monkeypatch):
    monkeypatch.setattr(network.socket, "getservbyport", lambda port, proto: "custom")
    assert network.known_service_name(1234) == "custom"


def test_probe_port_configures_timeout_and_connects(monkeypatch):
    calls = []

    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def settimeout(self, timeout):
            calls.append(("timeout", timeout))

        def connect_ex(self, address):
            calls.append(("connect", address))
            return 0

    monkeypatch.setattr(network.socket, "socket", lambda *_args: FakeSocket())

    assert network._probe_port("192.0.2.1", 443, 0.25)
    assert calls == [
        ("timeout", 0.25),
        ("connect", ("192.0.2.1", 443)),
    ]


def test_scan_open_ports_callbacks_and_probe_errors(monkeypatch):
    monkeypatch.setattr(network.socket, "gethostbyname", lambda _target: "192.0.2.5")
    monkeypatch.setattr(network, "known_service_name", lambda port: f"service-{port}")
    checked = []
    opened = []

    def probe(_ip, port, _timeout):
        if port == 20:
            raise OSError("closed")
        if port == 21:
            raise RuntimeError("unexpected")
        return port == 22

    result = network.scan_open_ports(
        "example.test",
        20,
        22,
        max_workers=1,
        probe_func=probe,
        on_checked=checked.append,
        on_open=opened.append,
    )

    assert set(checked) == {20, 21, 22}
    assert result == [OpenPort(22, "service-22")]
    assert opened == result


def test_scan_open_ports_pre_cancelled_event_returns_without_callbacks(monkeypatch):
    monkeypatch.setattr(network.socket, "gethostbyname", lambda _target: "192.0.2.5")
    stop = threading.Event()
    stop.set()
    checked = []

    result = network.scan_open_ports(
        "example.test",
        1,
        10,
        stop_event=stop,
        probe_func=lambda *_args: True,
        on_checked=checked.append,
    )

    assert result == []
    assert checked == []
