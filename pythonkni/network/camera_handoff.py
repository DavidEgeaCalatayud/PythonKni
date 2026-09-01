from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass

from pythonkni.network_intelligence.models import AssetRecord, DeviceKind

from .models import DiscoveredHost

_MAC_PATTERN = re.compile(r"^[0-9A-F]{2}(?::[0-9A-F]{2}){5}$")


@dataclass(frozen=True, slots=True)
class CameraHandoffCandidate:
    asset_id: str
    ip: str
    label: str
    identity_evidence: str


def _normalize_mac(value: str) -> str:
    candidate = (value or "").strip().upper().replace("-", ":")
    return candidate if _MAC_PATTERN.fullmatch(candidate) else ""


def _candidate_label(asset: AssetRecord) -> str:
    if asset.hostname and asset.hostname != "Unknown":
        return f"{asset.hostname} ({asset.ip})"
    if asset.vendor and asset.vendor != "Unknown":
        return f"{asset.vendor} camera ({asset.ip})"
    return f"Camera ({asset.ip})"


def match_persisted_cameras(
    scope: str,
    hosts: list[DiscoveredHost] | tuple[DiscoveredHost, ...],
    assets: list[AssetRecord] | tuple[AssetRecord, ...],
) -> tuple[CameraHandoffCandidate, ...]:
    network = ipaddress.ip_network(scope.strip(), strict=False)
    if not isinstance(network, ipaddress.IPv4Network):
        raise ValueError("Camera handoff currently supports IPv4 scopes only.")
    canonical_scope = network.with_prefixlen
    hosts_by_ip = {host.ip: host for host in hosts}
    candidates = []

    for asset in assets:
        if asset.scope != canonical_scope or asset.kind != DeviceKind.CAMERA:
            continue
        host = hosts_by_ip.get(asset.ip)
        if host is None:
            continue

        if asset.asset_id.startswith("mac:"):
            current_mac = _normalize_mac(host.mac)
            if not current_mac or asset.asset_id != f"mac:{current_mac}":
                continue
            identity_evidence = "Current discovery matched the persisted camera MAC identity."
        elif asset.asset_id.startswith("ip:"):
            if asset.asset_id != f"ip:{host.ip}":
                continue
            identity_evidence = (
                "Camera inventory identity is IP-based and the current IPv4 address matches."
            )
        else:
            continue

        candidates.append(
            CameraHandoffCandidate(
                asset_id=asset.asset_id,
                ip=asset.ip,
                label=_candidate_label(asset),
                identity_evidence=identity_evidence,
            )
        )

    candidates.sort(key=lambda item: ipaddress.ip_address(item.ip))
    return tuple(candidates)
