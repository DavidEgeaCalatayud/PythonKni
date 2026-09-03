from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pythonkni.camera_auditor.service import parse_camera_scope

from .fingerprint_policy import FingerprintPolicy

SCHEDULE_SCHEMA_VERSION = 2
SUPPORTED_SCHEDULE_SCHEMA_VERSIONS = frozenset({1, SCHEDULE_SCHEMA_VERSION})
DEFAULT_INTERVAL_MINUTES = 60
MIN_INTERVAL_MINUTES = 15
MAX_INTERVAL_MINUTES = 24 * 60
MAX_AUTOMATIC_SNAPSHOTS_PER_SCOPE = 120


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Schedule timestamps must be timezone-aware.")
    return value.astimezone(timezone.utc)


def _utc_text(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _utc(value).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: object, field: str) -> datetime | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO-8601 timestamp or null.")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone.")
    return parsed.astimezone(timezone.utc)


def _validate_interval(interval_minutes: int) -> int:
    if isinstance(interval_minutes, bool) or not isinstance(interval_minutes, int):
        raise ValueError("Schedule interval must be an integer number of minutes.")
    if not MIN_INTERVAL_MINUTES <= interval_minutes <= MAX_INTERVAL_MINUTES:
        raise ValueError(
            f"Schedule interval must be between {MIN_INTERVAL_MINUTES} and "
            f"{MAX_INTERVAL_MINUTES} minutes."
        )
    return interval_minutes


def _coerce_fingerprint_policy(value: object) -> FingerprintPolicy:
    if isinstance(value, FingerprintPolicy):
        return value
    try:
        return FingerprintPolicy(str(value))
    except ValueError as error:
        raise ValueError("Unsupported scheduled fingerprint policy.") from error


def canonical_schedule_scope(scope: str) -> str:
    if not isinstance(scope, str):
        raise ValueError("Schedule scope must be a CIDR string.")
    return parse_camera_scope(scope.strip()).with_prefixlen


@dataclass(frozen=True, slots=True)
class ScheduleConfig:
    enabled: bool = False
    scope: str = ""
    interval_minutes: int = DEFAULT_INTERVAL_MINUTES
    next_run_at: datetime | None = None
    last_started_at: datetime | None = None
    last_success_at: datetime | None = None
    last_snapshot: str = ""
    fingerprint_policy: FingerprintPolicy = FingerprintPolicy.MANUAL


def disabled_schedule() -> ScheduleConfig:
    return ScheduleConfig()


def create_schedule(
    scope: str,
    interval_minutes: int,
    *,
    now: datetime,
    fingerprint_policy: FingerprintPolicy = FingerprintPolicy.MANUAL,
) -> ScheduleConfig:
    canonical_scope = canonical_schedule_scope(scope)
    interval = _validate_interval(interval_minutes)
    now_utc = _utc(now)
    return ScheduleConfig(
        enabled=True,
        scope=canonical_scope,
        interval_minutes=interval,
        next_run_at=now_utc + timedelta(minutes=interval),
        fingerprint_policy=_coerce_fingerprint_policy(fingerprint_policy),
    )


def disable_schedule(config: ScheduleConfig) -> ScheduleConfig:
    return replace(config, enabled=False, next_run_at=None)


def change_schedule_interval(
    config: ScheduleConfig,
    interval_minutes: int,
    *,
    now: datetime,
) -> ScheduleConfig:
    interval = _validate_interval(interval_minutes)
    next_run_at = _utc(now) + timedelta(minutes=interval) if config.enabled else None
    return replace(config, interval_minutes=interval, next_run_at=next_run_at)


def change_fingerprint_policy(
    config: ScheduleConfig,
    policy: FingerprintPolicy,
) -> ScheduleConfig:
    return replace(config, fingerprint_policy=_coerce_fingerprint_policy(policy))


def schedule_due(config: ScheduleConfig, *, now: datetime) -> bool:
    if not config.enabled or config.next_run_at is None:
        return False
    return _utc(config.next_run_at) <= _utc(now)


def mark_schedule_started(config: ScheduleConfig, *, now: datetime) -> ScheduleConfig:
    if not config.enabled:
        return config
    now_utc = _utc(now)
    return replace(
        config,
        last_started_at=now_utc,
        next_run_at=now_utc + timedelta(minutes=config.interval_minutes),
    )


def mark_schedule_success(
    config: ScheduleConfig,
    *,
    now: datetime,
    snapshot: str | Path,
) -> ScheduleConfig:
    now_utc = _utc(now)
    return replace(
        config,
        last_success_at=now_utc,
        next_run_at=(
            now_utc + timedelta(minutes=config.interval_minutes) if config.enabled else None
        ),
        last_snapshot=str(snapshot),
    )


def _validated_config(config: ScheduleConfig) -> ScheduleConfig:
    if not isinstance(config.enabled, bool):
        raise ValueError("Schedule enabled must be a boolean.")
    if not isinstance(config.scope, str):
        raise ValueError("Schedule scope must be a CIDR string.")
    if not isinstance(config.last_snapshot, str):
        raise ValueError("Schedule last_snapshot must be a string.")

    interval = _validate_interval(config.interval_minutes)
    policy = _coerce_fingerprint_policy(config.fingerprint_policy)
    scope = config.scope.strip()
    if config.enabled:
        scope = canonical_schedule_scope(scope)
        if config.next_run_at is None:
            raise ValueError("An enabled schedule must include next_run_at.")
    elif scope:
        scope = canonical_schedule_scope(scope)

    timestamps = (
        config.next_run_at,
        config.last_started_at,
        config.last_success_at,
    )
    for value in timestamps:
        if value is not None:
            _utc(value)

    return replace(
        config,
        scope=scope,
        interval_minutes=interval,
        fingerprint_policy=policy,
    )


def load_schedule(path: str | Path) -> ScheduleConfig:
    source = Path(path)
    if not source.exists():
        return disabled_schedule()

    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Schedule file must contain a JSON object.")
    schema_version = payload.get("schema_version")
    if schema_version not in SUPPORTED_SCHEDULE_SCHEMA_VERSIONS:
        raise ValueError("Unsupported Network Intelligence schedule schema version.")

    enabled = payload.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError("Schedule enabled must be a boolean.")
    scope = payload.get("scope", "")
    last_snapshot = payload.get("last_snapshot", "")
    if not isinstance(scope, str):
        raise ValueError("Schedule scope must be a CIDR string.")
    if not isinstance(last_snapshot, str):
        raise ValueError("Schedule last_snapshot must be a string.")

    policy_value = (
        payload.get("fingerprint_policy", FingerprintPolicy.MANUAL.value)
        if schema_version >= 2
        else FingerprintPolicy.MANUAL.value
    )
    config = ScheduleConfig(
        enabled=enabled,
        scope=scope,
        interval_minutes=payload.get("interval_minutes", DEFAULT_INTERVAL_MINUTES),
        next_run_at=_parse_timestamp(payload.get("next_run_at"), "next_run_at"),
        last_started_at=_parse_timestamp(payload.get("last_started_at"), "last_started_at"),
        last_success_at=_parse_timestamp(payload.get("last_success_at"), "last_success_at"),
        last_snapshot=last_snapshot,
        fingerprint_policy=_coerce_fingerprint_policy(policy_value),
    )
    return _validated_config(config)


def save_schedule(path: str | Path, config: ScheduleConfig) -> None:
    destination = Path(path)
    validated = _validated_config(config)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SCHEDULE_SCHEMA_VERSION,
        "enabled": validated.enabled,
        "scope": validated.scope,
        "interval_minutes": validated.interval_minutes,
        "next_run_at": _utc_text(validated.next_run_at),
        "last_started_at": _utc_text(validated.last_started_at),
        "last_success_at": _utc_text(validated.last_success_at),
        "last_snapshot": validated.last_snapshot,
        "fingerprint_policy": validated.fingerprint_policy.value,
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


def _scope_slug(scope: str) -> str:
    canonical = canonical_schedule_scope(scope)
    return canonical.replace("/", "_").replace(":", "_")


def automatic_snapshot_destination(
    directory: str | Path,
    scope: str,
    *,
    generated_at: datetime,
) -> Path:
    stamp = _utc(generated_at).strftime("%Y%m%dT%H%M%S.%fZ")
    return Path(directory) / f"scheduled_{_scope_slug(scope)}_{stamp}.json"


def prune_automatic_snapshots(
    directory: str | Path,
    scope: str,
    *,
    keep: int = MAX_AUTOMATIC_SNAPSHOTS_PER_SCOPE,
) -> tuple[Path, ...]:
    if keep < 1:
        raise ValueError("Automatic snapshot retention must keep at least one snapshot.")
    root = Path(directory)
    if not root.exists():
        return ()

    prefix = f"scheduled_{_scope_slug(scope)}_"
    snapshots = sorted(
        path
        for path in root.glob(f"{prefix}*.json")
        if path.is_file() and path.name.startswith(prefix)
    )
    removable = snapshots[:-keep]
    removed: list[Path] = []
    for path in removable:
        path.unlink()
        removed.append(path)
    return tuple(removed)
