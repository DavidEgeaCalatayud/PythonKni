from __future__ import annotations

import time
from collections.abc import Callable

from PyQt5.QtCore import QThread, QTimer
from PyQt5.QtWidgets import QMainWindow


WORKER_SHUTDOWN_WAIT_MS = 3000
DEFERRED_CLOSE_POLL_MS = 50


class BaseTool(QMainWindow):
    """Common lifecycle and metadata contract for every PythonKni GUI tool.

    QThread instances started by a tool should preferably be registered with
    :meth:`manage_worker` / :meth:`start_managed_worker`. For compatibility with
    older tools, shutdown also discovers QThread objects stored directly on the
    window (for example ``self.worker`` or ``self.thread``).
    """

    name: str = ""
    description: str = ""
    category: str = "General"
    worker_shutdown_wait_ms: int = WORKER_SHUTDOWN_WAIT_MS

    def __init__(self, *args, **kwargs):
        self._managed_workers: set[QThread] = set()
        self._worker_cancel_callbacks: dict[QThread, Callable[[], None]] = {}
        self._close_when_workers_finish = False
        self._deferred_close_poll_scheduled = False
        super().__init__(*args, **kwargs)
        self.setup_ui()

    def setup_ui(self) -> None:
        """Build the tool user interface. Subclasses must override this method."""
        raise NotImplementedError

    def manage_worker(
        self,
        worker: QThread,
        *,
        cancel: Callable[[], None] | None = None,
    ) -> QThread:
        """Register a worker so its lifecycle is tied to this tool window."""
        if not isinstance(worker, QThread):
            raise TypeError("worker must be a QThread instance")

        if worker not in self._managed_workers:
            self._managed_workers.add(worker)
            # Some legacy workers accidentally shadow ``finished`` with their own
            # signal. Bind QThread.finished explicitly so cleanup still observes
            # the native thread lifecycle signal.
            native_finished = QThread.finished.__get__(worker, type(worker))
            native_finished.connect(
                lambda *_args, managed_worker=worker: self._on_managed_worker_finished(
                    managed_worker
                )
            )
        if cancel is not None:
            self._worker_cancel_callbacks[worker] = cancel
        return worker

    def start_managed_worker(
        self,
        worker: QThread,
        *,
        cancel: Callable[[], None] | None = None,
    ) -> QThread:
        """Register and start a QThread using the common lifecycle policy."""
        self.manage_worker(worker, cancel=cancel)
        worker.start()
        return worker

    def _on_managed_worker_finished(self, worker: QThread) -> None:
        self._managed_workers.discard(worker)
        self._worker_cancel_callbacks.pop(worker, None)
        if self._close_when_workers_finish:
            self._schedule_deferred_close_poll()

    def _discover_active_workers(self) -> list[QThread]:
        """Return running workers registered explicitly or held by the window."""
        workers = set(self._managed_workers)
        for value in vars(self).values():
            if isinstance(value, QThread):
                workers.add(value)

        return [worker for worker in workers if worker.isRunning()]

    def _cancel_worker(self, worker: QThread) -> None:
        """Request cooperative cancellation without ever terminating a thread."""
        callback = self._worker_cancel_callbacks.get(worker)
        if callback is not None:
            try:
                callback()
            except Exception:
                pass
        else:
            for method_name in ("cancel", "stop"):
                method = getattr(worker, method_name, None)
                if callable(method):
                    try:
                        method()
                    except Exception:
                        pass
                    break

        # requestInterruption is harmless when the worker does not inspect it and
        # provides a standard cancellation path for workers that do.
        try:
            worker.requestInterruption()
        except Exception:
            pass

    def _schedule_deferred_close_poll(self) -> None:
        if self._deferred_close_poll_scheduled:
            return
        self._deferred_close_poll_scheduled = True
        QTimer.singleShot(DEFERRED_CLOSE_POLL_MS, self._retry_deferred_close)

    def _retry_deferred_close(self) -> None:
        self._deferred_close_poll_scheduled = False
        if not self._close_when_workers_finish:
            return
        if self._discover_active_workers():
            self._schedule_deferred_close_poll()
            return

        self._close_when_workers_finish = False
        self.close()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API name
        """Cancel active workers and never destroy a running QThread."""
        active_workers = self._discover_active_workers()
        if not active_workers:
            self._close_when_workers_finish = False
            event.accept()
            return

        self._close_when_workers_finish = True
        for worker in active_workers:
            # Register discovered legacy workers so future tools can transition
            # incrementally without losing the shutdown guarantee.
            self.manage_worker(worker)
            self._cancel_worker(worker)

        deadline = time.monotonic() + max(0, self.worker_shutdown_wait_ms) / 1000
        for worker in active_workers:
            if not worker.isRunning():
                continue
            remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
            if remaining_ms <= 0:
                break
            worker.wait(remaining_ms)

        if not self._discover_active_workers():
            self._close_when_workers_finish = False
            event.accept()
            return

        # Keeping the close event ignored retains the window and all Python
        # references until the workers are genuinely finished. The timer retries
        # the close without blocking the UI indefinitely.
        event.ignore()
        self._schedule_deferred_close_poll()
