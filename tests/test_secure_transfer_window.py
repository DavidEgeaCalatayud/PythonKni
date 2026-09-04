from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from PyQt5.QtWidgets import QApplication, QLabel

from pythonkni.secure_transfer import window
from pythonkni.secure_transfer.models import (
    BackendInfo,
    TransferEvent,
    TransferEventKind,
    TransferMode,
    TransferResult,
)

TOKEN = "tc" + "C" * 32


@pytest.fixture
def tool(qtbot):
    instance = window.Tool()
    qtbot.addWidget(instance)
    return instance


def test_tool_builds_four_safe_tabs(tool):
    assert tool.tabs.count() == 4
    assert tool.accept_folders.isChecked() is False
    assert tool.serve_port.value() == 8080
    assert tool.local_port.value() == 18080
    labels = " ".join(label.text() for label in tool.findChildren(QLabel))
    assert "127.0.0.1" in labels
    assert "experimental" in labels


def test_choose_paths_update_fields(tool, monkeypatch, tmp_path):
    monkeypatch.setattr(window.QFileDialog, "getExistingDirectory", lambda *a: str(tmp_path))
    tool.choose_receive_destination()
    assert tool.receive_destination.text() == str(tmp_path)
    tool.choose_send_folder()
    assert tool.selected_path == tmp_path

    file_path = tmp_path / "x.txt"
    file_path.write_text("x")
    monkeypatch.setattr(window.QFileDialog, "getOpenFileName", lambda *a: (str(file_path), ""))
    tool.choose_send_file()
    assert tool.selected_path == file_path
    assert tool.send_path.text() == str(file_path)


def test_copy_token_validates_and_uses_clipboard(tool, monkeypatch):
    warnings = []
    monkeypatch.setattr(window, "show_warning", lambda *args: warnings.append(args))
    tool.copy_token(tool.receive_token)
    assert warnings
    tool.receive_token.setText(TOKEN)
    tool.copy_token(tool.receive_token)
    assert QApplication.clipboard().text() == TOKEN
    assert "copied" in tool.status_label.text().lower()


def test_start_receive_creates_managed_worker_and_stop_cancels(tool, monkeypatch, tmp_path):
    started = []
    monkeypatch.setattr(tool, "start_managed_worker", lambda worker, cancel=None: started.append(worker))
    tool.receive_destination.setText(str(tmp_path))
    tool.start_receive_files()
    assert tool.worker is started[0]
    assert tool._ready_field is tool.receive_token
    assert tool.stop_button.isEnabled()

    cancelled = []
    tool.worker = SimpleNamespace(isRunning=lambda: True, cancel=lambda: cancelled.append(True))
    tool.stop_operation()
    assert cancelled == [True]
    assert "stopping" in tool.status_label.text().lower()


def test_start_validation_paths_show_warning(tool, monkeypatch):
    warnings = []
    monkeypatch.setattr(window, "show_warning", lambda *args: warnings.append(args))
    tool.start_receive_files()
    tool.start_send_path()
    tool.start_send_text()
    tool.start_forward_port()
    assert len(warnings) == 4


def test_start_send_text_and_tunnel_create_operations(tool, monkeypatch):
    started = []
    monkeypatch.setattr(tool, "start_managed_worker", lambda worker, cancel=None: started.append(worker))
    tool.send_text_token.setText(TOKEN)
    tool.outgoing_text.setPlainText("hello")
    tool.start_send_text()
    assert len(started) == 1
    tool._worker_finished()

    tool.start_receive_text()
    assert tool._ready_field is tool.receive_text_token
    tool._worker_finished()

    tool.start_serve_port()
    assert tool._ready_field is tool.serve_token
    tool._worker_finished()

    tool.forward_token.setText(TOKEN)
    tool.start_forward_port()
    assert len(started) == 4


def test_start_send_path_uses_selected_path(tool, monkeypatch, tmp_path):
    started = []
    monkeypatch.setattr(tool, "start_managed_worker", lambda worker, cancel=None: started.append(worker))
    path = tmp_path / "x.txt"
    path.write_text("x")
    tool.selected_path = path
    tool.send_path.setText(str(path))
    tool.send_token.setText(TOKEN)
    tool.start_send_path()
    assert started


def test_progress_routes_ready_to_operation_field_not_current_tab(tool):
    tool._ready_field = tool.receive_token
    tool.tabs.setCurrentIndex(3)
    tool._progress(TransferEvent(TransferEventKind.READY, "ready", token=TOKEN))
    assert tool.receive_token.text() == TOKEN
    assert tool.serve_token.text() == ""

    tool._progress(TransferEvent(TransferEventKind.TEXT, "text", text="hello"))
    assert tool.received_text.toPlainText() == "hello"
    assert "text" in tool.log.toPlainText()


def test_completion_failure_cancel_and_finish(tool, monkeypatch):
    tool._completed(TransferResult(TransferMode.TEXT, "done"))
    assert tool.status_label.text() == "done"

    errors = []
    monkeypatch.setattr(window, "show_error", lambda *args: errors.append(args))
    tool._failed(RuntimeError("boom"))
    assert errors
    assert "boom" in tool.status_label.text()

    tool._cancelled()
    assert "cancelled" in tool.status_label.text().lower()

    tool._ready_field = tool.receive_token
    tool.worker = SimpleNamespace()
    tool._worker_finished()
    assert tool.worker is None
    assert tool._ready_field is None
    assert not tool.stop_button.isEnabled()


def test_check_backend_success_and_failure(tool, monkeypatch):
    monkeypatch.setattr(
        tool.service,
        "backend_info",
        lambda: BackendInfo("Tailcat", "0.5.0", Path("tailcat.exe"), True),
    )
    tool.check_backend()
    assert "v0.5.0" in tool.backend_label.text()

    errors = []
    monkeypatch.setattr(window, "show_error", lambda *args: errors.append(args))

    def fail():
        raise RuntimeError("missing")

    monkeypatch.setattr(tool.service, "backend_info", fail)
    tool.check_backend()
    assert errors
    assert "missing" in tool.backend_label.text()


def test_run_operation_forwards_worker_event_hooks():
    stop = SimpleNamespace()
    worker = SimpleNamespace(cancel_event=stop, report_progress=lambda event: None)
    seen = []

    def operation(*, stop_event, on_event):
        seen.append((stop_event, on_event))
        return TransferResult(TransferMode.TEXT, "ok")

    result = window._run_operation(worker, operation)
    assert result.message == "ok"
    assert seen[0][0] is stop
