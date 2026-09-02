from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from typing import Iterable

from pythonkni.network.models import ServiceFingerprint

from .models import NetworkIntelligenceDevice


def _fingerprint_service_label(fingerprint: ServiceFingerprint) -> str:
    identity = " ".join(
        part for part in (fingerprint.product.strip(), fingerprint.version.strip()) if part
    )
    if identity:
        return f"{fingerprint.protocol.upper()} ({identity})"
    return fingerprint.protocol.upper()


def enrich_device_with_fingerprints(
    device: NetworkIntelligenceDevice,
    fingerprints: Iterable[ServiceFingerprint],
) -> NetworkIntelligenceDevice:
    """Overlay verified application-layer identities without changing scan/risk semantics.

    The enrichment is deliberately data-only. It does not run Nerva, does not change
    risk by itself and therefore remains safe for inventory/history consumers.
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
