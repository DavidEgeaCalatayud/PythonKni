from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch

import psutil
import pytest
from PyQt5.QtWidgets import QMessageBox

from pythonkni.process_manager import service
from tools.process_manager_tool import (
    OwnProcessTerminationError,
    ProcessDetails,
    ProcessIdentityChangedError,
    ProcessUnavailableError,
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


def test_service_blocks_own_pid_before_touching_psutil():
    with patch("pythonkni.process_manager.service.psutil.Process") as process:
        with pytest.raises(OwnProcessTerminationError):
            service.get_termination_target(42, app_pid=42)

    process.assert_not_called()


def test_service_gets_a_stable_termination_target():
    proc = Mock(pid=1234)
    details = make_details()

    with ExitStack() as stack:
        process = stack.enter_context(
            patch("pythonkni.process_manager.service.psutil.Process", return_value=proc)
        )
        get_details = stack.enter_context(
            patch("pythonkni.process_manager.service.get_process_details", return_value=details)
        )
        result = service.get_termination_target(1234, app_pid=9999)

    assert result == details
    process.assert_called_once_with(1234)
    get_details.assert_called_once_with(proc)


def test_service_maps_unavailable_process_to_domain_error():
    with patch(
        "pythonkni.process_manager.service.psutil.Process",
        side_effect=psutil.AccessDenied(pid=1234),
    ):
        with pytest.raises(ProcessUnavailableError):
            service.get_termination_target(1234, app_pid=9999)


def test_service_terminates_only_after_identity_revalidation():
    details = make_details()
    proc = Mock(pid=details.pid)
    proc.is_running.return_value = True
    proc.create_time.return_value = details.create_time

    with patch("pythonkni.process_manager.service.psutil.Process", return_value=proc):
        service.terminate_process(details)

    proc.terminate.assert_called_once_with()


def test_service_refuses_recycled_pid_before_termination():
    details = make_details(create_time=100.0)
    proc = Mock(pid=details.pid)
    proc.is_running.return_value = True
    proc.create_time.return_value = 101.0

    with patch("pythonkni.process_manager.service.psutil.Process", return_value=proc):
        with pytest.raises(ProcessIdentityChangedError):
            service.terminate_process(details)

    proc.terminate.assert_not_called()


def test_kill_process_surfaces_own_process_protection():
    window = SimpleNamespace(table=FakeTable(1234), load_processes=Mock())

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "tools.process_manager_tool.get_termination_target",
                side_effect=OwnProcessTerminationError("protegido"),
            )
        )
        terminate = stack.enter_context(patch("tools.process_manager_tool.terminate_process"))
        warning = stack.enter_context(patch("tools.process_manager_tool.QMessageBox.warning"))
        Tool.kill_process(window)

    warning.assert_called_once()
    terminate.assert_not_called()
    window.load_processes.assert_not_called()


def test_kill_process_requires_confirmation_before_service_termination():
    window = SimpleNamespace(table=FakeTable(1234), load_processes=Mock())
    details = make_details()

    with ExitStack() as stack:
        stack.enter_context(
            patch("tools.process_manager_tool.get_termination_target", return_value=details)
        )
        terminate = stack.enter_context(patch("tools.process_manager_tool.terminate_process"))
        question = stack.enter_context(
            patch(
                "tools.process_manager_tool.QMessageBox.question",
                return_value=QMessageBox.No,
            )
        )
        Tool.kill_process(window)

    terminate.assert_not_called()
    prompt = question.call_args.args[2]
    assert "PID: 1234" in prompt
    assert "Nombre: notepad.exe" in prompt
    assert details.exe_path in prompt


def test_kill_process_requires_second_confirmation_for_system_process():
    window = SimpleNamespace(table=FakeTable(1234), load_processes=Mock())
    details = make_details(
        name="svchost.exe",
        exe_path=r"C:\Windows\System32\svchost.exe",
        username=r"NT AUTHORITY\SYSTEM",
    )

    with ExitStack() as stack:
        stack.enter_context(
            patch("tools.process_manager_tool.get_termination_target", return_value=details)
        )
        terminate = stack.enter_context(patch("tools.process_manager_tool.terminate_process"))
        question = stack.enter_context(
            patch(
                "tools.process_manager_tool.QMessageBox.question",
                side_effect=[QMessageBox.Yes, QMessageBox.No],
            )
        )
        Tool.kill_process(window)

    assert question.call_count == 2
    terminate.assert_not_called()


def test_kill_process_delegates_termination_after_confirmations():
    window = SimpleNamespace(table=FakeTable(1234), load_processes=Mock())
    details = make_details()

    with ExitStack() as stack:
        stack.enter_context(
            patch("tools.process_manager_tool.get_termination_target", return_value=details)
        )
        terminate = stack.enter_context(patch("tools.process_manager_tool.terminate_process"))
        stack.enter_context(
            patch(
                "tools.process_manager_tool.QMessageBox.question",
                return_value=QMessageBox.Yes,
            )
        )
        stack.enter_context(patch("tools.process_manager_tool.QMessageBox.information"))
        Tool.kill_process(window)

    terminate.assert_called_once_with(details)
    window.load_processes.assert_called_once_with()


def test_kill_process_surfaces_identity_change_from_service():
    window = SimpleNamespace(table=FakeTable(1234), load_processes=Mock())
    details = make_details()

    with ExitStack() as stack:
        stack.enter_context(
            patch("tools.process_manager_tool.get_termination_target", return_value=details)
        )
        stack.enter_context(
            patch(
                "tools.process_manager_tool.QMessageBox.question",
                return_value=QMessageBox.Yes,
            )
        )
        stack.enter_context(
            patch(
                "tools.process_manager_tool.terminate_process",
                side_effect=ProcessIdentityChangedError("cambió"),
            )
        )
        warning = stack.enter_context(patch("tools.process_manager_tool.QMessageBox.warning"))
        Tool.kill_process(window)

    warning.assert_called_once()
    window.load_processes.assert_not_called()
