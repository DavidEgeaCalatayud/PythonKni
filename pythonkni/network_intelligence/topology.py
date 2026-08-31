from __future__ import annotations

import ipaddress
from dataclasses import dataclass

from pythonkni.camera_auditor.models import RiskLevel

from .models import (
    AssetRecord,
    DeviceKind,
    NetworkRelationship,
    RelationshipConfidence,
    RelationshipKind,
)
from .relationships import INTERNET_NODE_ID, lan_node_id


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
    confidence: RelationshipConfidence
    evidence: tuple[str, ...] = ()


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


def _internet_node() -> TopologyNode:
    return TopologyNode(
        node_id=INTERNET_NODE_ID,
        label="Internet / WAN",
        ip="External reference",
        kind="Reference",
        risk=None,
        is_online=True,
        synthetic=True,
    )


def _lan_node(scope: str) -> TopologyNode:
    return TopologyNode(
        node_id=lan_node_id(scope),
        label="Local network",
        ip=scope,
        kind="LAN",
        risk=None,
        is_online=True,
        synthetic=True,
    )


def _fallback_relationships(assets: list[AssetRecord]) -> tuple[NetworkRelationship, ...]:
    ordered_assets = sorted(assets, key=lambda asset: (not asset.is_online, _asset_sort_key(asset)))
    scope = ordered_assets[0].scope if ordered_assets else "unknown"
    online_routers = [
        asset for asset in ordered_assets if asset.is_online and asset.kind == DeviceKind.ROUTER
    ]
    primary_router = online_routers[0] if online_routers else None
    relationships = []
    lan_id = lan_node_id(scope)

    if primary_router is not None:
        relationships.extend(
            [
                NetworkRelationship(
                    scope=scope,
                    source_id=INTERNET_NODE_ID,
                    target_id=primary_router.asset_id,
                    kind=RelationshipKind.DEFAULT_GATEWAY,
                    confidence=RelationshipConfidence.INFERRED,
                    evidence=(
                        "Gateway role inferred from the device classification; routing-table evidence is not available.",
                    ),
                    observed_at=primary_router.last_seen,
                ),
                NetworkRelationship(
                    scope=scope,
                    source_id=primary_router.asset_id,
                    target_id=lan_id,
                    kind=RelationshipKind.LAN_MEMBERSHIP,
                    confidence=RelationshipConfidence.INFERRED,
                    evidence=("Logical LAN relationship inferred from the persistent inventory.",),
                    observed_at=primary_router.last_seen,
                ),
            ]
        )
    else:
        observed_at = max((asset.last_seen for asset in ordered_assets), default=None)
        if observed_at is not None:
            relationships.append(
                NetworkRelationship(
                    scope=scope,
                    source_id=INTERNET_NODE_ID,
                    target_id=lan_id,
                    kind=RelationshipKind.DEFAULT_GATEWAY,
                    confidence=RelationshipConfidence.UNKNOWN,
                    evidence=("No current default-gateway evidence is available.",),
                    observed_at=observed_at,
                )
            )

    for asset in ordered_assets:
        if primary_router is not None and asset.asset_id == primary_router.asset_id:
            continue
        relationships.append(
            NetworkRelationship(
                scope=scope,
                source_id=lan_id,
                target_id=asset.asset_id,
                kind=RelationshipKind.SAME_SCOPE,
                confidence=(
                    RelationshipConfidence.INFERRED
                    if asset.is_online
                    else RelationshipConfidence.UNKNOWN
                ),
                evidence=(
                    "Asset belongs to the same audited scope; the physical attachment path is unknown.",
                ),
                observed_at=asset.last_seen,
            )
        )
    return tuple(relationships)


def build_logical_topology(
    assets: list[AssetRecord],
    relationships: list[NetworkRelationship] | tuple[NetworkRelationship, ...] | None = None,
) -> NetworkTopology:
    ordered_assets = sorted(assets, key=lambda asset: (not asset.is_online, _asset_sort_key(asset)))
    scope = ordered_assets[0].scope if ordered_assets else "unknown"
    active_relationships = tuple(relationships or _fallback_relationships(ordered_assets))

    nodes_by_id = {asset.asset_id: _asset_node(asset) for asset in ordered_assets}
    nodes_by_id[INTERNET_NODE_ID] = _internet_node()

    lan_ids = {
        relation.source_id
        for relation in active_relationships
        if relation.source_id.startswith("synthetic:lan:")
    } | {
        relation.target_id
        for relation in active_relationships
        if relation.target_id.startswith("synthetic:lan:")
    }
    if not lan_ids:
        lan_ids.add(lan_node_id(scope))
    for current_lan_id in lan_ids:
        current_scope = current_lan_id.removeprefix("synthetic:lan:") or scope
        nodes_by_id[current_lan_id] = _lan_node(current_scope)

    edges = []
    for relation in active_relationships:
        if relation.source_id not in nodes_by_id or relation.target_id not in nodes_by_id:
            continue
        edges.append(
            TopologyEdge(
                source_id=relation.source_id,
                target_id=relation.target_id,
                relationship=relation.kind.value,
                confidence=relation.confidence,
                evidence=relation.evidence,
            )
        )

    gateway_relation = next(
        (
            relation
            for relation in active_relationships
            if relation.kind == RelationshipKind.DEFAULT_GATEWAY
            and relation.confidence
            in {RelationshipConfidence.CONFIRMED, RelationshipConfidence.INFERRED}
            and relation.target_id in nodes_by_id
            and not relation.target_id.startswith("synthetic:")
        ),
        None,
    )
    gateway_node_id = (
        gateway_relation.target_id if gateway_relation is not None else sorted(lan_ids)[0]
    )

    return NetworkTopology(
        nodes=tuple(nodes_by_id.values()),
        edges=tuple(edges),
        gateway_node_id=gateway_node_id,
        physical_links_known=False,
        note=(
            "Relationship-aware logical topology. Solid links are confirmed by local evidence, "
            "dashed links are inferred, and dotted links are unknown. Confirmed currently means "
            "a logical fact such as the OS default route or observed LAN membership; PythonKni "
            "still does not claim physical switch, access-point or cabling paths."
        ),
    )
