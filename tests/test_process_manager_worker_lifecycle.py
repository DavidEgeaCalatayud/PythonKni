import threading
import time

from tools import process_manager_tool as process_manager


def _wait_until_released(worker, started, release):
    started.append(worker)
    while not release.wait(0.01):
        # Deliberately keep the task alive after cancellation to reproduce the
        # refresh race where an older worker can outlive the attribute pointing
        # at the newest worker.
        time.sleep(0)
    worker.check_cancelled()
    return []


def test_refresh_keeps_replaced_worker_managed_until_it_finishes(qtbot, monkeypatch):
    started = []
    release = threading.Event()

    def blocking_load(worker, _cpu_min, _mem_min):
        return _wait_until_released(worker, started, release)

    monkeypatch.setattr(process_manager, "load_processes_task", blocking_load)
    tool = process_manager.Tool()
    qtbot.addWidget(tool)
    tool.show()

    qtbot.waitUntil(lambda: len(started) == 1, timeout=2000)
    first = tool._process_worker
    assert first in tool._managed_workers

    tool.load_processes()
    qtbot.waitUntil(lambda: len(started) == 2, timeout=2000)
    second = tool._process_worker

    assert second is not first
    assert first.is_cancelled()
    assert first.isRunning()
    assert first in tool._managed_workers
    assert second in tool._managed_workers

    release.set()
    qtbot.waitUntil(
        lambda: not first.isRunning() and not second.isRunning(),
        timeout=3000,
    )
    qtbot.waitUntil(lambda: not tool._managed_workers, timeout=3000)


def test_close_cancels_every_replaced_refresh_worker(qtbot, monkeypatch):
    started = []
    release = threading.Event()

    def blocking_load(worker, _cpu_min, _mem_min):
        return _wait_until_released(worker, started, release)

    monkeypatch.setattr(process_manager, "load_processes_task", blocking_load)
    tool = process_manager.Tool()
    tool.worker_shutdown_wait_ms = 0
    qtbot.addWidget(tool)
    tool.show()

    qtbot.waitUntil(lambda: len(started) == 1, timeout=2000)
    first = tool._process_worker
    tool.load_processes()
    qtbot.waitUntil(lambda: len(started) == 2, timeout=2000)
    second = tool._process_worker

    tool.close()

    assert first.is_cancelled()
    assert second.is_cancelled()
    assert first in tool._managed_workers
    assert second in tool._managed_workers
    assert tool._close_when_workers_finish is True
    assert tool.isVisible()

    release.set()
    qtbot.waitUntil(
        lambda: not first.isRunning() and not second.isRunning(),
        timeout=3000,
    )
    qtbot.waitUntil(lambda: not tool.isVisible(), timeout=3000)


def test_analysis_worker_uses_base_tool_lifecycle(qtbot, monkeypatch):
    analysis_started = threading.Event()
    release = threading.Event()

    monkeypatch.setattr(process_manager, "load_processes_task", lambda worker, cpu, mem: [])
    monkeypatch.setattr(process_manager, "get_vt_api_key", lambda: "test-key")

    def blocking_analysis(worker, _pid, _api_key):
        analysis_started.set()
        while not release.wait(0.01):
            time.sleep(0)
        worker.check_cancelled()
        return None

    monkeypatch.setattr(process_manager, "analyze_process_task", blocking_analysis)

    tool = process_manager.Tool()
    qtbot.addWidget(tool)
    qtbot.waitUntil(
        lambda: tool._process_worker is None or not tool._process_worker.isRunning(),
        timeout=2000,
    )

    tool.analyze_process(1234)
    qtbot.waitUntil(analysis_started.is_set, timeout=2000)
    worker = tool._analysis_worker

    assert worker in tool._managed_workers

    worker.cancel()
    release.set()
    qtbot.waitUntil(lambda: not worker.isRunning(), timeout=3000)
    qtbot.waitUntil(lambda: worker not in tool._managed_workers, timeout=3000)
