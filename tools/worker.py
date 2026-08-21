from __future__ import annotations

import threading
from typing import Any, Callable

from PyQt5.QtCore import QThread, pyqtSignal

from pythonkni.core.tasks import WorkerCancelled


class Worker(QThread):
    """Reusable background worker with progress/result/error/cancelled signals."""

    progress = pyqtSignal(object)
    result = pyqtSignal(object)
    error = pyqtSignal(object)
    cancelled = pyqtSignal()

    def __init__(
        self,
        task: Callable[..., Any],
        *args: Any,
        parent=None,
        **kwargs: Any,
    ) -> None:
        super().__init__(parent)
        self._task = task
        self._args = args
        self._kwargs = kwargs
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        """Request cooperative cancellation from the GUI thread."""
        self._cancel_event.set()

    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def check_cancelled(self) -> None:
        if self.is_cancelled():
            raise WorkerCancelled()

    def report_progress(self, value: object) -> None:
        self.check_cancelled()
        self.progress.emit(value)

    def run(self) -> None:
        try:
            self.check_cancelled()
            value = self._task(self, *self._args, **self._kwargs)
            self.check_cancelled()
        except WorkerCancelled:
            self.cancelled.emit()
        except Exception as error:
            self.error.emit(error)
        else:
            self.result.emit(value)
