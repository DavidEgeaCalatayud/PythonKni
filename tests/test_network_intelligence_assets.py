from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pythonkni.camera_auditor.models import RiskLevel
from pythonkni.network.models import DiscoveredHost
from pythonkni.network_intelligence.auditors import build_device_audit
from pythonkni.network_intelligence.models import AssetRecord, DeviceKind
from pythonkni.network_intelligence.score import calculate_security_score
from pythonkni.network_intelligence.service import classify_device, infer_device_vendor


def asset(
    *,
    asset_id="mac:AA:BB:CC:DD:EE:FF",
    ip="192.168.1.34",
    kind=DeviceKind.NAS,
    services=("SMB", "NAS-Web-TLS"),
    ports=(445, 5001),
    risk=RiskLevel.LOW,
    first_seen=None,
    online=True,
):
    now = datetime(2026, 8, 31, 17, 0, tzinfo=timezone.utc)
    first_seen = first_seen or now - timedelta(days=2)
    return AssetRecord(
        asset_id=asset_id,
        scope="192.168.1.0/24",
        ip=ip,
        mac="AA:BB:CC:DD:EE:FF",
        hostname="device.local",
        vendor="Unknown",
        kind=kind,
        services=services,
        open_ports=ports,
        evidence=("classified",),
        risk=risk,
        first_seen=first_seen,
        last_seen=now,
        last_change=now,
        is_online=online,
    )


def test_security_score_reports_risk_unknown_rtsp_and_http():
    now = datetime(2026, 8, 31, 18, 0, tzinfo=timezone.utc)
    assets = [
        asset(
            asset_id="camera",
            kind=DeviceKind.CAMERA,
            services=("HTTP", "RTSP"),
            ports=(80, 554),
            risk=RiskLevel.MEDIUM,
        ),
        asset(
            asset_id="unknown",
            ip="192.168.1.81",
            kind=DeviceKind.UNKNOWN,
            services=(),
            ports=(),
            first_seen=now,
        ),
        asset(asset_id="offline", online=False, risk=RiskLevel.HIGH),
    ]

    score = calculate_security_score(assets, now=now)

    assert score.total_devices == 2
    assert score.unknown_devices == 1
    assert score.medium_risk == 1
    assert score.high_risk == 0
    assert score.score < 100
    assert any("RTSP" in finding for finding in score.findings)
    assert any("HTTP" in finding for finding in score.findings)
    assert any("appeared today" in finding for finding in score.findings)


def test_security_score_is_100_when_no_current_findings():
    score = calculate_security_score([asset(services=(), ports=())])
    assert score.score == 100
    assert score.findings == ("No critical findings in the current online inventory.",)


def test_profile_specific_auditors_use_existing_snapshot_only():
    nas = asset(services=("SMB", "NFS"), ports=(445, 2049), risk=RiskLevel.MEDIUM)
    report = build_device_audit(nas)
    assert report.title == "NAS Security Auditor"
    assert any("NFS" in finding.title for finding in report.findings)
    assert any("SMB" in finding.title for finding in report.findings)

    printer = asset(kind=DeviceKind.PRINTER, services=("JetDirect",), ports=(9100,))
    report = build_device_audit(printer)
    assert report.title == "Printer Security Auditor"
    assert any("Raw printing" in finding.title for finding in report.findings)

    pc = asset(kind=DeviceKind.PC, services=("SSH", "RDP"), ports=(22, 3389))
    report = build_device_audit(pc)
    assert report.title == "PC Security Auditor"
    assert report.risk == RiskLevel.MEDIUM


def test_camera_audit_recommends_dedicated_auditor():
    camera = asset(kind=DeviceKind.CAMERA, services=("RTSP",), ports=(554,))
    report = build_device_audit(camera)
    assert any("Dedicated camera audit" in finding.title for finding in report.findings)


def test_vendor_inference_uses_camera_or_hostname_signals():
    host = DiscoveredHost(ip="192.168.1.34", hostname="DiskStation", mac="AA:BB:CC:DD:EE:FF")
    assert infer_device_vendor(host) == "Synology"

    device = classify_device(host, (445, 5001))
    assert device.vendor == "Synology"
