from __future__ import annotations

from pathlib import Path

from .models import AssetRecord
from .physical_evidence import PhysicalImportResult, import_physical_snapshot

MAX_PHYSICAL_SNAPSHOT_BYTES = 2 * 1024 * 1024


def load_physical_snapshot_file(
    path: str | Path,
    assets: list[AssetRecord],
    *,
    expected_scope: str,
) -> PhysicalImportResult:
    snapshot_path = Path(path)
    with snapshot_path.open("rb") as stream:
        payload = stream.read(MAX_PHYSICAL_SNAPSHOT_BYTES + 1)
    if len(payload) > MAX_PHYSICAL_SNAPSHOT_BYTES:
        raise ValueError(
            f"Physical evidence snapshot exceeds the {MAX_PHYSICAL_SNAPSHOT_BYTES // (1024 * 1024)} MiB limit."
        )
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("Physical evidence snapshot must be UTF-8 JSON.") from error
    return import_physical_snapshot(text, assets, expected_scope=expected_scope)
