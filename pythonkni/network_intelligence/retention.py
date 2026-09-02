from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from .comparison import SnapshotReportError, load_network_report

RETENTION_SCHEMA_VERSION = 1
DEFAULT_KEEP_PER_SCOPE = 120
MIN_KEEP_PER_SCOPE = 1
MAX_KEEP_PER_SCOPE = 1000
MAX_RETENTION_DAYS = 3650
MAX_CATALOG_FILES = 2000


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    keep_per_scope: int = DEFAULT_KEEP_PER_SCOPE
    max_age_days: int | None = None


@dataclass(frozen=True, slots=True)
class SnapshotCatalogEntry:
    path: Path
    generated_at: datetime
    generated_at_text: str
    scope: str
    schema_version: int
    score: int
    total_devices: int
    high_risk: int
    medium_risk: int
    low_risk: int
    unknown_devices: int
    findings: tuple[str, ...]
    size_bytes: int


@dataclass(frozen=True, slots=True)
class SnapshotCatalog:
    entries: tuple[SnapshotCatalogEntry, ...]
    skipped: tuple[tuple[Path, str], ...] = ()
    truncated_count: int = 0

    @property
    def scopes(self) -> tuple[str, ...]:
        return tuple(sorted({entry.scope for entry in self.entries}))

    @property
    def total_size_bytes(self) -> int:
        return sum(entry.size_bytes for entry in self.entries)


@dataclass(frozen=True, slots=True)
class TrendSummary:
    points: int
    first_score: int
    latest_score: int
    lowest_score: int
    highest_score: int
    score_delta: int
    devices_delta: int
    high_risk_delta: int
    medium_risk_delta: int
    unknown_delta: int


@dataclass(frozen=True, slots=True)
class RetentionCleanup:
    removed: tuple[Path, ...]
    bytes_reclaimed: int


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Retention timestamps must be timezone-aware.")
    return value.astimezone(timezone.utc)


def _parse_timestamp(value: object, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise SnapshotReportError(f"{field} must be a non-empty ISO-8601 timestamp.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise SnapshotReportError(f"{field} must be a valid ISO-8601 timestamp.") from error
    if parsed.tzinfo is None:
        raise SnapshotReportError(f"{field} must include a timezone.")
    return parsed.astimezone(timezone.utc)


def validate_retention_policy(policy: RetentionPolicy) -> RetentionPolicy:
    keep = policy.keep_per_scope
    if isinstance(keep, bool) or not isinstance(keep, int):
        raise ValueError("Snapshot retention count must be an integer.")
    if not MIN_KEEP_PER_SCOPE <= keep <= MAX_KEEP_PER_SCOPE:
        raise ValueError(
            f"Snapshot retention count must be between {MIN_KEEP_PER_SCOPE} and "
            f"{MAX_KEEP_PER_SCOPE}."
        )

    age = policy.max_age_days
    if age is not None:
        if isinstance(age, bool) or not isinstance(age, int):
            raise ValueError("Snapshot retention age must be an integer number of days or null.")
        if not 1 <= age <= MAX_RETENTION_DAYS:
            raise ValueError(
                f"Snapshot retention age must be between 1 and {MAX_RETENTION_DAYS} days."
            )
    return policy


def load_retention_policy(path: str | Path) -> RetentionPolicy:
    source = Path(path)
    if not source.exists():
        return RetentionPolicy()

    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Retention configuration must contain a JSON object.")
    if payload.get("schema_version") != RETENTION_SCHEMA_VERSION:
        raise ValueError("Unsupported Network Intelligence retention schema version.")

    policy = RetentionPolicy(
        keep_per_scope=payload.get("keep_per_scope", DEFAULT_KEEP_PER_SCOPE),
        max_age_days=payload.get("max_age_days"),
    )
    return validate_retention_policy(policy)


def save_retention_policy(path: str | Path, policy: RetentionPolicy) -> None:
    validated = validate_retention_policy(policy)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": RETENTION_SCHEMA_VERSION,
        "keep_per_scope": validated.keep_per_scope,
        "max_age_days": validated.max_age_days,
    }

    fd, temp_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
        text=True,
    )
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, destination)
    except Exception:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _entry_from_report(path: Path, report: dict) -> SnapshotCatalogEntry:
    generated_at_text = str(report["generated_at"])
    generated_at = _parse_timestamp(generated_at_text, field="generated_at")
    score = report["security_score"]
    return SnapshotCatalogEntry(
        path=path,
        generated_at=generated_at,
        generated_at_text=generated_at_text,
        scope=str(report["scope"]),
        schema_version=int(report["schema_version"]),
        score=int(score["score"]),
        total_devices=int(score.get("total_devices", 0)),
        high_risk=int(score.get("high_risk", 0)),
        medium_risk=int(score.get("medium_risk", 0)),
        low_risk=int(score.get("low_risk", 0)),
        unknown_devices=int(score.get("unknown_devices", 0)),
        findings=tuple(str(item) for item in score.get("findings", [])),
        size_bytes=path.stat().st_size,
    )


def load_snapshot_catalog(
    directory: str | Path,
    *,
    max_files: int = MAX_CATALOG_FILES,
) -> SnapshotCatalog:
    if isinstance(max_files, bool) or not isinstance(max_files, int) or max_files < 1:
        raise ValueError("Snapshot catalog max_files must be a positive integer.")

    root = Path(directory)
    if not root.exists():
        return SnapshotCatalog(entries=())

    paths = sorted(
        (path for path in root.glob("scheduled_*.json") if path.is_file()),
        key=lambda path: path.name,
        reverse=True,
    )
    truncated_count = max(0, len(paths) - max_files)
    paths = paths[:max_files]

    entries: list[SnapshotCatalogEntry] = []
    skipped: list[tuple[Path, str]] = []
    for path in paths:
        try:
            entries.append(_entry_from_report(path, load_network_report(path)))
        except Exception as error:
            skipped.append((path, str(error)))

    entries.sort(key=lambda entry: (entry.generated_at, str(entry.path)))
    skipped.sort(key=lambda item: item[0].name)
    return SnapshotCatalog(
        entries=tuple(entries),
        skipped=tuple(skipped),
        truncated_count=truncated_count,
    )


def filter_snapshot_entries(
    entries: Iterable[SnapshotCatalogEntry],
    *,
    scope: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> tuple[SnapshotCatalogEntry, ...]:
    since_utc = _utc(since) if since is not None else None
    until_utc = _utc(until) if until is not None else None
    if since_utc is not None and until_utc is not None and since_utc > until_utc:
        raise ValueError("Snapshot filter start must not be after its end.")

    selected = []
    for entry in entries:
        if scope and entry.scope != scope:
            continue
        if since_utc is not None and entry.generated_at < since_utc:
            continue
        if until_utc is not None and entry.generated_at > until_utc:
            continue
        selected.append(entry)
    selected.sort(key=lambda entry: (entry.generated_at, str(entry.path)))
    return tuple(selected)


def summarize_trend(entries: Iterable[SnapshotCatalogEntry]) -> TrendSummary | None:
    ordered = sorted(entries, key=lambda entry: (entry.generated_at, str(entry.path)))
    if not ordered:
        return None
    first = ordered[0]
    latest = ordered[-1]
    return TrendSummary(
        points=len(ordered),
        first_score=first.score,
        latest_score=latest.score,
        lowest_score=min(entry.score for entry in ordered),
        highest_score=max(entry.score for entry in ordered),
        score_delta=latest.score - first.score,
        devices_delta=latest.total_devices - first.total_devices,
        high_risk_delta=latest.high_risk - first.high_risk,
        medium_risk_delta=latest.medium_risk - first.medium_risk,
        unknown_delta=latest.unknown_devices - first.unknown_devices,
    )


def previous_snapshot_for(
    entries: Iterable[SnapshotCatalogEntry],
    current: SnapshotCatalogEntry,
) -> SnapshotCatalogEntry | None:
    same_scope = sorted(
        (entry for entry in entries if entry.scope == current.scope and entry.path != current.path),
        key=lambda entry: (entry.generated_at, str(entry.path)),
    )
    previous = [entry for entry in same_scope if entry.generated_at < current.generated_at]
    return previous[-1] if previous else None


def retention_candidates(
    entries: Iterable[SnapshotCatalogEntry],
    policy: RetentionPolicy,
    *,
    now: datetime,
    scope: str | None = None,
) -> tuple[SnapshotCatalogEntry, ...]:
    validated = validate_retention_policy(policy)
    now_utc = _utc(now)
    grouped: dict[str, list[SnapshotCatalogEntry]] = {}
    for entry in entries:
        if scope and entry.scope != scope:
            continue
        grouped.setdefault(entry.scope, []).append(entry)

    removable: dict[Path, SnapshotCatalogEntry] = {}
    for scoped_entries in grouped.values():
        scoped_entries.sort(key=lambda entry: (entry.generated_at, str(entry.path)))
        if not scoped_entries:
            continue
        protected = {entry.path for entry in scoped_entries[-MIN_KEEP_PER_SCOPE:]}

        overflow = scoped_entries[:-validated.keep_per_scope]
        for entry in overflow:
            if entry.path not in protected:
                removable[entry.path] = entry

        if validated.max_age_days is not None:
            cutoff = now_utc - timedelta(days=validated.max_age_days)
            for entry in scoped_entries:
                if entry.path not in protected and entry.generated_at < cutoff:
                    removable[entry.path] = entry

    return tuple(
        sorted(removable.values(), key=lambda entry: (entry.generated_at, str(entry.path)))
    )


def apply_retention_policy(
    directory: str | Path,
    policy: RetentionPolicy,
    *,
    now: datetime,
    scope: str | None = None,
) -> RetentionCleanup:
    catalog = load_snapshot_catalog(directory)
    candidates = retention_candidates(catalog.entries, policy, now=now, scope=scope)
    removed: list[Path] = []
    reclaimed = 0
    for entry in candidates:
        entry.path.unlink()
        removed.append(entry.path)
        reclaimed += entry.size_bytes
    return RetentionCleanup(removed=tuple(removed), bytes_reclaimed=reclaimed)