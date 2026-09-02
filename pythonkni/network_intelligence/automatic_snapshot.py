from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .models import AssetRecord, NetworkRelationship, TimelineEvent
from .reporting import build_network_report, export_network_report
from .retention import RetentionPolicy, apply_retention_policy
from .scheduler import automatic_snapshot_destination


@dataclass(frozen=True, slots=True)
class AutomaticSnapshotResult:
    path: Path
    pruned_count: int


def create_automatic_snapshot(
    directory: str | Path,
    scope: str,
    assets: list[AssetRecord] | tuple[AssetRecord, ...],
    relationships: list[NetworkRelationship] | tuple[NetworkRelationship, ...],
    events: list[TimelineEvent] | tuple[TimelineEvent, ...],
    *,
    generated_at: datetime,
    retention_policy: RetentionPolicy | None = None,
) -> AutomaticSnapshotResult:
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    destination = automatic_snapshot_destination(root, scope, generated_at=generated_at)
    report = build_network_report(
        scope,
        assets,
        relationships,
        events,
        generated_at=generated_at,
    )

    fd, temp_name = tempfile.mkstemp(
        prefix=f".{destination.stem}.",
        suffix=".json",
        dir=root,
    )
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        export_network_report(temp_path, report)
        os.replace(temp_path, destination)
    except Exception:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise

    cleanup = apply_retention_policy(
        root,
        retention_policy or RetentionPolicy(),
        now=generated_at,
        scope=scope,
    )
    return AutomaticSnapshotResult(path=destination, pruned_count=len(cleanup.removed))
