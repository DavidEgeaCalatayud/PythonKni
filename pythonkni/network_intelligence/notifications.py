from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from .comparison import compare_network_reports, load_network_report, validate_network_report

NOTIFICATION_SCHEMA_VERSION = 1
MAX_NOTIFICATION_INBOX_ITEMS = 500
MAX_NOTIFICATION_FILE_BYTES = 2 * 1024 * 1024


class NotificationSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True, slots=True)
class ChangeNotification:
    event_id: str
    scope: str
    detected_at: datetime
    baseline_generated_at: str
    current_generated_at: str
    category: str
    severity: NotificationSeverity
    title: str
    message: str
    subject_id: str = ""
    details: tuple[str, ...] = ()
    read: bool = False


@dataclass(frozen=True, slots=True)
class NotificationBatch:
    scope: str
    baseline_generated_at: str
    current_generated_at: str
    security_score_delta: int
    notifications: tuple[ChangeNotification, ...]

    @property
    def critical_count(self) -> int:
        return sum(item.severity == NotificationSeverity.CRITICAL for item in self.notifications)

    @property
    def warning_count(self) -> int:
        return sum(item.severity == NotificationSeverity.WARNING for item in self.notifications)

    @property
    def info_count(self) -> int:
        return sum(item.severity == NotificationSeverity.INFO for item in self.notifications)


_RISK_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
_SEVERITY_RANK = {
    NotificationSeverity.INFO: 0,
    NotificationSeverity.WARNING: 1,
    NotificationSeverity.CRITICAL: 2,
}


def _parse_timestamp(value: str, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} must be a valid ISO-8601 timestamp.") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone.")
    return parsed.astimezone(timezone.utc)


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("notification timestamps must be timezone-aware.")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _event_id(
    *,
    scope: str,
    baseline_generated_at: str,
    current_generated_at: str,
    category: str,
    subject_id: str,
    before: Any,
    after: Any,
) -> str:
    payload = json.dumps(
        {
            "scope": scope,
            "baseline": baseline_generated_at,
            "current": current_generated_at,
            "category": category,
            "subject": subject_id,
            "before": before,
            "after": after,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _asset_identity(asset: dict[str, Any]) -> str:
    hostname = str(asset.get("hostname") or "").strip()
    asset_id = str(asset.get("asset_id") or "").strip()
    ip = str(asset.get("ip") or "?")
    return hostname or asset_id or ip


def _new_notification(
    *,
    scope: str,
    detected_at: datetime,
    baseline_generated_at: str,
    current_generated_at: str,
    category: str,
    severity: NotificationSeverity,
    title: str,
    message: str,
    subject_id: str = "",
    details: Iterable[str] = (),
    before: Any = None,
    after: Any = None,
) -> ChangeNotification:
    return ChangeNotification(
        event_id=_event_id(
            scope=scope,
            baseline_generated_at=baseline_generated_at,
            current_generated_at=current_generated_at,
            category=category,
            subject_id=subject_id,
            before=before,
            after=after,
        ),
        scope=scope,
        detected_at=detected_at,
        baseline_generated_at=baseline_generated_at,
        current_generated_at=current_generated_at,
        category=category,
        severity=severity,
        title=title,
        message=message,
        subject_id=subject_id,
        details=tuple(str(item) for item in details),
    )


def build_change_notifications(
    baseline: dict[str, Any],
    current: dict[str, Any],
) -> NotificationBatch:
    """Build meaningful, non-transient notifications from two validated snapshots.

    Deliberately ignored fields include first_seen, last_seen, last_change, online/offline status,
    classification confidence and other discovery churn. Notifications focus on security-relevant
    state transitions rather than scan timestamp noise.
    """

    baseline = validate_network_report(baseline)
    current = validate_network_report(current)
    comparison = compare_network_reports(baseline, current)
    detected_at = _parse_timestamp(current["generated_at"], field="generated_at")
    scope = comparison.scope
    notifications: list[ChangeNotification] = []

    before_assets = {item["asset_id"]: item for item in baseline["assets"]}
    after_assets = {item["asset_id"]: item for item in current["assets"]}

    for asset_id in sorted(after_assets.keys() - before_assets.keys()):
        asset = after_assets[asset_id]
        risk = str(asset.get("risk") or "LOW").upper()
        severity = NotificationSeverity.CRITICAL if risk == "HIGH" else NotificationSeverity.WARNING
        identity = _asset_identity(asset)
        notifications.append(
            _new_notification(
                scope=scope,
                detected_at=detected_at,
                baseline_generated_at=comparison.baseline_generated_at,
                current_generated_at=comparison.current_generated_at,
                category="new_device",
                severity=severity,
                title="Nuevo dispositivo detectado",
                message=(
                    f"{identity} apareció por primera vez en el snapshot actual "
                    f"({asset.get('ip', '?')}, riesgo {risk})."
                ),
                subject_id=asset_id,
                details=(
                    f"Tipo: {asset.get('kind', 'Unknown')}",
                    f"Vendor: {asset.get('vendor', 'Unknown')}",
                ),
                before=None,
                after={"ip": asset.get("ip"), "risk": risk, "kind": asset.get("kind")},
            )
        )

    for asset_id in sorted(before_assets.keys() & after_assets.keys()):
        before = before_assets[asset_id]
        after = after_assets[asset_id]
        identity = _asset_identity(after)

        before_risk = str(before.get("risk") or "LOW").upper()
        after_risk = str(after.get("risk") or "LOW").upper()
        if before_risk != after_risk:
            before_rank = _RISK_RANK.get(before_risk, 0)
            after_rank = _RISK_RANK.get(after_risk, 0)
            if after_rank > before_rank:
                severity = (
                    NotificationSeverity.CRITICAL
                    if after_risk == "HIGH"
                    else NotificationSeverity.WARNING
                )
                title = "Riesgo del dispositivo aumentado"
            else:
                severity = NotificationSeverity.INFO
                title = "Riesgo del dispositivo reducido"
            notifications.append(
                _new_notification(
                    scope=scope,
                    detected_at=detected_at,
                    baseline_generated_at=comparison.baseline_generated_at,
                    current_generated_at=comparison.current_generated_at,
                    category="risk_changed",
                    severity=severity,
                    title=title,
                    message=f"{identity}: {before_risk} → {after_risk}.",
                    subject_id=asset_id,
                    before=before_risk,
                    after=after_risk,
                )
            )

        before_ports = {int(port) for port in before.get("open_ports", [])}
        after_ports = {int(port) for port in after.get("open_ports", [])}
        opened_ports = tuple(sorted(after_ports - before_ports))
        if opened_ports:
            after_risk = str(after.get("risk") or "LOW").upper()
            severity = (
                NotificationSeverity.CRITICAL
                if after_risk == "HIGH"
                else NotificationSeverity.WARNING
            )
            notifications.append(
                _new_notification(
                    scope=scope,
                    detected_at=detected_at,
                    baseline_generated_at=comparison.baseline_generated_at,
                    current_generated_at=comparison.current_generated_at,
                    category="ports_opened",
                    severity=severity,
                    title="Nuevos puertos abiertos",
                    message=(
                        f"{identity} expone ahora: "
                        + ", ".join(str(port) for port in opened_ports)
                        + "."
                    ),
                    subject_id=asset_id,
                    details=(f"Riesgo actual: {after_risk}",),
                    before=sorted(before_ports),
                    after=sorted(after_ports),
                )
            )

    if comparison.security_score_delta < 0:
        drop = abs(comparison.security_score_delta)
        severity = NotificationSeverity.CRITICAL if drop >= 10 else NotificationSeverity.WARNING
        notifications.append(
            _new_notification(
                scope=scope,
                detected_at=detected_at,
                baseline_generated_at=comparison.baseline_generated_at,
                current_generated_at=comparison.current_generated_at,
                category="security_score_drop",
                severity=severity,
                title="Security Score reducido",
                message=(
                    f"Security Score: {comparison.security_score_before} → "
                    f"{comparison.security_score_after} ({comparison.security_score_delta:+d})."
                ),
                subject_id="security-score",
                details=comparison.findings_added,
                before=comparison.security_score_before,
                after=comparison.security_score_after,
            )
        )

    relationship_changes = (
        comparison.added_relationships,
        comparison.removed_relationships,
        comparison.changed_relationships,
    )
    if any(relationship_changes):
        details = [f"Añadida: {item.label}" for item in comparison.added_relationships]
        details.extend(f"Eliminada: {item.label}" for item in comparison.removed_relationships)
        for item in comparison.changed_relationships:
            details.append(f"Modificada: {item.label}")
            details.extend(f"  {detail}" for detail in item.details)
        severity = (
            NotificationSeverity.WARNING
            if comparison.added_relationships or comparison.changed_relationships
            else NotificationSeverity.INFO
        )
        notifications.append(
            _new_notification(
                scope=scope,
                detected_at=detected_at,
                baseline_generated_at=comparison.baseline_generated_at,
                current_generated_at=comparison.current_generated_at,
                category="relationships_changed",
                severity=severity,
                title="Topología de red modificada",
                message=(
                    f"Relaciones: +{len(comparison.added_relationships)} añadidas, "
                    f"-{len(comparison.removed_relationships)} eliminadas y "
                    f"{len(comparison.changed_relationships)} modificadas."
                ),
                subject_id="relationships",
                details=details,
                before=[item.label for item in comparison.removed_relationships],
                after=[item.label for item in comparison.added_relationships],
            )
        )

    notifications.sort(
        key=lambda item: (-_SEVERITY_RANK[item.severity], item.category, item.subject_id)
    )
    return NotificationBatch(
        scope=scope,
        baseline_generated_at=comparison.baseline_generated_at,
        current_generated_at=comparison.current_generated_at,
        security_score_delta=comparison.security_score_delta,
        notifications=tuple(notifications),
    )


def build_change_notifications_from_paths(
    baseline_path: str | Path,
    current_path: str | Path,
) -> NotificationBatch:
    return build_change_notifications(
        load_network_report(baseline_path),
        load_network_report(current_path),
    )


def _notification_to_dict(item: ChangeNotification) -> dict[str, Any]:
    return {
        "event_id": item.event_id,
        "scope": item.scope,
        "detected_at": _utc_iso(item.detected_at),
        "baseline_generated_at": item.baseline_generated_at,
        "current_generated_at": item.current_generated_at,
        "category": item.category,
        "severity": item.severity.value,
        "title": item.title,
        "message": item.message,
        "subject_id": item.subject_id,
        "details": list(item.details),
        "read": item.read,
    }


def _notification_from_dict(payload: Any, *, index: int) -> ChangeNotification:
    if not isinstance(payload, dict):
        raise ValueError(f"notifications[{index}] must be a JSON object.")

    required_strings = (
        "event_id",
        "scope",
        "baseline_generated_at",
        "current_generated_at",
        "category",
        "severity",
        "title",
        "message",
    )
    for key in required_strings:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"notifications[{index}].{key} must be a non-empty string.")

    detected_raw = payload.get("detected_at")
    if not isinstance(detected_raw, str):
        raise ValueError(f"notifications[{index}].detected_at must be a string.")
    detected_at = _parse_timestamp(detected_raw, field=f"notifications[{index}].detected_at")
    _parse_timestamp(
        payload["baseline_generated_at"],
        field=f"notifications[{index}].baseline_generated_at",
    )
    _parse_timestamp(
        payload["current_generated_at"],
        field=f"notifications[{index}].current_generated_at",
    )

    try:
        severity = NotificationSeverity(payload["severity"])
    except ValueError as error:
        raise ValueError(f"notifications[{index}].severity is invalid.") from error

    subject_id = payload.get("subject_id", "")
    if not isinstance(subject_id, str):
        raise ValueError(f"notifications[{index}].subject_id must be a string.")
    details = payload.get("details", [])
    if not isinstance(details, list) or any(not isinstance(item, str) for item in details):
        raise ValueError(f"notifications[{index}].details must contain strings only.")
    read = payload.get("read", False)
    if not isinstance(read, bool):
        raise ValueError(f"notifications[{index}].read must be a boolean.")

    return ChangeNotification(
        event_id=payload["event_id"],
        scope=payload["scope"],
        detected_at=detected_at,
        baseline_generated_at=payload["baseline_generated_at"],
        current_generated_at=payload["current_generated_at"],
        category=payload["category"],
        severity=severity,
        title=payload["title"],
        message=payload["message"],
        subject_id=subject_id,
        details=tuple(details),
        read=read,
    )


def load_notification_inbox(path: str | Path) -> tuple[ChangeNotification, ...]:
    source = Path(path)
    if not source.exists():
        return ()
    try:
        size = source.stat().st_size
    except OSError as error:
        raise ValueError(f"Could not inspect notification inbox: {source}") from error
    if size > MAX_NOTIFICATION_FILE_BYTES:
        raise ValueError("Notification inbox exceeds the 2 MiB safety limit.")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read notification inbox: {source}") from error
    if not isinstance(payload, dict):
        raise ValueError("Notification inbox root must be a JSON object.")
    if payload.get("schema_version") != NOTIFICATION_SCHEMA_VERSION:
        raise ValueError("Unsupported notification inbox schema version.")
    items = payload.get("notifications")
    if not isinstance(items, list):
        raise ValueError("Notification inbox notifications must be a JSON array.")
    if len(items) > MAX_NOTIFICATION_INBOX_ITEMS:
        raise ValueError(
            f"Notification inbox contains more than {MAX_NOTIFICATION_INBOX_ITEMS} items."
        )

    notifications = tuple(
        _notification_from_dict(item, index=index) for index, item in enumerate(items)
    )
    event_ids = [item.event_id for item in notifications]
    if len(event_ids) != len(set(event_ids)):
        raise ValueError("Notification inbox contains duplicate event_id values.")
    return notifications


def _ordered_notifications(
    notifications: Iterable[ChangeNotification],
) -> tuple[ChangeNotification, ...]:
    return tuple(
        sorted(
            notifications,
            key=lambda item: (
                item.detected_at,
                _SEVERITY_RANK[item.severity],
                item.event_id,
            ),
            reverse=True,
        )
    )


def merge_notifications(
    existing: Iterable[ChangeNotification],
    incoming: Iterable[ChangeNotification],
    *,
    max_items: int = MAX_NOTIFICATION_INBOX_ITEMS,
) -> tuple[tuple[ChangeNotification, ...], int]:
    if max_items < 1:
        raise ValueError("max_items must be at least 1.")
    by_id = {item.event_id: item for item in existing}
    added = 0
    for item in incoming:
        if item.event_id in by_id:
            continue
        by_id[item.event_id] = item
        added += 1
    ordered = _ordered_notifications(by_id.values())[:max_items]
    return ordered, added


def mark_all_notifications_read(
    notifications: Iterable[ChangeNotification],
) -> tuple[ChangeNotification, ...]:
    return tuple(replace(item, read=True) if not item.read else item for item in notifications)


def save_notification_inbox(
    path: str | Path,
    notifications: Iterable[ChangeNotification],
) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    ordered = _ordered_notifications(notifications)[:MAX_NOTIFICATION_INBOX_ITEMS]
    payload = {
        "schema_version": NOTIFICATION_SCHEMA_VERSION,
        "notifications": [_notification_to_dict(item) for item in ordered],
    }

    fd, temp_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, destination)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def notification_counts(
    notifications: Iterable[ChangeNotification],
    *,
    unread_only: bool = False,
) -> dict[NotificationSeverity, int]:
    counts = {severity: 0 for severity in NotificationSeverity}
    for item in notifications:
        if unread_only and item.read:
            continue
        counts[item.severity] += 1
    return counts


def format_notification_inbox(notifications: Iterable[ChangeNotification]) -> str:
    items = _ordered_notifications(notifications)
    if not items:
        return "No hay cambios relevantes registrados."

    lines: list[str] = []
    for item in items:
        state = "leído" if item.read else "nuevo"
        local_time = item.detected_at.astimezone().strftime("%d/%m/%Y %H:%M:%S")
        lines.append(f"[{item.severity.value}] {local_time} · {item.title} · {state}")
        lines.append(item.message)
        lines.extend(f"  - {detail}" for detail in item.details)
        lines.append("")
    return "\n".join(lines).rstrip()
