
import pytest

from pythonkni.core.tasks import WorkerCancelled
from tools import process_manager_tool as process_manager


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

    def check_cancelled(self):
        if self.cancel_event.is_set():
            raise WorkerCancelled()


class FakeProcess:
    def __init__(self, pid, name, cpu, memory):
        self.pid = pid
        self.info = {"pid": pid, "name": name}
        self.cpu = cpu
        self.memory = memory
        self.cpu_calls = []

    def cpu_percent(self, interval=None):
        self.cpu_calls.append(interval)
        return 0.0 if len(self.cpu_calls) == 1 else self.cpu

    def memory_percent(self):
        return self.memory


def test_process_cpu_sampling_primes_all_then_waits_once(monkeypatch):
    first = FakeProcess(1, "one.exe", 12.5, 1.0)
    second = FakeProcess(2, "two.exe", 3.0, 8.0)
    monkeypatch.setattr(process_manager.psutil, "process_iter", lambda _attrs: [first, second])
    worker = FakeWorker()

    result = process_manager.load_processes_task(worker, cpu_min=10, mem_min=5)

    assert worker.cancel_event.wait_calls == [process_manager.CPU_SAMPLE_SECONDS]
    assert first.cpu_calls == [None, None]
    assert second.cpu_calls == [None, None]
    assert result == [
        (1, "one.exe", 12.5, 1.0),
        (2, "two.exe", 3.0, 8.0),
    ]


def test_process_cpu_sampling_has_no_wait_when_there_are_no_candidates(monkeypatch):
    monkeypatch.setattr(process_manager.psutil, "process_iter", lambda _attrs: [])
    worker = FakeWorker()

    assert process_manager.load_processes_task(worker, 0, 0) == []
    assert worker.cancel_event.wait_calls == []


def test_process_cpu_sampling_cancels_during_shared_wait(monkeypatch):
    proc = FakeProcess(1, "one.exe", 12.5, 1.0)
    monkeypatch.setattr(process_manager.psutil, "process_iter", lambda _attrs: [proc])
    worker = FakeWorker()

    def cancel_on_wait(timeout):
        worker.cancel_event.wait_calls.append(timeout)
        worker.cancel_event.cancelled = True
        return True

    worker.cancel_event.wait = cancel_on_wait

    with pytest.raises(WorkerCancelled):
        process_manager.load_processes_task(worker, 0, 0)

    assert worker.cancel_event.wait_calls == [process_manager.CPU_SAMPLE_SECONDS]
    assert proc.cpu_calls == [None]
