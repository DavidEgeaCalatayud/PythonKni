from __future__ import annotations

import subprocess
import threading
from pathlib import Path

import pytest

from pythonkni.network import fingerprinting
from pythonkni.network.models import OpenPort, ServiceFingerprint


def test_build_nerva_command_is_bounded_and_never_enables_misconfigs():
    command = fingerprinting.build_nerva_command(
        Path("nerva.exe"),
        "192.0.2.10",
        [OpenPort(443, "https"), 22, 443],
        timeout_ms=1500,
        workers=8,
        max_host_connections=3,
    )

    assert command == [
        "nerva.exe",
        "--json",
        "--targets",
        "192.0.2.10:22,192.0.2.10:443",
        "--timeout",
        "1500",
        "--workers",
        "8",
        "--max-host-conn",
        "3",
    ]
    assert "--misconfigs" not in command
    assert "--udp" not in command
    assert "--sctp" not in command


def test_build_nerva_command_rejects_invalid_limits():
    with pytest.raises(ValueError):
        fingerprinting.build_nerva_command("nerva.exe", "192.0.2.1", [])
    with pytest.raises(ValueError):
        fingerprinting.build_nerva_command("nerva.exe", "192.0.2.1", [0])
    with pytest.raises(ValueError):
        fingerprinting.build_nerva_command("nerva.exe", "192.0.2.1", [80], workers=0)


def test_parse_nerva_output_accepts_single_json_object_and_preserves_metadata():
    results = fingerprinting.parse_nerva_output(
        '{"host":"server.local","ip":"192.0.2.5","port":22,"protocol":"SSH",'
        '"transport":"TCP","metadata":{"product":"OpenSSH","version":"9.8"},'
        '"banner":"SSH-2.0-OpenSSH_9.8"}'
    )

    assert results == [
        ServiceFingerprint(
            host="server.local",
            ip="192.0.2.5",
            port=22,
            protocol="ssh",
            transport="tcp",
            product="OpenSSH",
            version="9.8",
            metadata={
                "product": "OpenSSH",
                "version": "9.8",
                "banner": "SSH-2.0-OpenSSH_9.8",
            },
        )
    ]


def test_parse_nerva_output_accepts_ndjson_and_sorts_results():
    output = "\n".join(
        [
            '{"host":"x","ip":"192.0.2.2","port":443,"protocol":"https","metadata":{}}',
            '{"host":"x","ip":"192.0.2.2","port":22,"protocol":"ssh","metadata":{}}',
        ]
    )

    results = fingerprinting.parse_nerva_output(output)

    assert [(item.port, item.protocol) for item in results] == [(22, "ssh"), (443, "https")]


def test_parse_nerva_output_rejects_malformed_or_incomplete_results():
    with pytest.raises(ValueError, match="JSON no válido"):
        fingerprinting.parse_nerva_output('{"host":')
    with pytest.raises(ValueError, match="puerto válido"):
        fingerprinting.parse_nerva_output('{"protocol":"ssh"}')
    with pytest.raises(ValueError, match="sin protocolo"):
        fingerprinting.parse_nerva_output('{"port":22}')


def test_parse_nerva_output_can_keep_complete_entries_from_cancelled_partial_stream():
    output = (
        '{"host":"x","ip":"192.0.2.2","port":22,"protocol":"ssh"}\n'
        '{"host":"x","port":443'
    )

    results = fingerprinting.parse_nerva_output(output, allow_partial=True)

    assert [(item.port, item.protocol) for item in results] == [(22, "ssh")]


def test_resolve_nerva_executable_reports_missing_engine(monkeypatch, tmp_path):
    monkeypatch.delenv("PYTHONKNI_NERVA_PATH", raising=False)
    monkeypatch.setattr(fingerprinting, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(fingerprinting.shutil, "which", lambda _name: None)

    with pytest.raises(fingerprinting.FingerprintEngineUnavailable, match="Nerva no está disponible"):
        fingerprinting.resolve_nerva_executable()


def test_fingerprint_open_ports_pre_cancelled_does_not_launch_process():
    stop_event = threading.Event()
    stop_event.set()

    def should_not_launch(*_args, **_kwargs):
        raise AssertionError("process must not start")

    assert (
        fingerprinting.fingerprint_open_ports(
            "example.test",
            [22],
            stop_event=stop_event,
            popen_factory=should_not_launch,
        )
        == []
    )


class _CompletedProcess:
    def __init__(self, stdout: str, stderr: str = "", returncode: int = 0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.command = None
        self.kwargs = None

    def communicate(self, timeout=None):
        return self.stdout, self.stderr

    def terminate(self):
        self.returncode = -15

    def kill(self):
        self.returncode = -9


def test_fingerprint_open_ports_runs_pinned_style_command_and_emits_results(monkeypatch, tmp_path):
    engine = tmp_path / "nerva.exe"
    engine.write_bytes(b"engine")
    process = _CompletedProcess(
        '{"host":"192.0.2.20","ip":"192.0.2.20","port":6379,"protocol":"redis",'
        '"metadata":{"version":"7.4"}}'
    )

    def fake_popen(command, **kwargs):
        process.command = command
        process.kwargs = kwargs
        return process

    monkeypatch.setattr(fingerprinting.socket, "gethostbyname", lambda _target: "192.0.2.20")
    found = []

    results = fingerprinting.fingerprint_open_ports(
        "cache.local",
        [OpenPort(6379, "redis")],
        executable=engine,
        on_found=found.append,
        popen_factory=fake_popen,
    )

    assert results == found
    assert results[0].protocol == "redis"
    assert results[0].version == "7.4"
    assert process.command is not None
    assert process.command[0] == str(engine.resolve())
    assert "--misconfigs" not in process.command
    assert process.kwargs["shell"] is False


def test_fingerprint_open_ports_wraps_nonzero_exit(monkeypatch, tmp_path):
    engine = tmp_path / "nerva.exe"
    engine.write_bytes(b"engine")
    process = _CompletedProcess("", "connection failed", returncode=2)
    monkeypatch.setattr(fingerprinting.socket, "gethostbyname", lambda _target: "192.0.2.20")

    with pytest.raises(fingerprinting.FingerprintExecutionError, match="código 2"):
        fingerprinting.fingerprint_open_ports(
            "cache.local",
            [6379],
            executable=engine,
            popen_factory=lambda *_args, **_kwargs: process,
        )


def test_stop_process_escalates_after_grace_timeout():
    class SlowProcess(_CompletedProcess):
        def __init__(self):
            super().__init__("")
            self.calls = 0
            self.killed = False

        def communicate(self, timeout=None):
            self.calls += 1
            if self.calls == 1:
                raise subprocess.TimeoutExpired("nerva", timeout)
            return "", ""

        def kill(self):
            self.killed = True

    process = SlowProcess()
    assert fingerprinting._stop_process(process) == ("", "")
    assert process.killed is True
