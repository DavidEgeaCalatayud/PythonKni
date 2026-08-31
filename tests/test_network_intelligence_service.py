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
from pythonkni.network_intelligence.models import DeviceKind
from pythonkni.network_intelligence.service import (
    analyze_hosts,
    classify_device,
    inspect_host,
    probe_intelligence_ports,
)


def host(ip="192.168.1.20", hostname="No resuelto"):
    return DiscoveredHost(ip=ip, hostname=hostname, mac="AA:BB:CC:DD:EE:FF")


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


def test_gateway_style_router_requires_dns_and_web():
    device = classify_device(host(ip="192.168.1.1"), (53, 443))
    assert device.kind == DeviceKind.ROUTER
    assert device.risk == RiskLevel.LOW


def test_cleartext_printer_and_nas_signals_raise_medium_risk():
    printer = classify_device(host(), (9100,))
    nas = classify_device(host(), (2049,))
    assert printer.risk == RiskLevel.MEDIUM
    assert nas.risk == RiskLevel.MEDIUM


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
        "pythonkni.network_intelligence.service.probe_intelligence_ports",
        lambda *_args, **_kwargs: (),
    )
    monkeypatch.setattr(
        "pythonkni.network_intelligence.service.probe_camera_host",
        lambda *_args, **_kwargs: camera,
    )
    result = inspect_host(host(), onvif_match=match)
    assert result is not None
    assert result.kind == DeviceKind.CAMERA
    assert result.camera is camera


def test_inspect_host_stops_before_network_activity_when_cancelled(monkeypatch):
    event = threading.Event()
    event.set()
    monkeypatch.setattr(
        "pythonkni.network_intelligence.service.probe_intelligence_ports",
        lambda *_args, **_kwargs: pytest.fail("probe should not run"),
    )
    assert inspect_host(host(), stop_event=event) is None


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


def test_analyze_hosts_rejects_public_scope():
    with pytest.raises(ValueError):
        analyze_hosts("8.8.8.0/24", [])
