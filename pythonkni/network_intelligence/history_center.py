from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .comparison import SnapshotReportError, load_network_report
from .history import ScoreHistory, build_score_history

HISTORY_RETENTION_SCHEMA_VERSION = 1
DEFAULT_MAX_SNAPSHOTS_PER_SCOPE = 120
MIN_MAX_SNAPSHOTS_PER_SCOPE = 2
MAX_MAX_SNAPSHOTS_PER_SCOPE = 1000
MIN_MAX_AGE_DAYS = 1
MAX_MAX_AGE_DAYS = 3650


@dataclass(frozen=True, slots=True)
class HistoryRetentionPolicy:
    max_snapshots_per_scope: int = DEFAULT_MAX_SNAPSHOTS_PER_SCOPE
    max_age_days: int | None = None
    auto_cleanup: bool = True


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
    relationships: int
    findings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SnapshotCatalog:
    entries: tuple[SnapshotCatalogEntry, ...]
    warnings: tuple[str, ...] = ()

    @property
    def scopes(self) -> tuple[str, ...]:
        return tuple(sorted({entry.scope for entry in self.entries}))


@dataclass(frozen=True, slots=True)
class RetentionPlan:
    remove: tuple[Path, ...]
    keep: tuple[Path, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RetentionResult:
    removed: tuple[Path, ...]
    kept: tuple[Path, ...]
    warnings: tuple[str, ...] = ()


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("History timestamps must be timezone-aware.")
    return value.astimezone(timezone.utc)


def _parse_generated_at(value: object) -> tuple[datetime, str]:
    if not isinstance(value, str) or not value.strip():
        raise SnapshotReportError("generated_at must be a non-empty ISO-8601 timestamp.")
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise SnapshotReportError("generated_at must be a valid ISO-8601 timestamp.") from error
    if parsed.tzinfo is None:
        raise SnapshotReportError("generated_at must include a timezone.")
    return parsed.astimezone(timezone.utc), text


def _validated_policy(policy: HistoryRetentionPolicy) -> HistoryRetentionPolicy:
    count = policy.max_snapshots_per_scope
    if isinstance(count, bool) or not isinstance(count, int):
        raise ValueError("Snapshot retention count must be an integer.")
    if not MIN_MAX_SNAPSHOTS_PER_SCOPE <= count <= MAX_MAX_SNAPSHOTS_PER_SCOPE:
        raise ValueError(
            f"Snapshot retention count must be between {MIN_MAX_SNAPSHOTS_PER_SCOPE} and "
            f"{MAX_MAX_SNAPSHOTS_PER_SCOPE}."
        )

    age = policy.max_age_days
    if age is not None:
        if isinstance(age, bool) or not isinstance(age, int):
            raise ValueError("Snapshot retention age must be an integer number of days or null.")
        if not MIN_MAX_AGE_DAYS <= age <= MAX_MAX_AGE_DAYS:
            raise ValueError(
                f"Snapshot retention age must be between {MIN_MAX_AGE_DAYS} and "
                f"{MAX_MAX_AGE_DAYS} days."
            )

    if not isinstance(policy.auto_cleanup, bool):
        raise ValueError("Automatic history cleanup must be a boolean.")
    return policy


def default_retention_policy() -> HistoryRetentionPolicy:
    return HistoryRetentionPolicy()


def load_retention_policy(path: str | Path) -> HistoryRetentionPolicy:
    source = Path(path)
    if not source.exists():
        return default_retention_policy()
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("History retention file must contain a JSON object.")
    if payload.get("schema_version") != HISTORY_RETENTION_SCHEMA_VERSION:
        raise ValueError("Unsupported Network Intelligence history-retention schema version.")
    policy = HistoryRetentionPolicy(
        max_snapshots_per_scope=payload.get(
            "max_snapshots_per_scope", DEFAULT_MAX_SNAPSHOTS_PER_SCOPE
        ),
        max_age_days=payload.get("max_age_days"),
        auto_cleanup=payload.get("auto_cleanup", True),
    )
    return _validated_policy(policy)


def save_retention_policy(path: str | Path, policy: HistoryRetentionPolicy) -> None:
    destination = Path(path)
    validated = _validated_policy(policy)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": HISTORY_RETENTION_SCHEMA_VERSION,
        "max_snapshots_per_scope": validated.max_snapshots_per_scope,
        "max_age_days": validated.max_age_days,
        "auto_cleanup": validated.auto_cleanup,
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


def _catalog_entry(path: Path, report: dict) -> SnapshotCatalogEntry:
    generated_at, generated_at_text = _parse_generated_at(report.get("generated_at"))
    score = report["security_score"]
    summary = report.get("summary", {})
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
        relationships=int(summary.get("relationships", 0)),
        findings=tuple(str(item) for item in score.get("findings", [])),
    )


def load_snapshot_catalog(directory: str | Path) -> SnapshotCatalog:
    root = Path(directory)
    if not root.exists():
        return SnapshotCatalog(entries=())

    entries: list[SnapshotCatalogEntry] = []
    warnings: list[str] = []
    for path in sorted(root.glob("scheduled_*.json")):
        if not path.is_file():
            continue
        try:
            report = load_network_report(path)
            entries.append(_catalog_entry(path, report))
        except Exception as error:
            warnings.append(f"{path.name}: {error}")

    entries.sort(key=lambda entry: (entry.generated_at, str(entry.path)))
    return SnapshotCatalog(entries=tuple(entries), warnings=tuple(warnings))


def filter_catalog(
    entries: tuple[SnapshotCatalogEntry, ...] | list[SnapshotCatalogEntry],
    *,
    scope: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> tuple[SnapshotCatalogEntry, ...]:
    since_utc = _utc(since) if since is not None else None
    until_utc = _utc(until) if until is not None else None
    if since_utc is not None and until_utc is not None and since_utc > until_utc:
        raise ValueError("History start time cannot be after end time.")

    selected = []
    for entry in entries:
        if scope is not None and entry.scope != scope:
            continue
        if since_utc is not None and entry.generated_at < since_utc:
            continue
        if until_utc is not None and entry.generated_at > until_utc:
            continue
        selected.append(entry)
    return tuple(selected)


def range_start(now: datetime, days: int | None) -> datetime | None:
    if days is None:
        return None
    if isinstance(days, bool) or not isinstance(days, int) or days < 1:
        raise ValueError("History range days must be a positive integer or null.")
    return _utc(now) - timedelta(days=days)


def build_catalog_score_history(
    entries: tuple[SnapshotCatalogEntry, ...] | list[SnapshotCatalogEntry],
) -> ScoreHistory:
    ordered = sorted(entries, key=lambda entry: (entry.generated_at, str(entry.path)))
    snapshots = [(entry.path, load_network_report(entry.path)) for entry in ordered]
    return build_score_history(snapshots)


def previous_snapshot(
    entries: tuple[SnapshotCatalogEntry, ...] | list[SnapshotCatalogEntry],
    selected: SnapshotCatalogEntry,
) -> SnapshotCatalogEntry | None:
    same_scope = sorted(
        (entry for entry in entries if entry.scope == selected.scope),
        key=lambda entry: (entry.generated_at, str(entry.path)),
    )
    previous: SnapshotCatalogEntry | None = None
    for entry in same_scope:
        if entry.path == selected.path:
            return previous
        previous = entry
    return None


def next_snapshot(
    entries: tuple[SnapshotCatalogEntry, ...] | list[SnapshotCatalogEntry],
    selected: SnapshotCatalogEntry,
) -> SnapshotCatalogEntry | None:
    same_scope = sorted(
        (entry for entry in entries if entry.scope == selected.scope),
        key=lambda entry: (entry.generated_at, str(entry.path)),
    )
    for index, entry in enumerate(same_scope):
        if entry.path == selected.path:
            return same_scope[index + 1] if index + 1 < len(same_scope) else None
    return None


def plan_snapshot_retention(
    directory: str | Path,
    policy: HistoryRetentionPolicy,
    *,
    now: datetime,
) -> RetentionPlan:
    validated = _validated_policy(policy)
    now_utc = _utc(now)
    catalog = load_snapshot_catalog(directory)
    remove: set[Path] = set()

    for scope in catalog.scopes:
        scoped = [entry for entry in catalog.entries if entry.scope == scope]
        scoped.sort(key=lambda entry: (entry.generated_at, str(entry.path)))
        protected = {entry.path for entry in scoped[-MIN_MAX_SNAPSHOTS_PER_SCOPE:]}

        excess = max(0, len(scoped) - validated.max_snapshots_per_scope)
        for entry in scoped[:excess]:
            if entry.path not in protected:
                remove.add(entry.path)

        if validated.max_age_days is not None:
            cutoff = now_utc - timedelta(days=validated.max_age_days)
            for entry in scoped:
                if entry.generated_at < cutoff and entry.path not in protected:
                    remove.add(entry.path)

    ordered_remove = tuple(
        sorted(
            remove,
            key=lambda path: next(
                (
                    (entry.generated_at, str(entry.path))
                    for entry in catalog.entries
                    if entry.path == path
                ),
                (datetime.min.replace(tzinfo=timezone.utc), str(path)),
            ),
        )
    )
    remove_set = set(ordered_remove)
    kept = tuple(entry.path for entry in catalog.entries if entry.path not in remove_set)
    return RetentionPlan(remove=ordered_remove, keep=kept, warnings=catalog.warnings)


def apply_retention_plan(plan: RetentionPlan) -> RetentionResult:
    removed: list[Path] = []
    for path in plan.remove:
        path.unlink()
        removed.append(path)
    return RetentionResult(
        removed=tuple(removed),
        kept=plan.keep,
        warnings=plan.warnings,
    )


def cleanup_automatic_snapshots(
    directory: str | Path,
    policy: HistoryRetentionPolicy,
    *,
    now: datetime,
) -> RetentionResult:
    return apply_retention_plan(plan_snapshot_retention(directory, policy, now=now))
