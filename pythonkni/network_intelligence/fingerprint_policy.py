from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from pythonkni.network.fingerprinting import (
    FingerprintEngineUnavailable,
    fingerprint_open_ports,
)

from .fingerprints import persist_asset_fingerprints
from .inventory import InventoryStore
from .models import AssetRecord

MAX_SCHEDULED_FINGERPRINT_HOSTS = 32
MAX_SCHEDULED_PORTS_PER_HOST = 16
SCHEDULED_NERVA_WORKERS = 8
SCHEDULED_NERVA_MAX_HOST_CONNECTIONS = 2
SCHEDULED_NERVA_TIMEOUT_MS = 1500


class FingerprintPolicy(str, Enum):
    DISABLED = "disabled"
    MANUAL = "manual"
    AUTOMATIC_AFTER_DISCOVERY = "automatic_after_discovery"
    CHANGED_SERVICES_ONLY = "changed_services_only"

    @property
    def automatic(self) -> bool:
        return self in {
            FingerprintPolicy.AUTOMATIC_AFTER_DISCOVERY,
            FingerprintPolicy.CHANGED_SERVICES_ONLY,
        }


@dataclass(frozen=True, slots=True)
class ScheduledFingerprintResult:
    policy: FingerprintPolicy
    selected_assets: int
    attempted_assets: int
    fingerprinted_assets: int
    fingerprints: int
    errors: tuple[str, ...] = ()
    cancelled: bool = False


def _selected_assets(
    assets: list[AssetRecord],
    policy: FingerprintPolicy,
    *,
    changed_since: datetime | None,
    max_hosts: int,
) -> list[AssetRecord]:
    online = [asset for asset in assets if asset.is_online and asset.open_ports]
    if policy == FingerprintPolicy.CHANGED_SERVICES_ONLY and changed_since is not None:
        online = [asset for asset in online if asset.last_change >= changed_since]
    online.sort(key=lambda asset: (asset.ip, asset.asset_id))
    return online[:max_hosts]


def run_scheduled_fingerprinting(
    store: InventoryStore,
    scope: str,
    policy: FingerprintPolicy,
    *,
    stop_event: threading.Event | None = None,
    changed_since: datetime | None = None,
    max_hosts: int = MAX_SCHEDULED_FINGERPRINT_HOSTS,
    max_ports_per_host: int = MAX_SCHEDULED_PORTS_PER_HOST,
    on_progress: Callable[[str], None] | None = None,
) -> ScheduledFingerprintResult:
    """Run bounded automatic TCP fingerprinting over already-known open ports.

    This path never enables Nerva ``--misconfigs`` and never performs UDP/SCTP probing.
    ``changed_services_only`` can only use inventory changes already known before probing;
    detecting version drift on an otherwise unchanged endpoint requires
    ``automatic_after_discovery``.
    """

    if not isinstance(policy, FingerprintPolicy):
        policy = FingerprintPolicy(str(policy))
    if not policy.automatic:
        return ScheduledFingerprintResult(policy, 0, 0, 0, 0)
    if max_hosts < 1 or max_hosts > MAX_SCHEDULED_FINGERPRINT_HOSTS:
        raise ValueError(
            f"Scheduled fingerprint hosts must be between 1 and {MAX_SCHEDULED_FINGERPRINT_HOSTS}."
        )
    if max_ports_per_host < 1 or max_ports_per_host > MAX_SCHEDULED_PORTS_PER_HOST:
        raise ValueError(
            f"Scheduled ports per host must be between 1 and {MAX_SCHEDULED_PORTS_PER_HOST}."
        )

    stop_event = stop_event or threading.Event()
    selected = _selected_assets(
        store.list_assets(scope=scope, online_only=True),
        policy,
        changed_since=changed_since,
        max_hosts=max_hosts,
    )
    attempted = 0
    fingerprinted_assets = 0
    fingerprint_count = 0
    errors: list[str] = []

    for asset in selected:
        if stop_event.is_set():
            break
        ports = tuple(sorted(set(asset.open_ports)))[:max_ports_per_host]
        if not ports:
            continue
        attempted += 1
        if on_progress is not None:
            on_progress(
                f"Fingerprint automático {attempted}/{len(selected)} · {asset.ip} · "
                f"{len(ports)} puerto(s) TCP."
            )
        try:
            fingerprints = fingerprint_open_ports(
                asset.ip,
                ports,
                stop_event=stop_event,
                timeout_ms=SCHEDULED_NERVA_TIMEOUT_MS,
                workers=SCHEDULED_NERVA_WORKERS,
                max_host_connections=SCHEDULED_NERVA_MAX_HOST_CONNECTIONS,
                transport="tcp",
                misconfigs=False,
            )
        except FingerprintEngineUnavailable as error:
            errors.append(str(error))
            break
        except Exception as error:
            errors.append(f"{asset.ip}: {error}")
            continue
        if stop_event.is_set():
            break
        if not fingerprints:
            continue
        persist_asset_fingerprints(store, asset, fingerprints)
        fingerprinted_assets += 1
        fingerprint_count += len(fingerprints)

    return ScheduledFingerprintResult(
        policy=policy,
        selected_assets=len(selected),
        attempted_assets=attempted,
        fingerprinted_assets=fingerprinted_assets,
        fingerprints=fingerprint_count,
        errors=tuple(errors),
        cancelled=stop_event.is_set(),
    )
