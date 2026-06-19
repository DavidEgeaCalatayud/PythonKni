from pathlib import Path

import tools.temp_cleaner_tool as cleaner
from tools.temp_cleaner_tool import delete_folder_contents


def test_delete_folder_contents_returns_structured_result_for_missing_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(cleaner.platform, "system", lambda: "Windows")
    monkeypatch.setenv("TEMP", str(tmp_path))

    result = delete_folder_contents(tmp_path / "missing")

    assert result.deleted == 0
    assert result.failed == 0
    assert result.errors == []


def test_delete_folder_contents_counts_deleted_files(tmp_path, monkeypatch):
    monkeypatch.setattr(cleaner.platform, "system", lambda: "Windows")
    monkeypatch.setenv("TEMP", str(tmp_path))

    folder = tmp_path / "temp"
    nested = folder / "nested"
    nested.mkdir(parents=True)
    (folder / "a.txt").write_text("a", encoding="utf-8")
    (nested / "b.txt").write_text("b", encoding="utf-8")

    result = delete_folder_contents(folder)

    assert result.deleted == 3
    assert result.failed == 0


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
