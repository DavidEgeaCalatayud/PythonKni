from __future__ import annotations

from pythonkni.camera_auditor.models import CameraDevice, RiskLevel
from pythonkni.network.models import DiscoveredHost
from pythonkni.network_intelligence.models import DeviceKind
from pythonkni.network_intelligence.service import classify_device, infer_device_vendor


def host(mac: str, hostname: str = "No resuelto") -> DiscoveredHost:
    return DiscoveredHost(ip="192.168.1.20", hostname=hostname, mac=mac)


def test_hikvision_oui_can_classify_camera_without_active_service_signal():
    device = classify_device(host("0C:75:D2:12:34:56"), ())

    assert device.kind == DeviceKind.CAMERA
    assert device.vendor == "Hangzhou Hikvision Digital Technology Co.,Ltd."
    assert device.risk == RiskLevel.LOW
    assert any("OUI MAC: Hangzhou Hikvision" in item for item in device.evidence)


def test_synology_oui_can_classify_nas_without_active_service_signal():
    device = classify_device(host("00:11:32:12:34:56"), ())

    assert device.kind == DeviceKind.NAS
    assert device.vendor == "Synology Incorporated"
    assert device.risk == RiskLevel.LOW


def test_multi_purpose_vendor_does_not_force_router_classification():
    device = classify_device(host("F0:9F:C2:12:34:56"), ())

    assert device.kind == DeviceKind.UNKNOWN
    assert device.vendor == "Ubiquiti Inc"
    assert any("OUI MAC: Ubiquiti Inc" in item for item in device.evidence)


def test_locally_administered_mac_never_drives_vendor_or_type():
    device = classify_device(host("02:11:32:12:34:56"), ())

    assert device.kind == DeviceKind.UNKNOWN
    assert device.vendor == "Unknown"
    assert all("OUI MAC" not in item for item in device.evidence)


def test_explicit_camera_vendor_has_priority_over_mac_and_hostname():
    camera = CameraDevice(
        ip="192.168.1.20",
        vendor="Reolink",
        name="Patio",
        hardware="RLC",
        services=(),
        onvif=True,
        confidence="Alta",
        risk=RiskLevel.LOW,
    )
    discovered = host("00:11:32:12:34:56", hostname="qnap-office")

    assert infer_device_vendor(discovered, camera) == "Reolink"
    assert classify_device(discovered, (), camera=camera).vendor == "Reolink"


def test_hostname_vendor_remains_fallback_when_oui_is_not_eligible():
    discovered = host("02:11:22:12:34:56", hostname="diskstation-office")

    assert infer_device_vendor(discovered) == "Synology"


def test_ambiguous_historical_oui_never_forces_a_device_role():
    device = classify_device(host("08:00:30:12:34:56"), ())

    assert device.kind == DeviceKind.UNKNOWN
    assert device.vendor == ("CERN / NETWORK RESEARCH CORPORATION / ROYAL MELBOURNE INST OF TECH")
