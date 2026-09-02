from __future__ import annotations

from pythonkni.camera_auditor.models import RiskLevel

from .models import AssetRecord, AuditFinding, DeviceAuditReport, DeviceKind

_SEVERITY_ORDER = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2}


def _finding(
    severity: RiskLevel,
    title: str,
    evidence: str,
    recommendation: str,
) -> AuditFinding:
    return AuditFinding(
        severity=severity,
        title=title,
        evidence=evidence,
        recommendation=recommendation,
    )


def _common_findings(asset: AssetRecord) -> list[AuditFinding]:
    findings = []
    if "HTTP" in asset.services:
        findings.append(
            _finding(
                RiskLevel.MEDIUM,
                "Clear-text web service",
                "HTTP is reachable from the local network.",
                "Prefer HTTPS for administration and disable HTTP when the device supports it.",
            )
        )
    if asset.kind == DeviceKind.UNKNOWN:
        findings.append(
            _finding(
                RiskLevel.MEDIUM,
                "Unclassified asset",
                "The current evidence is insufficient to identify the device type.",
                "Confirm the owner and purpose of this asset before trusting it on the network.",
            )
        )
    return findings


def _router_findings(asset: AssetRecord) -> list[AuditFinding]:
    findings = _common_findings(asset)
    if 53 in asset.open_ports:
        findings.append(
            _finding(
                RiskLevel.LOW,
                "Local DNS service",
                "DNS is reachable on the gateway candidate.",
                "Keep resolver administration limited to trusted local interfaces.",
            )
        )
    if 22 in asset.open_ports:
        findings.append(
            _finding(
                RiskLevel.MEDIUM,
                "SSH administration exposed",
                "SSH is reachable from the local network.",
                "Restrict management access to trusted hosts and disable SSH when unused.",
            )
        )
    return findings


def _nas_findings(asset: AssetRecord) -> list[AuditFinding]:
    findings = _common_findings(asset)
    if 2049 in asset.open_ports:
        findings.append(
            _finding(
                RiskLevel.MEDIUM,
                "NFS service exposed",
                "NFS is reachable from the local network.",
                "Restrict NFS exports to required clients and review export permissions.",
            )
        )
    if 445 in asset.open_ports:
        findings.append(
            _finding(
                RiskLevel.LOW,
                "SMB file service",
                "SMB is reachable from the local network.",
                "Keep SMB patched and restrict shares to intended users and devices.",
            )
        )
    if 5000 in asset.open_ports and 5001 not in asset.open_ports:
        findings.append(
            _finding(
                RiskLevel.MEDIUM,
                "NAS management without TLS signal",
                "The clear-text NAS management port is reachable without its TLS counterpart.",
                "Prefer the HTTPS management endpoint and disable clear-text management.",
            )
        )
    return findings


def _printer_findings(asset: AssetRecord) -> list[AuditFinding]:
    findings = _common_findings(asset)
    if 9100 in asset.open_ports:
        findings.append(
            _finding(
                RiskLevel.MEDIUM,
                "Raw printing service exposed",
                "JetDirect/raw printing is reachable on TCP/9100.",
                "Disable raw printing if unused or restrict access to trusted print clients.",
            )
        )
    if 515 in asset.open_ports:
        findings.append(
            _finding(
                RiskLevel.MEDIUM,
                "Legacy LPD service exposed",
                "LPD is reachable on TCP/515.",
                "Prefer authenticated modern print protocols where supported.",
            )
        )
    return findings


def _pc_findings(asset: AssetRecord) -> list[AuditFinding]:
    findings = _common_findings(asset)
    remote_services = []
    if 22 in asset.open_ports:
        remote_services.append("SSH")
    if 3389 in asset.open_ports:
        remote_services.append("RDP")
    if 445 in asset.open_ports:
        remote_services.append("SMB")
    if remote_services:
        severity = RiskLevel.MEDIUM if len(remote_services) >= 2 else RiskLevel.LOW
        findings.append(
            _finding(
                severity,
                "Remote-access surface",
                f"Reachable services: {', '.join(remote_services)}.",
                "Disable unused services and keep host firewall rules limited to trusted networks.",
            )
        )
    return findings


def _camera_findings(asset: AssetRecord) -> list[AuditFinding]:
    findings = _common_findings(asset)
    if 554 in asset.open_ports or "RTSP" in asset.services:
        findings.append(
            _finding(
                RiskLevel.MEDIUM,
                "RTSP exposure",
                "RTSP is reachable from the local network.",
                "Require authentication, isolate cameras and restrict RTSP to trusted consumers.",
            )
        )
    findings.append(
        _finding(
            RiskLevel.LOW,
            "Dedicated camera audit available",
            "Camera Exposure Auditor can inspect ONVIF/HTTP/HTTPS/RTSP exposure for this single host.",
            "Open the dedicated auditor for protocol-specific evidence without credential attempts.",
        )
    )
    return findings


def build_device_audit(asset: AssetRecord) -> DeviceAuditReport:
    builders = {
        DeviceKind.ROUTER: _router_findings,
        DeviceKind.NAS: _nas_findings,
        DeviceKind.PRINTER: _printer_findings,
        DeviceKind.PC: _pc_findings,
        DeviceKind.CAMERA: _camera_findings,
        DeviceKind.UNKNOWN: _common_findings,
    }
    findings = builders[asset.kind](asset)
    if not findings:
        findings.append(
            _finding(
                RiskLevel.LOW,
                "No notable exposure",
                "No profile-specific exposure finding was identified from the stored snapshot.",
                "Continue monitoring for configuration or service changes.",
            )
        )
    risk = max((item.severity for item in findings), key=_SEVERITY_ORDER.get)
    return DeviceAuditReport(
        asset_id=asset.asset_id,
        title=f"{asset.kind.value} Security Auditor",
        risk=risk,
        findings=tuple(findings),
    )
