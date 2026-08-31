import os
from types import SimpleNamespace

import psutil
import pytest

from pythonkni.process_manager import service as process_service


class FakeCancelEvent:
    def wait(self, _timeout):
        return False


class FakeWorker:
    def __init__(self):
        self.cancel_event = FakeCancelEvent()
        self.progress = []

    def check_cancelled(self):
        return None

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


def test_safe_values_and_details_handle_restricted_fields():
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


def test_system_detection_covers_reserved_pids_and_syswow64():
    details = process_service.ProcessDetails(4, "demo.exe", "C:/x", "David", 1.0)
    assert process_service.is_system_process(details)

    syswow = process_service.ProcessDetails(
        10, "demo.exe", r"C:\Windows\SysWOW64\demo.exe", "David", 1.0
    )
    assert process_service.is_system_process(syswow)


def test_terminate_blocks_own_pid_and_unavailable_process(monkeypatch):
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


def test_terminate_rejects_not_running_process(monkeypatch):
    details = process_service.ProcessDetails(99, "gone.exe", "C:/gone", "me", 10.0)
    proc = SimpleNamespace(
        is_running=lambda: False,
        create_time=lambda: 10.0,
        terminate=lambda: None,
    )
    monkeypatch.setattr(process_service.psutil, "Process", lambda _pid: proc)

    with pytest.raises(process_service.ProcessIdentityChangedError):
        process_service.terminate_process(details)


def test_loading_skips_unavailable_and_filtered_candidates(monkeypatch):
    first = FakeProcess(1, "prime.exe", prime_error=psutil.AccessDenied(pid=1))
    second = FakeProcess(
        2,
        "sample.exe",
        cpu=50.0,
        memory=50.0,
        sample_error=psutil.NoSuchProcess(pid=2),
    )
    third = FakeProcess(3, None, cpu=1.0, memory=1.0)
    fourth = FakeProcess(4, None, cpu=15.0, memory=1.0)
    monkeypatch.setattr(
        process_service.psutil,
        "process_iter",
        lambda _attrs: [first, second, third, fourth],
    )

    result = process_service.load_processes_task(FakeWorker(), cpu_min=10, mem_min=10)

    assert result == [(4, "Desconocido", 15.0, 1.0)]


def test_virustotal_handles_not_found_and_http_error(monkeypatch, tmp_path):
    executable = _prepare_vt_file(monkeypatch, tmp_path, FakeResponse(404))
    result = process_service.analyze_process_task(FakeWorker(), 7, "key")
    assert result.status == "not_found"
    assert result.exe_path == str(executable)

    _prepare_vt_file(monkeypatch, tmp_path, FakeResponse(503, text="maintenance"))
    result = process_service.analyze_process_task(FakeWorker(), 7, "key")
    assert result.status == "http_error"
    assert result.response_text == "maintenance"


def test_virustotal_parses_malicious_results(monkeypatch, tmp_path):
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
