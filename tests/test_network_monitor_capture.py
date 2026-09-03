from __future__ import annotations

import subprocess

import pytest

from pythonkni.network_monitor import capture


def completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(["pktmon"], returncode, stdout=stdout, stderr=stderr)


def enable_pktmon(monkeypatch):
    monkeypatch.setattr(capture, "pktmon_path", lambda: r"C:\\Windows\\System32\\pktmon.exe")


def test_pktmon_path_requires_windows(monkeypatch):
    monkeypatch.setattr(capture.os, "name", "posix")
    assert capture.pktmon_path() is None
    monkeypatch.setattr(capture.os, "name", "nt")
    monkeypatch.setattr(
        capture.shutil, "which", lambda name: r"C:\\Windows\\System32\\pktmon.exe"
    )
    assert capture.pktmon_path().endswith("pktmon.exe")


def test_start_and_stop_capture(monkeypatch, tmp_path):
    enable_pktmon(monkeypatch)
    commands = []

    def fake_run(command):
        commands.append(command)
        return completed()

    monkeypatch.setattr(capture, "_run", fake_run)
    monitor = capture.PktmonCapture(tmp_path)
    etl = monitor.start()
    assert monitor.active is True
    assert etl.suffix == ".etl"
    assert commands[0][1:4] == ["start", "--capture", "--comp"]
    result = monitor.stop()
    assert monitor.active is False
    assert result.etl_path.endswith(".etl")
    assert result.pcapng_path.endswith(".pcapng")
    assert commands[1][1:] == ["stop"]
    assert commands[2][1] == "etl2pcap"


def test_capture_rejects_unavailable_duplicate_and_missing_stop(monkeypatch, tmp_path):
    monkeypatch.setattr(capture, "pktmon_path", lambda: None)
    monitor = capture.PktmonCapture(tmp_path)
    assert monitor.available is False
    with pytest.raises(capture.PacketCaptureError, match="not available"):
        monitor.start()

    enable_pktmon(monkeypatch)
    monkeypatch.setattr(capture, "_run", lambda command: completed())
    monitor.start()
    with pytest.raises(capture.PacketCaptureError, match="already active"):
        monitor.start()
    monitor.active = False
    with pytest.raises(capture.PacketCaptureError, match="No PythonKni"):
        monitor.stop()


def test_failed_start_never_claims_session_ownership(monkeypatch, tmp_path):
    enable_pktmon(monkeypatch)
    monkeypatch.setattr(capture, "_run", lambda command: completed(5, stderr="access denied"))
    monitor = capture.PktmonCapture(tmp_path)
    with pytest.raises(capture.PacketCaptureError, match="access denied"):
        monitor.start()
    assert monitor.active is False


def test_failed_stop_releases_local_ownership_without_conversion(monkeypatch, tmp_path):
    enable_pktmon(monkeypatch)
    calls = []

    def fake_run(command):
        calls.append(command)
        if len(calls) == 2:
            return completed(1, stderr="stop failed")
        return completed()

    monkeypatch.setattr(capture, "_run", fake_run)
    monitor = capture.PktmonCapture(tmp_path)
    monitor.start()
    with pytest.raises(capture.PacketCaptureError, match="stop failed"):
        monitor.stop()
    assert monitor.active is False
    assert len(calls) == 2


def test_conversion_failure_is_reported(monkeypatch, tmp_path):
    enable_pktmon(monkeypatch)
    calls = []

    def fake_run(command):
        calls.append(command)
        if len(calls) == 3:
            return completed(2, stdout="conversion failed")
        return completed()

    monkeypatch.setattr(capture, "_run", fake_run)
    monitor = capture.PktmonCapture(tmp_path)
    monitor.start()
    with pytest.raises(capture.PacketCaptureError, match="conversion failed"):
        monitor.stop()


def test_run_wraps_os_and_timeout_errors(monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("boom")

    monkeypatch.setattr(capture.subprocess, "run", fail)
    with pytest.raises(capture.PacketCaptureError, match="boom"):
        capture._run(["pktmon", "status"])
