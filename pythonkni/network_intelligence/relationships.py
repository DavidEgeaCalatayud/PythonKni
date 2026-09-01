from __future__ import annotations

import ipaddress
import platform
import re
import subprocess
from datetime import datetime, timezone

from pythonkni.camera_auditor.service import parse_camera_scope

from .models import (
    AssetRecord,
    NetworkRelationship,
    RelationshipConfidence,
    RelationshipKind,
)

INTERNET_NODE_ID = "synthetic:internet"
LAN_NODE_PREFIX = "synthetic:lan:"
_MAC_PATTERN = re.compile(r"^[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}$")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def lan_node_id(scope: str) -> str:
    return f"{LAN_NODE_PREFIX}{scope}"


def _valid_ipv4(value: str) -> str | None:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return None
    return str(address) if isinstance(address, ipaddress.IPv4Address) else None


def parse_windows_default_gateway(output: str) -> str | None:
    candidates: list[tuple[int, str]] = []
    for line in output.splitlines():
        tokens = line.split()
        if len(tokens) < 5 or tokens[0] != "0.0.0.0" or tokens[1] != "0.0.0.0":
            continue
        gateway = _valid_ipv4(tokens[2])
        if gateway is None:
            continue
        try:
            metric = int(tokens[-1])
        except ValueError:
            metric = 2**31 - 1
        candidates.append((metric, gateway))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], ipaddress.ip_address(item[1])))
    return candidates[0][1]


def parse_posix_default_gateway(output: str) -> str | None:
    for line in output.splitlines():
        tokens = line.split()
        if not tokens or tokens[0] != "default":
            continue
        if "via" not in tokens:
            continue
        index = tokens.index("via")
        if index + 1 >= len(tokens):
            continue
        gateway = _valid_ipv4(tokens[index + 1])
        if gateway is not None:
            return gateway
    return None


def discover_default_gateway(*, command_runner=None, system_name: str | None = None) -> str | None:
    command_runner = command_runner or subprocess.run
    system_name = system_name or platform.system()
    if system_name == "Windows":
        command = ["route", "print", "-4", "0.0.0.0"]
        parser = parse_windows_default_gateway
    else:
        command = ["ip", "route", "show", "default"]
        parser = parse_posix_default_gateway
    try:
        result = command_runner(command, capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if getattr(result, "returncode", 1) != 0:
        return None
    return parser(getattr(result, "stdout", ""))


def _asset_in_scope(asset: AssetRecord, network: ipaddress.IPv4Network) -> bool:
    try:
        address = ipaddress.ip_address(asset.ip)
    except ValueError:
        return False
    return isinstance(address, ipaddress.IPv4Address) and address in network


def _has_neighbor_mac(asset: AssetRecord) -> bool:
    return bool(_MAC_PATTERN.fullmatch((asset.mac or "").strip()))


def _neighbor_evidence(asset: AssetRecord) -> tuple[str, ...]:
    evidence = [f"Asset IP {asset.ip} belongs to the audited scope {asset.scope}."]
    if _has_neighbor_mac(asset):
        evidence.append(f"Local neighbor discovery associated {asset.ip} with MAC {asset.mac}.")
    return tuple(evidence)


def build_relationships(
    scope: str,
    assets: list[AssetRecord],
    *,
    gateway_ip: str | None = None,
    observed_at: datetime | None = None,
) -> tuple[NetworkRelationship, ...]:
    network = parse_camera_scope(scope)
    observed_at = observed_at or utc_now()
    lan_id = lan_node_id(network.with_prefixlen)
    relationships: list[NetworkRelationship] = []

    scoped_assets = [asset for asset in assets if _asset_in_scope(asset, network)]
    gateway_asset = next(
        (
            asset
            for asset in scoped_assets
            if asset.is_online and gateway_ip is not None and asset.ip == gateway_ip
        ),
        None,
    )

    if gateway_asset is not None:
        relationships.append(
            NetworkRelationship(
                scope=network.with_prefixlen,
                source_id=INTERNET_NODE_ID,
                target_id=gateway_asset.asset_id,
                kind=RelationshipKind.DEFAULT_GATEWAY,
                confidence=RelationshipConfidence.CONFIRMED,
                evidence=(
                    f"The operating-system IPv4 routing table identifies {gateway_ip} as the default gateway.",
                    f"That gateway IP matches online asset {gateway_asset.asset_id}.",
                ),
                observed_at=observed_at,
            )
        )
        relationships.append(
            NetworkRelationship(
                scope=network.with_prefixlen,
                source_id=gateway_asset.asset_id,
                target_id=lan_id,
                kind=RelationshipKind.LAN_MEMBERSHIP,
                confidence=RelationshipConfidence.CONFIRMED,
                evidence=(
                    f"Default gateway {gateway_asset.ip} is inside {network.with_prefixlen}.",
                    "This confirms logical LAN membership, not the physical switch or access-point path.",
                ),
                observed_at=observed_at,
            )
        )
    else:
        if gateway_ip:
            gateway_evidence = (
                f"The operating-system default gateway is {gateway_ip}, but no online asset with that IP is present in the inventory.",
            )
        else:
            gateway_evidence = (
                "The operating-system default IPv4 gateway could not be determined from the local routing table.",
            )
        relationships.append(
            NetworkRelationship(
                scope=network.with_prefixlen,
                source_id=INTERNET_NODE_ID,
                target_id=lan_id,
                kind=RelationshipKind.DEFAULT_GATEWAY,
                confidence=RelationshipConfidence.UNKNOWN,
                evidence=gateway_evidence,
                observed_at=observed_at,
            )
        )

    for asset in scoped_assets:
        if gateway_asset is not None and asset.asset_id == gateway_asset.asset_id:
            continue
        if not asset.is_online:
            confidence = RelationshipConfidence.UNKNOWN
        elif _has_neighbor_mac(asset):
            confidence = RelationshipConfidence.CONFIRMED
        else:
            confidence = RelationshipConfidence.INFERRED

        evidence = list(_neighbor_evidence(asset))
        if confidence == RelationshipConfidence.CONFIRMED:
            evidence.append(
                "The online asset also has local neighbor/MAC evidence; no physical attachment point is claimed."
            )
        elif confidence == RelationshipConfidence.INFERRED:
            evidence.append(
                "The asset was observed online in the audited scope, but no valid neighbor MAC was available."
            )
        else:
            evidence.append(
                "The asset is historical/offline, so its current LAN attachment cannot be confirmed."
            )
        relationships.append(
            NetworkRelationship(
                scope=network.with_prefixlen,
                source_id=lan_id,
                target_id=asset.asset_id,
                kind=RelationshipKind.LAN_MEMBERSHIP,
                confidence=confidence,
                evidence=tuple(evidence),
                observed_at=observed_at,
            )
        )

    return tuple(relationships)


def discover_relationships(
    scope: str,
    assets: list[AssetRecord],
    *,
    gateway_discovery=discover_default_gateway,
    observed_at: datetime | None = None,
) -> tuple[NetworkRelationship, ...]:
    return build_relationships(
        scope,
        assets,
        gateway_ip=gateway_discovery(),
        observed_at=observed_at,
    )
