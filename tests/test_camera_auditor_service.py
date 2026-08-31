import ipaddress
import socket
import threading

import pytest

from pythonkni.camera_auditor import service
from pythonkni.camera_auditor.models import (
    CameraDevice,
    CameraServiceFinding,
    OnvifDiscoveryMatch,
    RiskLevel,
)


class FakeSocket:
    def __init__(self, responses=()):
        self.responses = list(responses)
        self.sent = []
        self.closed = False
        self.timeout = None
        self.options = []

    def setsockopt(self, *args):
        self.options.append(args)

    def settimeout(self, value):
        self.timeout = value

    def sendto(self, payload, target):
        self.sent.append((payload, target))

    def sendall(self, payload):
        self.sent.append(payload)

    def recvfrom(self, _size):
        if not self.responses:
            raise OSError("done")
        value = self.responses.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value

    def recv(self, _size):
        if not self.responses:
            return b""
        value = self.responses.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value

    def close(self):
        self.closed = True


@pytest.mark.parametrize(
    ("cidr", "expected"),
    [
        ("192.168.1.44/24", "192.168.1.0/24"),
        ("10.10.0.1/31", "10.10.0.0/31"),
        ("127.0.0.1/32", "127.0.0.1/32"),
    ],
)
def test_parse_camera_scope_accepts_bounded_local_ranges(cidr, expected):
    assert service.parse_camera_scope(cidr).with_prefixlen == expected


def test_parse_camera_scope_rejects_invalid_ipv6_public_and_large_ranges():
    with pytest.raises(ValueError, match="formato CIDR"):
        service.parse_camera_scope("not-a-network")
    with pytest.raises(ValueError, match="IPv4"):
        service.parse_camera_scope("fd00::/120")
    with pytest.raises(ValueError, match="red local permitida"):
        service.parse_camera_scope("8.8.8.0/24")
    with pytest.raises(ValueError, match="máximo de 256"):
        service.parse_camera_scope("10.0.0.0/16")


def test_normalize_protocols_validates_selection():
    assert service.normalize_protocols((" http ", "ONVIF")) == frozenset({"HTTP", "ONVIF"})
    with pytest.raises(ValueError, match="no compatibles"):
        service.normalize_protocols(("FTP",))
    with pytest.raises(ValueError, match="al menos un protocolo"):
        service.normalize_protocols(())


def test_ws_probe_targets_network_video_transmitter_without_credentials():
    payload = service.build_ws_discovery_probe("uuid:test").decode("utf-8")
    assert "NetworkVideoTransmitter" in payload
    assert "uuid:test" in payload
    assert "Probe" in payload
    assert "username" not in payload.lower()
    assert "password" not in payload.lower()


def _probe_match_xml(ip="192.168.1.21", *, suffix=""):
    return f'''<?xml version="1.0"?>
    <s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
      xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
      xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing">
      <s:Body><d:ProbeMatches><d:ProbeMatch>
        <a:EndpointReference><a:Address>urn:uuid:camera{suffix}</a:Address></a:EndpointReference>
        <d:Types>dn:NetworkVideoTransmitter</d:Types>
        <d:Scopes>onvif://www.onvif.org/name/Front_Door
          onvif://www.onvif.org/hardware/Reolink_RLC</d:Scopes>
        <d:XAddrs>http://{ip}/onvif/device_service</d:XAddrs>
      </d:ProbeMatch></d:ProbeMatches></s:Body>
    </s:Envelope>'''.encode()


def test_parse_ws_discovery_extracts_fields_and_ignores_invalid_xml():
    assert service.parse_ws_discovery_response(b"<broken", "192.168.1.21") == []
    matches = service.parse_ws_discovery_response(_probe_match_xml(), "192.168.1.21")
    assert len(matches) == 1
    match = matches[0]
    assert match.ip == "192.168.1.21"
    assert match.endpoint_reference == "urn:uuid:camera"
    assert match.types == ("dn:NetworkVideoTransmitter",)
    assert match.xaddrs == ("http://192.168.1.21/onvif/device_service",)
    assert "Front_Door" in " ".join(match.scopes)


def test_discover_onvif_devices_filters_scope_and_merges_matches():
    first = _probe_match_xml("192.168.1.21")
    second = _probe_match_xml("192.168.1.21", suffix="-2")
    outside = _probe_match_xml("10.0.0.10")
    fake = FakeSocket(
        [
            (first, ("192.168.1.21", 3702)),
            (second, ("192.168.1.21", 3702)),
            (outside, ("10.0.0.10", 3702)),
            OSError("done"),
        ]
    )

    matches = service.discover_onvif_devices(
        ipaddress.ip_network("192.168.1.0/24"),
        socket_factory=lambda *_args: fake,
    )

    assert len(matches) == 1
    assert matches[0].ip == "192.168.1.21"
    assert matches[0].xaddrs == ("http://192.168.1.21/onvif/device_service",)
    assert fake.sent[0][1] == (service.WS_DISCOVERY_ADDRESS, service.WS_DISCOVERY_PORT)
    assert fake.closed


def test_discover_onvif_devices_handles_timeout_invalid_source_and_cancellation():
    fake = FakeSocket(
        [
            socket.timeout(),
            (_probe_match_xml(), ("not-an-ip", 3702)),
            OSError("done"),
        ]
    )
    results = service.discover_onvif_devices(
        ipaddress.ip_network("192.168.1.0/24"),
        socket_factory=lambda *_args: fake,
    )
    assert results == []

    stop_event = threading.Event()
    stop_event.set()
    cancelled_socket = FakeSocket()
    assert (
        service.discover_onvif_devices(
            ipaddress.ip_network("192.168.1.0/24"),
            stop_event=stop_event,
            socket_factory=lambda *_args: cancelled_socket,
        )
        == []
    )
    assert cancelled_socket.closed


def test_parse_headers_and_read_response_handle_headers_and_timeout():
    fake = FakeSocket([b"HTTP/1.0 401 Unauthorized\r\nServer: Camera\r\n", b"\r\n"])
    response = service._read_response(fake)
    status, headers = service._parse_headers(response)
    assert status == "HTTP/1.0 401 Unauthorized"
    assert headers["server"] == "Camera"

    timed_out = FakeSocket([socket.timeout()])
    assert service._read_response(timed_out) == b""


def test_probe_http_detects_status_auth_and_cleartext():
    fake = FakeSocket(
        [b"HTTP/1.0 401 Unauthorized\r\nWWW-Authenticate: Digest realm=cam\r\nServer: Hikvision\r\n\r\n"]
    )
    finding = service.probe_http_service(
        "192.168.1.21",
        tls=False,
        connection_factory=lambda *_args, **_kwargs: fake,
    )
    assert finding is not None
    assert finding.protocol == "HTTP"
    assert finding.port == 80
    assert finding.auth_required is True
    assert finding.cleartext is True
    assert "Hikvision" in finding.evidence
    assert fake.closed


def test_probe_http_supports_tls_and_rejects_empty_or_invalid_responses(monkeypatch):
    raw = FakeSocket()
    wrapped = FakeSocket([b"HTTP/1.1 200 OK\r\nServer: Reolink\r\n\r\n"])

    class FakeContext:
        check_hostname = True
        verify_mode = None

        def wrap_socket(self, sock, server_hostname):
            assert sock is raw
            assert server_hostname == "192.168.1.44"
            return wrapped

    monkeypatch.setattr(service.ssl, "create_default_context", FakeContext)
    finding = service.probe_http_service(
        "192.168.1.44",
        tls=True,
        connection_factory=lambda *_args, **_kwargs: raw,
    )
    assert finding is not None
    assert finding.protocol == "HTTPS"
    assert finding.cleartext is False
    assert wrapped.closed

    empty = FakeSocket([b""])
    assert (
        service.probe_http_service(
            "192.168.1.45",
            tls=False,
            connection_factory=lambda *_args, **_kwargs: empty,
        )
        is None
    )
    invalid = FakeSocket([b"NOT HTTP\r\n\r\n"])
    assert (
        service.probe_http_service(
            "192.168.1.46",
            tls=False,
            connection_factory=lambda *_args, **_kwargs: invalid,
        )
        is None
    )


def test_probe_http_handles_connection_errors():
    def fail(*_args, **_kwargs):
        raise OSError("offline")

    assert service.probe_http_service("192.168.1.50", tls=False, connection_factory=fail) is None


def test_probe_rtsp_uses_options_and_detects_authentication():
    fake = FakeSocket(
        [b"RTSP/1.0 401 Unauthorized\r\nWWW-Authenticate: Digest realm=cam\r\nServer: Reolink\r\n\r\n"]
    )
    finding = service.probe_rtsp_service(
        "192.168.1.21",
        connection_factory=lambda *_args, **_kwargs: fake,
    )
    assert finding is not None
    assert finding.protocol == "RTSP"
    assert finding.auth_required is True
    assert finding.cleartext is True
    assert b"OPTIONS" in fake.sent[0]
    assert b"DESCRIBE" not in fake.sent[0]
    assert fake.closed


def test_probe_rtsp_rejects_non_rtsp_and_connection_errors():
    invalid = FakeSocket([b"HTTP/1.0 200 OK\r\n\r\n"])
    assert (
        service.probe_rtsp_service(
            "192.168.1.21",
            connection_factory=lambda *_args, **_kwargs: invalid,
        )
        is None
    )

    def fail(*_args, **_kwargs):
        raise TimeoutError("offline")

    assert service.probe_rtsp_service("192.168.1.22", connection_factory=fail) is None


@pytest.mark.parametrize(
    ("evidence", "expected"),
    [
        ("Server: Hikvision-Webs", "Hikvision"),
        ("onvif://www.onvif.org/hardware/Reolink_RLC", "Reolink"),
        ("Dahua IPC", "Dahua"),
        ("AXIS Communications", "Axis"),
        ("generic server", "Unknown"),
    ],
)
def test_vendor_inference_uses_public_evidence(evidence, expected):
    assert service.infer_vendor(evidence) == expected


def test_scope_values_and_onvif_finding_decode_metadata_and_ports():
    match = OnvifDiscoveryMatch(
        ip="192.168.1.21",
        scopes=(
            "onvif://www.onvif.org/name/Front_Door",
            "onvif://www.onvif.org/hardware/Reolink_RLC-810A",
        ),
        xaddrs=("https://192.168.1.21:8443/onvif/device_service",),
    )
    assert service._scope_value(match.scopes, "name") == "Front Door"
    assert service._scope_value(match.scopes, "location") == ""
    finding = service._onvif_finding(match)
    assert finding.protocol == "ONVIF"
    assert finding.port == 8443
    assert finding.cleartext is False

    default_port = service._onvif_finding(
        OnvifDiscoveryMatch(ip="192.168.1.22", xaddrs=("http://192.168.1.22/onvif",))
    )
    assert default_port.port == 80
    assert default_port.cleartext is True
    assert service._onvif_finding(OnvifDiscoveryMatch(ip="192.168.1.23")).port == 3702


def test_risk_classification_reports_transport_exposure_and_low_case():
    services = (
        CameraServiceFinding("HTTP", 80, cleartext=True),
        CameraServiceFinding("RTSP", 554, status="RTSP/1.0 401 Unauthorized", auth_required=True),
    )
    match = OnvifDiscoveryMatch(
        ip="192.168.1.21",
        xaddrs=("http://192.168.1.21/onvif/device_service",),
    )
    risk, reasons = service.classify_risk(services, onvif_match=match)
    assert risk is RiskLevel.MEDIUM
    assert len(reasons) == 3

    risk, reasons = service.classify_risk(
        (CameraServiceFinding("HTTPS", 443, cleartext=False),)
    )
    assert risk is RiskLevel.LOW
    assert "No se detectaron" in reasons[0]


def test_probe_camera_host_combines_onvif_services_and_vendor(monkeypatch):
    match = OnvifDiscoveryMatch(
        ip="192.168.1.21",
        scopes=(
            "onvif://www.onvif.org/name/Front_Door",
            "onvif://www.onvif.org/hardware/Reolink_RLC",
        ),
        xaddrs=("http://192.168.1.21/onvif/device_service",),
    )
    monkeypatch.setattr(
        service,
        "probe_http_service",
        lambda ip, tls, timeout: CameraServiceFinding(
            "HTTPS" if tls else "HTTP",
            443 if tls else 80,
            cleartext=not tls,
            evidence="Reolink",
        ),
    )
    monkeypatch.setattr(
        service,
        "probe_rtsp_service",
        lambda ip, timeout: CameraServiceFinding("RTSP", 554, evidence="Reolink"),
    )
    device = service.probe_camera_host(
        "192.168.1.21",
        frozenset({"HTTP", "HTTPS", "RTSP", "ONVIF"}),
        onvif_match=match,
    )
    assert device is not None
    assert device.vendor == "Reolink"
    assert device.name == "Front Door"
    assert device.hardware == "Reolink RLC"
    assert device.confidence == "Alta"
    assert device.risk is RiskLevel.MEDIUM
    assert set(device.service_labels) == {"ONVIF", "HTTP", "HTTPS", "RTSP"}


def test_probe_camera_host_filters_generic_http_but_keeps_vendor_or_rtsp(monkeypatch):
    monkeypatch.setattr(
        service,
        "probe_http_service",
        lambda ip, tls, timeout: CameraServiceFinding("HTTP", 80, evidence="generic"),
    )
    monkeypatch.setattr(service, "probe_rtsp_service", lambda ip, timeout: None)
    assert service.probe_camera_host("192.168.1.2", frozenset({"HTTP"})) is None

    monkeypatch.setattr(
        service,
        "probe_http_service",
        lambda ip, tls, timeout: CameraServiceFinding("HTTP", 80, evidence="Hikvision"),
    )
    vendor_device = service.probe_camera_host("192.168.1.3", frozenset({"HTTP"}))
    assert vendor_device is not None
    assert vendor_device.confidence == "Media"

    monkeypatch.setattr(
        service,
        "probe_rtsp_service",
        lambda ip, timeout: CameraServiceFinding("RTSP", 554),
    )
    rtsp_device = service.probe_camera_host("192.168.1.4", frozenset({"RTSP"}))
    assert rtsp_device is not None
    assert rtsp_device.confidence == "Alta"


def test_audit_is_bounded_merges_onvif_progress_and_sorts_results():
    discovered = OnvifDiscoveryMatch(
        ip="192.168.1.1",
        scopes=("onvif://www.onvif.org/hardware/Reolink",),
        xaddrs=("http://192.168.1.1/onvif/device_service",),
    )
    seen = []

    def fake_discovery(network, stop_event):
        assert network == ipaddress.ip_network("192.168.1.0/30")
        assert isinstance(stop_event, threading.Event)
        return [discovered]

    def fake_probe(ip, protocols, onvif_match, timeout):
        seen.append(ip)
        if onvif_match is None:
            return None
        return CameraDevice(
            ip=ip,
            vendor="Reolink",
            name="",
            hardware="",
            services=(CameraServiceFinding("ONVIF", 80),),
            onvif=True,
            confidence="Alta",
            risk=RiskLevel.LOW,
        )

    progress = []
    devices = service.audit_camera_exposure(
        "192.168.1.0/30",
        ("ONVIF",),
        max_workers=2,
        discovery_func=fake_discovery,
        host_probe_func=fake_probe,
        on_progress=progress.append,
    )
    assert set(seen) == {"192.168.1.1", "192.168.1.2"}
    assert [device.ip for device in devices] == ["192.168.1.1"]
    assert progress[0].kind == "status"
    assert any(item.device is not None for item in progress)


def test_audit_without_onvif_handles_probe_error_and_cancellation():
    def failing_probe(ip, protocols, onvif_match, timeout):
        if ip.endswith(".1"):
            raise RuntimeError("probe failed")
        return None

    progress = []
    assert (
        service.audit_camera_exposure(
            "192.168.1.0/30",
            ("HTTP",),
            max_workers=1,
            host_probe_func=failing_probe,
            on_progress=progress.append,
        )
        == []
    )
    assert all(item.kind == "progress" for item in progress)

    stop_event = threading.Event()
    stop_event.set()
    assert (
        service.audit_camera_exposure(
            "192.168.1.0/30",
            ("HTTP",),
            stop_event=stop_event,
            host_probe_func=failing_probe,
        )
        == []
    )
