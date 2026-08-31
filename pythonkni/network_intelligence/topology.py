from __future__ import annotations

import ipaddress
from dataclasses import dataclass

from pythonkni.camera_auditor.models import RiskLevel

from .models import AssetRecord, DeviceKind


@dataclass(frozen=True, slots=True)
class TopologyNode:
    node_id: str
    label: str
    ip: str
    kind: str
    risk: RiskLevel | None
    is_online: bool
    asset_id: str | None = None
    synthetic: bool = False


@dataclass(frozen=True, slots=True)
class TopologyEdge:
    source_id: str
    target_id: str
    relationship: str


@dataclass(frozen=True, slots=True)
class NetworkTopology:
    nodes: tuple[TopologyNode, ...]
    edges: tuple[TopologyEdge, ...]
    gateway_node_id: str
    physical_links_known: bool
    note: str


def _asset_sort_key(asset: AssetRecord):
    try:
        address = ipaddress.ip_address(asset.ip)
    except ValueError:
        return (1, asset.ip)
    return (0, int(address))


def _asset_node(asset: AssetRecord) -> TopologyNode:
    label = asset.hostname if asset.hostname and asset.hostname != "Unknown" else asset.kind.value
    return TopologyNode(
        node_id=asset.asset_id,
        label=label,
        ip=asset.ip,
        kind=asset.kind.value,
        risk=asset.risk,
        is_online=asset.is_online,
        asset_id=asset.asset_id,
    )


def build_logical_topology(assets: list[AssetRecord]) -> NetworkTopology:
    ordered_assets = sorted(assets, key=lambda asset: (not asset.is_online, _asset_sort_key(asset)))
    online_routers = [
        asset for asset in ordered_assets if asset.is_online and asset.kind == DeviceKind.ROUTER
    ]
    primary_router = online_routers[0] if online_routers else None

    internet = TopologyNode(
        node_id="synthetic:internet",
        label="Internet / WAN",
        ip="Not verified",
        kind="Reference",
        risk=None,
        is_online=True,
        synthetic=True,
    )
    nodes = [internet]
    edges: list[TopologyEdge] = []

    if primary_router is not None:
        gateway = _asset_node(primary_router)
        gateway_node_id = gateway.node_id
        nodes.append(gateway)
        edges.append(
            TopologyEdge(
                source_id=internet.node_id,
                target_id=gateway.node_id,
                relationship="logical uplink",
            )
        )
    else:
        gateway = TopologyNode(
            node_id="synthetic:lan",
            label="Local network",
            ip="Gateway not classified",
            kind="LAN",
            risk=None,
            is_online=True,
            synthetic=True,
        )
        gateway_node_id = gateway.node_id
        nodes.append(gateway)
        edges.append(
            TopologyEdge(
                source_id=internet.node_id,
                target_id=gateway.node_id,
                relationship="reference",
            )
        )

    for asset in ordered_assets:
        if primary_router is not None and asset.asset_id == primary_router.asset_id:
            continue
        node = _asset_node(asset)
        nodes.append(node)
        edges.append(
            TopologyEdge(
                source_id=gateway_node_id,
                target_id=node.node_id,
                relationship="same local scope",
            )
        )

    return NetworkTopology(
        nodes=tuple(nodes),
        edges=tuple(edges),
        gateway_node_id=gateway_node_id,
        physical_links_known=False,
        note=(
            "Logical topology inferred from the persistent asset inventory. "
            "Links mean that devices belong to the same audited local scope; physical switch, "
            "access-point and cabling paths are not inferred by the current discovery layer."
        ),
    )
