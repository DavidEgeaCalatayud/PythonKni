import os
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PyQt5.QtWidgets import QMessageBox

from tools.process_manager_tool import (
    ProcessDetails,
    Tool,
    format_process_identity,
    is_own_process,
    is_system_process,
)


class FakeTable:
    def __init__(self, pid):
        self.pid = pid

    def currentRow(self):
        return 0

    def item(self, row, column):
        assert row == 0
        assert column == 0
        return SimpleNamespace(text=lambda: str(self.pid))


def make_details(
    pid=1234,
    name="notepad.exe",
    exe_path=r"C:\Program Files\App\notepad.exe",
    username="David",
    create_time=100.0,
):
    return ProcessDetails(pid, name, exe_path, username, create_time)


def test_is_own_process_uses_application_pid():
    assert is_own_process(42, app_pid=42)
    assert not is_own_process(43, app_pid=42)


def test_system_process_detects_system_identity_and_windows_path():
    assert is_system_process(
        make_details(name="svchost.exe", exe_path=r"C:\Windows\System32\svchost.exe")
    )
    assert is_system_process(make_details(username=r"NT AUTHORITY\SYSTEM"))
    assert is_system_process(
        make_details(name="helper.exe", exe_path=r"C:\Windows\System32\helper.exe")
    )
    assert not is_system_process(make_details())


def test_confirmation_identity_contains_pid_name_and_path():
    details = make_details()

    text = format_process_identity(details)

    assert "PID: 1234" in text
    assert "Nombre: notepad.exe" in text
    assert r"C:\Program Files\App\notepad.exe" in text


def test_kill_process_blocks_pythonkni_own_pid():
    window = SimpleNamespace(table=FakeTable(os.getpid()))

    with (
        patch("tools.process_manager_tool.QMessageBox.warning") as warning,
        patch("tools.process_manager_tool.psutil.Process") as process,
    ):
        Tool.kill_process(window)

    warning.assert_called_once()
    process.assert_not_called()


def test_kill_process_requires_confirmation_before_terminate():
    window = SimpleNamespace(table=FakeTable(1234), load_processes=Mock())
    proc = Mock(pid=1234)
    details = make_details()

    with (
        patch("tools.process_manager_tool.psutil.Process", return_value=proc),
        patch("tools.process_manager_tool.get_process_details", return_value=details),
        patch("tools.process_manager_tool.QMessageBox.question", return_value=QMessageBox.No) as question,
    ):
        Tool.kill_process(window)

    proc.terminate.assert_not_called()
    prompt = question.call_args.args[2]
    assert "PID: 1234" in prompt
    assert "Nombre: notepad.exe" in prompt
    assert details.exe_path in prompt


def test_kill_process_requires_second_confirmation_for_system_process():
    window = SimpleNamespace(table=FakeTable(1234), load_processes=Mock())
    proc = Mock(pid=1234)
    details = make_details(
        name="svchost.exe",
        exe_path=r"C:\Windows\System32\svchost.exe",
        username=r"NT AUTHORITY\SYSTEM",
    )

    with (
        patch("tools.process_manager_tool.psutil.Process", return_value=proc),
        patch("tools.process_manager_tool.get_process_details", return_value=details),
        patch(
            "tools.process_manager_tool.QMessageBox.question",
            side_effect=[QMessageBox.Yes, QMessageBox.No],
        ) as question,
    ):
        Tool.kill_process(window)

    assert question.call_count == 2
    proc.terminate.assert_not_called()


def test_kill_process_terminates_after_confirmations_and_identity_check():
    window = SimpleNamespace(table=FakeTable(1234), load_processes=Mock())
    proc = Mock(pid=1234)
    proc.is_running.return_value = True
    proc.create_time.return_value = 100.0
    details = make_details()

    with (
        patch("tools.process_manager_tool.psutil.Process", return_value=proc),
        patch("tools.process_manager_tool.get_process_details", return_value=details),
        patch("tools.process_manager_tool.QMessageBox.question", return_value=QMessageBox.Yes),
        patch("tools.process_manager_tool.QMessageBox.information"),
    ):
        Tool.kill_process(window)

    proc.terminate.assert_called_once_with()
    window.load_processes.assert_called_once_with()


def test_kill_process_aborts_if_pid_identity_changes():
    window = SimpleNamespace(table=FakeTable(1234), load_processes=Mock())
    proc = Mock(pid=1234)
    proc.is_running.return_value = True
    proc.create_time.return_value = 101.0
    details = make_details(create_time=100.0)

    with (
        patch("tools.process_manager_tool.psutil.Process", return_value=proc),
        patch("tools.process_manager_tool.get_process_details", return_value=details),
        patch("tools.process_manager_tool.QMessageBox.question", return_value=QMessageBox.Yes),
        patch("tools.process_manager_tool.QMessageBox.warning") as warning,
    ):
        Tool.kill_process(window)

    warning.assert_called_once()
    proc.terminate.assert_not_called()
    window.load_processes.assert_not_called()
