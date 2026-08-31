from pathlib import Path

from PyQt5.QtCore import QThread, pyqtSignal

from pythonkni.archive import window as archive_window


class FakeArchiveWorker(QThread):
    progress = pyqtSignal(object)
    result = pyqtSignal(object)
    error = pyqtSignal(object)
    cancelled = pyqtSignal()

    instances = []

    def __init__(self, *args, parent=None, **kwargs):
        super().__init__(parent)
        self.args = args
        self.kwargs = kwargs
        self.running = False
        self.cancel_requested = False
        self.__class__.instances.append(self)

    def start(self):
        self.running = True

    def isRunning(self):
        return self.running

    def cancel(self):
        self.cancel_requested = True


def _tool(qtbot):
    tool = archive_window.Tool()
    qtbot.addWidget(tool)
    return tool


def test_busy_state_and_progress_variants(qtbot):
    tool = _tool(qtbot)

    tool._set_busy(True, "Procesando")
    assert all(not button.isEnabled() for button in tool._action_buttons)
    assert tool.btn_cancel.isEnabled()
    assert not tool.progress.isHidden()
    assert tool.progress.value() == 0
    assert tool.status.text() == "Procesando"

    tool._on_progress({"message": "Mitad", "percent": 52})
    assert tool.status.text() == "Mitad"
    assert tool.progress.value() == 52

    tool._on_progress({"message": "Sin porcentaje"})
    assert tool.status.text() == "Sin porcentaje"
    assert tool.progress.value() == 52

    tool._on_progress("Finalizando")
    assert tool.status.text() == "Finalizando"

    tool._set_busy(False)
    assert all(button.isEnabled() for button in tool._action_buttons)
    assert not tool.btn_cancel.isEnabled()


def test_start_task_wires_worker_and_handles_completion(qtbot, monkeypatch):
    FakeArchiveWorker.instances.clear()
    monkeypatch.setattr(archive_window, "Worker", FakeArchiveWorker)
    messages = []
    monkeypatch.setattr(
        archive_window.QMessageBox,
        "information",
        lambda *args: messages.append(args),
    )
    tool = _tool(qtbot)
    task = lambda *_args, **_kwargs: None

    assert tool._start_task(task, ("source", "dest"), "Starting", "Success")

    worker = FakeArchiveWorker.instances[-1]
    assert worker.args[0] is task
    assert worker.args[1:] == ("source", "dest")
    assert worker.running
    assert tool.worker is worker
    assert tool.status.text() == "Starting"
    assert tool.btn_cancel.isEnabled()

    worker.result.emit(None)
    assert messages[-1][1:] == ("Éxito", "Success")

    worker.running = False
    tool._on_finished(worker)
    assert tool.worker is None
    assert all(button.isEnabled() for button in tool._action_buttons)
    assert not tool.btn_cancel.isEnabled()
    assert tool.progress.isHidden()


def test_start_task_rejects_overlap(qtbot, monkeypatch):
    tool = _tool(qtbot)
    worker = FakeArchiveWorker(parent=tool)
    worker.running = True
    tool.worker = worker
    messages = []
    monkeypatch.setattr(
        archive_window.QMessageBox,
        "information",
        lambda *args: messages.append(args),
    )

    started = tool._start_task(lambda: None, (), "ignored", "ignored")

    assert not started
    assert messages[-1][1] == "Archivo"
    assert "curso" in messages[-1][2]
    worker.running = False
    tool.worker = None


def test_finished_ignores_stale_worker(qtbot):
    tool = _tool(qtbot)
    current = FakeArchiveWorker(parent=tool)
    stale = FakeArchiveWorker(parent=tool)
    tool.worker = current
    tool._set_busy(True, "Busy")

    tool._on_finished(stale)

    assert tool.worker is current
    assert tool.btn_cancel.isEnabled()
    tool.worker = None


def test_cancel_operation_noop_and_running(qtbot):
    tool = _tool(qtbot)
    tool.cancel_operation()

    worker = FakeArchiveWorker(parent=tool)
    tool.worker = worker
    worker.running = False
    tool.cancel_operation()
    assert not worker.cancel_requested

    worker.running = True
    tool.btn_cancel.setEnabled(True)
    tool.cancel_operation()
    assert worker.cancel_requested
    assert not tool.btn_cancel.isEnabled()
    assert tool.status.text() == "Cancelando..."
    worker.running = False
    tool.worker = None


def test_cancelled_sets_status(qtbot):
    tool = _tool(qtbot)
    tool._on_cancelled()
    assert tool.status.text() == "Operación cancelada"


def test_extract_zip_dialog_flow(qtbot, monkeypatch):
    tool = _tool(qtbot)
    calls = []
    monkeypatch.setattr(
        archive_window.QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: ("sample.zip", ""),
    )
    monkeypatch.setattr(archive_window, "_default_extract_path", lambda path: Path("out-zip"))
    monkeypatch.setattr(tool, "_start_task", lambda *args: calls.append(args) or True)

    tool.extract_zip_action()

    assert calls[0][0] is archive_window.extract_zip_task
    assert calls[0][1] == ("sample.zip", Path("out-zip"))
    assert "ZIP" in calls[0][2]
    assert "out-zip" in calls[0][3]


def test_extract_7z_dialog_flow(qtbot, monkeypatch):
    tool = _tool(qtbot)
    calls = []
    monkeypatch.setattr(
        archive_window.QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: ("sample.7z", ""),
    )
    monkeypatch.setattr(archive_window, "_default_extract_path", lambda path: Path("out-7z"))
    monkeypatch.setattr(tool, "_start_task", lambda *args: calls.append(args) or True)

    tool.extract_7z_action()

    assert calls[0][0] is archive_window.extract_7z_task
    assert calls[0][1] == ("sample.7z", Path("out-7z"))
    assert "7Z" in calls[0][2]
    assert "out-7z" in calls[0][3]


def test_create_zip_dialog_flow(qtbot, monkeypatch):
    tool = _tool(qtbot)
    calls = []
    monkeypatch.setattr(
        archive_window.QFileDialog,
        "getOpenFileNames",
        lambda *args, **kwargs: (["a.txt", "b.txt"], ""),
    )
    monkeypatch.setattr(
        archive_window.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: ("bundle.zip", ""),
    )
    monkeypatch.setattr(tool, "_start_task", lambda *args: calls.append(args) or True)

    tool.create_zip_action()

    assert calls[0][0] is archive_window.create_zip_task
    assert calls[0][1] == (["a.txt", "b.txt"], Path("bundle.zip"))
    assert "ZIP" in calls[0][2]
    assert "bundle.zip" in calls[0][3]


def test_create_7z_dialog_flow(qtbot, monkeypatch):
    tool = _tool(qtbot)
    calls = []
    monkeypatch.setattr(
        archive_window.QFileDialog,
        "getOpenFileNames",
        lambda *args, **kwargs: (["a.txt"], ""),
    )
    monkeypatch.setattr(
        archive_window.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: ("bundle.7z", ""),
    )
    monkeypatch.setattr(tool, "_start_task", lambda *args: calls.append(args) or True)

    tool.create_7z_action()

    assert calls[0][0] is archive_window.create_7z_task
    assert calls[0][1] == (["a.txt"], Path("bundle.7z"))
    assert "7Z" in calls[0][2]
    assert "bundle.7z" in calls[0][3]


def test_archive_dialog_cancellations_do_not_start_tasks(qtbot, monkeypatch):
    tool = _tool(qtbot)
    calls = []
    monkeypatch.setattr(tool, "_start_task", lambda *args: calls.append(args) or True)

    monkeypatch.setattr(
        archive_window.QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: ("", ""),
    )
    tool.extract_zip_action()
    tool.extract_7z_action()

    monkeypatch.setattr(
        archive_window.QFileDialog,
        "getOpenFileNames",
        lambda *args, **kwargs: ([], ""),
    )
    tool.create_zip_action()
    tool.create_7z_action()

    monkeypatch.setattr(
        archive_window.QFileDialog,
        "getOpenFileNames",
        lambda *args, **kwargs: (["a.txt"], ""),
    )
    monkeypatch.setattr(
        archive_window.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: ("", ""),
    )
    tool.create_zip_action()
    tool.create_7z_action()

    assert calls == []
