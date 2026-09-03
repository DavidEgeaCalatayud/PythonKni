from __future__ import annotations

from collections import defaultdict
from contextlib import closing
from dataclasses import replace
from datetime import datetime
from typing import Iterable

from pythonkni.network.models import DiscoveredHost, ServiceFingerprint, ServiceSecurityFinding

from .inventory import InventoryStore, _iso, utc_now
from .models import AssetRecord, NetworkIntelligenceDevice


def _fingerprint_service_label(fingerprint: ServiceFingerprint) -> str:
    identity = " ".join(
        part for part in (fingerprint.product.strip(), fingerprint.version.strip()) if part
    )
    if identity:
        return f"{fingerprint.protocol.upper()} ({identity})"
    return fingerprint.protocol.upper()


def _fingerprint_evidence(fingerprint: ServiceFingerprint) -> str:
    identity = " ".join(
        part for part in (fingerprint.product.strip(), fingerprint.version.strip()) if part
    )
    detail = f" — {identity}" if identity else ""
    return (
        f"Fingerprint de aplicación {fingerprint.port}/{fingerprint.transport}: "
        f"{fingerprint.protocol}{detail}."
    )


def _finding_evidence(
    fingerprint: ServiceFingerprint,
    finding: ServiceSecurityFinding,
) -> str:
    evidence = f" · {finding.evidence}" if finding.evidence else ""
    return (
        f"Nerva finding [{finding.severity.value}] {finding.finding_id} "
        f"on {fingerprint.port}/{fingerprint.transport}: {finding.description}{evidence}"
    )


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
    """Overlay application identities and findings without changing classification/risk.

    The legacy ``open_ports``/``services`` fields remain TCP-only. UDP/SCTP identities are
    retained as transport-qualified evidence so ``53/tcp`` and ``53/udp`` cannot collide.
    Security findings are also persisted as deterministic evidence and are scored separately.
    TCP identities are accepted only for ports already present in the device observation.
    """

    matching = tuple(
        fingerprint
        for fingerprint in fingerprints
        if (not fingerprint.ip or fingerprint.ip == device.host.ip)
        and (fingerprint.transport != "tcp" or fingerprint.port in device.open_ports)
    )
    if not matching:
        return device

    grouped_tcp: dict[int, list[ServiceFingerprint]] = defaultdict(list)
    for fingerprint in matching:
        if fingerprint.transport == "tcp":
            grouped_tcp[fingerprint.port].append(fingerprint)

    existing = dict(zip(device.open_ports, device.services))
    services: list[str] = []
    evidence = list(device.evidence)

    for port in device.open_ports:
        matches = sorted(
            grouped_tcp.get(port, ()),
            key=lambda item: (item.protocol, item.product, item.version),
        )
        if not matches:
            services.append(existing.get(port, f"TCP/{port}"))
            continue
        labels = tuple(dict.fromkeys(_fingerprint_service_label(item) for item in matches))
        services.append(" / ".join(labels))

    for fingerprint in sorted(
        matching,
        key=lambda item: (item.transport, item.port, item.protocol, item.product, item.version),
    ):
        evidence.append(_fingerprint_evidence(fingerprint))
        for finding in fingerprint.security_findings:
            evidence.append(_finding_evidence(fingerprint, finding))

    return replace(
        device,
        services=tuple(services),
        evidence=tuple(dict.fromkeys(evidence)),
    )


def enrich_asset_with_fingerprints(
    asset: AssetRecord,
    fingerprints: Iterable[ServiceFingerprint],
) -> NetworkIntelligenceDevice:
    """Apply accepted fingerprints to one persisted asset observation.

    TCP fingerprints may extend the legacy TCP port set because Network Explorer confirmed
    those ports open first. UDP/SCTP observations never enter that TCP-only tuple; they are
    represented with transport-qualified evidence and timeline events instead.
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
    tcp_ports = {item.port for item in matching if item.transport == "tcp"}
    ports = tuple(sorted(set(base.open_ports) | tcp_ports))
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
    """Persist accepted service identities/findings and track meaningful changes.

    The asset is reloaded immediately before mutation, so Nerva output cannot synthesize an
    inventory asset. TCP service identity changes become ``service_changed`` events. New
    UDP/SCTP observations become ``service_observed`` events, and newly observed Nerva security
    findings become ``security_finding`` events. Device classification and risk remain unchanged.
    """

    current = store.get_asset(asset.asset_id)
    if current is None:
        raise ValueError("The Network Intelligence asset no longer exists.")
    if current.scope != asset.scope or current.ip != asset.ip:
        raise ValueError("The Network Intelligence asset changed before fingerprints were applied.")
    asset = current

    matching = tuple(
        fingerprint
        for fingerprint in fingerprints
        if not fingerprint.ip or fingerprint.ip == asset.ip
    )
    observed_at = observed_at or utc_now()
    enriched = enrich_asset_with_fingerprints(asset, matching)
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
    previous_evidence = set(asset.evidence)
    new_evidence = set(enriched.evidence) - previous_evidence

    with closing(store._connect()) as connection:
        asset_id = store._upsert_device(connection, asset.scope, enriched, observed_at)
        custom_change = False
        for port, before, after in changed_services:
            custom_change = True
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

        for fingerprint in matching:
            fingerprint_evidence = _fingerprint_evidence(fingerprint)
            if fingerprint.transport != "tcp" and fingerprint_evidence in new_evidence:
                custom_change = True
                store._event(
                    connection,
                    asset_id=asset_id,
                    scope=asset.scope,
                    created_at=observed_at,
                    event_type="service_observed",
                    summary="Transport service observed",
                    details=(
                        f"{fingerprint.port}/{fingerprint.transport} "
                        f"{_fingerprint_service_label(fingerprint)}"
                    ),
                    ip=asset.ip,
                )
            for finding in fingerprint.security_findings:
                finding_evidence = _finding_evidence(fingerprint, finding)
                if finding_evidence not in new_evidence:
                    continue
                custom_change = True
                store._event(
                    connection,
                    asset_id=asset_id,
                    scope=asset.scope,
                    created_at=observed_at,
                    event_type="security_finding",
                    summary="Service security finding detected",
                    details=(
                        f"[{finding.severity.value}] {finding.finding_id} · "
                        f"{fingerprint.port}/{fingerprint.transport} · {finding.description}"
                    ),
                    ip=asset.ip,
                )

        if custom_change:
            connection.execute(
                "UPDATE assets SET last_change = ? WHERE asset_id = ?",
                (_iso(observed_at), asset_id),
            )
        connection.commit()

    persisted = store.get_asset(asset_id)
    if persisted is None:
        raise RuntimeError("The fingerprint-enriched asset could not be reloaded.")
    return persisted
