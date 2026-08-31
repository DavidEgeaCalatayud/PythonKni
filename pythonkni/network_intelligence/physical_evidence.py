from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from pythonkni.camera_auditor.service import parse_camera_scope

from .models import (
    AssetRecord,
    NetworkRelationship,
    RelationshipConfidence,
    RelationshipKind,
)

_MAC_PATTERN = re.compile(r"^[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}$")
_MAX_LINKS = 4096
_MAX_EVIDENCE_ITEMS = 16
_MAX_TEXT = 512


class PhysicalEvidenceProtocol(str, Enum):
    LLDP = "LLDP"
    MAC_TABLE = "MAC_TABLE"


@dataclass(frozen=True, slots=True)
class PhysicalImportResult:
    scope: str
    relationships: tuple[NetworkRelationship, ...]
    warnings: tuple[str, ...]

    @property
    def imported_count(self) -> int:
        return len(self.relationships)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_observed_at(value) -> datetime:
    if value in (None, ""):
        return _utc_now()
    if not isinstance(value, str):
        raise ValueError("observed_at must be an ISO-8601 string.")
    candidate = value.strip()
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as error:
        raise ValueError("observed_at must be a valid ISO-8601 timestamp.") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalize_mac(value) -> str:
    if value in (None, ""):
        return ""
    if not isinstance(value, str):
        raise ValueError("MAC identifiers must be strings.")
    candidate = value.strip().upper().replace("-", ":")
    if not _MAC_PATTERN.fullmatch(candidate):
        raise ValueError(f"Invalid MAC address: {value!r}.")
    return candidate


def _normalize_ip(value) -> str:
    if value in (None, ""):
        return ""
    if not isinstance(value, str):
        raise ValueError("IP identifiers must be strings.")
    try:
        address = ipaddress.ip_address(value.strip())
    except ValueError as error:
        raise ValueError(f"Invalid IP address: {value!r}.") from error
    if not isinstance(address, ipaddress.IPv4Address):
        raise ValueError("Physical evidence snapshots currently support IPv4 assets only.")
    return str(address)


def _clean_text(value, *, field: str, allow_empty: bool = True) -> str:
    if value in (None, "") and allow_empty:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string.")
    text = value.strip()
    if not text and not allow_empty:
        raise ValueError(f"{field} cannot be empty.")
    if len(text) > _MAX_TEXT:
        raise ValueError(f"{field} exceeds {_MAX_TEXT} characters.")
    if any(ord(character) < 32 and character not in "\t" for character in text):
        raise ValueError(f"{field} contains unsupported control characters.")
    return text


def _normalize_evidence(value) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if not isinstance(value, list):
        raise ValueError("evidence must be a JSON array of strings.")
    if len(value) > _MAX_EVIDENCE_ITEMS:
        raise ValueError(f"evidence accepts at most {_MAX_EVIDENCE_ITEMS} entries per link.")
    return tuple(
        _clean_text(item, field="evidence item", allow_empty=False)
        for item in value
    )


def _asset_indexes(assets: list[AssetRecord]):
    by_id = {asset.asset_id: asset for asset in assets}
    by_ip = {asset.ip: asset for asset in assets}
    by_mac = {}
    for asset in assets:
        try:
            mac = _normalize_mac(asset.mac)
        except ValueError:
            continue
        if mac:
            by_mac[mac] = asset
    return by_id, by_ip, by_mac


def _resolve_endpoint(endpoint, *, indexes, label: str):
    if not isinstance(endpoint, dict):
        raise ValueError(f"{label} must be a JSON object.")

    asset_id = _clean_text(endpoint.get("asset_id"), field=f"{label}.asset_id")
    ip = _normalize_ip(endpoint.get("ip"))
    mac = _normalize_mac(endpoint.get("mac"))
    port = _clean_text(endpoint.get("port"), field=f"{label}.port")
    if not any((asset_id, ip, mac)):
        raise ValueError(f"{label} requires asset_id, ip or mac.")

    by_id, by_ip, by_mac = indexes
    matches = []
    if asset_id:
        matches.append(("asset_id", by_id.get(asset_id)))
    if ip:
        matches.append(("ip", by_ip.get(ip)))
    if mac:
        matches.append(("mac", by_mac.get(mac)))

    resolved = {asset.asset_id: asset for _, asset in matches if asset is not None}
    missing = [kind for kind, asset in matches if asset is None]
    if missing:
        raise ValueError(
            f"{label} could not resolve supplied identifier(s): {', '.join(missing)}."
        )
    if len(resolved) != 1:
        raise ValueError(f"{label} identifiers resolve to different inventory assets.")

    asset = next(iter(resolved.values()))
    strong_identity = bool(asset_id or mac)
    return asset, port, strong_identity


def import_physical_snapshot(
    payload: str | bytes | dict,
    assets: list[AssetRecord],
    *,
    expected_scope: str | None = None,
) -> PhysicalImportResult:
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    if isinstance(payload, str):
        try:
            document = json.loads(payload)
        except json.JSONDecodeError as error:
            raise ValueError("Physical evidence snapshot is not valid JSON.") from error
    elif isinstance(payload, dict):
        document = payload
    else:
        raise ValueError("Physical evidence snapshot must be JSON text or an object.")

    version = document.get("version", 1)
    if version != 1:
        raise ValueError(f"Unsupported physical evidence snapshot version: {version!r}.")

    raw_scope = _clean_text(document.get("scope"), field="scope", allow_empty=False)
    scope = parse_camera_scope(raw_scope).with_prefixlen
    if expected_scope is not None:
        normalized_expected = parse_camera_scope(expected_scope).with_prefixlen
        if scope != normalized_expected:
            raise ValueError(
                f"Snapshot scope {scope} does not match the active scope {normalized_expected}."
            )

    observed_at = _parse_observed_at(document.get("observed_at"))
    links = document.get("links")
    if not isinstance(links, list):
        raise ValueError("links must be a JSON array.")
    if len(links) > _MAX_LINKS:
        raise ValueError(f"Snapshot contains more than {_MAX_LINKS} physical links.")

    scoped_assets = [asset for asset in assets if asset.scope == scope]
    indexes = _asset_indexes(scoped_assets)
    relationships: list[NetworkRelationship] = []
    warnings: list[str] = []
    seen_pairs: set[tuple[str, str]] = set()

    for index, link in enumerate(links, start=1):
        try:
            if not isinstance(link, dict):
                raise ValueError("link entry must be a JSON object.")
            protocol = PhysicalEvidenceProtocol(
                _clean_text(link.get("protocol"), field="protocol", allow_empty=False).upper()
            )
            source, source_port, source_strong = _resolve_endpoint(
                link.get("source"), indexes=indexes, label="source"
            )
            target, target_port, target_strong = _resolve_endpoint(
                link.get("target"), indexes=indexes, label="target"
            )
            if source.asset_id == target.asset_id:
                raise ValueError("source and target resolve to the same asset.")
            if protocol == PhysicalEvidenceProtocol.MAC_TABLE and not source_port:
                raise ValueError("MAC_TABLE evidence requires source.port.")

            pair = (source.asset_id, target.asset_id)
            if pair in seen_pairs:
                raise ValueError("duplicate physical link for the same directed asset pair.")
            seen_pairs.add(pair)

            imported_evidence = list(_normalize_evidence(link.get("evidence")))
            imported_evidence.insert(
                0,
                f"Administrative {protocol.value} snapshot resolved both endpoints to inventory assets.",
            )
            if source_port or target_port:
                imported_evidence.append(
                    "Attachment ports from snapshot: "
                    f"{source.asset_id}:{source_port or '?'} -> "
                    f"{target.asset_id}:{target_port or '?'}"
                )

            confidence = (
                RelationshipConfidence.CONFIRMED
                if source_strong and target_strong
                else RelationshipConfidence.INFERRED
            )
            if confidence == RelationshipConfidence.INFERRED:
                imported_evidence.append(
                    "At least one endpoint was resolved only by IPv4 address; physical identity is not treated as fully confirmed."
                )

            relationships.append(
                NetworkRelationship(
                    scope=scope,
                    source_id=source.asset_id,
                    target_id=target.asset_id,
                    kind=RelationshipKind.PHYSICAL_LINK,
                    confidence=confidence,
                    evidence=tuple(imported_evidence),
                    observed_at=observed_at,
                    source_port=source_port,
                    target_port=target_port,
                    protocol=protocol.value,
                )
            )
        except (KeyError, TypeError, ValueError) as error:
            warnings.append(f"Link {index}: {error}")

    return PhysicalImportResult(
        scope=scope,
        relationships=tuple(relationships),
        warnings=tuple(warnings),
    )
