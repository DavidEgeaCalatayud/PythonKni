from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts import update_oui_registry as updater


def _source(count: int, *, vendor_prefix: str = "Vendor") -> bytes:
    rows = [
        f"MA-L,{0x100000 + index:06X},{vendor_prefix} {index},Address {index}"
        for index in range(count)
    ]
    return (
        "Registry,Assignment,Organization Name,Organization Address\n"
        + "\n".join(rows)
        + "\n"
    ).encode("utf-8")


def _write_valid_registry(tmp_path: Path, count: int = 20) -> tuple[Path, Path, Path]:
    source = tmp_path / "ieee.csv"
    registry = tmp_path / "registry.csv"
    metadata = tmp_path / "metadata.json"
    source.write_bytes(_source(count))
    updater.update_registry(
        registry_path=registry,
        metadata_path=metadata,
        source_file=source,
        min_entries=1,
        retrieved_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
    )
    return source, registry, metadata


def test_entry_count_continuity_rejects_large_drop_without_replacing_pair(tmp_path):
    source, registry, metadata = _write_valid_registry(tmp_path, count=20)
    previous_registry = registry.read_bytes()
    previous_metadata = metadata.read_bytes()
    source.write_bytes(_source(18, vendor_prefix="Updated"))

    with pytest.raises(updater.RegistryUpdateError, match="dropped unexpectedly"):
        updater.update_registry(
            registry_path=registry,
            metadata_path=metadata,
            source_file=source,
            min_entries=1,
            max_entry_drop_fraction=0.05,
        )

    assert registry.read_bytes() == previous_registry
    assert metadata.read_bytes() == previous_metadata


def test_entry_count_continuity_accepts_exact_configured_boundary(tmp_path):
    source, registry, metadata = _write_valid_registry(tmp_path, count=20)
    source.write_bytes(_source(19, vendor_prefix="Updated"))

    assert updater.update_registry(
        registry_path=registry,
        metadata_path=metadata,
        source_file=source,
        min_entries=1,
        max_entry_drop_fraction=0.05,
        retrieved_at=datetime(2026, 9, 3, tzinfo=timezone.utc),
    ) is True
    assert updater.validate_bundled_registry(
        registry_path=registry,
        metadata_path=metadata,
        min_entries=1,
    ) == 19


@pytest.mark.parametrize("value", [-0.01, 1.0, 1.5])
def test_entry_count_continuity_rejects_invalid_drop_fraction(value):
    with pytest.raises(updater.RegistryUpdateError, match="entry-drop fraction"):
        updater._enforce_entry_count_continuity(
            previous_count=100,
            new_count=100,
            max_drop_fraction=value,
        )


def test_duplicate_metadata_must_match_ambiguous_registry_value(tmp_path):
    source = tmp_path / "ieee.csv"
    source.write_bytes(
        (
            "Registry,Assignment,Organization Name,Organization Address\n"
            "MA-L,080030,CERN,Geneva\n"
            "MA-L,080030,NETWORK RESEARCH CORPORATION,Oxnard\n"
        ).encode("utf-8")
    )
    registry = tmp_path / "registry.csv"
    metadata = tmp_path / "metadata.json"
    updater.update_registry(
        registry_path=registry,
        metadata_path=metadata,
        source_file=source,
        min_entries=1,
        retrieved_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
    )

    payload = json.loads(metadata.read_text(encoding="utf-8"))
    payload["duplicate_assignments"][0]["vendors"] = ["CERN", "OTHER VENDOR"]
    metadata.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(updater.RegistryUpdateError, match="does not match registry value"):
        updater.validate_bundled_registry(
            registry_path=registry,
            metadata_path=metadata,
            min_entries=1,
        )


def test_pair_publication_cleans_first_staged_file_when_second_stage_fails(
    tmp_path, monkeypatch
):
    registry = tmp_path / "registry.csv"
    metadata = tmp_path / "metadata.json"
    registry.write_bytes(b"old-registry")
    metadata.write_bytes(b"old-metadata")
    real_stage = updater._stage_file
    calls = 0

    def failing_stage(path, content):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("metadata staging failed")
        return real_stage(path, content)

    monkeypatch.setattr(updater, "_stage_file", failing_stage)

    with pytest.raises(OSError, match="metadata staging failed"):
        updater.write_registry_pair(
            registry,
            metadata,
            b"new-registry",
            b"new-metadata",
        )

    assert registry.read_bytes() == b"old-registry"
    assert metadata.read_bytes() == b"old-metadata"
    assert not any(path.suffix == ".tmp" for path in tmp_path.iterdir())


def test_generated_registry_is_pinned_to_lf_for_cross_platform_hashes():
    attributes = (Path(__file__).resolve().parents[1] / ".gitattributes").read_text(
        encoding="utf-8"
    )

    assert "assets/network_oui_prefixes.csv text eol=lf" in attributes.splitlines()
