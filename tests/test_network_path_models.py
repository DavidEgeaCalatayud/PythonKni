from pathlib import Path

from pythonkni.network_path.models import (
    BackendInfo,
    HopHost,
    HopProbe,
    TraceProtocol,
    TraceRequest,
    TraceSnapshot,
)


def test_hop_host_and_probe_helpers():
    named = HopHost("192.0.2.1", "router.example")
    unnamed = HopHost("192.0.2.2")
    assert named.label == "router.example"
    assert unnamed.label == "192.0.2.2"

    probe = HopProbe(2, (named, unnamed), 2, 1, 50.0, 12.0)
    assert probe.responded is True
    assert probe.primary_ip == "192.0.2.1"
    assert probe.primary_hostname == "router.example"
    assert probe.host_ips == ("192.0.2.1", "192.0.2.2")

    silent = HopProbe(3, (), 1, 0, 100.0, None)
    assert silent.responded is False
    assert silent.primary_ip == ""
    assert silent.primary_hostname == ""


def test_trace_snapshot_destination_helper_matches_resolved_ip():
    destination = HopProbe(3, (HopHost("8.8.8.8", "dns.google"),), 1, 1, 0.0, 30.0)
    snapshot = TraceSnapshot(
        1.0,
        "dns.google",
        "8.8.8.8",
        "dns.google",
        TraceProtocol.ICMP,
        None,
        (HopProbe(1, (), 1, 0, 100.0, None), destination),
        True,
    )
    assert snapshot.destination_hop is destination

    missing = TraceSnapshot(
        2.0,
        "dns.google",
        "8.8.8.8",
        "dns.google",
        TraceProtocol.ICMP,
        None,
        (),
        False,
    )
    assert missing.destination_hop is None


def test_backend_and_request_models_hold_runtime_contract():
    info = BackendInfo("Trippy", "0.13.0", Path("trip.exe"), True, False)
    request = TraceRequest("8.8.8.8")
    assert info.version == "0.13.0"
    assert info.elevated is False
    assert request.protocol is TraceProtocol.ICMP
    assert request.max_ttl == 30
