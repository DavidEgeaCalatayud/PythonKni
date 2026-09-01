from __future__ import annotations

import threading

import pytest

from pythonkni.camera_auditor.models import (
    CameraDevice,
    CameraServiceFinding,
    OnvifDiscoveryMatch,
    RiskLevel,
)
from pythonkni.network.models import DiscoveredHost
from pythonkni.network_intelligence import service
from pythonkni.network_intelligence.models import DeviceKind
from pythonkni.network_intelligence.service import (
    analyze_hosts,
    classify_device,
    inspect_host,
    probe_intelligence_ports,
)


def host(ip="192.168.1.20", hostname="No resuelto"):
    return DiscoveredHost(ip=ip, hostname=hostname, mac="AA:BB:CC:DD:EE:FF")


def test_local_ip_helper_accepts_local_addresses_and_rejects_invalid_or_public():
    assert service._is_local_ip("192.168.1.20") is True
    assert service._is_local_ip("127.0.0.1") is True
    assert service._is_local_ip("169.254.1.20") is True
    assert service._is_local_ip("8.8.8.8") is False
    assert service._is_local_ip("not-an-ip") is False


def test_gateway_style_address_handles_edges_and_invalid_values():
    assert service._gateway_style_address("192.168.1.1") is True
    assert service._gateway_style_address("192.168.1.254") is True
    assert service._gateway_style_address("192.168.1.20") is False
    assert service._gateway_style_address("::1") is False
    assert service._gateway_style_address("invalid") is False


def test_low_level_port_probe_reports_success_and_socket_failure(monkeypatch):
    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(service.socket, "create_connection", lambda *_args, **_kwargs: Connection())
    assert service._probe_port("192.168.1.20", 80) is True

    def fail(*_args, **_kwargs):
        raise OSError("unreachable")

    monkeypatch.setattr(service.socket, "create_connection", fail)
    assert service._probe_port("192.168.1.20", 80) is False


def test_probe_intelligence_ports_is_bounded_to_curated_ports():
    calls = []

    def probe(ip, port, timeout):
        calls.append((ip, port, timeout))
        return port in {80, 554}

    ports = probe_intelligence_ports("192.168.1.20", probe_func=probe)
    assert ports == (80, 554)
    assert len(calls) == 14
    assert all(call[0] == "192.168.1.20" for call in calls)


def test_probe_intelligence_ports_rejects_public_targets():
    with pytest.raises(ValueError):
        probe_intelligence_ports("8.8.8.8", probe_func=lambda *_args: False)


def test_classify_camera_from_rtsp_signal():
    device = classify_device(host(), (80, 554))
    assert device.kind == DeviceKind.CAMERA
    assert device.risk == RiskLevel.MEDIUM
    assert device.can_open_camera is True


def test_classify_camera_preserves_camera_auditor_risk_and_evidence():
    camera = CameraDevice(
        ip="192.168.1.20",
        vendor="Reolink",
        name="Patio",
        hardware="RLC",
        services=(CameraServiceFinding(protocol="RTSP", port=554),),
        onvif=True,
        confidence="Alta",
        risk=RiskLevel.MEDIUM,
        risk_reasons=("RTSP expuesto",),
    )
    device = classify_device(host(), (554,), camera=camera)
    assert device.kind == DeviceKind.CAMERA
    assert device.camera is camera
    assert "RTSP expuesto" in device.evidence


@pytest.mark.parametrize(
    ("hostname", "ports", "expected"),
    [
        ("office-printer", (631,), DeviceKind.PRINTER),
        ("DiskStation", (445, 5000), DeviceKind.NAS),
        ("router.home", (53, 80), DeviceKind.ROUTER),
        ("workstation", (3389,), DeviceKind.PC),
        ("No resuelto", (), DeviceKind.UNKNOWN),
    ],
)
def test_classification_heuristics(hostname, ports, expected):
    device = classify_device(host(hostname=hostname), ports)
    assert device.kind == expected


def test_hostname_only_camera_is_conservative_low_risk():
    device = classify_device(host(hostname="front-camera"), ())
    assert device.kind == DeviceKind.CAMERA
    assert device.risk == RiskLevel.LOW


def test_non_cleartext_printer_and_nas_signals_remain_low_risk():
    printer = classify_device(host(), (631,))
    nas = classify_device(host(), (5001,))
    assert printer.kind == DeviceKind.PRINTER
    assert printer.risk == RiskLevel.LOW
    assert nas.kind == DeviceKind.NAS
    assert nas.risk == RiskLevel.LOW


def test_smb_without_nas_evidence_is_pc():
    device = classify_device(host(), (445,))
    assert device.kind == DeviceKind.PC


def test_gateway_style_router_requires_dns_and_web():
    device = classify_device(host(ip="192.168.1.1"), (53, 443))
    assert device.kind == DeviceKind.ROUTER
    assert device.risk == RiskLevel.LOW


def test_gateway_http_router_is_medium_risk():
    device = classify_device(host(ip="192.168.1.254"), (53, 80))
    assert device.kind == DeviceKind.ROUTER
    assert device.risk == RiskLevel.MEDIUM


def test_cleartext_printer_and_nas_signals_raise_medium_risk():
    printer = classify_device(host(), (9100,))
    nas = classify_device(host(), (2049,))
    assert printer.risk == RiskLevel.MEDIUM
    assert nas.risk == RiskLevel.MEDIUM


def test_inspect_host_rejects_non_local_host_without_probing(monkeypatch):
    monkeypatch.setattr(
        service,
        "probe_intelligence_ports",
        lambda *_args, **_kwargs: pytest.fail("probe should not run"),
    )
    assert inspect_host(host("8.8.8.8")) is None


def test_inspect_host_uses_onvif_camera_evidence(monkeypatch):
    match = OnvifDiscoveryMatch(ip="192.168.1.20")
    camera = CameraDevice(
        ip="192.168.1.20",
        vendor="Hikvision",
        name="",
        hardware="",
        services=(),
        onvif=True,
        confidence="Alta",
        risk=RiskLevel.LOW,
    )
    monkeypatch.setattr(
        service,
        "probe_intelligence_ports",
        lambda *_args, **_kwargs: (),
    )
    monkeypatch.setattr(
        service,
        "probe_camera_host",
        lambda *_args, **_kwargs: camera,
    )
    result = inspect_host(host(), onvif_match=match)
    assert result is not None
    assert result.kind == DeviceKind.CAMERA
    assert result.camera is camera


def test_inspect_host_without_camera_signal_skips_camera_probe(monkeypatch):
    monkeypatch.setattr(
        service,
        "probe_camera_host",
        lambda *_args, **_kwargs: pytest.fail("camera probe should not run"),
    )
    result = inspect_host(
        host(),
        port_probe_func=lambda _ip, port, _timeout: port == 3389,
    )
    assert result is not None
    assert result.kind == DeviceKind.PC


def test_inspect_host_stops_before_network_activity_when_cancelled(monkeypatch):
    event = threading.Event()
    event.set()
    monkeypatch.setattr(
        service,
        "probe_intelligence_ports",
        lambda *_args, **_kwargs: pytest.fail("probe should not run"),
    )
    assert inspect_host(host(), stop_event=event) is None


def test_inspect_host_honors_cancellation_after_port_probe(monkeypatch):
    event = threading.Event()

    def probe(_ip, _port, _timeout):
        event.set()
        return False

    monkeypatch.setattr(
        service,
        "probe_camera_host",
        lambda *_args, **_kwargs: pytest.fail("camera probe should not run"),
    )
    assert inspect_host(host(), stop_event=event, port_probe_func=probe) is None


def test_analyze_hosts_filters_out_of_scope_hosts_and_reports_devices():
    hosts = [host("192.168.1.10"), host("192.168.2.10")]
    discovered = []
    checked = []

    def discovery(_network, **_kwargs):
        return []

    def inspect(item, **_kwargs):
        return classify_device(item, (3389,))

    results = analyze_hosts(
        "192.168.1.0/24",
        hosts,
        discovery_func=discovery,
        inspect_func=inspect,
        on_device=discovered.append,
        on_checked=checked.append,
    )
    assert [item.host.ip for item in results] == ["192.168.1.10"]
    assert [item.host.ip for item in discovered] == ["192.168.1.10"]
    assert [item.ip for item in checked] == ["192.168.1.10"]


def test_analyze_hosts_passes_onvif_match_into_host_inspection():
    match = OnvifDiscoveryMatch(ip="192.168.1.10")
    captured = []

    def discovery(_network, **_kwargs):
        return [match]

    def inspect(item, **kwargs):
        captured.append(kwargs.get("onvif_match"))
        return classify_device(item, (), camera=None)

    results = analyze_hosts(
        "192.168.1.0/24",
        [host("192.168.1.10")],
        discovery_func=discovery,
        inspect_func=inspect,
    )
    assert len(results) == 1
    assert captured == [match]


def test_analyze_hosts_pre_cancelled_skips_discovery_and_work():
    event = threading.Event()
    event.set()

    def discovery(*_args, **_kwargs):
        pytest.fail("discovery should not run")

    results = analyze_hosts(
        "192.168.1.0/24",
        [host("192.168.1.10")],
        stop_event=event,
        discovery_func=discovery,
    )
    assert results == []


def test_analyze_hosts_tolerates_inspection_failure_and_none_result():
    checked = []

    def discovery(_network, **_kwargs):
        return []

    def raising_inspect(item, **_kwargs):
        if item.ip.endswith("10"):
            raise RuntimeError("probe failed")
        return None

    results = analyze_hosts(
        "192.168.1.0/24",
        [host("192.168.1.10"), host("192.168.1.11")],
        discovery_func=discovery,
        inspect_func=raising_inspect,
        on_checked=checked.append,
    )
    assert results == []
    assert sorted(item.ip for item in checked) == ["192.168.1.10", "192.168.1.11"]


@pytest.mark.parametrize("scope", ["8.8.8.0/24", "192.168.0.0/16"])
def test_analyze_hosts_rejects_public_or_oversized_scope(scope):
    with pytest.raises(ValueError):
        analyze_hosts(scope, [])
