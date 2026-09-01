from __future__ import annotations

import ipaddress
import json
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

MAX_REPORT_BYTES = 20 * 1024 * 1024
MAX_ZIP_COMPRESSION_RATIO = 200.0
SUPPORTED_REPORT_SCHEMA_VERSIONS = frozenset({1, 2})


@dataclass(frozen=True, slots=True)
class SnapshotAssetDelta:
    asset_id: str
    change: str
    before_label: str
    after_label: str
    details: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SnapshotRelationshipDelta:
    change: str
    label: str
    details: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SnapshotComparison:
    scope: str
    baseline_generated_at: str
    current_generated_at: str
    baseline_schema_version: int
    current_schema_version: int
    added_assets: tuple[SnapshotAssetDelta, ...]
    removed_assets: tuple[SnapshotAssetDelta, ...]
    changed_assets: tuple[SnapshotAssetDelta, ...]
    unchanged_assets: int
    added_relationships: tuple[SnapshotRelationshipDelta, ...]
    removed_relationships: tuple[SnapshotRelationshipDelta, ...]
    changed_relationships: tuple[SnapshotRelationshipDelta, ...]
    unchanged_relationships: int
    security_score_before: int
    security_score_after: int
    findings_added: tuple[str, ...]
    findings_removed: tuple[str, ...]

    @property
    def security_score_delta(self) -> int:
        return self.security_score_after - self.security_score_before


class SnapshotReportError(ValueError):
    pass


def _parse_timestamp(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SnapshotReportError(f"{field} must be a non-empty ISO-8601 timestamp.")
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise SnapshotReportError(f"{field} is not a valid ISO-8601 timestamp.") from error
    if parsed.tzinfo is None:
        raise SnapshotReportError(f"{field} must include a timezone.")
    return value.strip()


def _canonical_scope(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SnapshotReportError("scope must be a non-empty IPv4 CIDR.")
    try:
        network = ipaddress.ip_network(value.strip(), strict=False)
    except ValueError as error:
        raise SnapshotReportError("scope is not a valid IPv4 CIDR.") from error
    if not isinstance(network, ipaddress.IPv4Network):
        raise SnapshotReportError("Snapshot comparison currently supports IPv4 scopes only.")
    return network.with_prefixlen


def _require_list(report: dict[str, Any], key: str) -> list[Any]:
    value = report.get(key)
    if not isinstance(value, list):
        raise SnapshotReportError(f"{key} must be a JSON array.")
    return value


def _validate_assets(report: dict[str, Any], scope: str) -> None:
    network = ipaddress.ip_network(scope)
    seen: set[str] = set()
    for index, asset in enumerate(_require_list(report, "assets")):
        if not isinstance(asset, dict):
            raise SnapshotReportError(f"assets[{index}] must be a JSON object.")
        asset_id = asset.get("asset_id")
        if not isinstance(asset_id, str) or not asset_id.strip():
            raise SnapshotReportError(f"assets[{index}].asset_id must be non-empty.")
        if asset_id in seen:
            raise SnapshotReportError(f"Duplicate asset_id in snapshot: {asset_id}")
        seen.add(asset_id)

        ip_value = asset.get("ip")
        try:
            address = ipaddress.ip_address(ip_value)
        except ValueError as error:
            raise SnapshotReportError(f"assets[{index}].ip is invalid.") from error
        if not isinstance(address, ipaddress.IPv4Address) or address not in network:
            raise SnapshotReportError(f"assets[{index}].ip is outside the snapshot scope.")

        ports = asset.get("open_ports", [])
        if not isinstance(ports, list) or any(
            isinstance(port, bool) or not isinstance(port, int) or not 0 < port <= 65535
            for port in ports
        ):
            raise SnapshotReportError(f"assets[{index}].open_ports contains an invalid port.")
        services = asset.get("services", [])
        if not isinstance(services, list) or any(not isinstance(item, str) for item in services):
            raise SnapshotReportError(f"assets[{index}].services must contain strings only.")


def _relationship_key(item: dict[str, Any]) -> tuple[str, str, str, str, str, str]:
    return (
        str(item.get("kind", "")),
        str(item.get("source_id", "")),
        str(item.get("target_id", "")),
        str(item.get("protocol", "")),
        str(item.get("source_port", "")),
        str(item.get("target_port", "")),
    )


def _validate_relationships(report: dict[str, Any]) -> None:
    seen: set[tuple[str, str, str, str, str, str]] = set()
    for index, relationship in enumerate(_require_list(report, "relationships")):
        if not isinstance(relationship, dict):
            raise SnapshotReportError(f"relationships[{index}] must be a JSON object.")
        for key in ("kind", "source_id", "target_id"):
            if not isinstance(relationship.get(key), str) or not relationship[key].strip():
                raise SnapshotReportError(f"relationships[{index}].{key} must be non-empty.")
        identity = _relationship_key(relationship)
        if identity in seen:
            raise SnapshotReportError("Duplicate relationship identity in snapshot.")
        seen.add(identity)


def _validate_security_score(report: dict[str, Any]) -> None:
    score = report.get("security_score")
    if not isinstance(score, dict):
        raise SnapshotReportError("security_score must be a JSON object.")
    value = score.get("score")
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
        raise SnapshotReportError("security_score.score must be an integer from 0 to 100.")
    findings = score.get("findings", [])
    if not isinstance(findings, list) or any(not isinstance(item, str) for item in findings):
        raise SnapshotReportError("security_score.findings must contain strings only.")


def validate_network_report(report: Any) -> dict[str, Any]:
    if not isinstance(report, dict):
        raise SnapshotReportError("Snapshot root must be a JSON object.")
    schema_version = report.get("schema_version")
    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or schema_version not in SUPPORTED_REPORT_SCHEMA_VERSIONS
    ):
        supported = ", ".join(str(value) for value in sorted(SUPPORTED_REPORT_SCHEMA_VERSIONS))
        raise SnapshotReportError(f"Unsupported snapshot schema_version. Supported: {supported}.")

    scope = _canonical_scope(report.get("scope"))
    _parse_timestamp(report.get("generated_at"), field="generated_at")
    _validate_assets(report, scope)
    _validate_relationships(report)
    _validate_security_score(report)

    timeline = report.get("timeline", [])
    if not isinstance(timeline, list):
        raise SnapshotReportError("timeline must be a JSON array.")
    summary = report.get("summary", {})
    if not isinstance(summary, dict):
        raise SnapshotReportError("summary must be a JSON object.")

    normalized = dict(report)
    normalized["scope"] = scope
    return normalized


def _read_json_bytes(payload: bytes, *, source: Path) -> dict[str, Any]:
    if len(payload) > MAX_REPORT_BYTES:
        raise SnapshotReportError(
            f"Snapshot exceeds the {MAX_REPORT_BYTES // (1024 * 1024)} MiB limit."
        )
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except UnicodeDecodeError as error:
        raise SnapshotReportError(f"Snapshot is not valid UTF-8: {source}") from error
    except json.JSONDecodeError as error:
        raise SnapshotReportError(f"Snapshot contains invalid JSON: {source}") from error
    return validate_network_report(decoded)


def load_network_report(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix == ".json":
        try:
            size = source.stat().st_size
        except OSError as error:
            raise SnapshotReportError(f"Could not read snapshot: {source}") from error
        if size > MAX_REPORT_BYTES:
            raise SnapshotReportError(
                f"Snapshot exceeds the {MAX_REPORT_BYTES // (1024 * 1024)} MiB limit."
            )
        try:
            payload = source.read_bytes()
        except OSError as error:
            raise SnapshotReportError(f"Could not read snapshot: {source}") from error
        return _read_json_bytes(payload, source=source)

    if suffix != ".zip":
        raise SnapshotReportError("Unsupported snapshot format. Use .json or .zip.")

    try:
        with zipfile.ZipFile(source) as archive:
            try:
                info = archive.getinfo("report.json")
            except KeyError as error:
                raise SnapshotReportError(
                    "Evidence bundle does not contain report.json."
                ) from error
            if info.is_dir():
                raise SnapshotReportError("report.json is not a regular ZIP member.")
            if info.file_size > MAX_REPORT_BYTES:
                raise SnapshotReportError(
                    f"report.json exceeds the {MAX_REPORT_BYTES // (1024 * 1024)} MiB limit."
                )
            if info.flag_bits & 0x1:
                raise SnapshotReportError("Encrypted snapshot bundles are not supported.")
            if info.compress_size > 0 and info.file_size > 1024 * 1024:
                ratio = info.file_size / info.compress_size
                if ratio > MAX_ZIP_COMPRESSION_RATIO:
                    raise SnapshotReportError("report.json has a suspicious ZIP compression ratio.")
            payload = archive.read(info)
    except SnapshotReportError:
        raise
    except (OSError, zipfile.BadZipFile, RuntimeError) as error:
        raise SnapshotReportError(f"Could not read snapshot bundle: {source}") from error
    return _read_json_bytes(payload, source=source)


def _asset_label(asset: dict[str, Any] | None) -> str:
    if not asset:
        return ""
    hostname = str(asset.get("hostname") or "").strip()
    kind = str(asset.get("kind") or "Unknown")
    ip = str(asset.get("ip") or "?")
    identity = hostname or str(asset.get("asset_id") or ip)
    return f"{identity} · {kind} · {ip}"


def _asset_details(before: dict[str, Any], after: dict[str, Any]) -> tuple[str, ...]:
    details: list[str] = []
    scalar_fields = (
        ("ip", "IP"),
        ("mac", "MAC"),
        ("hostname", "Hostname"),
        ("vendor", "Vendor"),
        ("kind", "Type"),
        ("risk", "Risk"),
        ("is_online", "Status"),
    )
    for key, label in scalar_fields:
        left = before.get(key)
        right = after.get(key)
        if left == right:
            continue
        if key == "is_online":
            left = "Online" if left else "Offline"
            right = "Online" if right else "Offline"
        details.append(f"{label}: {left} → {right}")

    before_confidence = before.get("classification_confidence")
    after_confidence = after.get("classification_confidence")
    if (
        isinstance(before_confidence, int)
        and not isinstance(before_confidence, bool)
        and isinstance(after_confidence, int)
        and not isinstance(after_confidence, bool)
        and before_confidence != after_confidence
    ):
        details.append(f"Classification confidence: {before_confidence} → {after_confidence}")

    before_ports = set(before.get("open_ports", []))
    after_ports = set(after.get("open_ports", []))
    opened = sorted(after_ports - before_ports)
    closed = sorted(before_ports - after_ports)
    if opened:
        details.append("Ports opened: " + ", ".join(str(port) for port in opened))
    if closed:
        details.append("Ports closed: " + ", ".join(str(port) for port in closed))

    before_services = {str(item) for item in before.get("services", [])}
    after_services = {str(item) for item in after.get("services", [])}
    added_services = sorted(after_services - before_services)
    removed_services = sorted(before_services - after_services)
    if added_services:
        details.append("Services added: " + ", ".join(added_services))
    if removed_services:
        details.append("Services removed: " + ", ".join(removed_services))
    return tuple(details)


def _relationship_label(item: dict[str, Any]) -> str:
    kind, source, target, protocol, source_port, target_port = _relationship_key(item)
    endpoint = f"{source}"
    if source_port:
        endpoint += f" [{source_port}]"
    endpoint += f" → {target}"
    if target_port:
        endpoint += f" [{target_port}]"
    suffix = f" · {protocol}" if protocol else ""
    return f"{kind}: {endpoint}{suffix}"


def _relationship_details(before: dict[str, Any], after: dict[str, Any]) -> tuple[str, ...]:
    details: list[str] = []
    if before.get("confidence") != after.get("confidence"):
        details.append(f"Confidence: {before.get('confidence')} → {after.get('confidence')}")
    before_evidence = {str(item) for item in before.get("evidence", [])}
    after_evidence = {str(item) for item in after.get("evidence", [])}
    if before_evidence != after_evidence:
        added = sorted(after_evidence - before_evidence)
        removed = sorted(before_evidence - after_evidence)
        if added:
            details.append("Evidence added: " + " | ".join(added))
        if removed:
            details.append("Evidence removed: " + " | ".join(removed))
    return tuple(details)


def compare_network_reports(
    baseline: dict[str, Any],
    current: dict[str, Any],
) -> SnapshotComparison:
    baseline = validate_network_report(baseline)
    current = validate_network_report(current)
    if baseline["scope"] != current["scope"]:
        raise SnapshotReportError(
            f"Snapshot scopes differ: {baseline['scope']} vs {current['scope']}."
        )

    before_assets = {item["asset_id"]: item for item in baseline["assets"]}
    after_assets = {item["asset_id"]: item for item in current["assets"]}
    added_assets = tuple(
        SnapshotAssetDelta(
            asset_id=asset_id,
            change="added",
            before_label="",
            after_label=_asset_label(after_assets[asset_id]),
        )
        for asset_id in sorted(after_assets.keys() - before_assets.keys())
    )
    removed_assets = tuple(
        SnapshotAssetDelta(
            asset_id=asset_id,
            change="removed",
            before_label=_asset_label(before_assets[asset_id]),
            after_label="",
        )
        for asset_id in sorted(before_assets.keys() - after_assets.keys())
    )
    changed_assets: list[SnapshotAssetDelta] = []
    unchanged_assets = 0
    for asset_id in sorted(before_assets.keys() & after_assets.keys()):
        before = before_assets[asset_id]
        after = after_assets[asset_id]
        details = _asset_details(before, after)
        if details:
            changed_assets.append(
                SnapshotAssetDelta(
                    asset_id=asset_id,
                    change="changed",
                    before_label=_asset_label(before),
                    after_label=_asset_label(after),
                    details=details,
                )
            )
        else:
            unchanged_assets += 1

    before_relationships = {_relationship_key(item): item for item in baseline["relationships"]}
    after_relationships = {_relationship_key(item): item for item in current["relationships"]}
    added_relationships = tuple(
        SnapshotRelationshipDelta(
            change="added",
            label=_relationship_label(after_relationships[key]),
        )
        for key in sorted(after_relationships.keys() - before_relationships.keys())
    )
    removed_relationships = tuple(
        SnapshotRelationshipDelta(
            change="removed",
            label=_relationship_label(before_relationships[key]),
        )
        for key in sorted(before_relationships.keys() - after_relationships.keys())
    )
    changed_relationships: list[SnapshotRelationshipDelta] = []
    unchanged_relationships = 0
    for key in sorted(before_relationships.keys() & after_relationships.keys()):
        details = _relationship_details(before_relationships[key], after_relationships[key])
        if details:
            changed_relationships.append(
                SnapshotRelationshipDelta(
                    change="changed",
                    label=_relationship_label(after_relationships[key]),
                    details=details,
                )
            )
        else:
            unchanged_relationships += 1

    before_score = baseline["security_score"]
    after_score = current["security_score"]
    before_findings = {str(item) for item in before_score.get("findings", [])}
    after_findings = {str(item) for item in after_score.get("findings", [])}
    return SnapshotComparison(
        scope=baseline["scope"],
        baseline_generated_at=baseline["generated_at"],
        current_generated_at=current["generated_at"],
        baseline_schema_version=baseline["schema_version"],
        current_schema_version=current["schema_version"],
        added_assets=added_assets,
        removed_assets=removed_assets,
        changed_assets=tuple(changed_assets),
        unchanged_assets=unchanged_assets,
        added_relationships=added_relationships,
        removed_relationships=removed_relationships,
        changed_relationships=tuple(changed_relationships),
        unchanged_relationships=unchanged_relationships,
        security_score_before=before_score["score"],
        security_score_after=after_score["score"],
        findings_added=tuple(sorted(after_findings - before_findings)),
        findings_removed=tuple(sorted(before_findings - after_findings)),
    )


def _signed(value: int) -> str:
    return f"{value:+d}"


def format_snapshot_comparison(comparison: SnapshotComparison) -> str:
    lines = [
        "Network Intelligence Snapshot Comparison",
        "",
        f"Scope: {comparison.scope}",
        f"Baseline: {comparison.baseline_generated_at} · schema v{comparison.baseline_schema_version}",
        f"Current:  {comparison.current_generated_at} · schema v{comparison.current_schema_version}",
        "",
        (
            f"Security score: {comparison.security_score_before} → "
            f"{comparison.security_score_after} ({_signed(comparison.security_score_delta)})"
        ),
        (
            "Assets: "
            f"+{len(comparison.added_assets)} added · "
            f"-{len(comparison.removed_assets)} removed · "
            f"{len(comparison.changed_assets)} changed · "
            f"{comparison.unchanged_assets} unchanged"
        ),
        (
            "Relationships: "
            f"+{len(comparison.added_relationships)} added · "
            f"-{len(comparison.removed_relationships)} removed · "
            f"{len(comparison.changed_relationships)} changed · "
            f"{comparison.unchanged_relationships} unchanged"
        ),
    ]

    sections = (
        ("Added assets", comparison.added_assets, "after_label"),
        ("Removed assets", comparison.removed_assets, "before_label"),
        ("Changed assets", comparison.changed_assets, "after_label"),
    )
    for title, items, label_attribute in sections:
        if not items:
            continue
        lines.extend(["", title])
        for item in items:
            lines.append(f"• {getattr(item, label_attribute)}")
            lines.extend(f"    - {detail}" for detail in item.details)

    relationship_sections = (
        ("Added relationships", comparison.added_relationships),
        ("Removed relationships", comparison.removed_relationships),
        ("Changed relationships", comparison.changed_relationships),
    )
    for title, items in relationship_sections:
        if not items:
            continue
        lines.extend(["", title])
        for item in items:
            lines.append(f"• {item.label}")
            lines.extend(f"    - {detail}" for detail in item.details)

    if comparison.findings_added:
        lines.extend(["", "New security findings"])
        lines.extend(f"• {finding}" for finding in comparison.findings_added)
    if comparison.findings_removed:
        lines.extend(["", "Resolved security findings"])
        lines.extend(f"• {finding}" for finding in comparison.findings_removed)
    if (
        not any(
            (
                comparison.added_assets,
                comparison.removed_assets,
                comparison.changed_assets,
                comparison.added_relationships,
                comparison.removed_relationships,
                comparison.changed_relationships,
                comparison.findings_added,
                comparison.findings_removed,
            )
        )
        and comparison.security_score_delta == 0
    ):
        lines.extend(["", "No meaningful state changes were detected."])
    return "\n".join(lines)
