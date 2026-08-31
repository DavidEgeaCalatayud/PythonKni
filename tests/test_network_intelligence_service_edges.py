from __future__ import annotations

import threading

from pythonkni.network.models import DiscoveredHost
from pythonkni.network_intelligence import service
from pythonkni.network_intelligence.models import DeviceKind


def _host(hostname: str = "No resuelto") -> DiscoveredHost:
    return DiscoveredHost(
        ip="192.168.1.20",
        hostname=hostname,
        mac="AA:BB:CC:DD:EE:FF",
    )


def test_single_host_allowlist_rejects_documentation_network():
    assert service._is_local_ip("192.0.2.10") is False


def test_curated_probe_stops_between_ports_when_cancelled():
    event = threading.Event()
    calls = []

    def probe(_ip, port, _timeout):
        calls.append(port)
        event.set()
        return True

    ports = service.probe_intelligence_ports(
        "192.168.1.20",
        probe_func=probe,
        stop_event=event,
    )

    assert calls == [22]
    assert ports == (22,)


def test_curated_probe_skips_all_ports_when_already_cancelled():
    event = threading.Event()
    event.set()
    calls = []

    ports = service.probe_intelligence_ports(
        "192.168.1.20",
        probe_func=lambda *_args: calls.append(True) or True,
        stop_event=event,
    )

    assert ports == ()
    assert calls == []


def test_generic_cam_substring_does_not_create_camera_false_positive():
    result = service.classify_device(_host("cambridge-office"), ())
    assert result.kind == DeviceKind.UNKNOWN
