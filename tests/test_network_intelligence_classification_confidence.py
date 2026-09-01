from __future__ import annotations

from pythonkni.camera_auditor.models import CameraDevice, RiskLevel
from pythonkni.network.models import DiscoveredHost
from pythonkni.network_intelligence.classification import classification_confidence_level
from pythonkni.network_intelligence.models import ClassificationConfidenceLevel, DeviceKind
from pythonkni.network_intelligence.service import classify_device


def host(
    ip: str = "192.168.1.20",
    *,
    hostname: str = "device.local",
    mac: str = "AA:BB:CC:DD:EE:FF",
) -> DiscoveredHost:
    return DiscoveredHost(ip=ip, hostname=hostname, mac=mac)


def camera(ip: str) -> CameraDevice:
    return CameraDevice(
        ip=ip,
        vendor="Hikvision",
        name="Camera",
        hardware="",
        services=(),
        onvif=True,
        confidence="high",
        risk=RiskLevel.LOW,
    )


def test_confidence_levels_are_clamped_and_deterministic():
    assert classification_confidence_level(-1) == ClassificationConfidenceLevel.LOW
    assert classification_confidence_level(39) == ClassificationConfidenceLevel.LOW
    assert classification_confidence_level(40) == ClassificationConfidenceLevel.MEDIUM
    assert classification_confidence_level(69) == ClassificationConfidenceLevel.MEDIUM
    assert classification_confidence_level(70) == ClassificationConfidenceLevel.HIGH
    assert classification_confidence_level(1000) == ClassificationConfidenceLevel.HIGH


def test_high_confidence_camera_does_not_imply_high_security_risk():
    current_host = host(
        hostname="hikvision-garage",
        mac="0C:75:D2:AA:BB:CC",
    )
    device = classify_device(current_host, (554,), camera=camera(current_host.ip))

    assert device.kind == DeviceKind.CAMERA
    assert device.classification_confidence == 100
    assert classification_confidence_level(device.classification_confidence).value == "HIGH"
    assert device.risk == RiskLevel.LOW
    matched = {signal.key: signal.contribution for signal in device.classification_signals}
    assert matched == {
        "camera.onvif": 45,
        "camera.rtsp": 30,
        "camera.vendor": 25,
        "camera.hostname": 15,
    }


def test_rtsp_only_camera_remains_low_confidence_and_medium_risk():
    device = classify_device(host(), (554,))

    assert device.kind == DeviceKind.CAMERA
    assert device.classification_confidence == 30
    assert classification_confidence_level(device.classification_confidence).value == "LOW"
    assert device.risk == RiskLevel.MEDIUM
    assert [signal.matched for signal in device.classification_signals] == [False, True, False, False]


def test_nas_combines_service_and_vendor_signals():
    device = classify_device(
        host(hostname="storage.local", mac="00:11:32:AA:BB:CC"),
        (2049, 5001),
    )

    assert device.kind == DeviceKind.NAS
    assert device.vendor == "Synology"
    assert device.classification_confidence == 100
    assert classification_confidence_level(device.classification_confidence).value == "HIGH"


def test_gateway_signature_without_hostname_is_medium_confidence():
    device = classify_device(host(ip="192.168.1.1"), (53, 443))

    assert device.kind == DeviceKind.ROUTER
    assert device.classification_confidence == 65
    assert classification_confidence_level(device.classification_confidence).value == "MEDIUM"
    assert next(
        signal for signal in device.classification_signals if signal.key == "router.gateway_signature"
    ).matched


def test_unknown_device_has_zero_confidence_and_explicit_signal():
    device = classify_device(host(), ())

    assert device.kind == DeviceKind.UNKNOWN
    assert device.classification_confidence == 0
    assert len(device.classification_signals) == 1
    signal = device.classification_signals[0]
    assert signal.key == "unknown.no_decisive_evidence"
    assert signal.matched
    assert signal.contribution == 0
