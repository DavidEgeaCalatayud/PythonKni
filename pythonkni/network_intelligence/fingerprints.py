from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from typing import Iterable

from pythonkni.network.models import DiscoveredHost, ServiceFingerprint

from .models import AssetRecord, NetworkIntelligenceDevice


def _fingerprint_service_label(fingerprint: ServiceFingerprint) -> str:
    identity = " ".join(
        part for part in (fingerprint.product.strip(), fingerprint.version.strip()) if part
    )
    if identity:
        return f"{fingerprint.protocol.upper()} ({identity})"
    return fingerprint.protocol.upper()


def device_from_asset(asset: AssetRecord) -> NetworkIntelligenceDevice:
    """Rebuild the domain device represented by one persisted inventory asset."""

    return NetworkIntelligenceDevice(
        host=DiscoveredHost(ip=asset.ip, hostname=asset.hostname, mac=asset.mac),
        kind=asset.kind,
        open_ports=asset.open_ports,
        services=asset.services,
        evidence=asset.evidence,
        risk=asset.risk,
        vendor=asset.vendor,
        classification_confidence=asset.classification_confidence,
        classification_signals=asset.classification_signals,
    )


def enrich_device_with_fingerprints(
    device: NetworkIntelligenceDevice,
    fingerprints: Iterable[ServiceFingerprint],
) -> NetworkIntelligenceDevice:
    """Overlay verified application-layer identities without changing risk semantics.

    The enrichment is deliberately data-only. It does not run Nerva and does not
    change classification or risk by itself.
    """

    grouped: dict[int, list[ServiceFingerprint]] = defaultdict(list)
    for fingerprint in fingerprints:
        if fingerprint.ip and fingerprint.ip != device.host.ip:
            continue
        if fingerprint.port not in device.open_ports:
            continue
        grouped[fingerprint.port].append(fingerprint)

    if not grouped:
        return device

    existing = dict(zip(device.open_ports, device.services))
    services: list[str] = []
    evidence = list(device.evidence)

    for port in device.open_ports:
        matches = sorted(
            grouped.get(port, ()),
            key=lambda item: (item.protocol, item.product, item.version),
        )
        if not matches:
            services.append(existing.get(port, f"TCP/{port}"))
            continue

        labels = tuple(dict.fromkeys(_fingerprint_service_label(item) for item in matches))
        services.append(" / ".join(labels))
        for match in matches:
            identity = " ".join(
                part for part in (match.product.strip(), match.version.strip()) if part
            )
            detail = f" — {identity}" if identity else ""
            evidence.append(
                f"Fingerprint de aplicación {port}/{match.transport}: {match.protocol}{detail}."
            )

    return replace(
        device,
        services=tuple(services),
        evidence=tuple(dict.fromkeys(evidence)),
    )


def enrich_asset_with_fingerprints(
    asset: AssetRecord,
    fingerprints: Iterable[ServiceFingerprint],
) -> NetworkIntelligenceDevice:
    """Apply explicitly confirmed fingerprints to a persisted asset observation.

    Fingerprints from Network Explorer originate from ports that were first confirmed
    open. Those identified ports may extend the smaller Network Intelligence probe
    set, so they are merged into the observation before applying service labels.
    """

    matching = tuple(
        fingerprint
        for fingerprint in fingerprints
        if not fingerprint.ip or fingerprint.ip == asset.ip
    )
    if not matching:
        return device_from_asset(asset)

    base = device_from_asset(asset)
    existing = dict(zip(base.open_ports, base.services))
    ports = tuple(sorted(set(base.open_ports) | {item.port for item in matching}))
    expanded = replace(
        base,
        open_ports=ports,
        services=tuple(existing.get(port, f"TCP/{port}") for port in ports),
    )
    return enrich_device_with_fingerprints(expanded, matching)
