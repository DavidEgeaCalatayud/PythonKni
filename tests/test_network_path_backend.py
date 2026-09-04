from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from pythonkni.network_path import backend
from pythonkni.network_path.models import AddressFamily, TraceProtocol, TraceRequest


def request(protocol=TraceProtocol.ICMP, *, port=None):
    return TraceRequest(
        "8.8.8.8",
        protocol=protocol,
        interval_seconds=1.0,
        max_ttl=30,
        port=port,
        address_family=AddressFamily.AUTO,
    )


def report(*, target="8.8.8.8", reached=True):
    hops = [
        {
            "ttl": 1,
            "hosts": [{"ip": "192.168.1.1", "hostname": "router.local."}],
            "loss_pct": "0.00",
            "sent": 1,
            "last": "1.20",
            "recv": 1,
            "avg": "1.20",
            "best": "1.20",
            "worst": "1.20",
            "stddev": "0.00",
        },
        {
            "ttl": 2,
            "hosts": (
                [{"ip": target, "hostname": "dns.google."}, {"ip": target, "hostname": "dns.google."}]
                if reached
                else []
            ),
            "loss_pct": "0.00" if reached else "100.00",
            "sent": 1,
            "last": "31.50" if reached else "0.00",
            "recv": 1 if reached else 0,
        },
    ]
    return json.dumps(
        {
            "info": {"target": {"ip": target, "hostname": "dns.google."}},
            "hops": hops,
        }
    )


def test_effective_ports_and_trace_command_are_protocol_specific(tmp_path):
    executable = tmp_path / "trip.exe"
    config = tmp_path / "config.toml"
    icmp = backend.build_trace_command(executable, request(), config_file=config)
    assert icmp[0] == str(executable)
    assert "--mode" in icmp and "json" in icmp
    assert "--report-cycles" in icmp
    assert "--target-port" not in icmp
    assert "--dns-resolve-method" in icmp and "system" in icmp

    udp = backend.build_trace_command(
        executable, request(TraceProtocol.UDP), config_file=config
    )
    assert udp[udp.index("--target-port") + 1] == "33434"
    assert udp[udp.index("--multipath-strategy") + 1] == "dublin"

    tcp = backend.build_trace_command(
        executable, request(TraceProtocol.TCP, port=8443), config_file=config
    )
    assert tcp[tcp.index("--target-port") + 1] == "8443"
    assert "--multipath-strategy" not in tcp
    assert backend.effective_port(request(TraceProtocol.TCP)) == 443


def test_duration_argument_has_safe_lower_bound():
    assert backend._duration_argument(0.01) == "250ms"
    assert backend._duration_argument(1.25) == "1250ms"


def test_parse_trippy_report_normalizes_hosts_and_destination():
    snapshot = backend.parse_trippy_report(report(), request(), timestamp=123.0)
    assert snapshot.timestamp == 123.0
    assert snapshot.target_ip == "8.8.8.8"
    assert snapshot.target_hostname == "dns.google"
    assert snapshot.reached_destination is True
    assert snapshot.destination_hop is not None
    assert snapshot.destination_hop.ttl == 2
    assert snapshot.hops[0].primary_hostname == "router.local"
    assert len(snapshot.hops[1].hosts) == 1
    assert snapshot.hops[1].last_ms == 31.5


def test_parse_report_handles_loss_and_invalid_shapes():
    snapshot = backend.parse_trippy_report(report(reached=False), request())
    assert snapshot.reached_destination is False
    assert snapshot.hops[1].loss_pct == 100.0
    assert snapshot.hops[1].responded is False

    with pytest.raises(backend.TrippyExecutionError, match="JSON"):
        backend.parse_trippy_report("{", request())
    with pytest.raises(backend.TrippyExecutionError, match="estructura"):
        backend.parse_trippy_report([], request())
    with pytest.raises(backend.TrippyExecutionError, match="lista de saltos"):
        backend.parse_trippy_report({"info": {}}, request())


def test_parse_report_uses_computed_loss_when_missing():
    payload = {
        "info": {"target": {"ip": "8.8.8.8", "hostname": ""}},
        "hops": [{"ttl": 1, "hosts": [], "sent": 4, "recv": 3, "last": None}],
    }
    snapshot = backend.parse_trippy_report(payload, request())
    assert snapshot.hops[0].loss_pct == 25.0
    assert snapshot.hops[0].last_ms is None


def test_resolve_trippy_executable_precedence(tmp_path, monkeypatch):
    explicit = tmp_path / "explicit.exe"
    explicit.write_bytes(b"x")
    assert backend.resolve_trippy_executable(explicit) == explicit.resolve()

    configured = tmp_path / "env.exe"
    configured.write_bytes(b"x")
    monkeypatch.setenv("PYTHONKNI_TRIPPY_PATH", str(configured))
    assert backend.resolve_trippy_executable() == configured.resolve()

    monkeypatch.delenv("PYTHONKNI_TRIPPY_PATH")
    monkeypatch.setattr(backend, "PROJECT_ROOT", tmp_path / "missing")
    path_trip = tmp_path / "trip.exe"
    path_trip.write_bytes(b"x")
    monkeypatch.setattr(backend.shutil, "which", lambda name: str(path_trip) if name == "trip" else None)
    assert backend.resolve_trippy_executable() == path_trip.resolve()

    path_trip.unlink()
    monkeypatch.setattr(backend.shutil, "which", lambda _name: None)
    with pytest.raises(backend.TrippyUnavailable):
        backend.resolve_trippy_executable()


def test_clean_environment_removes_trip_overrides(monkeypatch):
    monkeypatch.setenv("TRIP_MODE", "tui")
    monkeypatch.setenv("SAFE_KEY", "value")
    cleaned = backend._clean_environment()
    assert "TRIP_MODE" not in cleaned
    assert cleaned["SAFE_KEY"] == "value"


def test_windows_is_elevated_is_platform_aware(monkeypatch):
    monkeypatch.setattr(backend.sys, "platform", "linux")
    assert backend.windows_is_elevated() is True

    monkeypatch.setattr(backend.sys, "platform", "win32")
    fake_shell = SimpleNamespace(IsUserAnAdmin=lambda: 1)
    monkeypatch.setattr(backend.ctypes, "windll", SimpleNamespace(shell32=fake_shell), raising=False)
    assert backend.windows_is_elevated() is True

    fake_shell.IsUserAnAdmin = lambda: 0
    assert backend.windows_is_elevated() is False


def test_backend_info_validates_version(tmp_path):
    executable = tmp_path / "trip.exe"
    executable.write_bytes(b"x")

    def run_ok(*_args, **_kwargs):
        return subprocess.CompletedProcess([], 0, stdout="trip 0.13.0\n", stderr="")

    info = backend.TrippyBackend(executable, run_command=run_ok).info()
    assert info.name == "Trippy"
    assert info.version == "0.13.0"
    assert info.executable == executable.resolve()

    def run_bad_version(*_args, **_kwargs):
        return subprocess.CompletedProcess([], 0, stdout="trip 0.12.0\n", stderr="")

    with pytest.raises(backend.TrippyVersionUnsupported):
        backend.TrippyBackend(executable, run_command=run_bad_version).info()

    def run_bad(*_args, **_kwargs):
        return subprocess.CompletedProcess([], 2, stdout="", stderr="broken")

    with pytest.raises(backend.TrippyExecutionError, match="versión"):
        backend.TrippyBackend(executable, run_command=run_bad).info()


class FakeProcess:
    def __init__(self, stdout: bytes, stderr: bytes = b"", returncode: int = 0):
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode
        self.terminated = False
        self.killed = False

    def communicate(self, timeout=None):
        del timeout
        return self._stdout, self._stderr

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        del timeout
        return self.returncode


def test_trace_once_runs_json_contract(tmp_path, monkeypatch):
    executable = tmp_path / "trip.exe"
    executable.write_bytes(b"x")
    process = FakeProcess(report().encode())
    captured = {}

    def popen(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return process

    monkeypatch.setattr(backend.sys, "platform", "linux")
    instance = backend.TrippyBackend(executable, popen_factory=popen)
    stop_event = SimpleNamespace(is_set=lambda: False)
    snapshot = instance.trace_once(request(), stop_event=stop_event)
    assert snapshot.reached_destination is True
    assert "--config-file" in captured["command"]
    assert captured["kwargs"]["shell"] is False


def test_trace_once_refuses_non_elevated_windows(tmp_path, monkeypatch):
    executable = tmp_path / "trip.exe"
    executable.write_bytes(b"x")
    monkeypatch.setattr(backend.sys, "platform", "win32")
    monkeypatch.setattr(backend, "windows_is_elevated", lambda: False)
    with pytest.raises(backend.TrippyPrivilegesRequired):
        backend.TrippyBackend(executable).trace_once(
            request(), stop_event=SimpleNamespace(is_set=lambda: False)
        )


def test_trace_once_reports_process_failure_and_output_limit(tmp_path, monkeypatch):
    executable = tmp_path / "trip.exe"
    executable.write_bytes(b"x")
    monkeypatch.setattr(backend.sys, "platform", "linux")

    failed = backend.TrippyBackend(
        executable, popen_factory=lambda *_args, **_kwargs: FakeProcess(b"", b"denied", 2)
    )
    with pytest.raises(backend.TrippyExecutionError, match="código 2"):
        failed.trace_once(request(), stop_event=SimpleNamespace(is_set=lambda: False))

    monkeypatch.setattr(backend, "MAX_OUTPUT_BYTES", 2)
    oversized = backend.TrippyBackend(
        executable, popen_factory=lambda *_args, **_kwargs: FakeProcess(b"{}{}")
    )
    with pytest.raises(backend.TrippyExecutionError, match="límite"):
        oversized.trace_once(request(), stop_event=SimpleNamespace(is_set=lambda: False))


def test_trace_once_cancels_active_process(tmp_path, monkeypatch):
    executable = tmp_path / "trip.exe"
    executable.write_bytes(b"x")
    monkeypatch.setattr(backend.sys, "platform", "linux")
    process = FakeProcess(b"")
    process.returncode = None
    instance = backend.TrippyBackend(
        executable, popen_factory=lambda *_args, **_kwargs: process
    )
    with pytest.raises(backend.TraceCancelled):
        instance.trace_once(request(), stop_event=SimpleNamespace(is_set=lambda: True))
    assert process.terminated is True
