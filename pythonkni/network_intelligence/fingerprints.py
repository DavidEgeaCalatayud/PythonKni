from __future__ import annotations

from collections import defaultdict
from contextlib import closing
from dataclasses import replace
from datetime import datetime
from typing import Iterable

from pythonkni.network.models import DiscoveredHost, ServiceFingerprint

from .inventory import InventoryStore, _iso, utc_now
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


def persist_asset_fingerprints(
    store: InventoryStore,
    asset: AssetRecord,
    fingerprints: Iterable[ServiceFingerprint],
    *,
    observed_at: datetime | None = None,
) -> AssetRecord:
    """Persist explicitly accepted service identities and track identity changes.

    The caller must resolve an existing ``AssetRecord`` first. The record is reloaded
    and revalidated immediately before mutation so this path cannot synthesize a new
    inventory asset from Nerva output alone. Risk and classification remain unchanged.
    Existing-port product/version changes become ``service_changed`` timeline events;
    newly observed ports continue through the inventory's normal ``port_opened`` path.
    """

    current = store.get_asset(asset.asset_id)
    if current is None:
        raise ValueError("The Network Intelligence asset no longer exists.")
    if current.scope != asset.scope or current.ip != asset.ip:
        raise ValueError("The Network Intelligence asset changed before fingerprints were applied.")
    asset = current

    observed_at = observed_at or utc_now()
    enriched = enrich_asset_with_fingerprints(asset, fingerprints)
    if (
        enriched.open_ports == asset.open_ports
        and enriched.services == asset.services
        and enriched.evidence == asset.evidence
    ):
        return asset

    before_services = dict(zip(asset.open_ports, asset.services))
    after_services = dict(zip(enriched.open_ports, enriched.services))
    changed_services = tuple(
        (port, before_services[port], after_services[port])
        for port in sorted(before_services.keys() & after_services.keys())
        if before_services[port] != after_services[port]
    )

    with closing(store._connect()) as connection:
        asset_id = store._upsert_device(connection, asset.scope, enriched, observed_at)
        for port, before, after in changed_services:
            store._event(
                connection,
                asset_id=asset_id,
                scope=asset.scope,
                created_at=observed_at,
                event_type="service_changed",
                summary="Service fingerprint changed",
                details=f"{port}/tcp {before} → {after}",
                ip=asset.ip,
            )
        if changed_services:
            connection.execute(
                "UPDATE assets SET last_change = ? WHERE asset_id = ?",
                (_iso(observed_at), asset_id),
            )
        connection.commit()

    persisted = store.get_asset(asset_id)
    if persisted is None:
        raise RuntimeError("The fingerprint-enriched asset could not be reloaded.")
    return persisted
