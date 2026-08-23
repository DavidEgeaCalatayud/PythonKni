import os
import subprocess
from pathlib import Path

import pytest

import pythonkni.temp_cleaner.service as cleaner
from pythonkni.temp_cleaner.models import CleanTarget


def _make_directory_link(link: Path, target: Path) -> None:
    if os.name == "nt":
        subprocess.run(
            ["cmd.exe", "/c", "mklink", "/J", str(link), str(target)],
            check=True,
            capture_output=True,
            text=True,
        )
    else:
        link.symlink_to(target, target_is_directory=True)


def _remove_directory_link(link: Path) -> None:
    if not os.path.lexists(link):
        return
    if os.name == "nt":
        link.rmdir()
    else:
        link.unlink()


def test_delete_folder_contents_returns_structured_result_for_missing_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(cleaner.platform, "system", lambda: "Windows")
    monkeypatch.setenv("TEMP", str(tmp_path / "missing"))

    result = cleaner.delete_folder_contents(tmp_path / "missing")

    assert result.deleted == 0
    assert result.failed == 0
    assert result.errors == []


def test_delete_folder_contents_counts_deleted_files(tmp_path, monkeypatch):
    folder = tmp_path / "temp"
    nested = folder / "nested"
    nested.mkdir(parents=True)
    (folder / "a.txt").write_text("a", encoding="utf-8")
    (nested / "b.txt").write_text("b", encoding="utf-8")

    monkeypatch.setattr(cleaner.platform, "system", lambda: "Windows")
    monkeypatch.setenv("TEMP", str(folder))
    monkeypatch.delenv("TMP", raising=False)

    result = cleaner.delete_folder_contents(folder)

    assert result.deleted == 3
    assert result.failed == 0
    assert list(folder.iterdir()) == []


def test_windows_general_containers_are_never_exact_clean_targets(tmp_path, monkeypatch):
    home = tmp_path / "user"
    local = home / "AppData" / "Local"
    temp = local / "Temp"
    windows = tmp_path / "Windows"
    windows_temp = windows / "Temp"
    for folder in (home, local, temp, windows, windows_temp):
        folder.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(cleaner.platform, "system", lambda: "Windows")
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("TEMP", str(temp))
    monkeypatch.setenv("TMP", str(temp))
    monkeypatch.setenv("SystemRoot", str(windows))

    assert cleaner._is_safe_clean_root(temp)
    assert cleaner._is_safe_clean_root(windows_temp)
    assert not cleaner._is_safe_clean_root(local)
    assert not cleaner._is_safe_clean_root(temp.parent)
    assert not cleaner._is_safe_clean_root(home)
    assert not cleaner._is_safe_clean_root(windows)


def test_arbitrary_localappdata_descendant_is_not_cleanable(tmp_path, monkeypatch):
    home = tmp_path / "user"
    local = home / "AppData" / "Local"
    temp = local / "Temp"
    arbitrary = local / "ImportantAppData"
    for folder in (temp, arbitrary):
        folder.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(cleaner.platform, "system", lambda: "Windows")
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("TEMP", str(temp))
    monkeypatch.setenv("TMP", str(temp))

    assert not cleaner._is_safe_clean_root(arbitrary)


def test_env_temp_pointing_to_general_root_is_rejected(tmp_path, monkeypatch):
    home = tmp_path / "user"
    local = home / "AppData" / "Local"
    local.mkdir(parents=True)

    monkeypatch.setattr(cleaner.platform, "system", lambda: "Windows")
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("TEMP", str(local))
    monkeypatch.setenv("TMP", str(home))

    assert cleaner.get_temp_targets() == []
    assert not cleaner._is_safe_clean_root(local)
    assert not cleaner._is_safe_clean_root(home)


def test_delete_folder_contents_refuses_localappdata_root(tmp_path, monkeypatch):
    home = tmp_path / "user"
    local = home / "AppData" / "Local"
    local.mkdir(parents=True)
    sentinel = local / "keep.txt"
    sentinel.write_text("important", encoding="utf-8")

    monkeypatch.setattr(cleaner.platform, "system", lambda: "Windows")
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("TEMP", str(local / "Temp"))

    result = cleaner.delete_folder_contents(local)

    assert result.deleted == 0
    assert sentinel.read_text(encoding="utf-8") == "important"


def test_empty_or_relative_temp_environment_paths_are_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(cleaner.platform, "system", lambda: "Windows")
    monkeypatch.setenv("TEMP", "")
    monkeypatch.setenv("TMP", "relative-temp")
    monkeypatch.chdir(tmp_path)

    assert cleaner.get_temp_targets() == []


def test_clean_logs_does_not_target_var_log_on_non_windows(monkeypatch):
    monkeypatch.setattr(cleaner.platform, "system", lambda: "Linux")

    assert cleaner.get_log_targets() == []


def test_empty_xdg_cache_home_falls_back_to_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setattr(cleaner.platform, "system", lambda: "Linux")
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("XDG_CACHE_HOME", "")

    assert cleaner._browser_cache_root() == home / ".cache"


def test_relative_xdg_cache_home_falls_back_to_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setattr(cleaner.platform, "system", lambda: "Linux")
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("XDG_CACHE_HOME", "relative-cache")

    assert cleaner._browser_cache_root() == home / ".cache"


def test_firefox_cache_targets_only_cache2_on_linux(tmp_path, monkeypatch):
    cache_home = tmp_path / ".cache"
    firefox_profile = cache_home / "mozilla" / "firefox" / "abc.default"
    cache2 = firefox_profile / "cache2"
    cache2.mkdir(parents=True)

    monkeypatch.setattr(cleaner.platform, "system", lambda: "Linux")
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    targets = cleaner.get_browser_cache_targets()

    assert CleanTarget("Firefox Cache", cache2.resolve()) in targets
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
        pytest.skip("El sistema no permite crear symlinks de directorio")

    monkeypatch.setattr(cleaner.platform, "system", lambda: "Windows")
    monkeypatch.setenv("TEMP", str(folder))
    monkeypatch.delenv("TMP", raising=False)

    result = cleaner.delete_folder_contents(folder)

    assert result.failed == 0
    assert marker.read_text(encoding="utf-8") == "keep"
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
        pytest.skip("El sistema no permite crear symlinks de archivo")

    monkeypatch.setattr(cleaner.platform, "system", lambda: "Windows")
    monkeypatch.setenv("TEMP", str(folder))
    monkeypatch.delenv("TMP", raising=False)

    result = cleaner.delete_folder_contents(folder)

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
        pytest.skip("El sistema no permite crear symlinks de archivo")

    monkeypatch.setattr(cleaner.platform, "system", lambda: "Windows")
    monkeypatch.setenv("TEMP", str(folder))
    monkeypatch.delenv("TMP", raising=False)

    preview = cleaner.build_preview(cleaner.get_temp_targets())

    assert preview.items == 1
    assert preview.bytes == link.lstat().st_size
    assert preview.bytes != outside_file.stat().st_size


@pytest.mark.skipif(os.name != "nt", reason="Los junctions son específicos de Windows")
def test_windows_junction_is_removed_without_touching_external_target(tmp_path, monkeypatch):
    folder = tmp_path / "temp"
    outside = tmp_path / "outside"
    folder.mkdir()
    outside.mkdir()
    marker = outside / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    junction = folder / "outside-junction"
    _make_directory_link(junction, outside)

    monkeypatch.setattr(cleaner.platform, "system", lambda: "Windows")
    monkeypatch.setenv("TEMP", str(folder))
    monkeypatch.delenv("TMP", raising=False)

    result = cleaner.delete_folder_contents(folder)

    assert result.failed == 0
    assert marker.read_text(encoding="utf-8") == "keep"
    assert not os.path.lexists(junction)


def test_target_root_symlink_is_rejected(tmp_path, monkeypatch):
    real_temp = tmp_path / "real-temp"
    real_temp.mkdir()
    marker = real_temp / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    link = tmp_path / "temp-link"

    try:
        link.symlink_to(real_temp, target_is_directory=True)
    except OSError:
        pytest.skip("El sistema no permite crear symlinks de directorio")

    monkeypatch.setattr(cleaner.platform, "system", lambda: "Windows")
    monkeypatch.setenv("TEMP", str(link))
    monkeypatch.delenv("TMP", raising=False)

    result = cleaner.delete_folder_contents(link)

    assert result.deleted == 0
    assert marker.read_text(encoding="utf-8") == "keep"
    assert cleaner.get_temp_targets() == []


def test_root_replacement_during_scandir_fails_closed(tmp_path, monkeypatch):
    folder = tmp_path / "temp"
    original = tmp_path / "original-temp"
    outside = tmp_path / "outside"
    folder.mkdir()
    outside.mkdir()
    (folder / "original.txt").write_text("original", encoding="utf-8")
    outside_marker = outside / "outside.txt"
    outside_marker.write_text("outside", encoding="utf-8")

    monkeypatch.setattr(cleaner.platform, "system", lambda: "Windows")
    monkeypatch.setenv("TEMP", str(folder))
    monkeypatch.delenv("TMP", raising=False)

    real_scandir = cleaner.os.scandir
    raced = False

    def racing_scandir(path):
        nonlocal raced
        if not raced and Path(path) == folder:
            raced = True
            folder.rename(original)
            _make_directory_link(folder, outside)
        return real_scandir(path)

    monkeypatch.setattr(cleaner.os, "scandir", racing_scandir)

    try:
        result = cleaner.delete_folder_contents(folder)

        assert result.deleted == 0
        assert result.failed >= 1
        assert (original / "original.txt").read_text(encoding="utf-8") == "original"
        assert outside_marker.read_text(encoding="utf-8") == "outside"
    finally:
        _remove_directory_link(folder)


def test_subdirectory_replacement_is_not_recursively_deleted(tmp_path, monkeypatch):
    folder = tmp_path / "temp"
    nested = folder / "nested"
    replacement = tmp_path / "replacement"
    nested.mkdir(parents=True)
    replacement.mkdir()
    (nested / "old.txt").write_text("old", encoding="utf-8")
    replacement_marker = replacement / "keep.txt"
    replacement_marker.write_text("keep", encoding="utf-8")

    monkeypatch.setattr(cleaner.platform, "system", lambda: "Windows")
    monkeypatch.setenv("TEMP", str(folder))
    monkeypatch.delenv("TMP", raising=False)

    real_scandir = cleaner.os.scandir
    swapped = False

    def racing_scandir(path):
        nonlocal swapped
        path = Path(path)
        if path == nested and not swapped:
            swapped = True
            old_nested = folder / "old-nested"
            nested.rename(old_nested)
            _make_directory_link(nested, replacement)
        return real_scandir(path)

    monkeypatch.setattr(cleaner.os, "scandir", racing_scandir)

    try:
        result = cleaner.delete_folder_contents(folder)

        assert result.failed >= 1
        assert replacement_marker.read_text(encoding="utf-8") == "keep"
    finally:
        if os.path.lexists(nested):
            _remove_directory_link(nested)
