from __future__ import annotations

from .models import (
    ClassificationConfidenceLevel,
    ClassificationSignal,
    DeviceKind,
)


def classification_confidence_level(score: int) -> ClassificationConfidenceLevel:
    score = max(0, min(int(score), 100))
    if score >= 70:
        return ClassificationConfidenceLevel.HIGH
    if score >= 40:
        return ClassificationConfidenceLevel.MEDIUM
    return ClassificationConfidenceLevel.LOW


def _signal(
    key: str,
    label: str,
    weight: int,
    matched: bool,
    matched_evidence: str,
    missing_evidence: str,
) -> ClassificationSignal:
    return ClassificationSignal(
        key=key,
        label=label,
        weight=weight,
        matched=matched,
        evidence=matched_evidence if matched else missing_evidence,
    )


def score_device_classification(
    kind: DeviceKind,
    open_ports: tuple[int, ...] | frozenset[int],
    *,
    onvif: bool = False,
    hostname_hint: bool = False,
    vendor_hint: bool = False,
    gateway_signature: bool = False,
) -> tuple[int, tuple[ClassificationSignal, ...]]:
    """Return a deterministic confidence score for an already-selected device kind.

    The score describes confidence in the classification, not security risk. The existing
    classification precedence remains authoritative; this function only explains the signals
    supporting that result. Scores are intentionally heuristic and project-defined rather than
    an industry-standard probability.
    """

    ports = frozenset(open_ports)
    signals: list[ClassificationSignal] = []

    if kind == DeviceKind.CAMERA:
        signals.extend(
            [
                _signal(
                    "camera.onvif",
                    "ONVIF device evidence",
                    45,
                    onvif,
                    "ONVIF camera evidence was observed.",
                    "No ONVIF camera evidence was observed.",
                ),
                _signal(
                    "camera.rtsp",
                    "RTSP service :554",
                    30,
                    554 in ports,
                    "RTSP :554 is reachable on the local network.",
                    "RTSP :554 was not observed.",
                ),
                _signal(
                    "camera.vendor",
                    "Camera-specific vendor evidence",
                    25,
                    vendor_hint,
                    "The offline OUI/vendor evidence is specific to a camera manufacturer.",
                    "No camera-specific OUI/vendor evidence was observed.",
                ),
                _signal(
                    "camera.hostname",
                    "Camera hostname hint",
                    15,
                    hostname_hint,
                    "The hostname contains a camera-specific hint.",
                    "The hostname is not camera-specific.",
                ),
            ]
        )
    elif kind == DeviceKind.PRINTER:
        signals.extend(
            [
                _signal(
                    "printer.jetdirect",
                    "JetDirect :9100",
                    45,
                    9100 in ports,
                    "JetDirect :9100 is reachable.",
                    "JetDirect :9100 was not observed.",
                ),
                _signal(
                    "printer.ipp",
                    "IPP :631",
                    35,
                    631 in ports,
                    "IPP :631 is reachable.",
                    "IPP :631 was not observed.",
                ),
                _signal(
                    "printer.lpd",
                    "LPD :515",
                    30,
                    515 in ports,
                    "LPD :515 is reachable.",
                    "LPD :515 was not observed.",
                ),
                _signal(
                    "printer.hostname",
                    "Printer hostname hint",
                    25,
                    hostname_hint,
                    "The hostname contains a printer-specific hint.",
                    "The hostname is not printer-specific.",
                ),
            ]
        )
    elif kind == DeviceKind.NAS:
        signals.extend(
            [
                _signal(
                    "nas.nfs",
                    "NFS :2049",
                    40,
                    2049 in ports,
                    "NFS :2049 is reachable.",
                    "NFS :2049 was not observed.",
                ),
                _signal(
                    "nas.web",
                    "NAS web service",
                    35,
                    bool(ports & {5000, 5001}),
                    "A common NAS management web port is reachable.",
                    "Common NAS management web ports were not observed.",
                ),
                _signal(
                    "nas.vendor",
                    "NAS-specific vendor evidence",
                    40,
                    vendor_hint,
                    "The offline OUI/vendor evidence is specific to a NAS manufacturer.",
                    "No NAS-specific OUI/vendor evidence was observed.",
                ),
                _signal(
                    "nas.hostname",
                    "NAS hostname hint",
                    25,
                    hostname_hint,
                    "The hostname contains a NAS-specific hint.",
                    "The hostname is not NAS-specific.",
                ),
            ]
        )
    elif kind == DeviceKind.ROUTER:
        signals.extend(
            [
                _signal(
                    "router.gateway_signature",
                    "Gateway-style DNS + web signature",
                    65,
                    gateway_signature,
                    "The host uses a typical gateway address and exposes DNS plus web management.",
                    "The strong gateway-style DNS + web signature was not observed.",
                ),
                _signal(
                    "router.hostname",
                    "Router hostname hint",
                    35,
                    hostname_hint,
                    "The hostname contains a router/gateway-specific hint.",
                    "The hostname is not router-specific.",
                ),
            ]
        )
    elif kind == DeviceKind.PC:
        signals.extend(
            [
                _signal(
                    "pc.rdp",
                    "RDP :3389",
                    50,
                    3389 in ports,
                    "RDP :3389 is reachable.",
                    "RDP :3389 was not observed.",
                ),
                _signal(
                    "pc.ssh",
                    "SSH :22",
                    30,
                    22 in ports,
                    "SSH :22 is reachable.",
                    "SSH :22 was not observed.",
                ),
                _signal(
                    "pc.smb",
                    "SMB :445",
                    30,
                    445 in ports,
                    "SMB :445 is reachable without stronger NAS evidence.",
                    "SMB :445 was not observed.",
                ),
            ]
        )
    else:
        signals.append(
            ClassificationSignal(
                key="unknown.no_decisive_evidence",
                label="No decisive classification evidence",
                weight=0,
                matched=True,
                evidence="No supported signal was strong enough to identify a device role.",
            )
        )

    score = min(100, sum(signal.contribution for signal in signals))
    return score, tuple(signals)
