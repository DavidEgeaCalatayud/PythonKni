from __future__ import annotations

import threading

from pythonkni.network.fingerprinting import (
    FingerprintEngineUnavailable,
    FingerprintExecutionError,
    fingerprint_open_ports,
)

from .models import PortResult

NERVA_TIMEOUT_MS = 1500
NERVA_WORKERS = 8
NERVA_MAX_HOST_CONNECTIONS = 2


def enrich_ports_with_nerva(
    hostname: str,
    ports: tuple[PortResult, ...],
    *,
    stop_event: threading.Event | None = None,
) -> tuple[PortResult, ...]:
    if not ports:
        return ports
    try:
        fingerprints = fingerprint_open_ports(
            hostname,
            (item.port for item in ports),
            stop_event=stop_event,
            timeout_ms=NERVA_TIMEOUT_MS,
            workers=NERVA_WORKERS,
            max_host_connections=NERVA_MAX_HOST_CONNECTIONS,
            transport="tcp",
            misconfigs=False,
        )
    except (FingerprintEngineUnavailable, FingerprintExecutionError, OSError):
        return ports
    by_port = {item.port: item for item in fingerprints}
    enriched: list[PortResult] = []
    for port in ports:
        fingerprint = by_port.get(port.port)
        if fingerprint is None:
            enriched.append(port)
            continue
        label = fingerprint.protocol
        if fingerprint.product:
            label += f" · {fingerprint.product}"
        if fingerprint.version:
            label += f" {fingerprint.version}"
        enriched.append(
            PortResult(
                port=port.port,
                service=port.service,
                product=fingerprint.product,
                version=fingerprint.version,
                fingerprint=label,
            )
        )
    return tuple(enriched)
