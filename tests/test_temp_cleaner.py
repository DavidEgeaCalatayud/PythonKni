from pathlib import Path

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
