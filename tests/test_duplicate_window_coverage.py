from types import SimpleNamespace

import pytest

from pythonkni.duplicate import window as duplicate_window


class WorkerStub:
    def __init__(self, running=False):
        self.running = running
        self.cancel_requested = False

    def isRunning(self):
        return self.running

    def cancel(self):
        self.cancel_requested = True


def _tool(qtbot):
    tool = duplicate_window.Tool()
    qtbot.addWidget(tool)
    return tool


def test_scan_task_translates_domain_cancellation(monkeypatch):
    worker = SimpleNamespace(cancel_event=object())
    monkeypatch.setattr(
        duplicate_window,
        "find_duplicates",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            duplicate_window.DuplicateOperationCancelled()
        ),
    )

    with pytest.raises(duplicate_window.WorkerCancelled):
        duplicate_window._scan_duplicates_task(worker, "folder")


def test_move_task_translates_domain_cancellation(monkeypatch):
    worker = SimpleNamespace(cancel_event=object())
    monkeypatch.setattr(
        duplicate_window,
        "move_duplicates",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            duplicate_window.DuplicateOperationCancelled()
        ),
    )

    with pytest.raises(duplicate_window.WorkerCancelled):
        duplicate_window._move_duplicates_task(worker, {"hash": ["a", "b"]}, "folder")


def test_busy_state_tracks_duplicates(qtbot):
    tool = _tool(qtbot)
    tool.duplicates = {"hash": ["a", "b"]}

    tool._set_busy(True)
    assert not tool.btn_select_folder.isEnabled()
    assert not tool.btn_move.isEnabled()
    assert tool.btn_cancel.isEnabled()

    tool._set_busy(False)
    assert tool.btn_select_folder.isEnabled()
    assert tool.btn_move.isEnabled()
    assert not tool.btn_cancel.isEnabled()


def test_select_folder_ignores_active_worker_and_cancelled_dialog(qtbot, monkeypatch):
    tool = _tool(qtbot)
    started = []
    monkeypatch.setattr(tool, "_start_scan", lambda path: started.append(path) or True)

    worker = WorkerStub(running=True)
    tool.worker = worker
    tool.select_folder()
    assert started == []

    worker.running = False
    tool.worker = None
    monkeypatch.setattr(
        duplicate_window.QFileDialog,
        "getExistingDirectory",
        lambda *args, **kwargs: "",
    )
    tool.select_folder()
    assert started == []


def test_select_folder_starts_scan(qtbot, monkeypatch):
    tool = _tool(qtbot)
    monkeypatch.setattr(
        duplicate_window.QFileDialog,
        "getExistingDirectory",
        lambda *args, **kwargs: "C:/Data",
    )
    started = []
    monkeypatch.setattr(tool, "_start_scan", lambda path: started.append(path) or True)

    tool.select_folder()

    assert started == ["C:/Data"]


def test_duplicates_found_empty_clears_result_and_disables_move(qtbot, monkeypatch):
    tool = _tool(qtbot)
    tool.result_box.setPlainText("searching")
    info = []
    monkeypatch.setattr(
        duplicate_window.QMessageBox,
        "information",
        lambda *args: info.append(args),
    )

    tool.on_duplicates_found({})
    tool._set_busy(False)

    assert tool.duplicates == {}
    assert tool.result_box.toPlainText() == ""
    assert info[-1][1] == "Resultado"
    assert not tool.btn_move.isEnabled()


def test_duplicates_found_renders_hashes_and_paths(qtbot):
    tool = _tool(qtbot)
    duplicates = {
        "abc123": ["C:/a.txt", "C:/b.txt"],
        "def456": ["C:/c.bin", "C:/d.bin"],
    }

    tool.on_duplicates_found(duplicates)
    tool._set_busy(False)

    text = tool.result_box.toPlainText()
    assert "SHA-256 abc123" in text
    assert "C:/a.txt" in text
    assert "C:/b.txt" in text
    assert "SHA-256 def456" in text
    assert tool.btn_move.isEnabled()


def test_scan_cancelled_resets_duplicates(qtbot):
    tool = _tool(qtbot)
    tool.duplicates = {"hash": ["a", "b"]}

    tool.on_scan_cancelled()

    assert tool.duplicates == {}
    assert "cancelada" in tool.result_box.toPlainText().lower()


def test_start_move_guards_missing_state_and_active_worker(qtbot):
    tool = _tool(qtbot)
    assert not tool._start_move()

    tool.duplicates = {"hash": ["a", "b"]}
    assert not tool._start_move()

    tool.folder_path = "C:/Data"
    worker = WorkerStub(running=True)
    tool.worker = worker
    assert not tool._start_move()
    worker.running = False
    tool.worker = None


def test_move_action_delegates(qtbot, monkeypatch):
    tool = _tool(qtbot)
    calls = []
    monkeypatch.setattr(tool, "_start_move", lambda: calls.append(True) or True)

    tool.move_duplicates_action()

    assert calls == [True]


def test_move_finished_resets_state_and_reports_manifest(qtbot, monkeypatch):
    tool = _tool(qtbot)
    tool.duplicates = {"hash": ["a", "b"]}
    info = []
    monkeypatch.setattr(
        duplicate_window.QMessageBox,
        "information",
        lambda *args: info.append(args),
    )

    tool.on_move_finished(3)

    assert tool.duplicates == {}
    assert info[-1][1] == "Duplicados movidos"
    assert "3 archivos" in info[-1][2]
    assert duplicate_window.DUPLICATES_DIR_NAME in info[-1][2]
    assert "manifiesto JSON" in info[-1][2]
    assert "3 archivo(s)" in tool.result_box.toPlainText()


def test_move_cancelled_resets_state_and_describes_partial_manifest(qtbot):
    tool = _tool(qtbot)
    tool.duplicates = {"hash": ["a", "b"]}

    tool.on_move_cancelled()

    assert tool.duplicates == {}
    text = tool.result_box.toPlainText().lower()
    assert "movimiento cancelado" in text
    assert "manifiesto" in text
    assert "estado parcial" in text


def test_operation_failed_plain_diagnostic_uses_details(qtbot, monkeypatch):
    tool = _tool(qtbot)
    tool.duplicates = {"hash": ["a", "b"]}
    feedback = []
    monkeypatch.setattr(
        duplicate_window,
        "show_error",
        lambda *args, **kwargs: feedback.append((args, kwargs)),
    )

    tool.on_operation_failed("plain diagnostic")

    assert tool.duplicates == {}
    assert feedback[-1][1]["details"] == "plain diagnostic"
    assert "detalles técnicos" in tool.result_box.toPlainText()


def test_cancel_current_operation_noop_and_running(qtbot):
    tool = _tool(qtbot)
    tool.cancel_current_operation()

    worker = WorkerStub(running=False)
    tool.worker = worker
    tool.cancel_current_operation()
    assert not worker.cancel_requested

    worker.running = True
    tool.btn_cancel.setEnabled(True)
    tool.cancel_current_operation()
    assert worker.cancel_requested
    assert not tool.btn_cancel.isEnabled()
    assert "Cancelando operación" in tool.result_box.toPlainText()
    worker.running = False
    tool.worker = None


def test_operation_thread_finished_ignores_stale_and_clears_current(qtbot):
    tool = _tool(qtbot)
    current = WorkerStub(running=False)
    stale = WorkerStub(running=False)
    tool.worker = current
    tool._operation_kind = "scan"
    tool.duplicates = {"hash": ["a", "b"]}
    tool._set_busy(True)

    tool._on_operation_thread_finished(stale)
    assert tool.worker is current
    assert tool._operation_kind == "scan"
    assert tool.btn_cancel.isEnabled()

    tool._on_operation_thread_finished(current)
    assert tool.worker is None
    assert tool._operation_kind is None
    assert tool.btn_select_folder.isEnabled()
    assert tool.btn_move.isEnabled()
    assert not tool.btn_cancel.isEnabled()
