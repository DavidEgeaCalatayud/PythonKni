from __future__ import annotations

import importlib
import threading
import time

import pytest
from PyQt5.QtCore import QThread, pyqtSignal

from tools.base_tool import BaseTool


class DummyTool(BaseTool):
    name = "Dummy"
    description = "Worker lifecycle test tool"
    category = "Tests"

    def setup_ui(self) -> None:
        self.resize(200, 100)


class CooperativeWorker(QThread):
    def __init__(self):
        super().__init__()
        self.cancel_called = False
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self.cancel_called = True
        self._cancel_event.set()

    def run(self) -> None:
        while not self._cancel_event.wait(0.005):
            pass


class SlowWorker(QThread):
    def run(self) -> None:
        time.sleep(0.12)


class ShadowFinishedWorker(QThread):
    # DiskAnalyzerWorker historically shadows QThread.finished with a payload
    # signal. BaseTool must still bind the native QThread lifecycle signal.
    finished = pyqtSignal(list)

    def run(self) -> None:
        self.msleep(20)
        self.finished.emit([])


@pytest.mark.parametrize(
    "module_name",
    [
        "tools.duplicate_tool",
        "tools.disk_analyzer_tool",
        "pythonkni.event_viewer.window",
        "pythonkni.system_report.window",
    ],
)
def test_affected_tools_inherit_common_close_lifecycle(module_name):
    module = importlib.import_module(module_name)
    assert module.Tool.closeEvent is BaseTool.closeEvent


def test_close_discovers_and_cancels_unregistered_legacy_worker(qtbot):
    tool = DummyTool()
    qtbot.addWidget(tool)
    tool.show()

    worker = CooperativeWorker()
    tool.worker = worker
    worker.start()
    qtbot.waitUntil(worker.isRunning, timeout=1000)

    tool.close()

    qtbot.waitUntil(lambda: not worker.isRunning(), timeout=1000)
    qtbot.waitUntil(lambda: not tool.isVisible(), timeout=1000)
    assert worker.cancel_called


def test_close_is_deferred_until_non_cooperative_worker_finishes(qtbot):
    tool = DummyTool()
    tool.worker_shutdown_wait_ms = 1
    qtbot.addWidget(tool)
    tool.show()

    worker = SlowWorker()
    tool.thread = worker
    worker.start()
    qtbot.waitUntil(worker.isRunning, timeout=1000)

    tool.close()
    assert tool.isVisible()

    qtbot.waitUntil(lambda: not worker.isRunning(), timeout=1000)
    qtbot.waitUntil(lambda: not tool.isVisible(), timeout=1000)


def test_start_managed_worker_uses_explicit_cancel_callback(qtbot):
    tool = DummyTool()
    qtbot.addWidget(tool)
    tool.show()

    release = threading.Event()

    class ManagedWorker(QThread):
        def run(self) -> None:
            release.wait(1)

    worker = ManagedWorker()
    tool.start_managed_worker(worker, cancel=release.set)
    qtbot.waitUntil(worker.isRunning, timeout=1000)

    tool.close()

    qtbot.waitUntil(lambda: not worker.isRunning(), timeout=1000)
    assert release.is_set()


def test_managed_worker_handles_legacy_finished_signal_shadow(qtbot):
    tool = DummyTool()
    qtbot.addWidget(tool)

    worker = ShadowFinishedWorker()
    tool.start_managed_worker(worker)
    qtbot.waitUntil(lambda: not worker.isRunning(), timeout=1000)
    qtbot.waitUntil(lambda: worker not in tool._managed_workers, timeout=1000)

    assert worker not in tool._managed_workers
