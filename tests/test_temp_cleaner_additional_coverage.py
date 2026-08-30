from pathlib import Path

import pytest

from pythonkni.temp_cleaner import service as cleaner
from pythonkni.temp_cleaner.models import CleanPreview, CleanResult, CleanTarget


def test_env_absolute_path_handles_missing_blank_relative_and_absolute(monkeypatch, tmp_path):
    monkeypatch.delenv("PYTHONKNI_TEMP_TEST", raising=False)
    assert cleaner._env_absolute_path("PYTHONKNI_TEMP_TEST") is None

    monkeypatch.setenv("PYTHONKNI_TEMP_TEST", "   ")
    assert cleaner._env_absolute_path("PYTHONKNI_TEMP_TEST") is None

    monkeypatch.setenv("PYTHONKNI_TEMP_TEST", "relative/path")
    assert cleaner._env_absolute_path("PYTHONKNI_TEMP_TEST") is None

    monkeypatch.setenv("PYTHONKNI_TEMP_TEST", str(tmp_path))
    assert cleaner._env_absolute_path("PYTHONKNI_TEMP_TEST") == tmp_path


def test_link_helpers_detect_symlink_and_handle_lstat_failure(tmp_path):
    target = tmp_path / "target.txt"
    target.write_text("x", encoding="utf-8")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("Symlinks unavailable")

    assert cleaner._is_link_or_reparse(link)

    missing = tmp_path / "missing"
    assert not cleaner._is_link_or_reparse(missing)


def test_path_chain_and_resolve_helpers_reject_relative_missing_and_files(tmp_path):
    assert not cleaner._path_chain_is_real(Path("relative/path"))
    assert cleaner._resolve_existing(tmp_path / "missing") is None
    assert cleaner._resolved_path(Path("relative/path")) is None

    file_path = tmp_path / "file.txt"
    file_path.write_text("x", encoding="utf-8")
    assert cleaner._resolve_existing(file_path) is None


def test_temp_candidates_switch_by_platform(monkeypatch, tmp_path):
    monkeypatch.setattr(cleaner.platform, "system", lambda: "Linux")
    assert cleaner._temp_candidates() == []

    temp = tmp_path / "temp"
    other = tmp_path / "tmp"
    monkeypatch.setattr(cleaner.platform, "system", lambda: "Windows")
    monkeypatch.setenv("TEMP", str(temp))
    monkeypatch.setenv("TMP", str(other))

    assert cleaner._temp_candidates() == [
        CleanTarget("Temporal de usuario (TEMP)", temp),
        CleanTarget("Temporal de usuario (TMP)", other),
    ]


@pytest.mark.parametrize(
    ("system", "expected_suffix"),
    [
        ("Windows", ("AppData", "Local")),
        ("Darwin", ("Library", "Caches")),
        ("Linux", (".cache",)),
    ],
)
def test_browser_cache_root_platform_fallbacks(monkeypatch, tmp_path, system, expected_suffix):
    monkeypatch.setattr(cleaner.platform, "system", lambda: system)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)

    result = cleaner._browser_cache_root()

    assert result.parts[-len(expected_suffix) :] == expected_suffix


def test_browser_cache_candidates_platform_shapes(monkeypatch, tmp_path):
    monkeypatch.setattr(cleaner, "_browser_cache_root", lambda: tmp_path)
    monkeypatch.setattr(cleaner, "_resolve_existing", lambda _path: None)

    monkeypatch.setattr(cleaner.platform, "system", lambda: "Windows")
    windows = cleaner._browser_cache_candidates()
    assert [target.label for target in windows] == ["Chrome Cache", "Edge Cache"]

    monkeypatch.setattr(cleaner.platform, "system", lambda: "Darwin")
    darwin = cleaner._browser_cache_candidates()
    assert [target.label for target in darwin] == ["Chrome Cache", "Edge Cache"]

    monkeypatch.setattr(cleaner.platform, "system", lambda: "Linux")
    linux = cleaner._browser_cache_candidates()
    assert [target.label for target in linux] == ["Chrome Cache", "Edge Cache"]


def test_log_candidates_windows_default_and_non_windows(monkeypatch):
    monkeypatch.setattr(cleaner.platform, "system", lambda: "Linux")
    assert cleaner._log_candidates() == []

    monkeypatch.setattr(cleaner.platform, "system", lambda: "Windows")
    monkeypatch.delenv("SystemRoot", raising=False)
    assert cleaner._log_candidates() == [CleanTarget("Windows Temp", Path("C:/Windows") / "Temp")]


def test_unique_safe_targets_deduplicates_and_skips_unsafe(monkeypatch, tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    targets = [
        CleanTarget("One", first),
        CleanTarget("Duplicate", first),
        CleanTarget("Unsafe", second),
    ]

    monkeypatch.setattr(cleaner, "_resolve_existing", lambda path: path.resolve())
    monkeypatch.setattr(cleaner, "_is_safe_clean_root", lambda path: path == first)

    result = cleaner._unique_safe_targets(targets)

    assert result == [CleanTarget("One", first.resolve())]


def test_directory_identity_and_match_helpers(tmp_path):
    folder = tmp_path / "folder"
    folder.mkdir()
    identity = cleaner._directory_identity(folder)

    assert identity is not None
    assert cleaner._directory_matches(folder, identity)
    assert cleaner._directory_identity(tmp_path / "missing") is None

    file_path = tmp_path / "file.txt"
    file_path.write_text("x", encoding="utf-8")
    assert cleaner._directory_identity(file_path) is None


def test_record_failure_updates_result(tmp_path):
    result = CleanResult()
    path = tmp_path / "failed"

    cleaner._record_failure(result, path, "failure")

    assert result.failed == 1
    assert result.errors == [str(path)]


def test_delete_directory_contents_dry_run_counts_without_deleting(tmp_path):
    folder = tmp_path / "temp"
    nested = folder / "nested"
    nested.mkdir(parents=True)
    file_path = folder / "file.txt"
    nested_file = nested / "nested.txt"
    file_path.write_text("file", encoding="utf-8")
    nested_file.write_text("nested", encoding="utf-8")
    identity = cleaner._directory_identity(folder)
    result = CleanResult()

    completed = cleaner._delete_directory_contents(
        folder,
        identity,
        result,
        dry_run=True,
    )

    assert completed
    assert result.failed == 0
    assert result.deleted == 3
    assert file_path.exists()
    assert nested.exists()
    assert nested_file.exists()


def test_delete_directory_contents_rejects_identity_change(tmp_path):
    folder = tmp_path / "temp"
    folder.mkdir()
    result = CleanResult()

    assert not cleaner._delete_directory_contents(
        folder,
        (-1, -1),
        result,
        dry_run=False,
    )
    assert result.failed == 1


def test_preview_directory_counts_files_and_directories(tmp_path):
    folder = tmp_path / "temp"
    nested = folder / "nested"
    nested.mkdir(parents=True)
    (folder / "a.bin").write_bytes(b"abc")
    (nested / "b.bin").write_bytes(b"12345")
    preview = CleanPreview()
    identity = cleaner._directory_identity(folder)

    assert cleaner._preview_directory(folder, identity, preview)
    assert preview.items == 3
    assert preview.bytes == 8


def test_build_preview_skips_unresolved_and_identityless_targets(monkeypatch, tmp_path):
    target = CleanTarget("Target", tmp_path / "target")
    monkeypatch.setattr(cleaner, "_resolve_existing", lambda _path: None)

    assert cleaner.build_preview([target]) == CleanPreview()

    resolved = tmp_path / "target"
    resolved.mkdir()
    monkeypatch.setattr(cleaner, "_resolve_existing", lambda _path: resolved)
    monkeypatch.setattr(cleaner, "_is_safe_clean_root", lambda _path: True)
    monkeypatch.setattr(cleaner, "_directory_identity", lambda _path: None)

    assert cleaner.build_preview([target]) == CleanPreview()


def test_delete_folder_contents_early_exit_branches(monkeypatch, tmp_path):
    target = tmp_path / "target"
    monkeypatch.setattr(cleaner, "_is_safe_clean_root", lambda _path: False)
    assert cleaner.delete_folder_contents(target) == CleanResult()

    monkeypatch.setattr(cleaner, "_is_safe_clean_root", lambda _path: True)
    monkeypatch.setattr(cleaner, "_resolve_existing", lambda _path: None)
    assert cleaner.delete_folder_contents(target) == CleanResult()

    monkeypatch.setattr(cleaner, "_resolve_existing", lambda _path: target)
    monkeypatch.setattr(cleaner, "_directory_identity", lambda _path: None)
    assert cleaner.delete_folder_contents(target) == CleanResult()


def test_clean_targets_aggregates_results(monkeypatch, tmp_path):
    first = CleanTarget("One", tmp_path / "one")
    second = CleanTarget("Two", tmp_path / "two")

    def fake_delete(path, dry_run=False):
        assert dry_run
        if path == first.path:
            return CleanResult(deleted=2, failed=1, errors=["one"])
        return CleanResult(deleted=3, failed=0, errors=[])

    monkeypatch.setattr(cleaner, "delete_folder_contents", fake_delete)

    result = cleaner.clean_targets([first, second], dry_run=True)

    assert result.deleted == 5
    assert result.failed == 1
    assert result.errors == ["one"]


def test_clean_wrappers_delegate_to_expected_target_getters(monkeypatch):
    temp_target = CleanTarget("Temp", Path("/temp"))
    browser_target = CleanTarget("Browser", Path("/browser"))
    log_target = CleanTarget("Log", Path("/log"))
    calls = []

    monkeypatch.setattr(cleaner, "get_temp_targets", lambda: [temp_target])
    monkeypatch.setattr(cleaner, "get_browser_cache_targets", lambda: [browser_target])
    monkeypatch.setattr(cleaner, "get_log_targets", lambda: [log_target])
    monkeypatch.setattr(
        cleaner,
        "clean_targets",
        lambda targets, dry_run=False: calls.append((targets, dry_run)) or CleanResult(deleted=1),
    )

    assert cleaner.clean_temp(dry_run=True).deleted == 1
    assert cleaner.clean_browser_cache().deleted == 1
    assert cleaner.clean_logs(dry_run=True).deleted == 1
    assert calls == [
        ([temp_target], True),
        ([browser_target], False),
        ([log_target], True),
    ]
