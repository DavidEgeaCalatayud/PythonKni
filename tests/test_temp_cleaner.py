from pathlib import Path

import tools.temp_cleaner_tool as cleaner
from tools.temp_cleaner_tool import delete_folder_contents


def test_delete_folder_contents_returns_structured_result_for_missing_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(cleaner.platform, "system", lambda: "Windows")
    monkeypatch.setenv("TEMP", str(tmp_path / "missing"))

    result = delete_folder_contents(tmp_path / "missing")

    assert result.deleted == 0
    assert result.failed == 0
    assert result.errors == []


def test_delete_folder_contents_counts_deleted_files(tmp_path, monkeypatch):
    monkeypatch.setattr(cleaner.platform, "system", lambda: "Windows")

    folder = tmp_path / "temp"
    nested = folder / "nested"
    nested.mkdir(parents=True)
    (folder / "a.txt").write_text("a", encoding="utf-8")
    (nested / "b.txt").write_text("b", encoding="utf-8")
    monkeypatch.setenv("TEMP", str(folder))

    result = delete_folder_contents(folder)

    assert result.deleted == 3
    assert result.failed == 0


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

    result = delete_folder_contents(local)

    assert result.deleted == 0
    assert sentinel.read_text(encoding="utf-8") == "important"


def test_clean_logs_does_not_target_var_log_on_non_windows(monkeypatch):
    monkeypatch.setattr(cleaner.platform, "system", lambda: "Linux")

    assert cleaner.get_log_targets() == []


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
