import os
from pathlib import Path

import pytest

import tools.temp_cleaner_tool as cleaner
from tools.temp_cleaner_tool import delete_folder_contents


def test_delete_folder_contents_returns_structured_result_for_missing_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(cleaner.platform, "system", lambda: "Windows")
    monkeypatch.setenv("TEMP", str(tmp_path / "temp"))

    result = delete_folder_contents(tmp_path / "missing")

    assert result.deleted == 0
    assert result.failed == 0
    assert result.errors == []


def test_delete_folder_contents_counts_deleted_files_for_exact_temp_target(tmp_path, monkeypatch):
    folder = tmp_path / "temp"
    nested = folder / "nested"
    nested.mkdir(parents=True)
    (folder / "a.txt").write_text("a", encoding="utf-8")
    (nested / "b.txt").write_text("b", encoding="utf-8")

    monkeypatch.setattr(cleaner.platform, "system", lambda: "Windows")
    monkeypatch.setenv("TEMP", str(folder))
    monkeypatch.delenv("TMP", raising=False)

    result = delete_folder_contents(folder)

    assert result.deleted == 3
    assert result.failed == 0


def test_delete_folder_contents_rejects_arbitrary_child_of_temp(tmp_path, monkeypatch):
    temp_root = tmp_path / "temp"
    arbitrary = temp_root / "do-not-delete"
    arbitrary.mkdir(parents=True)
    marker = arbitrary / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    monkeypatch.setattr(cleaner.platform, "system", lambda: "Windows")
    monkeypatch.setenv("TEMP", str(temp_root))
    monkeypatch.delenv("TMP", raising=False)

    result = delete_folder_contents(arbitrary)

    assert result.deleted == 0
    assert marker.exists()


def test_localappdata_is_not_generic_delete_authorization(tmp_path, monkeypatch):
    local = tmp_path / "LocalAppData"
    arbitrary = local / "SomeApplication" / "Data"
    arbitrary.mkdir(parents=True)
    marker = arbitrary / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    monkeypatch.setattr(cleaner.platform, "system", lambda: "Windows")
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.delenv("TEMP", raising=False)
    monkeypatch.delenv("TMP", raising=False)

    result = delete_folder_contents(arbitrary)

    assert result.deleted == 0
    assert marker.exists()


def test_known_browser_cache_is_an_exact_allowed_target(tmp_path, monkeypatch):
    local = tmp_path / "LocalAppData"
    cache = local / "Google" / "Chrome" / "User Data" / "Default" / "Cache"
    cache.mkdir(parents=True)
    marker = cache / "cache.bin"
    marker.write_bytes(b"cache")

    monkeypatch.setattr(cleaner.platform, "system", lambda: "Windows")
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.delenv("TEMP", raising=False)
    monkeypatch.delenv("TMP", raising=False)

    result = delete_folder_contents(cache)

    assert result.deleted == 1
    assert not marker.exists()


def test_clean_logs_does_not_target_var_log_on_non_windows(monkeypatch):
    monkeypatch.setattr(cleaner.platform, "system", lambda: "Linux")

    assert cleaner.get_log_targets() == []


def test_empty_xdg_cache_home_never_uses_current_directory(tmp_path, monkeypatch):
    home = tmp_path / "home"
    work = tmp_path / "work"
    work.mkdir()
    marker = work / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    monkeypatch.setattr(cleaner.platform, "system", lambda: "Linux")
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("XDG_CACHE_HOME", "")
    monkeypatch.chdir(work)

    result = delete_folder_contents(work)

    assert result.deleted == 0
    assert marker.exists()
    assert cleaner._cache_home_for_current_platform() == home / ".cache"


def test_relative_xdg_cache_home_is_ignored(tmp_path, monkeypatch):
    home = tmp_path / "home"

    monkeypatch.setattr(cleaner.platform, "system", lambda: "Linux")
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("XDG_CACHE_HOME", "relative-cache")

    assert cleaner._cache_home_for_current_platform() == home / ".cache"


def test_firefox_cache_targets_only_cache2_on_linux(tmp_path, monkeypatch):
    cache_home = tmp_path / ".cache"
    firefox_profile = cache_home / "mozilla" / "firefox" / "abc.default"
    cache2 = firefox_profile / "cache2"
    cache2.mkdir(parents=True)

    monkeypatch.setattr(cleaner.platform, "system", lambda: "Linux")
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    targets = cleaner.get_browser_cache_targets()

    assert cleaner.CleanTarget("Firefox Cache", cache2.resolve()) in targets
    assert all(target.path != firefox_profile.resolve() for target in targets)


def test_directory_symlink_is_removed_without_touching_external_target(tmp_path, monkeypatch):
    folder = tmp_path / "temp"
    outside = tmp_path / "outside"
    folder.mkdir()
    outside.mkdir()
    marker = outside / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    link = folder / "outside-link"

    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("El sistema no permite crear symlinks en este entorno")

    monkeypatch.setattr(cleaner.platform, "system", lambda: "Windows")
    monkeypatch.setenv("TEMP", str(folder))
    monkeypatch.delenv("TMP", raising=False)

    result = delete_folder_contents(folder)

    assert result.failed == 0
    assert marker.exists()
    assert not os.path.lexists(link)


def test_directory_symlink_is_safe_in_path_walk_fallback(tmp_path, monkeypatch):
    folder = tmp_path / "temp"
    outside = tmp_path / "outside"
    folder.mkdir()
    outside.mkdir()
    marker = outside / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    link = folder / "outside-link"

    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("El sistema no permite crear symlinks en este entorno")

    monkeypatch.setattr(cleaner.platform, "system", lambda: "Windows")
    monkeypatch.setattr(cleaner, "_supports_fd_walk", lambda: False)
    monkeypatch.setenv("TEMP", str(folder))
    monkeypatch.delenv("TMP", raising=False)

    result = delete_folder_contents(folder)

    assert result.failed == 0
    assert marker.exists()
    assert not os.path.lexists(link)


def test_file_symlink_is_removed_without_touching_external_file(tmp_path, monkeypatch):
    folder = tmp_path / "temp"
    folder.mkdir()
    outside_file = tmp_path / "keep.txt"
    outside_file.write_text("keep", encoding="utf-8")
    link = folder / "outside-file-link"

    try:
        link.symlink_to(outside_file)
    except OSError:
        pytest.skip("El sistema no permite crear symlinks en este entorno")

    monkeypatch.setattr(cleaner.platform, "system", lambda: "Windows")
    monkeypatch.setenv("TEMP", str(folder))
    monkeypatch.delenv("TMP", raising=False)

    result = delete_folder_contents(folder)

    assert result.failed == 0
    assert outside_file.read_text(encoding="utf-8") == "keep"
    assert not os.path.lexists(link)


def test_preview_uses_lstat_for_file_symlinks(tmp_path, monkeypatch):
    folder = tmp_path / "temp"
    folder.mkdir()
    outside_file = tmp_path / "large.bin"
    outside_file.write_bytes(b"x" * 10000)
    link = folder / "outside-file-link"

    try:
        link.symlink_to(outside_file)
    except OSError:
        pytest.skip("El sistema no permite crear symlinks en este entorno")

    monkeypatch.setattr(cleaner.platform, "system", lambda: "Windows")
    monkeypatch.setenv("TEMP", str(folder))
    monkeypatch.delenv("TMP", raising=False)

    preview = cleaner.build_preview(cleaner.get_temp_targets())

    assert preview.items == 1
    assert preview.bytes == link.lstat().st_size
    assert preview.bytes != outside_file.stat().st_size


def test_fd_walk_rejects_root_replaced_by_symlink_before_open(tmp_path, monkeypatch):
    if not cleaner._supports_fd_walk():
        pytest.skip("Este entorno no dispone de fwalk + dir_fd seguros")

    folder = tmp_path / "temp"
    original = tmp_path / "original-temp"
    outside = tmp_path / "outside"
    folder.mkdir()
    outside.mkdir()
    original_marker = folder / "original.txt"
    original_marker.write_text("original", encoding="utf-8")
    outside_marker = outside / "outside.txt"
    outside_marker.write_text("outside", encoding="utf-8")

    monkeypatch.setattr(cleaner.platform, "system", lambda: "Windows")
    monkeypatch.setenv("TEMP", str(folder))
    monkeypatch.delenv("TMP", raising=False)

    real_open = cleaner.os.open
    raced = False

    def racing_open(path, flags, *args, **kwargs):
        nonlocal raced
        if not raced and Path(path) == folder:
            raced = True
            folder.rename(original)
            folder.symlink_to(outside, target_is_directory=True)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(cleaner.os, "open", racing_open)

    result = delete_folder_contents(folder)

    assert result.deleted == 0
    assert result.failed >= 1
    assert (original / "original.txt").exists()
    assert outside_marker.exists()
