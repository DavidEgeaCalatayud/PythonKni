import threading

from PyQt5.QtCore import QThread

from tools import duplicate_tool as duplicate


def silence_message_boxes(monkeypatch):
    monkeypatch.setattr(duplicate.QMessageBox, "information", lambda *args, **kwargs: None)
    monkeypatch.setattr(duplicate.QMessageBox, "critical", lambda *args, **kwargs: None)


def test_second_scan_is_rejected_while_first_worker_runs(monkeypatch, qtbot, tmp_path):
    entered = threading.Event()

    def fake_find_duplicates(_folder_path, cancel_event=None):
        entered.set()
        while cancel_event is not None and not cancel_event.wait(0.005):
            pass
        raise duplicate.DuplicateOperationCancelled()

    monkeypatch.setattr(duplicate, "find_duplicates", fake_find_duplicates)
    silence_message_boxes(monkeypatch)

    tool = duplicate.Tool()
    qtbot.addWidget(tool)
    tool.show()

    assert tool._start_scan(str(tmp_path)) is True
    qtbot.waitUntil(entered.is_set, timeout=1000)
    first_worker = tool.worker

    assert isinstance(first_worker, duplicate.Worker)
    assert tool._start_scan(str(tmp_path / "other")) is False
    assert tool.worker is first_worker
    assert not tool.btn_select_folder.isEnabled()
    assert not tool.btn_move.isEnabled()
    assert tool.btn_cancel.isEnabled()

    tool.cancel_current_operation()
    qtbot.waitUntil(lambda: tool.worker is None, timeout=1000)

    assert tool.btn_select_folder.isEnabled()
    assert not tool.btn_cancel.isEnabled()
    assert "cancelada" in tool.result_box.toPlainText().lower()


def test_move_revalidation_runs_off_gui_thread(monkeypatch, qtbot, tmp_path):
    entered = threading.Event()
    release = threading.Event()
    worker_threads = []

    def fake_move_duplicates(_duplicates, _base_folder, cancel_event=None):
        worker_threads.append(QThread.currentThread())
        entered.set()
        while not release.wait(0.005):
            if cancel_event is not None and cancel_event.is_set():
                raise duplicate.DuplicateOperationCancelled()
        return 1

    monkeypatch.setattr(duplicate, "move_duplicates", fake_move_duplicates)
    silence_message_boxes(monkeypatch)

    tool = duplicate.Tool()
    qtbot.addWidget(tool)
    tool.show()
    tool.folder_path = str(tmp_path)
    tool.duplicates = {"hash": [str(tmp_path / "a"), str(tmp_path / "b")]}

    gui_thread = QThread.currentThread()
    assert tool._start_move() is True
    qtbot.waitUntil(entered.is_set, timeout=1000)

    assert isinstance(tool.worker, duplicate.Worker)
    assert worker_threads
    assert worker_threads[0] is not gui_thread
    assert not tool.btn_select_folder.isEnabled()
    assert not tool.btn_move.isEnabled()
    assert tool.btn_cancel.isEnabled()

    release.set()
    qtbot.waitUntil(lambda: tool.worker is None, timeout=1000)

    assert tool.btn_select_folder.isEnabled()
    assert not tool.btn_move.isEnabled()
    assert "operación completada" in tool.result_box.toPlainText().lower()


def test_move_can_be_cancelled_without_blocking_gui(monkeypatch, qtbot, tmp_path):
    entered = threading.Event()

    def fake_move_duplicates(_duplicates, _base_folder, cancel_event=None):
        entered.set()
        assert cancel_event is not None
        cancel_event.wait(1)
        if cancel_event.is_set():
            raise duplicate.DuplicateOperationCancelled(moved_count=2)
        return 3

    monkeypatch.setattr(duplicate, "move_duplicates", fake_move_duplicates)
    silence_message_boxes(monkeypatch)

    tool = duplicate.Tool()
    qtbot.addWidget(tool)
    tool.show()
    tool.folder_path = str(tmp_path)
    tool.duplicates = {"hash": [str(tmp_path / "a"), str(tmp_path / "b")]}

    assert tool._start_move() is True
    qtbot.waitUntil(entered.is_set, timeout=1000)

    tool.cancel_current_operation()
    assert not tool.btn_cancel.isEnabled()
    qtbot.waitUntil(lambda: tool.worker is None, timeout=1000)

    text = tool.result_box.toPlainText().lower()
    assert "movimiento cancelado" in text
    assert "manifiesto" in text
    assert tool.btn_select_folder.isEnabled()
    assert not tool.btn_move.isEnabled()
