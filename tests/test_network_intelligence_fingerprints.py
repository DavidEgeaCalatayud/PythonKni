from __future__ import annotations

from pythonkni.camera_auditor.models import RiskLevel
from pythonkni.network.models import DiscoveredHost, ServiceFingerprint
from pythonkni.network_intelligence.fingerprints import enrich_device_with_fingerprints
from pythonkni.network_intelligence.models import DeviceKind, NetworkIntelligenceDevice


def _device() -> NetworkIntelligenceDevice:
    return NetworkIntelligenceDevice(
        host=DiscoveredHost(ip="192.168.1.20", hostname="server.local", mac="00:11:22:33:44:55"),
        kind=DeviceKind.PC,
        open_ports=(22, 443),
        services=("SSH", "HTTPS"),
        evidence=("Base evidence",),
        risk=RiskLevel.MEDIUM,
    )


def test_fingerprints_enrich_services_and_evidence_without_changing_risk_or_kind():
    device = _device()
    enriched = enrich_device_with_fingerprints(
        device,
        [
            ServiceFingerprint(
                host="server.local",
                ip="192.168.1.20",
                port=22,
                protocol="ssh",
                product="OpenSSH",
                version="9.8",
            ),
            ServiceFingerprint(
                host="server.local",
                ip="192.168.1.20",
                port=443,
                protocol="https",
                product="nginx",
                version="1.27",
            ),
        ],
    )

    assert enriched.services == ("SSH (OpenSSH 9.8)", "HTTPS (nginx 1.27)")
    assert enriched.kind is device.kind
    assert enriched.risk is device.risk
    assert "Fingerprint de aplicación 22/tcp: ssh — OpenSSH 9.8." in enriched.evidence
    assert "Fingerprint de aplicación 443/tcp: https — nginx 1.27." in enriched.evidence


def test_fingerprints_ignore_other_assets_and_closed_ports():
    device = _device()
    irrelevant = [
        ServiceFingerprint(host="x", ip="192.168.1.99", port=22, protocol="ssh"),
        ServiceFingerprint(host="x", ip="192.168.1.20", port=6379, protocol="redis"),
    ]

    assert enrich_device_with_fingerprints(device, irrelevant) is device


def test_multiple_protocols_on_same_port_are_deterministic_and_existing_fallback_is_preserved():
    device = _device()
    enriched = enrich_device_with_fingerprints(
        device,
        [
            ServiceFingerprint(host="x", ip="192.168.1.20", port=443, protocol="http"),
            ServiceFingerprint(host="x", ip="192.168.1.20", port=443, protocol="https"),
        ],
    )

    assert enriched.services == ("SSH", "HTTP / HTTPS")
