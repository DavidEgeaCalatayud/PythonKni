from __future__ import annotations

import io
import subprocess
import threading
from pathlib import Path

import pytest

from pythonkni.secure_transfer import tailcat_backend as backend

TOKEN = "tc" + "A" * 32


class FakeProcess:
    def __init__(
        self,
        *,
        stdout: bytes = b"",
        stderr: bytes = b"",
        returncode: int | None = 0,
    ) -> None:
        self.stdout = io.BytesIO(stdout)
        self.stderr = io.BytesIO(stderr)
        self.returncode = returncode
        self.terminated = False
        self.killed = False
        self.communicated = []

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def kill(self):
        self.killed = True
        self.returncode = -9

    def communicate(self, input=None, timeout=None):
        self.communicated.append((input, timeout))
        return self.stdout.read(), self.stderr.read()


class DelayedTextProcess(FakeProcess):
    def __init__(self, payload: bytes):
        super().__init__(
            stdout=(f'{{"listenAddr":"{TOKEN}"}}\n'.encode() + payload),
            stderr=b"",
            returncode=None,
        )
        self.poll_count = 0

    def poll(self):
        self.poll_count += 1
        if self.poll_count >= 2:
            self.returncode = 0
        return self.returncode


@pytest.mark.parametrize("value", [TOKEN, "  " + TOKEN + "  "])
def test_validate_address_shape_accepts_tailcat_address(value):
    assert backend.validate_address_shape(value) == TOKEN


@pytest.mark.parametrize("value", ["", "example.com", "tc-short", "TC" + "A" * 40])
def test_validate_address_shape_rejects_invalid_values(value):
    with pytest.raises(backend.TailcatAddressError):
        backend.validate_address_shape(value)


@pytest.mark.parametrize("value, expected", [(1, 1), ("443", 443), (65535, 65535)])
def test_normalize_port(value, expected):
    assert backend.normalize_port(value) == expected


@pytest.mark.parametrize("value", [0, 65536, "x", None])
def test_normalize_port_rejects_bad_values(value):
    with pytest.raises(ValueError):
        backend.normalize_port(value)


def test_command_builders_force_ephemeral_keys_and_loopback(tmp_path):
    exe = tmp_path / "tailcat.exe"
    file_path = tmp_path / "a.txt"
    receive = backend.build_receive_command(exe, tmp_path, accept_directories=True)
    assert receive == [str(exe), "--json", "--key=new", "recv", "--accept-dirs", str(tmp_path)]
    assert backend.build_send_path_command(exe, TOKEN, file_path, recursive=True) == [
        str(exe),
        "--key=new",
        "cp",
        "-r",
        str(file_path),
        f"{TOKEN}:",
    ]
    assert backend.build_send_text_command(exe, TOKEN) == [str(exe), "--key=new", TOKEN]
    assert backend.build_receive_text_command(exe) == [str(exe), "--json", "--key=new"]
    assert backend.build_serve_port_command(exe, 8080)[-2:] == ["serve", "8080"]
    forward = backend.build_forward_command(exe, TOKEN, remote_port=8080, local_port=18080)
    assert "--bind=127.0.0.1" in forward
    assert "0.0.0.0" not in " ".join(forward)
    assert forward[-2:] == [TOKEN, "18080:8080"]


def test_resolve_tailcat_executable_prefers_explicit_path(tmp_path):
    executable = tmp_path / "tailcat.exe"
    executable.write_bytes(b"x")
    assert backend.resolve_tailcat_executable(executable) == executable.resolve()


def test_resolve_tailcat_executable_uses_environment(tmp_path, monkeypatch):
    executable = tmp_path / "env-tailcat.exe"
    executable.write_bytes(b"x")
    monkeypatch.setenv("PYTHONKNI_TAILCAT_PATH", str(executable))
    assert backend.resolve_tailcat_executable() == executable.resolve()


def test_resolve_tailcat_executable_reports_missing(monkeypatch, tmp_path):
    monkeypatch.delenv("PYTHONKNI_TAILCAT_PATH", raising=False)
    monkeypatch.setattr(backend, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(backend.shutil, "which", lambda _name: None)
    with pytest.raises(backend.TailcatUnavailable, match="fetch_tailcat"):
        backend.resolve_tailcat_executable()


def test_require_scp_executable(tmp_path, monkeypatch):
    scp = tmp_path / "scp.exe"
    scp.write_bytes(b"x")
    monkeypatch.setattr(backend.shutil, "which", lambda name: str(scp) if name == "scp" else None)
    assert backend.require_scp_executable() == scp.resolve()
    monkeypatch.setattr(backend.shutil, "which", lambda _name: None)
    with pytest.raises(backend.TailcatUnavailable, match="OpenSSH"):
        backend.require_scp_executable()


def _run_result(stdout="tailcat v0.5.0\n", stderr="", returncode=0):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def test_info_accepts_only_pinned_version(tmp_path):
    exe = tmp_path / "tailcat.exe"
    exe.write_bytes(b"x")
    seen = []

    def runner(command, **kwargs):
        seen.append((command, kwargs))
        return _run_result()

    instance = backend.TailcatBackend(exe, run_command=runner)
    info = instance.info()
    assert info.version == "0.5.0"
    assert info.executable == exe.resolve()
    assert seen[0][0][-1] == "version"
    assert seen[0][1]["shell"] is False


def test_info_rejects_other_version_and_bad_output(tmp_path):
    exe = tmp_path / "tailcat.exe"
    exe.write_bytes(b"x")
    instance = backend.TailcatBackend(exe, run_command=lambda *a, **k: _run_result("v0.6.0"))
    with pytest.raises(backend.TailcatVersionUnsupported):
        instance.info()
    instance = backend.TailcatBackend(exe, run_command=lambda *a, **k: _run_result("devel"))
    with pytest.raises(backend.TailcatExecutionError, match="versión"):
        instance.info()
    instance = backend.TailcatBackend(
        exe,
        run_command=lambda *a, **k: _run_result("", "boom", returncode=2),
    )
    with pytest.raises(backend.TailcatExecutionError, match="boom"):
        instance.info()


def test_parse_address_uses_tailcat_parse_and_validates_json(tmp_path):
    exe = tmp_path / "tailcat.exe"
    exe.write_bytes(b"x")
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        return _run_result('{"ServerPublic":"nodekey:x","RegionID":302}')

    instance = backend.TailcatBackend(exe, run_command=runner)
    assert instance.parse_address(TOKEN)["RegionID"] == 302
    assert calls == [[str(exe.resolve()), "parse", TOKEN]]

    instance = backend.TailcatBackend(exe, run_command=lambda *a, **k: _run_result("[]"))
    with pytest.raises(backend.TailcatExecutionError, match="estructura"):
        instance.parse_address(TOKEN)

    instance = backend.TailcatBackend(exe, run_command=lambda *a, **k: _run_result("not json"))
    with pytest.raises(backend.TailcatExecutionError, match="JSON"):
        instance.parse_address(TOKEN)

    instance = backend.TailcatBackend(
        exe,
        run_command=lambda *a, **k: _run_result("", "bad token", returncode=1),
    )
    with pytest.raises(backend.TailcatAddressError, match="bad token"):
        instance.parse_address(TOKEN)


def test_extract_token_finds_address_in_json():
    assert backend._extract_token({"ignored": 1, "listenAddr": TOKEN}) == TOKEN
    with pytest.raises(backend.TailcatExecutionError):
        backend._extract_token({"listenAddr": "bad"})


def test_stop_process_terminates_then_kills_on_timeout():
    process = FakeProcess(returncode=None)
    backend._stop_process(process)
    assert process.terminated is True

    class Stubborn(FakeProcess):
        def wait(self, timeout=None):
            if not self.killed:
                raise subprocess.TimeoutExpired("tailcat", timeout)
            return -9

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.killed = True
            self.returncode = -9

    stubborn = Stubborn(returncode=None)
    backend._stop_process(stubborn)
    assert stubborn.terminated and stubborn.killed


def test_wait_interruptibly_observes_cancellation(monkeypatch):
    process = FakeProcess(returncode=None)
    stop = threading.Event()
    stop.set()
    assert backend._wait_interruptibly(process, stop_event=stop) == -15
    assert process.terminated


def test_server_ready_token_parses_json_line(tmp_path):
    exe = tmp_path / "tailcat.exe"
    exe.write_bytes(b"x")
    instance = backend.TailcatBackend(exe)
    process = FakeProcess(
        stdout=f'{{"listenAddr":"{TOKEN}"}}\n'.encode(),
        returncode=None,
    )
    assert instance._server_ready_token(process, stop_event=threading.Event()) == TOKEN


def test_server_ready_token_reports_invalid_json(tmp_path):
    exe = tmp_path / "tailcat.exe"
    exe.write_bytes(b"x")
    instance = backend.TailcatBackend(exe)
    process = FakeProcess(stdout=b"oops\n", returncode=None)
    with pytest.raises(backend.TailcatExecutionError, match="JSON"):
        instance._server_ready_token(process, stop_event=threading.Event())


def test_receive_files_emits_token_and_handles_exit(tmp_path, monkeypatch):
    exe = tmp_path / "tailcat.exe"
    exe.write_bytes(b"x")
    process = FakeProcess(returncode=0)
    instance = backend.TailcatBackend(exe, popen_factory=lambda *a, **k: process)
    monkeypatch.setattr(instance, "_server_ready_token", lambda *a, **k: TOKEN)
    ready = []
    instance.receive_files(
        tmp_path,
        accept_directories=False,
        stop_event=threading.Event(),
        on_ready=ready.append,
    )
    assert ready == [TOKEN]


def test_send_path_validates_token_and_requires_scp(tmp_path, monkeypatch):
    exe = tmp_path / "tailcat.exe"
    exe.write_bytes(b"x")
    source = tmp_path / "file.txt"
    source.write_text("x")
    process = FakeProcess(returncode=0)
    spawned = []

    def factory(command, **kwargs):
        spawned.append((command, kwargs))
        return process

    instance = backend.TailcatBackend(exe, popen_factory=factory)
    monkeypatch.setattr(instance, "parse_address", lambda token: {"token": token})
    monkeypatch.setattr(backend, "require_scp_executable", lambda: Path("scp.exe"))
    instance.send_path(TOKEN, source, recursive=False, stop_event=threading.Event())
    assert spawned[0][0][-2:] == [str(source), f"{TOKEN}:"]
    assert spawned[0][1]["stdout"] == subprocess.DEVNULL
    assert spawned[0][1]["stderr"] == subprocess.DEVNULL


def test_receive_text_reads_payload(tmp_path):
    exe = tmp_path / "tailcat.exe"
    exe.write_bytes(b"x")
    process = DelayedTextProcess(b"hello")
    instance = backend.TailcatBackend(exe, popen_factory=lambda *a, **k: process)
    ready = []
    assert instance.receive_text(stop_event=threading.Event(), on_ready=ready.append) == "hello"
    assert ready == [TOKEN]


def test_receive_text_enforces_size_limit(tmp_path, monkeypatch):
    exe = tmp_path / "tailcat.exe"
    exe.write_bytes(b"x")
    monkeypatch.setattr(backend, "MAX_TEXT_BYTES", 4)
    process = DelayedTextProcess(b"12345")
    instance = backend.TailcatBackend(exe, popen_factory=lambda *a, **k: process)
    with pytest.raises(backend.TailcatExecutionError, match="límite"):
        instance.receive_text(stop_event=threading.Event())


def test_send_text_communicates_payload_and_reports_failure(tmp_path, monkeypatch):
    exe = tmp_path / "tailcat.exe"
    exe.write_bytes(b"x")
    process = FakeProcess(stderr=b"denied", returncode=0)
    instance = backend.TailcatBackend(exe, popen_factory=lambda *a, **k: process)
    monkeypatch.setattr(instance, "parse_address", lambda token: {})
    instance.send_text(TOKEN, "hello", stop_event=threading.Event())
    assert process.communicated[0][0] == b"hello"

    failed = FakeProcess(stderr=b"denied", returncode=2)
    instance = backend.TailcatBackend(exe, popen_factory=lambda *a, **k: failed)
    monkeypatch.setattr(instance, "parse_address", lambda token: {})
    with pytest.raises(backend.TailcatExecutionError, match="denied"):
        instance.send_text(TOKEN, "hello", stop_event=threading.Event())


def test_send_text_rejects_oversized_payload(tmp_path, monkeypatch):
    exe = tmp_path / "tailcat.exe"
    exe.write_bytes(b"x")
    instance = backend.TailcatBackend(exe)
    monkeypatch.setattr(instance, "parse_address", lambda token: {})
    monkeypatch.setattr(backend, "MAX_TEXT_BYTES", 3)
    with pytest.raises(ValueError, match="superar"):
        instance.send_text(TOKEN, "1234", stop_event=threading.Event())


def test_serve_port_emits_token(tmp_path, monkeypatch):
    exe = tmp_path / "tailcat.exe"
    exe.write_bytes(b"x")
    process = FakeProcess(returncode=0)
    instance = backend.TailcatBackend(exe, popen_factory=lambda *a, **k: process)
    monkeypatch.setattr(instance, "_server_ready_token", lambda *a, **k: TOKEN)
    ready = []
    instance.serve_port(8080, stop_event=threading.Event(), on_ready=ready.append)
    assert ready == [TOKEN]


def test_forward_port_is_loopback_only_and_reports_ready(tmp_path, monkeypatch):
    exe = tmp_path / "tailcat.exe"
    exe.write_bytes(b"x")
    stop = threading.Event()

    class RunningProcess(FakeProcess):
        def poll(self):
            return None if not self.terminated else self.returncode

    process = RunningProcess(returncode=None)
    commands = []
    instance = backend.TailcatBackend(
        exe,
        popen_factory=lambda command, **kwargs: commands.append(command) or process,
    )
    monkeypatch.setattr(instance, "parse_address", lambda token: {})
    monkeypatch.setattr(backend.time, "sleep", lambda _seconds: None)
    ticks = iter([0.0, 1.0])
    monkeypatch.setattr(backend.time, "monotonic", lambda: next(ticks, 1.0))

    def ready():
        stop.set()

    instance.forward_port(
        TOKEN,
        remote_port=8080,
        local_port=18080,
        stop_event=stop,
        on_ready=ready,
    )
    assert "--bind=127.0.0.1" in commands[0]
    assert process.terminated


def test_creation_flags_and_diagnostic_helpers(monkeypatch):
    monkeypatch.setattr(backend.subprocess, "CREATE_NO_WINDOW", 123, raising=False)
    assert backend._creationflags() == 123
    assert backend._decode(b"caf\xc3\xa9") == "café"
    assert backend._diagnostic(b"  one\n two  ") == "one two"


def test_resolve_tailcat_executable_uses_path(tmp_path, monkeypatch):
    executable = tmp_path / "path-tailcat.exe"
    executable.write_bytes(b"x")
    monkeypatch.delenv("PYTHONKNI_TAILCAT_PATH", raising=False)
    monkeypatch.setattr(backend, "PROJECT_ROOT", tmp_path / "missing-root")
    monkeypatch.setattr(backend.shutil, "which", lambda name: str(executable) if name == "tailcat" else None)
    assert backend.resolve_tailcat_executable() == executable.resolve()


def test_decode_none_and_wait_loop(monkeypatch):
    assert backend._decode(None) == ""

    class Polls(FakeProcess):
        def __init__(self):
            super().__init__(returncode=None)
            self.count = 0

        def poll(self):
            self.count += 1
            if self.count > 1:
                self.returncode = 0
            return self.returncode

    monkeypatch.setattr(backend.time, "sleep", lambda _seconds: None)
    assert backend._wait_interruptibly(Polls(), stop_event=threading.Event()) == 0


def test_wait_after_stream_times_out(monkeypatch):
    process = FakeProcess(returncode=None)
    monkeypatch.setattr(backend.time, "sleep", lambda _seconds: None)
    ticks = iter([0.0, 10.0])
    monkeypatch.setattr(backend.time, "monotonic", lambda: next(ticks, 10.0))
    with pytest.raises(backend.TailcatExecutionError, match="no cerró"):
        backend._wait_after_stream(process)
    assert process.terminated


def test_spawn_passes_safe_subprocess_options(tmp_path):
    exe = tmp_path / "tailcat.exe"
    exe.write_bytes(b"x")
    seen = []

    def factory(command, **kwargs):
        seen.append((command, kwargs))
        return FakeProcess()

    instance = backend.TailcatBackend(exe, popen_factory=factory)
    instance._spawn([str(exe), "version"], stdin=subprocess.DEVNULL)
    assert seen[0][1]["shell"] is False
    assert seen[0][1]["stdout"] == subprocess.PIPE


def test_server_ready_token_error_paths(tmp_path, monkeypatch):
    exe = tmp_path / "tailcat.exe"
    exe.write_bytes(b"x")
    instance = backend.TailcatBackend(exe)

    process = FakeProcess(returncode=None)
    process.stdout = None
    with pytest.raises(backend.TailcatExecutionError, match="stdout"):
        instance._server_ready_token(process, stop_event=threading.Event())

    cancelled = FakeProcess(stdout=b"", returncode=None)
    stop = threading.Event()
    stop.set()
    assert instance._server_ready_token(cancelled, stop_event=stop) == ""
    assert cancelled.terminated

    exited = FakeProcess(stdout=b"", stderr=b"startup failed", returncode=2)
    with pytest.raises(backend.TailcatExecutionError, match="startup failed"):
        instance._server_ready_token(exited, stop_event=threading.Event())

    empty = FakeProcess(stdout=b"", returncode=None)
    with pytest.raises(backend.TailcatExecutionError, match="cerró stdout"):
        instance._server_ready_token(empty, stop_event=threading.Event())

    array = FakeProcess(stdout=b"[]\n", returncode=None)
    with pytest.raises(backend.TailcatExecutionError, match="inesperado"):
        instance._server_ready_token(array, stop_event=threading.Event())


def test_receive_files_cancellation_and_error(tmp_path, monkeypatch):
    exe = tmp_path / "tailcat.exe"
    exe.write_bytes(b"x")
    instance = backend.TailcatBackend(exe, popen_factory=lambda *a, **k: FakeProcess())
    monkeypatch.setattr(instance, "_server_ready_token", lambda *a, **k: TOKEN)
    stop = threading.Event()
    stop.set()
    monkeypatch.setattr(backend, "_wait_interruptibly", lambda *a, **k: -15)
    instance.receive_files(tmp_path, accept_directories=False, stop_event=stop)

    process = FakeProcess(stderr=b"recv failed", returncode=3)
    instance = backend.TailcatBackend(exe, popen_factory=lambda *a, **k: process)
    monkeypatch.setattr(instance, "_server_ready_token", lambda *a, **k: TOKEN)
    monkeypatch.setattr(backend, "_wait_interruptibly", lambda *a, **k: 3)
    with pytest.raises(backend.TailcatExecutionError, match="recv failed"):
        instance.receive_files(tmp_path, accept_directories=False, stop_event=threading.Event())


def test_send_path_cancellation_and_error(tmp_path, monkeypatch):
    exe = tmp_path / "tailcat.exe"
    exe.write_bytes(b"x")
    source = tmp_path / "x"
    source.write_text("x")
    monkeypatch.setattr(backend, "require_scp_executable", lambda: Path("scp.exe"))

    process = FakeProcess(returncode=5)
    instance = backend.TailcatBackend(exe, popen_factory=lambda *a, **k: process)
    monkeypatch.setattr(instance, "parse_address", lambda token: {})
    with pytest.raises(backend.TailcatExecutionError, match="código 5"):
        instance.send_path(TOKEN, source, recursive=False, stop_event=threading.Event())

    stop = threading.Event()
    stop.set()
    process = FakeProcess(returncode=0)
    instance = backend.TailcatBackend(exe, popen_factory=lambda *a, **k: process)
    monkeypatch.setattr(instance, "parse_address", lambda token: {})
    instance.send_path(TOKEN, source, recursive=False, stop_event=stop)


def test_receive_text_missing_stdout_cancel_and_nonzero(tmp_path, monkeypatch):
    exe = tmp_path / "tailcat.exe"
    exe.write_bytes(b"x")

    missing = FakeProcess(returncode=None)
    missing.stdout = None
    instance = backend.TailcatBackend(exe, popen_factory=lambda *a, **k: missing)
    monkeypatch.setattr(instance, "_server_ready_token", lambda *a, **k: TOKEN)
    with pytest.raises(backend.TailcatExecutionError, match="recibir texto"):
        instance.receive_text(stop_event=threading.Event())

    stop = threading.Event()
    stop.set()
    cancelled = FakeProcess(stdout=b"payload", returncode=None)
    instance = backend.TailcatBackend(exe, popen_factory=lambda *a, **k: cancelled)
    monkeypatch.setattr(instance, "_server_ready_token", lambda *a, **k: TOKEN)
    assert instance.receive_text(stop_event=stop) == ""

    failed = FakeProcess(stdout=b"payload", stderr=b"text failed", returncode=4)
    instance = backend.TailcatBackend(exe, popen_factory=lambda *a, **k: failed)
    monkeypatch.setattr(instance, "_server_ready_token", lambda *a, **k: TOKEN)
    monkeypatch.setattr(backend, "_wait_after_stream", lambda _process: 4)
    with pytest.raises(backend.TailcatExecutionError, match="text failed"):
        instance.receive_text(stop_event=threading.Event())


def test_send_text_timeout_then_cancel(tmp_path, monkeypatch):
    exe = tmp_path / "tailcat.exe"
    exe.write_bytes(b"x")

    class TimeoutProcess(FakeProcess):
        def communicate(self, input=None, timeout=None):
            raise subprocess.TimeoutExpired("tailcat", timeout)

    process = TimeoutProcess(returncode=None)
    instance = backend.TailcatBackend(exe, popen_factory=lambda *a, **k: process)
    monkeypatch.setattr(instance, "parse_address", lambda token: {})
    stop = threading.Event()
    stop.set()
    instance.send_text(TOKEN, "hello", stop_event=stop)
    assert process.terminated


def test_send_text_timeout_then_success(tmp_path):
    exe = tmp_path / "tailcat.exe"
    exe.write_bytes(b"x")

    class OnceTimeout(FakeProcess):
        def __init__(self):
            super().__init__(returncode=None)
            self.count = 0

        def communicate(self, input=None, timeout=None):
            self.count += 1
            if self.count == 1:
                raise subprocess.TimeoutExpired("tailcat", timeout)
            self.returncode = 0
            return b"", b""

    process = OnceTimeout()
    instance = backend.TailcatBackend(exe, popen_factory=lambda *a, **k: process)
    instance.parse_address = lambda token: {}
    instance.send_text(TOKEN, "hello", stop_event=threading.Event())
    assert process.count == 2


def test_serve_port_cancellation_and_failure(tmp_path, monkeypatch):
    exe = tmp_path / "tailcat.exe"
    exe.write_bytes(b"x")
    stop = threading.Event()
    stop.set()
    process = FakeProcess(returncode=0)
    instance = backend.TailcatBackend(exe, popen_factory=lambda *a, **k: process)
    monkeypatch.setattr(instance, "_server_ready_token", lambda *a, **k: TOKEN)
    instance.serve_port(8080, stop_event=stop)

    failed = FakeProcess(stderr=b"serve failed", returncode=7)
    instance = backend.TailcatBackend(exe, popen_factory=lambda *a, **k: failed)
    monkeypatch.setattr(instance, "_server_ready_token", lambda *a, **k: TOKEN)
    with pytest.raises(backend.TailcatExecutionError, match="serve failed"):
        instance.serve_port(8080, stop_event=threading.Event())


def test_forward_port_startup_failure_and_runtime_failure(tmp_path, monkeypatch):
    exe = tmp_path / "tailcat.exe"
    exe.write_bytes(b"x")
    monkeypatch.setattr(backend.time, "sleep", lambda _seconds: None)

    exited = FakeProcess(stderr=b"bind failed", returncode=2)
    instance = backend.TailcatBackend(exe, popen_factory=lambda *a, **k: exited)
    monkeypatch.setattr(instance, "parse_address", lambda token: {})
    with pytest.raises(backend.TailcatExecutionError, match="bind failed"):
        instance.forward_port(
            TOKEN,
            remote_port=8080,
            local_port=18080,
            stop_event=threading.Event(),
        )

    class StartsThenFails(FakeProcess):
        def __init__(self):
            super().__init__(stderr=b"runtime failed", returncode=None)
            self.poll_count = 0

        def poll(self):
            self.poll_count += 1
            if self.poll_count >= 4:
                self.returncode = 9
            return self.returncode

    failed = StartsThenFails()
    ticks = iter([0.0, 1.0])
    monkeypatch.setattr(backend.time, "monotonic", lambda: next(ticks, 1.0))
    instance = backend.TailcatBackend(exe, popen_factory=lambda *a, **k: failed)
    monkeypatch.setattr(instance, "parse_address", lambda token: {})
    with pytest.raises(backend.TailcatExecutionError, match="runtime failed"):
        instance.forward_port(
            TOKEN,
            remote_port=8080,
            local_port=18080,
            stop_event=threading.Event(),
        )
