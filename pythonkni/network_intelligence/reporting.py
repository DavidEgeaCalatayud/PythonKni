from __future__ import annotations

import csv
import io
import ipaddress
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.csv_utils import safe_csv_row

from .models import AssetRecord, NetworkRelationship, NetworkSecurityScore, TimelineEvent
from .score import calculate_security_score

REPORT_SCHEMA_VERSION = 1


def _utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _asset_to_dict(asset: AssetRecord) -> dict[str, Any]:
    return {
        "asset_id": asset.asset_id,
        "scope": asset.scope,
        "ip": asset.ip,
        "mac": asset.mac,
        "hostname": asset.hostname,
        "vendor": asset.vendor,
        "kind": asset.kind.value,
        "services": list(asset.services),
        "open_ports": list(asset.open_ports),
        "evidence": list(asset.evidence),
        "risk": asset.risk.value,
        "first_seen": _utc_iso(asset.first_seen),
        "last_seen": _utc_iso(asset.last_seen),
        "last_change": _utc_iso(asset.last_change),
        "is_online": asset.is_online,
    }


def _relationship_to_dict(relationship: NetworkRelationship) -> dict[str, Any]:
    return {
        "scope": relationship.scope,
        "source_id": relationship.source_id,
        "target_id": relationship.target_id,
        "kind": relationship.kind.value,
        "confidence": relationship.confidence.value,
        "evidence": list(relationship.evidence),
        "observed_at": _utc_iso(relationship.observed_at),
        "source_port": relationship.source_port,
        "target_port": relationship.target_port,
        "protocol": relationship.protocol,
    }


def _event_to_dict(event: TimelineEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "asset_id": event.asset_id,
        "scope": event.scope,
        "created_at": _utc_iso(event.created_at),
        "event_type": event.event_type,
        "summary": event.summary,
        "details": event.details,
        "ip": event.ip,
    }


def _score_to_dict(score: NetworkSecurityScore) -> dict[str, Any]:
    return {
        "score": score.score,
        "total_devices": score.total_devices,
        "unknown_devices": score.unknown_devices,
        "high_risk": score.high_risk,
        "medium_risk": score.medium_risk,
        "low_risk": score.low_risk,
        "findings": list(score.findings),
    }


def build_network_report(
    scope: str,
    assets: list[AssetRecord] | tuple[AssetRecord, ...],
    relationships: list[NetworkRelationship] | tuple[NetworkRelationship, ...],
    events: list[TimelineEvent] | tuple[TimelineEvent, ...],
    *,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    network = ipaddress.ip_network(scope.strip(), strict=False)
    if not isinstance(network, ipaddress.IPv4Network):
        raise ValueError("Network Intelligence reports currently support IPv4 scopes only.")

    generated_at = generated_at or datetime.now(timezone.utc)
    if generated_at.tzinfo is None:
        raise ValueError("generated_at must be timezone-aware.")

    ordered_assets = sorted(
        assets,
        key=lambda asset: (ipaddress.ip_address(asset.ip), asset.asset_id),
    )
    ordered_relationships = sorted(
        relationships,
        key=lambda relationship: (
            relationship.kind.value,
            relationship.source_id,
            relationship.target_id,
            relationship.protocol,
            relationship.source_port,
            relationship.target_port,
        ),
    )
    ordered_events = sorted(events, key=lambda event: (event.created_at, event.event_id), reverse=True)
    score = calculate_security_score(list(ordered_assets), now=generated_at)

    online = sum(asset.is_online for asset in ordered_assets)
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": _utc_iso(generated_at),
        "scope": network.with_prefixlen,
        "summary": {
            "assets": len(ordered_assets),
            "online_assets": online,
            "offline_assets": len(ordered_assets) - online,
            "relationships": len(ordered_relationships),
            "timeline_events": len(ordered_events),
        },
        "security_score": _score_to_dict(score),
        "assets": [_asset_to_dict(asset) for asset in ordered_assets],
        "relationships": [
            _relationship_to_dict(relationship) for relationship in ordered_relationships
        ],
        "timeline": [_event_to_dict(event) for event in ordered_events],
    }


def _csv_text(headers: list[str], rows: list[list[Any]]) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(headers)
    for row in rows:
        writer.writerow(safe_csv_row(row))
    return output.getvalue()


def _assets_csv(report: dict[str, Any]) -> str:
    rows = []
    for asset in report["assets"]:
        rows.append(
            [
                asset["asset_id"],
                asset["ip"],
                asset["mac"],
                asset["hostname"],
                asset["vendor"],
                asset["kind"],
                " | ".join(asset["services"]),
                " | ".join(str(port) for port in asset["open_ports"]),
                asset["risk"],
                "online" if asset["is_online"] else "offline",
                asset["first_seen"],
                asset["last_seen"],
                asset["last_change"],
                " | ".join(asset["evidence"]),
            ]
        )
    return _csv_text(
        [
            "asset_id",
            "ip",
            "mac",
            "hostname",
            "vendor",
            "kind",
            "services",
            "open_ports",
            "risk",
            "status",
            "first_seen",
            "last_seen",
            "last_change",
            "evidence",
        ],
        rows,
    )


def _relationships_csv(report: dict[str, Any]) -> str:
    rows = []
    for relationship in report["relationships"]:
        rows.append(
            [
                relationship["confidence"],
                relationship["kind"],
                relationship["protocol"],
                relationship["source_id"],
                relationship["source_port"],
                relationship["target_id"],
                relationship["target_port"],
                relationship["observed_at"],
                " | ".join(relationship["evidence"]),
            ]
        )
    return _csv_text(
        [
            "confidence",
            "kind",
            "protocol",
            "source_id",
            "source_port",
            "target_id",
            "target_port",
            "observed_at",
            "evidence",
        ],
        rows,
    )


def _timeline_csv(report: dict[str, Any]) -> str:
    rows = [
        [
            event["event_id"],
            event["created_at"],
            event["event_type"],
            event["asset_id"],
            event["ip"],
            event["summary"],
            event["details"],
        ]
        for event in report["timeline"]
    ]
    return _csv_text(
        ["event_id", "created_at", "event_type", "asset_id", "ip", "summary", "details"],
        rows,
    )


def export_network_report(path: str | Path, report: dict[str, Any]) -> Path:
    destination = Path(path)
    suffix = destination.suffix.lower()
    if suffix == ".json":
        destination.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return destination
    if suffix != ".zip":
        raise ValueError("Unsupported report format. Use .json or .zip.")

    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "report.json",
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        )
        archive.writestr("assets.csv", _assets_csv(report))
        archive.writestr("relationships.csv", _relationships_csv(report))
        archive.writestr("timeline.csv", _timeline_csv(report))
    return destination
