import os
import subprocess
import threading
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest

from pythonkni.core.tasks import WorkerCancelled
from pythonkni.disk_analyzer import service as disk_service
from pythonkni.duplicate import service as duplicate_service
from pythonkni.process_manager import service as process_service
from pythonkni.wifi import service as wifi_service


class FakeCancelEvent:
    def __init__(self, cancelled=False):
        self.cancelled = cancelled
        self.wait_calls = []

    def wait(self, timeout):
        self.wait_calls.append(timeout)
        return self.cancelled

    def is_set(self):
        return self.cancelled


class FakeWorker:
    def __init__(self, cancelled=False):
        self.cancel_event = FakeCancelEvent(cancelled)
        self.progress = []

    def check_cancelled(self):
        if self.cancel_event.is_set():
            raise WorkerCancelled()

    def report_progress(self, value):
        self.progress.append(value)


class FakeProcess:
    def __init__(self, pid, name, cpu=0.0, memory=0.0, prime_error=None, sample_error=None):
        self.pid = pid
        self.info = {"pid": pid, "name": name}
        self.cpu = cpu
        self.memory = memory
        self.prime_error = prime_error
        self.sample_error = sample_error
        self.cpu_calls = 0

    def cpu_percent(self, interval=None):
        assert interval is None
        self.cpu_calls += 1
        if self.cpu_calls == 1 and self.prime_error is not None:
            raise self.prime_error
        if self.cpu_calls > 1 and self.sample_error is not None:
            raise self.sample_error
        return 0.0 if self.cpu_calls == 1 else self.cpu

    def memory_percent(self):
        return self.memory


def test_disk_format_bytes_reaches_tb_and_directory_size_skips_symlinks(tmp_path):
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


def test_disk_directory_size_ignores_unreadable_file(monkeypatch, tmp_path):
    file_path = tmp_path / "blocked.bin"
    file_path.write_bytes(b"payload")
    original_stat = Path.stat

    def fake_stat(path, *args, **kwargs):
        if path == file_path:
            raise OSError("blocked")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", fake_stat)

    assert disk_service.directory_size(tmp_path) == 0


def test_disk_analyze_skips_symlink_special_and_unreadable_entries(monkeypatch, tmp_path):
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


class _ScandirContext:
    def __init__(self, entries):
        self.entries = entries

    def __enter__(self):
        return iter(self.entries)

    def __exit__(self, exc_type, exc, tb):
        del exc_type, exc, tb
        return False


def test_wifi_profile_helpers_cover_empty_and_missing_values():
    assert wifi_service._parse_profiles("line without separator") == []
    root = ET.fromstring("<WLANProfile><name /></WLANProfile>")
    assert wifi_service._profile_name_from_xml(root) is None
    assert wifi_service._key_material_from_xml(root) is None

    namespaced = ET.fromstring(
        '<WLANProfile xmlns="urn:test"><name>Office</name><keyMaterial /></WLANProfile>'
    )
    assert wifi_service._profile_name_from_xml(namespaced) == "Office"
    assert wifi_service._key_material_from_xml(namespaced) is None


def test_wifi_export_requires_matching_xml(monkeypatch, tmp_path):
    def fake_run(args, timeout=wifi_service.NETSH_TIMEOUT_SECONDS):
        del timeout
        export_dir = Path(
            next(value.removeprefix("folder=") for value in args if value.startswith("folder="))
        )
        (export_dir / "wrong.xml").write_text(
            "<WLANProfile><name>Other</name></WLANProfile>", encoding="utf-8"
        )
        return ""

    monkeypatch.setattr(wifi_service, "_run_netsh", fake_run)

    with pytest.raises(ValueError, match="Office"):
        wifi_service._read_exported_password("Office", tmp_path)


def test_wifi_profile_without_key_reports_no_password(monkeypatch, tmp_path):
    def fake_run(args, timeout=wifi_service.NETSH_TIMEOUT_SECONDS):
        del timeout
        export_dir = Path(
            next(value.removeprefix("folder=") for value in args if value.startswith("folder="))
        )
        (export_dir / "profile.xml").write_text(
            "<WLANProfile><name>Office</name></WLANProfile>", encoding="utf-8"
        )
        return ""

    monkeypatch.setattr(wifi_service, "_run_netsh", fake_run)

    assert wifi_service._read_exported_password("Office", tmp_path) == "No Password"


def test_wifi_per_profile_timeout_and_parse_error_are_isolated(monkeypatch):
    monkeypatch.setattr(
        wifi_service,
        "_run_netsh",
        lambda _args, timeout=wifi_service.NETSH_TIMEOUT_SECONDS: (
            "All User Profile : Office\nAll User Profile : Home\n"
        ),
    )
    responses = iter(
        [
            subprocess.TimeoutExpired("netsh", 10),
            ET.ParseError("invalid xml"),
        ]
    )

    def fake_read(_profile, _root):
        raise next(responses)

    monkeypatch.setattr(wifi_service, "_read_exported_password", fake_read)

    assert wifi_service.get_wifi_profiles() == [
        ("Office", "Timeout retrieving"),
        ("Home", "Error retrieving"),
    ]


def test_wifi_generic_list_error_is_reported(monkeypatch):
    monkeypatch.setattr(
        wifi_service,
        "_run_netsh",
        lambda _args, timeout=wifi_service.NETSH_TIMEOUT_SECONDS: (_ for _ in ()).throw(
            RuntimeError("netsh exploded")
        ),
    )

    assert wifi_service.get_wifi_profiles() == [("Error", "netsh exploded")]


def test_wifi_pre_cancelled_and_post_cancelled_events_raise(monkeypatch):
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(WorkerCancelled):
        wifi_service.get_wifi_profiles(cancel_event=cancelled)

    event = threading.Event()

    def fake_run(_args, timeout=wifi_service.NETSH_TIMEOUT_SECONDS):
        del timeout
        event.set()
        return ""

    monkeypatch.setattr(wifi_service, "_run_netsh", fake_run)
    with pytest.raises(WorkerCancelled):
        wifi_service.get_wifi_profiles(cancel_event=event)


def test_process_safe_values_and_details_handle_restricted_fields():
    fallback = process_service._safe_process_value(
        lambda: (_ for _ in ()).throw(psutil.AccessDenied(pid=1)), "fallback"
    )
    assert fallback == "fallback"
    assert process_service._safe_process_value(lambda: "") == "No disponible"
    assert process_service._safe_process_value(lambda: 123) == "123"

    proc = SimpleNamespace(
        pid=7,
        name=lambda: "demo.exe",
        exe=lambda: (_ for _ in ()).throw(psutil.AccessDenied(pid=7)),
        username=lambda: None,
        create_time=lambda: 123.5,
    )
    details = process_service.get_process_details(proc)
    assert details.pid == 7
    assert details.name == "demo.exe"
    assert details.exe_path == "No disponible"
    assert details.username == "No disponible"
    assert details.create_time == 123.5


def test_process_system_detection_covers_reserved_pids_and_syswow64():
    details = process_service.ProcessDetails(4, "demo.exe", "C:/x", "David", 1.0)
    assert process_service.is_system_process(details)

    syswow = process_service.ProcessDetails(
        10, "demo.exe", r"C:\Windows\SysWOW64\demo.exe", "David", 1.0
    )
    assert process_service.is_system_process(syswow)


def test_process_terminate_blocks_own_pid_and_unavailable_process(monkeypatch):
    details = process_service.ProcessDetails(os.getpid(), "self.exe", "C:/self", "me", 1.0)
    with pytest.raises(process_service.OwnProcessTerminationError):
        process_service.terminate_process(details)

    other = process_service.ProcessDetails(99123, "gone.exe", "C:/gone", "me", 1.0)
    monkeypatch.setattr(
        process_service.psutil,
        "Process",
        lambda _pid: (_ for _ in ()).throw(psutil.NoSuchProcess(_pid)),
    )
    with pytest.raises(process_service.ProcessUnavailableError):
        process_service.terminate_process(other)


def test_process_terminate_rejects_not_running_process(monkeypatch):
    details = process_service.ProcessDetails(99, "gone.exe", "C:/gone", "me", 10.0)
    proc = SimpleNamespace(is_running=lambda: False, create_time=lambda: 10.0, terminate=lambda: None)
    monkeypatch.setattr(process_service.psutil, "Process", lambda _pid: proc)

    with pytest.raises(process_service.ProcessIdentityChangedError):
        process_service.terminate_process(details)


def test_process_loading_skips_unavailable_and_filtered_candidates(monkeypatch):
    prime_error = psutil.AccessDenied(pid=1)
    sample_error = psutil.NoSuchProcess(pid=2)
    first = FakeProcess(1, "prime.exe", prime_error=prime_error)
    second = FakeProcess(2, "sample.exe", cpu=50.0, memory=50.0, sample_error=sample_error)
    third = FakeProcess(3, None, cpu=1.0, memory=1.0)
    fourth = FakeProcess(4, None, cpu=15.0, memory=1.0)
    monkeypatch.setattr(
        process_service.psutil,
        "process_iter",
        lambda _attrs: [first, second, third, fourth],
    )

    result = process_service.load_processes_task(FakeWorker(), cpu_min=10, mem_min=10)

    assert result == [(4, "Desconocido", 15.0, 1.0)]


class FakeResponse:
    def __init__(self, status_code, text="", payload=None):
        self.status_code = status_code
        self.text = text
        self.payload = payload

    def json(self):
        return self.payload


def _prepare_vt_file(monkeypatch, tmp_path, response):
    executable = tmp_path / "app.exe"
    executable.write_bytes(b"abc")
    monkeypatch.setattr(
        process_service.psutil,
        "Process",
        lambda _pid: SimpleNamespace(exe=lambda: str(executable)),
    )
    monkeypatch.setattr(process_service.requests, "get", lambda *args, **kwargs: response)
    return executable


def test_process_vt_handles_not_found_and_http_error(monkeypatch, tmp_path):
    executable = _prepare_vt_file(monkeypatch, tmp_path, FakeResponse(404))
    result = process_service.analyze_process_task(FakeWorker(), 7, "key")
    assert result.status == "not_found"
    assert result.exe_path == str(executable)

    _prepare_vt_file(monkeypatch, tmp_path, FakeResponse(503, text="maintenance"))
    result = process_service.analyze_process_task(FakeWorker(), 7, "key")
    assert result.status == "http_error"
    assert result.response_text == "maintenance"


def test_process_vt_parses_malicious_results(monkeypatch, tmp_path):
    response = FakeResponse(
        200,
        payload={
            "data": {
                "attributes": {
                    "last_analysis_stats": {"malicious": 2, "undetected": 70},
                    "last_analysis_results": {
                        "EngineA": {"category": "malicious", "result": "Trojan.A"},
                        "EngineB": {"category": "undetected", "result": None},
                        "EngineC": {"category": "malicious", "result": "Trojan.C"},
                    },
                }
            }
        },
    )
    _prepare_vt_file(monkeypatch, tmp_path, response)

    worker = FakeWorker()
    result = process_service.analyze_process_task(worker, 7, "key")

    assert result.status == "found"
    assert result.positives == 2
    assert result.total == 72
    assert result.detections == ("EngineA: Trojan.A", "EngineC: Trojan.C")
    assert any(item.get("percent") == 100 for item in worker.progress if isinstance(item, dict))


def test_duplicate_helpers_cover_unreadable_and_identity_fallback(monkeypatch, tmp_path):
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


def test_duplicate_quick_hash_and_files_equal_error_paths(tmp_path):
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


def test_duplicate_quick_hash_honours_cancel_event(tmp_path):
    path = tmp_path / "payload.bin"
    path.write_bytes(b"payload")
    event = threading.Event()
    event.set()

    with pytest.raises(duplicate_service.DuplicateOperationCancelled):
        duplicate_service.quick_hash_file(path, cancel_event=event)


def test_duplicate_find_ignores_unhashable_candidates(monkeypatch, tmp_path):
    first = tmp_path / "a.bin"
    second = tmp_path / "b.bin"
    first.write_bytes(b"same")
    second.write_bytes(b"same")

    monkeypatch.setattr(duplicate_service, "quick_hash_file", lambda *_args, **_kwargs: None)
    assert duplicate_service.find_duplicates(tmp_path) == {}

    monkeypatch.setattr(duplicate_service, "quick_hash_file", lambda *_args, **_kwargs: "quick")
    monkeypatch.setattr(duplicate_service, "hash_file", lambda *_args, **_kwargs: None)
    assert duplicate_service.find_duplicates(tmp_path) == {}


def test_duplicate_verified_groups_support_multiple_collision_groups(monkeypatch, tmp_path):
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


def test_duplicate_manifest_paths_and_inside_checks(monkeypatch, tmp_path):
    monkeypatch.setattr(
        duplicate_service.datetime,
        "now",
        lambda _tz: SimpleNamespace(strftime=lambda _fmt: "20260831T100000Z"),
    )
    first = tmp_path / f"{duplicate_service.RESTORE_MANIFEST_PREFIX}_20260831T100000Z.json"
    first.write_text("{}", encoding="utf-8")

    candidate = duplicate_service._new_manifest_path(tmp_path)

    assert candidate.name.endswith("_1.json")
    assert duplicate_service._is_inside(tmp_path / "child", tmp_path)
    assert not duplicate_service._is_inside(tmp_path.parent / "outside", tmp_path)


def test_duplicate_move_records_failed_move_and_completes(monkeypatch, tmp_path):
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
    manifest = __import__("json").loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "complete"
    assert manifest["moves"][0]["status"] == "failed"
    assert manifest["moves"][0]["error"] == "move failed"
