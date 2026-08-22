import hashlib
import json
import threading
from pathlib import Path

import pytest

from tools import duplicate_tool as duplicate


def normalized_paths(paths):
    return {Path(path).as_posix() for path in paths}


def test_hash_file_returns_none_for_missing_file(tmp_path):
    assert duplicate.hash_file(tmp_path / "missing.txt") is None


def test_hash_file_uses_sha256_and_is_stable_for_same_content(tmp_path):
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    content = b"same content"
    first.write_bytes(content)
    second.write_bytes(content)

    expected = hashlib.sha256(content).hexdigest()
    assert duplicate.hash_file(first) == expected
    assert duplicate.hash_file(second) == expected
    assert len(expected) == 64


def test_find_duplicates_groups_files_with_same_content(tmp_path):
    original = tmp_path / "a.txt"
    copy = tmp_path / "b.txt"
    unique = tmp_path / "c.txt"

    original.write_text("repeat", encoding="utf-8")
    copy.write_text("repeat", encoding="utf-8")
    unique.write_text("different", encoding="utf-8")

    duplicates = duplicate.find_duplicates(tmp_path)

    assert len(duplicates) == 1
    duplicate_paths = next(iter(duplicates.values()))
    assert normalized_paths(duplicate_paths) == {original.as_posix(), copy.as_posix()}


def test_unique_sizes_never_reach_quick_or_secure_hash(monkeypatch, tmp_path):
    unique = tmp_path / "unique.bin"
    first = tmp_path / "first.bin"
    second = tmp_path / "second.bin"
    unique.write_bytes(b"unique-size")
    first.write_bytes(b"same")
    second.write_bytes(b"same")

    original_quick_hash = duplicate.quick_hash_file
    original_secure_hash = duplicate.hash_file
    quick_calls = []
    secure_calls = []

    def quick_spy(path, *args, **kwargs):
        quick_calls.append(Path(path).name)
        return original_quick_hash(path, *args, **kwargs)

    def secure_spy(path, *args, **kwargs):
        secure_calls.append(Path(path).name)
        return original_secure_hash(path, *args, **kwargs)

    monkeypatch.setattr(duplicate, "quick_hash_file", quick_spy)
    monkeypatch.setattr(duplicate, "hash_file", secure_spy)

    duplicate.find_duplicates(tmp_path)

    assert "unique.bin" not in quick_calls
    assert "unique.bin" not in secure_calls
    assert set(quick_calls) == {"first.bin", "second.bin"}
    assert set(secure_calls) == {"first.bin", "second.bin"}


def test_final_byte_comparison_splits_forced_hash_collision(monkeypatch, tmp_path):
    first = tmp_path / "a.bin"
    copy = tmp_path / "b.bin"
    collision = tmp_path / "c.bin"
    first.write_bytes(b"AAAA")
    copy.write_bytes(b"AAAA")
    collision.write_bytes(b"BBBB")

    monkeypatch.setattr(duplicate, "quick_hash_file", lambda _path, **_kwargs: "forced-quick")
    monkeypatch.setattr(duplicate, "hash_file", lambda _path, **_kwargs: "forced-secure")

    duplicates = duplicate.find_duplicates(tmp_path)

    assert list(duplicates) == ["forced-secure"]
    assert normalized_paths(duplicates["forced-secure"]) == {
        first.as_posix(),
        copy.as_posix(),
    }
    assert collision.as_posix() not in normalized_paths(duplicates["forced-secure"])


def test_duplicate_output_folder_is_automatically_excluded(tmp_path):
    original = tmp_path / "original.txt"
    target = tmp_path / duplicate.DUPLICATES_DIR_NAME
    target.mkdir()
    previously_moved = target / "old-copy.txt"
    original.write_text("same", encoding="utf-8")
    previously_moved.write_text("same", encoding="utf-8")

    assert duplicate.find_duplicates(tmp_path) == {}


def test_symlink_files_are_not_scanned(tmp_path):
    source = tmp_path / "source.txt"
    source.write_text("same", encoding="utf-8")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(source)
    except OSError:
        return

    assert duplicate.find_duplicates(tmp_path) == {}


def test_find_duplicates_honours_pre_cancelled_event(tmp_path):
    (tmp_path / "a.txt").write_text("same", encoding="utf-8")
    (tmp_path / "b.txt").write_text("same", encoding="utf-8")
    cancel_event = threading.Event()
    cancel_event.set()

    with pytest.raises(duplicate.DuplicateOperationCancelled):
        duplicate.find_duplicates(tmp_path, cancel_event=cancel_event)


def test_move_duplicates_rechecks_content_before_moving(tmp_path):
    original = tmp_path / "a.txt"
    stale_copy = tmp_path / "b.txt"
    original.write_text("same", encoding="utf-8")
    stale_copy.write_text("changed", encoding="utf-8")

    moved = duplicate.move_duplicates({"stale": [str(original), str(stale_copy)]}, tmp_path)

    assert moved == 0
    assert stale_copy.exists()
    target = tmp_path / duplicate.DUPLICATES_DIR_NAME
    manifests = list(target.glob(f"{duplicate.RESTORE_MANIFEST_PREFIX}_*.json"))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert manifest["status"] == "complete"
    assert manifest["moved_count"] == 0
    assert manifest["moves"] == []


def test_move_duplicates_creates_atomic_restoration_manifest(tmp_path):
    original = tmp_path / "a.txt"
    copy = tmp_path / "b.txt"
    original.write_text("duplicate data", encoding="utf-8")
    copy.write_text("duplicate data", encoding="utf-8")
    duplicates = duplicate.find_duplicates(tmp_path)

    moved = duplicate.move_duplicates(duplicates, tmp_path)

    assert moved == 1
    assert original.exists()
    assert not copy.exists()

    target = tmp_path / duplicate.DUPLICATES_DIR_NAME
    moved_copy = target / "b.txt"
    assert moved_copy.read_text(encoding="utf-8") == "duplicate data"
    assert not list(target.glob("*.tmp"))

    manifests = list(target.glob(f"{duplicate.RESTORE_MANIFEST_PREFIX}_*.json"))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert manifest["version"] == 1
    assert manifest["status"] == "complete"
    assert manifest["moved_count"] == 1
    assert len(manifest["moves"]) == 1

    entry = manifest["moves"][0]
    assert entry["status"] == "moved"
    assert Path(entry["source"]) == copy.resolve()
    assert Path(entry["destination"]) == moved_copy.resolve()
    assert Path(entry["retained_original"]) == original.resolve()
    assert entry["sha256"] == duplicate.hash_file(original)
    assert entry["size"] == original.stat().st_size
    assert "moved_at" in entry


def test_move_duplicates_uses_unique_destination_names(tmp_path):
    original = tmp_path / "a.txt"
    nested = tmp_path / "nested"
    nested.mkdir()
    copy = nested / "a.txt"
    original.write_text("same", encoding="utf-8")
    copy.write_text("same", encoding="utf-8")

    target = tmp_path / duplicate.DUPLICATES_DIR_NAME
    target.mkdir()
    (target / "a.txt").write_text("existing", encoding="utf-8")

    moved = duplicate.move_duplicates(duplicate.find_duplicates(tmp_path), tmp_path)

    assert moved == 1
    assert (target / "a.txt").read_text(encoding="utf-8") == "existing"
    assert (target / "a_1.txt").read_text(encoding="utf-8") == "same"


def test_cancelled_move_marks_manifest_and_keeps_unmoved_files(tmp_path):
    original = tmp_path / "a.txt"
    copy = tmp_path / "b.txt"
    original.write_text("same", encoding="utf-8")
    copy.write_text("same", encoding="utf-8")
    duplicates = duplicate.find_duplicates(tmp_path)
    cancel_event = threading.Event()
    cancel_event.set()

    with pytest.raises(duplicate.DuplicateOperationCancelled) as exc_info:
        duplicate.move_duplicates(duplicates, tmp_path, cancel_event=cancel_event)

    assert exc_info.value.moved_count == 0
    assert original.exists()
    assert copy.exists()

    target = tmp_path / duplicate.DUPLICATES_DIR_NAME
    manifests = list(target.glob(f"{duplicate.RESTORE_MANIFEST_PREFIX}_*.json"))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert manifest["status"] == "cancelled"
    assert manifest["moved_count"] == 0
    assert "cancelled_at" in manifest
