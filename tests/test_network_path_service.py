from __future__ import annotations

import json

import pytest

from pythonkni.network_path import service
from pythonkni.network_path.models import (
    AddressFamily,
    PathEvent,
    PathEventSeverity,
    PathHistoryPoint,
    TraceProtocol,
)


def test_validate_target_accepts_ip_hostname_and_idna():
    assert service.validate_target(" 8.8.8.8 ") == "8.8.8.8"
    assert service.validate_target("Example.COM.") == "example.com"
    assert service.validate_target("münich.example") == "xn--mnich-kva.example"


@pytest.mark.parametrize(
    "value",
    ["", "a b", "10.0.0.0/24", "one,two", "one;two", "https://example.com", "a\\b"],
)
def test_validate_target_rejects_non_single_targets(value):
    with pytest.raises(ValueError):
        service.validate_target(value)


def test_validate_target_rejects_invalid_or_too_long_hostname():
    with pytest.raises(ValueError, match="DNS"):
        service.validate_target("bad_label.example")
    with pytest.raises(ValueError, match="largo"):
        service.validate_target("a" * 254)


def test_normalizers_enforce_protocol_family_interval_ttl_and_port():
    assert service.normalize_protocol("TCP") is TraceProtocol.TCP
    assert service.normalize_address_family("ipv6") is AddressFamily.IPV6
    assert service.normalize_interval("0.5") == 0.5
    assert service.normalize_max_ttl("64") == 64
    assert service.normalize_port(0) is None
    assert service.normalize_port("443") == 443

    with pytest.raises(ValueError, match="ICMP"):
        service.normalize_protocol("sctp")
    with pytest.raises(ValueError, match="familia"):
        service.normalize_address_family("anything")
    with pytest.raises(ValueError, match="intervalo"):
        service.normalize_interval("nope")
    with pytest.raises(ValueError, match="entre"):
        service.normalize_interval(0.1)
    with pytest.raises(ValueError, match="entero"):
        service.normalize_max_ttl("x")
    with pytest.raises(ValueError, match="entre"):
        service.normalize_max_ttl(65)
    with pytest.raises(ValueError, match="entero"):
        service.normalize_port("x")
    with pytest.raises(ValueError, match="entre"):
        service.normalize_port(70000)


def test_build_request_normalizes_and_strips_icmp_port():
    request = service.build_request(
        "Example.com",
        protocol="icmp",
        interval_seconds=1,
        max_ttl=30,
        port=443,
        address_family="system",
    )
    assert request.target == "example.com"
    assert request.protocol is TraceProtocol.ICMP
    assert request.port is None
    assert request.address_family is AddressFamily.AUTO

    tcp = service.build_request("1.1.1.1", protocol="tcp", port=8443)
    assert tcp.port == 8443


def test_jsonl_persistence_serializes_history_and_events(tmp_path):
    history_path = tmp_path / "history.jsonl"
    event_path = tmp_path / "events.jsonl"
    service.append_history_jsonl(
        history_path,
        PathHistoryPoint(10.0, "8.8.8.8", 31.5, 5.0, 5, True, 3),
    )
    service.append_events_jsonl(
        event_path,
        (
            PathEvent(
                "event-1",
                "latency_spike",
                PathEventSeverity.WARNING,
                10.0,
                "Latency spike",
                "Latency increased.",
                "8.8.8.8",
                3,
                "192.0.2.1",
            ),
        ),
    )
    history = json.loads(history_path.read_text(encoding="utf-8"))
    event = json.loads(event_path.read_text(encoding="utf-8"))
    assert history["destination_rtt_ms"] == 31.5
    assert history["issue_hop_ttl"] == 3
    assert event["kind"] == "latency_spike"
    assert event["hop_ip"] == "192.0.2.1"


def test_bounded_jsonl_trims_to_recent_records(tmp_path, monkeypatch):
    path = tmp_path / "history.jsonl"
    monkeypatch.setattr(service, "JSONL_TRIM_BYTES", 1)
    monkeypatch.setattr(service, "JSONL_MAX_RECORDS", 2)
    for index in range(4):
        service._append_jsonl_bounded(path, ({"index": index},))
    lines = path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["index"] for line in lines] == [2, 3]


def test_bounded_jsonl_empty_records_do_not_create_file(tmp_path):
    path = tmp_path / "none.jsonl"
    service._append_jsonl_bounded(path, ())
    assert not path.exists()
