import os
from pathlib import Path

from pythonkni.disk_analyzer import service as disk_service


class _ScandirContext:
    def __init__(self, entries):
        self.entries = entries

    def __enter__(self):
        return iter(self.entries)

    def __exit__(self, exc_type, exc, tb):
        del exc_type, exc, tb
        return False


def test_format_bytes_reaches_tb_and_directory_size_skips_symlinks(tmp_path):
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "payload.bin").write_bytes(b"x" * 12)
    link = tmp_path / "linked"
    try:
        link.symlink_to(nested, target_is_directory=True)
    except OSError:
        link = None

    assert disk_service.format_bytes(1024**5) == "1024.00 TB"
    assert disk_service.directory_size(tmp_path) == 12
    if link is not None:
        assert link.is_symlink()


def test_directory_size_ignores_unreadable_file(monkeypatch, tmp_path):
    file_path = tmp_path / "blocked.bin"
    file_path.write_bytes(b"payload")
    original_stat = Path.stat

    def fake_stat(path, *args, **kwargs):
        if path == file_path:
            raise OSError("blocked")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", fake_stat)

    assert disk_service.directory_size(tmp_path) == 0


def test_analyze_directory_skips_symlink_special_and_unreadable_entries(monkeypatch, tmp_path):
    good = tmp_path / "good.bin"
    good.write_bytes(b"1234")
    link = tmp_path / "link.bin"
    try:
        link.symlink_to(good)
    except OSError:
        link = None

    class BrokenEntry:
        name = "broken"
        path = str(tmp_path / "broken")

        def is_symlink(self):
            return False

        def is_dir(self, follow_symlinks=False):
            del follow_symlinks
            raise PermissionError("denied")

    class SpecialEntry:
        name = "special"
        path = str(tmp_path / "special")

        def is_symlink(self):
            return False

        def is_dir(self, follow_symlinks=False):
            del follow_symlinks
            return False

        def is_file(self, follow_symlinks=False):
            del follow_symlinks
            return False

    real_entries = list(os.scandir(tmp_path))
    monkeypatch.setattr(
        disk_service.os,
        "scandir",
        lambda _path: _ScandirContext([*real_entries, BrokenEntry(), SpecialEntry()]),
    )

    items = disk_service.analyze_directory(tmp_path)

    assert [item.name for item in items] == ["good.bin"]
    if link is not None:
        assert all(item.name != "link.bin" for item in items)
