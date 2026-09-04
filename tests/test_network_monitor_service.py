from __future__ import annotations

import json
import socket
from types import SimpleNamespace

import psutil
import pytest

from pythonkni.network_monitor import service
from pythonkni.network_monitor.models import (
    EndpointScope,
    EventSeverity,
    MonitorEvent,
    NetworkAdapter,
    TrafficCounters,
)


def adapter(name="Ethernet", addresses=("192.168.1.10",), *, sent=1000, recv=2000):
    return NetworkAdapter(name, addresses, True, 1000, 1500, sent, recv)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, EndpointScope.UNSPECIFIED),
        ("", EndpointScope.UNSPECIFIED),
        ("0.0.0.0", EndpointScope.UNSPECIFIED),
        ("127.0.0.1", EndpointScope.LOOPBACK),
        ("192.168.1.2", EndpointScope.PRIVATE),
        ("169.254.1.2", EndpointScope.LINK_LOCAL),
        ("224.0.0.251", EndpointScope.MULTICAST),
        ("8.8.8.8", EndpointScope.PUBLIC),
        ("not-an-ip", EndpointScope.UNKNOWN),
        ("fe80::1%12", EndpointScope.LINK_LOCAL),
    ],
)
def test_classify_ip(value, expected):
    assert service.classify_ip(value) is expected


def test_infer_protocol_prefers_remote_port_and_falls_back_to_transport():
    assert service.infer_protocol("tcp", 51500, 443) == "HTTPS"
    assert service.infer_protocol("udp", 5353, None) == "MDNS"
    assert service.infer_protocol("tcp", 51500, 4444) == "TCP"


def test_calculate_traffic_handles_baseline_elapsed_and_counter_reset():
    current = TrafficCounters(timestamp=12.0, bytes_sent=1500, bytes_recv=5000)
    assert service.calculate_traffic(None, current).total_bps == 0
    zero = service.calculate_traffic(TrafficCounters(12.0, 1000, 1000), current)
    assert zero.total_bps == 0
    rate = service.calculate_traffic(TrafficCounters(10.0, 1000, 3000), current)
    assert rate.tx_bps == 250
    assert rate.rx_bps == 1000
    reset = service.calculate_traffic(TrafficCounters(10.0, 9999, 9999), current)
    assert reset.total_bps == 0


def test_read_traffic_counters_supports_all_and_named_adapter():
    adapters = (adapter("Ethernet", sent=100, recv=200), adapter("Wi-Fi", sent=50, recv=70))
    all_counters = service.read_traffic_counters(
        service.ALL_ADAPTERS, adapters=adapters, timestamp=1.5
    )
    assert (all_counters.bytes_sent, all_counters.bytes_recv) == (150, 270)
    wifi = service.read_traffic_counters("Wi-Fi", adapters=adapters, timestamp=2.0)
    assert (wifi.bytes_sent, wifi.bytes_recv) == (50, 70)
    missing = service.read_traffic_counters("Missing", adapters=adapters, timestamp=3.0)
    assert (missing.bytes_sent, missing.bytes_recv) == (0, 0)


def test_list_adapters_combines_addresses_stats_and_counters(monkeypatch):
    monkeypatch.setattr(
        service.psutil,
        "net_if_addrs",
        lambda: {
            "Ethernet": [
                SimpleNamespace(family=socket.AF_INET, address="192.168.1.10"),
                SimpleNamespace(family=socket.AF_INET6, address="fe80::1%7"),
                SimpleNamespace(family=999, address="ignored"),
            ]
        },
    )
    monkeypatch.setattr(
        service.psutil,
        "net_if_stats",
        lambda: {
            "Ethernet": SimpleNamespace(isup=True, speed=1000, mtu=1500),
            "Virtual": SimpleNamespace(isup=False, speed=-1, mtu=0),
        },
    )
    monkeypatch.setattr(
        service.psutil,
        "net_io_counters",
        lambda pernic=True: {"Ethernet": SimpleNamespace(bytes_sent=123, bytes_recv=456)},
    )
    result = service.list_adapters()
    assert [item.name for item in result] == ["Ethernet", "Virtual"]
    assert result[0].addresses == ("192.168.1.10", "fe80::1")
    assert result[0].bytes_recv == 456
    assert result[1].speed_mbps == 0


def test_collect_connections_filters_adapter_and_normalizes_process(monkeypatch):
    connections = [
        SimpleNamespace(
            laddr=SimpleNamespace(ip="192.168.1.10", port=51500),
            raddr=SimpleNamespace(ip="8.8.8.8", port=443),
            type=socket.SOCK_STREAM,
            family=socket.AF_INET,
            status="ESTABLISHED",
            pid=10,
        ),
        SimpleNamespace(
            laddr=("10.0.0.2", 5353),
            raddr=(),
            type=socket.SOCK_DGRAM,
            family=socket.AF_INET,
            status="NONE",
            pid=None,
        ),
        SimpleNamespace(
            laddr=("0.0.0.0", 22),
            raddr=(),
            type=socket.SOCK_STREAM,
            family=socket.AF_INET,
            status="LISTEN",
            pid=11,
        ),
    ]
    monkeypatch.setattr(service.psutil, "net_connections", lambda kind="inet": connections)

    class Proc:
        def __init__(self, pid):
            self.pid = pid

        def name(self):
            if self.pid == 11:
                raise psutil.AccessDenied(self.pid)
            return "chrome.exe"

    monkeypatch.setattr(service.psutil, "Process", Proc)
    adapters = (adapter("Ethernet"), adapter("VPN", ("10.0.0.2",)))
    result = service.collect_connections("Ethernet", adapters=adapters)
    assert len(result) == 2
    remote = next(item for item in result if item.remote_ip)
    assert remote.process_name == "chrome.exe"
    assert remote.protocol == "HTTPS"
    assert remote.scope is EndpointScope.PUBLIC
    listener = next(item for item in result if item.is_listener)
    assert listener.local_port == 22
    assert listener.process_name == service.UNKNOWN_PROCESS
    assert listener.adapter == service.ALL_ADAPTERS


def test_collect_connections_reuses_process_cache(monkeypatch):
    connection = SimpleNamespace(
        laddr=("192.168.1.10", 5000),
        raddr=("1.1.1.1", 53),
        type=socket.SOCK_DGRAM,
        family=socket.AF_INET6,
        status="",
        pid=99,
    )
    monkeypatch.setattr(service.psutil, "net_connections", lambda kind="inet": [connection])
    calls = []

    class Proc:
        def __init__(self, pid):
            calls.append(pid)

        def name(self):
            return "dns.exe"

    monkeypatch.setattr(service.psutil, "Process", Proc)
    cache = {}
    adapters = (adapter(),)
    first = service.collect_connections(adapters=adapters, process_cache=cache)
    second = service.collect_connections(adapters=adapters, process_cache=cache)
    assert first[0].family == "ipv6"
    assert first[0].protocol == "DNS"
    assert second[0].process_name == "dns.exe"
    assert calls == [99]


def test_reverse_dns_returns_empty_on_resolution_error(monkeypatch):
    monkeypatch.setattr(service.socket, "gethostbyaddr", lambda ip: ("example.test.", [], [ip]))
    assert service.reverse_dns("1.2.3.4") == "example.test"

    def fail(_ip):
        raise socket.herror()

    monkeypatch.setattr(service.socket, "gethostbyaddr", fail)
    assert service.reverse_dns("1.2.3.4") == ""


def test_append_events_jsonl(tmp_path):
    path = tmp_path / "nested" / "events.jsonl"
    event = MonitorEvent(
        event_id="abc",
        kind="new_remote_host",
        severity=EventSeverity.INFO,
        timestamp=1.0,
        title="title",
        description="description",
        process_name="proc.exe",
        remote_ip="1.2.3.4",
        port=443,
        asset_id="asset-1",
    )
    service.append_events_jsonl(path, ())
    assert not path.exists()
    service.append_events_jsonl(path, (event,))
    payload = json.loads(path.read_text(encoding="utf-8").strip())
    assert payload["event_id"] == "abc"
    assert payload["severity"] == "INFO"


def test_lookup_asn_is_public_only_and_parses_ripestat(monkeypatch):
    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": {"asns": [15169, "15169", "bad", 0], "prefix": "8.8.8.0/24"}}

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr(service.requests, "get", fake_get)
    assert service.lookup_asn("192.168.1.10").asns == ()
    result = service.lookup_asn("8.8.8.8")
    assert result.asns == (15169,)
    assert result.label == "AS15169"
    assert result.prefix == "8.8.8.0/24"
    assert calls[0][1]["params"]["sourceapp"] == "pythonkni-network-monitor"


def test_lookup_asn_degrades_on_http_or_json_error(monkeypatch):
    class Response:
        def raise_for_status(self):
            raise service.requests.RequestException("offline")

    monkeypatch.setattr(service.requests, "get", lambda *args, **kwargs: Response())
    assert service.lookup_asn("8.8.8.8").asns == ()


def test_append_history_jsonl_and_bounded_trim(monkeypatch, tmp_path):
    from pythonkni.network_monitor.models import MonitorHistoryPoint

    path = tmp_path / "history.jsonl"
    point = MonitorHistoryPoint(1.0, 2.0, 3.0, 4, 5, 6)
    service.append_history_jsonl(path, point)
    payload = json.loads(path.read_text(encoding="utf-8").strip())
    assert payload["connections"] == 4

    monkeypatch.setattr(service, "JSONL_TRIM_BYTES", 1)
    monkeypatch.setattr(service, "JSONL_MAX_RECORDS", 2)
    service.append_history_jsonl(path, MonitorHistoryPoint(2.0, 0, 0, 0, 0, 0))
    service.append_history_jsonl(path, MonitorHistoryPoint(3.0, 0, 0, 0, 0, 0))
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[-1])["timestamp"] == 3.0


def test_collect_snapshot_composes_adapters_connections_and_rates(monkeypatch):
    adapters = (adapter(sent=1600, recv=2600),)
    monkeypatch.setattr(service, "list_adapters", lambda: adapters)
    monkeypatch.setattr(
        service,
        "read_traffic_counters",
        lambda adapter_name, adapters=None: TrafficCounters(12.0, 1600, 2600),
    )
    monkeypatch.setattr(service, "collect_connections", lambda *args, **kwargs: ())
    previous = TrafficCounters(10.0, 1000, 2000)
    snap, counters = service.collect_snapshot("Ethernet", previous)
    assert counters.bytes_sent == 1600
    assert snap.adapter == "Ethernet"
    assert snap.traffic.tx_bps == 300
    assert snap.traffic.rx_bps == 300
