import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace

from PyQt5.QtCore import QThread

from pythonkni.core.tasks import WorkerCancelled
from tools import wifi_tool as wifi


def wifi_xml(profile: str, password: str) -> str:
    return f"""<?xml version="1.0"?>
<WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">
  <name>{profile}</name>
  <MSM>
    <security>
      <sharedKey>
        <keyMaterial>{password}</keyMaterial>
      </sharedKey>
    </security>
  </MSM>
</WLANProfile>
"""


def test_parse_profiles_accepts_english_and_spanish_labels():
    output = """
    All User Profile     : Office
    Perfil de todos los usuarios : Casa
    """

    assert wifi._parse_profiles(output) == ["Office", "Casa"]


def test_run_netsh_applies_explicit_timeout(monkeypatch):
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return SimpleNamespace(stdout="ok")

    monkeypatch.setattr(wifi.subprocess, "run", fake_run)

    assert wifi._run_netsh(["wlan", "show", "profiles"]) == "ok"
    assert captured["command"] == ["netsh", "wlan", "show", "profiles"]
    assert captured["timeout"] == wifi.NETSH_TIMEOUT_SECONDS
    assert captured["check"] is True


def test_exported_password_uses_isolated_matching_profile_xml(monkeypatch, tmp_path):
    export_dirs = []

    def fake_run(args, timeout=wifi.NETSH_TIMEOUT_SECONDS):
        del timeout
        profile = next(value.removeprefix("name=") for value in args if value.startswith("name="))
        export_dir = Path(
            next(value.removeprefix("folder=") for value in args if value.startswith("folder="))
        )
        export_dirs.append(export_dir)
        (export_dir / "a-wrong.xml").write_text(
            wifi_xml("Different profile", "wrong-password"), encoding="utf-8"
        )
        (export_dir / "b-correct.xml").write_text(
            wifi_xml(profile, "correct-password"), encoding="utf-8"
        )
        return ""

    monkeypatch.setattr(wifi, "_run_netsh", fake_run)

    password = wifi._read_exported_password("Office", tmp_path)

    assert password == "correct-password"
    assert len(export_dirs) == 1
    assert export_dirs[0].parent == tmp_path


def test_each_wifi_profile_uses_a_distinct_export_directory(monkeypatch):
    export_dirs = []

    def fake_run(args, timeout=wifi.NETSH_TIMEOUT_SECONDS):
        del timeout
        if args == ["wlan", "show", "profiles"]:
            return "All User Profile : Office\nAll User Profile : Home\n"

        profile = next(value.removeprefix("name=") for value in args if value.startswith("name="))
        export_dir = Path(
            next(value.removeprefix("folder=") for value in args if value.startswith("folder="))
        )
        export_dirs.append(export_dir)
        (export_dir / "profile.xml").write_text(
            wifi_xml(profile, f"password-{profile}"), encoding="utf-8"
        )
        return ""

    monkeypatch.setattr(wifi, "_run_netsh", fake_run)

    data = wifi.get_wifi_profiles()

    assert data == [("Office", "password-Office"), ("Home", "password-Home")]
    assert len(export_dirs) == 2
    assert export_dirs[0] != export_dirs[1]


def test_profile_list_timeout_is_reported_without_hanging(monkeypatch):
    def fake_run(_args, timeout=wifi.NETSH_TIMEOUT_SECONDS):
        raise subprocess.TimeoutExpired("netsh", timeout)

    monkeypatch.setattr(wifi, "_run_netsh", fake_run)

    assert wifi.get_wifi_profiles() == [("Error", "Tiempo de espera agotado ejecutando netsh.")]


def test_wifi_loading_runs_off_gui_thread(monkeypatch, qtbot):
    entered = threading.Event()
    release = threading.Event()
    worker_threads = []

    def fake_get_wifi_profiles(cancel_event=None):
        worker_threads.append(QThread.currentThread())
        entered.set()
        while not release.wait(0.005):
            if cancel_event is not None and cancel_event.is_set():
                raise WorkerCancelled()
        return [("Office", "secret")]

    monkeypatch.setattr(wifi, "get_wifi_profiles", fake_get_wifi_profiles)

    tool = wifi.Tool()
    qtbot.addWidget(tool)
    tool.show()
    gui_thread = QThread.currentThread()

    try:
        qtbot.waitUntil(entered.is_set, timeout=1000)
        assert worker_threads
        assert worker_threads[0] is not gui_thread
        assert not tool.btn_refresh.isEnabled()
        assert tool.btn_cancel.isEnabled()
    finally:
        release.set()
        qtbot.waitUntil(lambda: tool.worker is None, timeout=1000)

    assert tool.btn_refresh.isEnabled()
    assert not tool.btn_cancel.isEnabled()
    assert tool.table.item(0, 0).text() == "Office"
    assert tool.table.item(0, 1).text() == "secret"


def test_wifi_loading_can_be_cancelled(monkeypatch, qtbot):
    entered = threading.Event()

    def fake_get_wifi_profiles(cancel_event=None):
        entered.set()
        while cancel_event is not None and not cancel_event.wait(0.005):
            pass
        raise WorkerCancelled()

    monkeypatch.setattr(wifi, "get_wifi_profiles", fake_get_wifi_profiles)

    tool = wifi.Tool()
    qtbot.addWidget(tool)
    tool.show()
    qtbot.waitUntil(entered.is_set, timeout=1000)

    tool.cancel_loading()
    qtbot.waitUntil(lambda: tool.worker is None, timeout=1000)

    assert tool.table.item(0, 0).text() == "Carga cancelada"
    assert tool.btn_refresh.isEnabled()
    assert not tool.btn_cancel.isEnabled()
