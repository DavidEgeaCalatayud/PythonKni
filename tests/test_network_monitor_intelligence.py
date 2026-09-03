from __future__ import annotations

from types import SimpleNamespace

from pythonkni.network_monitor import intelligence
from pythonkni.network_monitor.models import (
    ConnectionObservation,
    EndpointScope,
    EventSeverity,
    KnownAssetRef,
    MonitorSnapshot,
    TrafficSample,
)


def connection(
    *,
    process="chrome.exe",
    pid=100,
    local_port=50000,
    remote_ip="8.8.8.8",
    remote_port=443,
    scope=EndpointScope.PUBLIC,
    status="ESTABLISHED",
    transport="tcp",
):
    return ConnectionObservation(
        transport=transport,
        family="ipv4",
        local_ip="192.168.1.10",
        local_port=local_port,
        remote_ip=remote_ip,
        remote_port=remote_port,
        status=status,
        pid=pid,
        process_name=process,
        adapter="Ethernet",
        scope=scope,
        protocol="HTTPS" if remote_port == 443 else transport.upper(),
    )


def snapshot(*connections, timestamp=1000.0, rx=1000.0, tx=500.0):
    return MonitorSnapshot(
        timestamp=timestamp,
        adapter="Ethernet",
        traffic=TrafficSample(rx_bps=rx, tx_bps=tx),
        connections=tuple(connections),
    )


def kinds(update):
    return [event.kind for event in update.events]


def test_first_external_connection_generates_temporal_events_once():
    state = intelligence.MonitorState(traffic_spike_bps=99999999)
    item = connection(remote_port=4444)
    first = state.observe(snapshot(item))
    assert set(kinds(first)) == {
        "new_remote_host",
        "process_network_activity",
        "new_external_connection",
        "unusual_destination",
    }
    second = state.observe(snapshot(item, timestamp=1001.0))
    assert second.events == ()
    assert len(second.history) == 2


def test_listener_and_private_known_asset_are_detected():
    listener = connection(
        process="sshd.exe",
        pid=22,
        local_port=22,
        remote_ip=None,
        remote_port=None,
        scope=EndpointScope.UNSPECIFIED,
        status="LISTEN",
    )
    private = connection(
        process="python.exe",
        pid=200,
        remote_ip="192.168.1.30",
        remote_port=22,
        scope=EndpointScope.PRIVATE,
    )
    known = {"192.168.1.30": KnownAssetRef("asset-1", "192.168.1.30", "NAS")}
    update = intelligence.MonitorState().observe(snapshot(listener, private), known_assets=known)
    assert "new_listening_port" in kinds(update)
    assert "known_asset_connection" in kinds(update)
    host = next(item for item in update.hosts if item.ip == "192.168.1.30")
    assert host.known_asset_id == "asset-1"
    assert host.known_asset_label == "NAS"


def test_process_and_host_aggregation():
    connections = (
        connection(process="chrome.exe", pid=1, remote_ip="8.8.8.8", remote_port=443),
        connection(process="chrome.exe", pid=1, remote_ip="1.1.1.1", remote_port=443),
        connection(process="discord.exe", pid=2, remote_ip="8.8.8.8", remote_port=443),
    )
    update = intelligence.MonitorState(traffic_spike_bps=99999999).observe(snapshot(*connections))
    chrome = next(item for item in update.processes if item.process_name == "chrome.exe")
    assert chrome.connection_count == 2
    assert chrome.external_connections == 2
    assert chrome.remote_hosts == ("1.1.1.1", "8.8.8.8")
    google = next(item for item in update.hosts if item.ip == "8.8.8.8")
    assert google.connection_count == 2
    assert google.processes == ("chrome.exe", "discord.exe")


def test_dns_enrichment_is_cached_and_bounded():
    calls = []

    def resolver(ip):
        calls.append(ip)
        return f"host-{ip}"

    items = tuple(
        connection(pid=index, remote_ip=f"8.8.8.{index}", remote_port=443)
        for index in range(1, 7)
    )
    state = intelligence.MonitorState(traffic_spike_bps=99999999)
    update = state.observe(snapshot(*items), resolver=resolver)
    assert len(calls) == intelligence.MAX_DNS_LOOKUPS_PER_SAMPLE
    assert sum(bool(item.hostname) for item in update.snapshot.connections) == 4
    state.observe(snapshot(*items, timestamp=1001.0), resolver=resolver)
    assert len(calls) == 6
    state.observe(snapshot(*items, timestamp=1002.0), resolver=resolver)
    assert len(calls) == 6


def test_traffic_spike_only_fires_on_threshold_transition():
    state = intelligence.MonitorState(traffic_spike_bps=1000)
    first = state.observe(snapshot(timestamp=1.0, rx=900, tx=200))
    assert kinds(first) == ["traffic_spike"]
    second = state.observe(snapshot(timestamp=2.0, rx=1200, tx=0))
    assert "traffic_spike" not in kinds(second)
    state.observe(snapshot(timestamp=3.0, rx=100, tx=0))
    fourth = state.observe(snapshot(timestamp=4.0, rx=1000, tx=1))
    assert kinds(fourth) == ["traffic_spike"]
    assert fourth.events[0].severity is EventSeverity.WARNING


def test_load_known_assets_maps_hostname_kind_and_ip(monkeypatch, tmp_path):
    assets = [
        SimpleNamespace(
            asset_id="1",
            ip="192.168.1.1",
            hostname="router.local",
            kind=SimpleNamespace(value="Router"),
        ),
        SimpleNamespace(
            asset_id="2", ip="192.168.1.2", hostname="", kind=SimpleNamespace(value="NAS")
        ),
        SimpleNamespace(asset_id="3", ip="192.168.1.3", hostname="", kind=None),
    ]

    class Store:
        def __init__(self, path):
            assert path == tmp_path / "db.sqlite3"

        def list_assets(self):
            return assets

    monkeypatch.setattr(intelligence, "_inventory_store", lambda path: Store(path))
    result = intelligence.load_known_assets(tmp_path / "db.sqlite3")
    assert result["192.168.1.1"].label == "router.local"
    assert result["192.168.1.2"].label == "NAS"
    assert result["192.168.1.3"].label == "192.168.1.3"


def test_event_ids_are_deterministic_between_states():
    item = connection(remote_port=4444)
    first = intelligence.MonitorState(traffic_spike_bps=99999999).observe(snapshot(item))
    second = intelligence.MonitorState(traffic_spike_bps=99999999).observe(snapshot(item))
    assert [event.event_id for event in first.events] == [event.event_id for event in second.events]


def test_asn_enrichment_is_opt_in_public_only_cached_and_bounded():
    from pythonkni.network_monitor.models import AsnInfo

    calls = []

    def resolver(ip):
        calls.append(ip)
        return AsnInfo((64500 + len(calls),), f"{ip}/32")

    items = tuple(
        connection(pid=index, remote_ip=f"8.8.4.{index}", remote_port=443)
        for index in range(1, 5)
    ) + (
        connection(
            pid=20,
            remote_ip="192.168.1.30",
            remote_port=22,
            scope=EndpointScope.PRIVATE,
        ),
    )
    state = intelligence.MonitorState(traffic_spike_bps=99999999)
    first = state.observe(snapshot(*items), asn_resolver=resolver)
    assert len(calls) == intelligence.MAX_ASN_LOOKUPS_PER_SAMPLE
    assert sum(bool(host.asn) for host in first.hosts) == 2
    assert all(ip.startswith("8.8.4.") for ip in calls)
    second = state.observe(snapshot(*items, timestamp=1001), asn_resolver=resolver)
    assert len(calls) == 4
    assert sum(bool(host.asn) for host in second.hosts) == 4
    state.observe(snapshot(*items, timestamp=1002), asn_resolver=resolver)
    assert len(calls) == 4
