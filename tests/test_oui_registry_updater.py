from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from scripts import update_oui_registry as updater


def _source(*rows: str) -> bytes:
    return (
        "Registry,Assignment,Organization Name,Organization Address\n"
        + "\n".join(rows)
        + "\n"
    ).encode("utf-8")


def test_ieee_parser_normalizes_and_sorts_assignments_and_vendors():
    source = _source(
        'MA-L,245EBE,"QNAP   Systems, Inc.",Taipei',
        'MA-L,001132,"Synology Incorporated",Taipei',
    )

    entries = updater.parse_ieee_ma_l_csv(source)

    assert entries == (
        updater.RegistryEntry("00-11-32", "Synology Incorporated"),
        updater.RegistryEntry("24-5E-BE", "QNAP Systems, Inc."),
    )


def test_ieee_parser_accepts_utf8_bom_and_unicode_vendor_names():
    source = b"\xef\xbb\xbf" + _source(
        'MA-L,AABBCC,"Tecnología España S.A.",Madrid'
    )

    assert updater.parse_ieee_ma_l_csv(source) == (
        updater.RegistryEntry("AA-BB-CC", "Tecnología España S.A."),
    )


@pytest.mark.parametrize(
    "source, message",
    [
        (b"Assignment,Organization Name\n001132,Synology\n", "missing required columns"),
        (_source("MA-M,001132,Synology,Taipei"), "unexpected registry"),
        (_source("MA-L,nothex,Synology,Taipei"), "invalid MA-L assignment"),
        (_source("MA-L,001132,,Taipei"), "vendor name is empty"),
    ],
)
def test_ieee_parser_rejects_invalid_source_contract(source, message):
    with pytest.raises(updater.RegistryUpdateError, match=message):
        updater.parse_ieee_ma_l_csv(source)


def test_ieee_parser_rejects_duplicate_assignments():
    source = _source(
        "MA-L,001132,Synology,Taipei",
        "MA-L,00-11-32,Duplicate,Taipei",
    )

    with pytest.raises(updater.RegistryUpdateError, match="duplicate MA-L assignment"):
        updater.parse_ieee_ma_l_csv(source)


def test_render_registry_is_deterministic_for_input_order():
    entries_a = [
        updater.RegistryEntry("24-5E-BE", "QNAP"),
        updater.RegistryEntry("00-11-32", "Synology"),
    ]
    entries_b = list(reversed(entries_a))

    expected = b"prefix,vendor\n00-11-32,Synology\n24-5E-BE,QNAP\n"
    assert updater.render_registry(entries_a) == expected
    assert updater.render_registry(entries_b) == expected


def test_render_registry_rejects_duplicate_prefixes():
    entries = [
        updater.RegistryEntry("00-11-32", "Synology"),
        updater.RegistryEntry("001132", "Duplicate"),
    ]

    with pytest.raises(updater.RegistryUpdateError, match="duplicate bundled assignment"):
        updater.render_registry(entries)


@pytest.mark.parametrize(
    "content, message",
    [
        (b"vendor,prefix\nSynology,00-11-32\n", "exactly the columns"),
        (
            b"prefix,vendor\n00-11-32,Synology\n00-11-32,Duplicate\n",
            "duplicate bundled assignment",
        ),
        (
            b"prefix,vendor\n24-5E-BE,QNAP\n00-11-32,Synology\n",
            "not strictly sorted",
        ),
    ],
)
def test_bundled_parser_rejects_noncanonical_registry(content, message):
    with pytest.raises(updater.RegistryUpdateError, match=message):
        updater.parse_bundled_registry(content)


def test_metadata_is_reproducible_with_fixed_timestamp():
    source = updater.DownloadedSource(
        content=b"raw-ieee-source",
        etag='"fixture"',
        last_modified="Tue, 01 Sep 2026 00:00:00 GMT",
    )
    registry = b"prefix,vendor\n00-11-32,Synology\n"
    timestamp = datetime(2026, 9, 2, 8, 0, tzinfo=timezone.utc)

    first = updater.build_metadata(
        source=source,
        registry_bytes=registry,
        entry_count=1,
        retrieved_at=timestamp,
    )
    second = updater.build_metadata(
        source=source,
        registry_bytes=registry,
        entry_count=1,
        retrieved_at=timestamp,
    )

    assert first == second
    payload = json.loads(first)
    assert payload["retrieved_at"] == "2026-09-02T08:00:00Z"
    assert payload["entry_count"] == 1
    assert payload["source_etag"] == '"fixture"'
    assert len(payload["source_sha256"]) == 64
    assert len(payload["registry_sha256"]) == 64


def test_update_from_local_source_writes_valid_pair_and_is_idempotent(tmp_path):
    source_path = tmp_path / "ieee.csv"
    source_path.write_bytes(
        _source(
            "MA-L,245EBE,QNAP,Taipei",
            "MA-L,001132,Synology,Taipei",
        )
    )
    registry = tmp_path / "network_oui_prefixes.csv"
    metadata = tmp_path / "network_oui_prefixes.meta.json"
    timestamp = datetime(2026, 9, 2, 8, 0, tzinfo=timezone.utc)

    assert (
        updater.update_registry(
            registry_path=registry,
            metadata_path=metadata,
            source_file=source_path,
            min_entries=2,
            retrieved_at=timestamp,
        )
        is True
    )
    before_registry = registry.read_bytes()
    before_metadata = metadata.read_bytes()

    assert (
        updater.update_registry(
            registry_path=registry,
            metadata_path=metadata,
            source_file=source_path,
            min_entries=2,
            retrieved_at=datetime(2026, 9, 3, 8, 0, tzinfo=timezone.utc),
        )
        is False
    )
    assert registry.read_bytes() == before_registry
    assert metadata.read_bytes() == before_metadata
    assert (
        updater.validate_bundled_registry(
            registry_path=registry,
            metadata_path=metadata,
            min_entries=2,
        )
        == 2
    )


def test_update_rejects_truncated_source_before_replacing_existing_files(tmp_path):
    source_path = tmp_path / "ieee.csv"
    source_path.write_bytes(_source("MA-L,001132,Synology,Taipei"))
    registry = tmp_path / "network_oui_prefixes.csv"
    metadata = tmp_path / "network_oui_prefixes.meta.json"
    registry.write_bytes(b"old-registry")
    metadata.write_bytes(b"old-metadata")

    with pytest.raises(updater.RegistryUpdateError, match="expected at least 2"):
        updater.update_registry(
            registry_path=registry,
            metadata_path=metadata,
            source_file=source_path,
            min_entries=2,
        )

    assert registry.read_bytes() == b"old-registry"
    assert metadata.read_bytes() == b"old-metadata"


def test_validate_detects_registry_metadata_hash_mismatch(tmp_path):
    source_path = tmp_path / "ieee.csv"
    source_path.write_bytes(_source("MA-L,001132,Synology,Taipei"))
    registry = tmp_path / "network_oui_prefixes.csv"
    metadata = tmp_path / "network_oui_prefixes.meta.json"
    updater.update_registry(
        registry_path=registry,
        metadata_path=metadata,
        source_file=source_path,
        min_entries=1,
        retrieved_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
    )
    registry.write_bytes(registry.read_bytes() + b"24-5E-BE,QNAP\n")

    with pytest.raises(updater.RegistryUpdateError, match="metadata mismatch"):
        updater.validate_bundled_registry(
            registry_path=registry,
            metadata_path=metadata,
            min_entries=1,
        )


def test_validate_rejects_invalid_source_hash_and_naive_retrieval_time(tmp_path):
    source_path = tmp_path / "ieee.csv"
    source_path.write_bytes(_source("MA-L,001132,Synology,Taipei"))
    registry = tmp_path / "network_oui_prefixes.csv"
    metadata = tmp_path / "network_oui_prefixes.meta.json"
    updater.update_registry(
        registry_path=registry,
        metadata_path=metadata,
        source_file=source_path,
        min_entries=1,
        retrieved_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
    )

    payload = json.loads(metadata.read_text(encoding="utf-8"))
    payload["source_sha256"] = "bad"
    metadata.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(updater.RegistryUpdateError, match="source_sha256"):
        updater.validate_bundled_registry(
            registry_path=registry,
            metadata_path=metadata,
            min_entries=1,
        )

    payload["source_sha256"] = "0" * 64
    payload["retrieved_at"] = "2026-09-02T08:00:00"
    metadata.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(updater.RegistryUpdateError, match="timezone"):
        updater.validate_bundled_registry(
            registry_path=registry,
            metadata_path=metadata,
            min_entries=1,
        )


def test_download_uses_bounded_read_and_preserves_http_metadata(monkeypatch):
    class Headers:
        def get(self, name):
            return {
                "ETag": '"etag"',
                "Last-Modified": "Wed, 02 Sep 2026 00:00:00 GMT",
            }.get(name)

    class Response:
        headers = Headers()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, size):
            assert size == 17
            return b"fixture"

    monkeypatch.setattr(updater, "urlopen", lambda request, timeout: Response())

    downloaded = updater.download_ieee_ma_l_csv(max_bytes=16)

    assert downloaded.content == b"fixture"
    assert downloaded.etag == '"etag"'
    assert downloaded.last_modified == "Wed, 02 Sep 2026 00:00:00 GMT"


def test_download_rejects_source_above_safety_limit(monkeypatch):
    class Response:
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, size):
            return b"x" * size

    monkeypatch.setattr(updater, "urlopen", lambda request, timeout: Response())

    with pytest.raises(updater.RegistryUpdateError, match="safety limit"):
        updater.download_ieee_ma_l_csv(max_bytes=8)


def test_cli_update_and_validate_work_offline(tmp_path, capsys):
    source = tmp_path / "ieee.csv"
    source.write_bytes(_source("MA-L,001132,Synology,Taipei"))
    registry = tmp_path / "registry.csv"
    metadata = tmp_path / "metadata.json"

    assert (
        updater.main(
            [
                "update",
                "--source-file",
                str(source),
                "--registry",
                str(registry),
                "--metadata",
                str(metadata),
                "--min-entries",
                "1",
                "--retrieved-at",
                "2026-09-02T08:00:00Z",
            ]
        )
        == 0
    )
    assert "1 IEEE MA-L assignments" in capsys.readouterr().out

    assert (
        updater.main(
            [
                "validate",
                "--registry",
                str(registry),
                "--metadata",
                str(metadata),
                "--min-entries",
                "1",
            ]
        )
        == 0
    )
    assert "OUI registry valid: 1" in capsys.readouterr().out
