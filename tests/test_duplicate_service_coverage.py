import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from pythonkni.duplicate import service as duplicate_service


def test_helpers_cover_unreadable_and_identity_fallback(monkeypatch, tmp_path):
    missing = tmp_path / "missing.bin"
    assert duplicate_service._physical_identity(missing) is None

    fake_stat = SimpleNamespace(st_ino=0, st_dev=1)
    monkeypatch.setattr(Path, "stat", lambda _path: fake_stat)
    assert duplicate_service._physical_identity(tmp_path / "x") is None

    monkeypatch.setattr(
        duplicate_service.os.path,
        "samefile",
        lambda _first, _second: (_ for _ in ()).throw(ValueError("bad path")),
    )
    assert not duplicate_service._same_physical_file("a", "b")


def test_quick_hash_and_files_equal_error_paths(tmp_path):
    missing = tmp_path / "missing.bin"
    assert duplicate_service.quick_hash_file(missing) is None
    assert not duplicate_service.files_equal(missing, missing)

    first = tmp_path / "first.bin"
    second = tmp_path / "second.bin"
    first.write_bytes(b"aaaa")
    second.write_bytes(b"bbb")
    assert not duplicate_service.files_equal(first, second)

    second.write_bytes(b"aaab")
    assert not duplicate_service.files_equal(first, second)


def test_quick_hash_honours_cancel_event(tmp_path):
    path = tmp_path / "payload.bin"
    path.write_bytes(b"payload")
    event = threading.Event()
    event.set()

    with pytest.raises(duplicate_service.DuplicateOperationCancelled):
        duplicate_service.quick_hash_file(path, cancel_event=event)


def test_find_ignores_unhashable_candidates(monkeypatch, tmp_path):
    first = tmp_path / "a.bin"
    second = tmp_path / "b.bin"
    first.write_bytes(b"same")
    second.write_bytes(b"same")

    monkeypatch.setattr(duplicate_service, "quick_hash_file", lambda *_args, **_kwargs: None)
    assert duplicate_service.find_duplicates(tmp_path) == {}

    monkeypatch.setattr(duplicate_service, "quick_hash_file", lambda *_args, **_kwargs: "quick")
    monkeypatch.setattr(duplicate_service, "hash_file", lambda *_args, **_kwargs: None)
    assert duplicate_service.find_duplicates(tmp_path) == {}


def test_verified_groups_support_multiple_collision_groups(monkeypatch, tmp_path):
    paths = [tmp_path / name for name in ("a", "b", "c", "d")]
    for path in paths:
        path.write_bytes(b"x")

    monkeypatch.setattr(duplicate_service, "_same_physical_file", lambda *_args: False)

    def fake_equal(first, second, cancel_event=None):
        del cancel_event
        return {Path(first).name, Path(second).name} in ({"a", "b"}, {"c", "d"})

    monkeypatch.setattr(duplicate_service, "files_equal", fake_equal)
    groups = duplicate_service._verified_byte_groups(paths)

    assert [[item.name for item in group] for group in groups] == [["a", "b"], ["c", "d"]]


def test_manifest_paths_and_inside_checks(monkeypatch, tmp_path):
    class FakeDateTime:
        @classmethod
        def now(cls, _tz):
            return SimpleNamespace(strftime=lambda _fmt: "20260831T100000Z")

    monkeypatch.setattr(duplicate_service, "datetime", FakeDateTime)
    first = tmp_path / f"{duplicate_service.RESTORE_MANIFEST_PREFIX}_20260831T100000Z.json"
    first.write_text("{}", encoding="utf-8")

    candidate = duplicate_service._new_manifest_path(tmp_path)

    assert candidate.name.endswith("_1.json")
    assert duplicate_service._is_inside(tmp_path / "child", tmp_path)
    assert not duplicate_service._is_inside(tmp_path.parent / "outside", tmp_path)


def test_move_records_failed_move_and_completes(monkeypatch, tmp_path):
    original = tmp_path / "a.bin"
    copy = tmp_path / "b.bin"
    original.write_bytes(b"same")
    copy.write_bytes(b"same")
    duplicates = duplicate_service.find_duplicates(tmp_path)

    monkeypatch.setattr(
        duplicate_service.shutil,
        "move",
        lambda *_args: (_ for _ in ()).throw(OSError("move failed")),
    )

    moved = duplicate_service.move_duplicates(duplicates, tmp_path)

    assert moved == 0
    target = tmp_path / duplicate_service.DUPLICATES_DIR_NAME
    manifest_path = next(target.glob(f"{duplicate_service.RESTORE_MANIFEST_PREFIX}_*.json"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "complete"
    assert manifest["moves"][0]["status"] == "failed"
    assert manifest["moves"][0]["error"] == "move failed"
