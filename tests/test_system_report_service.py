from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest

from pythonkni.system_report import service as report


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, "0.00 B"),
        (1023, "1023.00 B"),
        (1024, "1.00 KB"),
        (1024**2, "1.00 MB"),
        (1024**3, "1.00 GB"),
        (1024**4, "1.00 TB"),
    ],
)
def test_format_bytes_units(value, expected):
    assert report.format_bytes(value) == expected


def test_safe_gethostbyname_handles_success_and_failure(monkeypatch):
    monkeypatch.setattr(report.socket, "gethostbyname", lambda _host: "192.0.2.10")
    assert report.safe_gethostbyname("host") == "192.0.2.10"

    def fail(_host):
        raise OSError("dns")

    monkeypatch.setattr(report.socket, "gethostbyname", fail)
    assert report.safe_gethostbyname("host") == "No disponible"


def test_default_gateway_is_platform_aware(monkeypatch):
    monkeypatch.setattr(report.platform, "system", lambda: "Linux")
    assert report.get_default_gateway_windows() == "Solo disponible en Windows"

    monkeypatch.setattr(report.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        report.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            stdout="Default Gateway . . . . . . . . . : 192.168.1.1\n"
        ),
    )
    assert report.get_default_gateway_windows() == "192.168.1.1"


def test_default_gateway_handles_empty_and_execution_errors(monkeypatch):
    monkeypatch.setattr(report.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        report.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            stdout="Puerta de enlace predeterminada . . . : \n"
        ),
    )
    assert report.get_default_gateway_windows() == "No disponible"

    def fail(*_args, **_kwargs):
        raise OSError("ipconfig unavailable")

    monkeypatch.setattr(report.subprocess, "run", fail)
    assert report.get_default_gateway_windows() == "No disponible"


@pytest.mark.parametrize(("returncode", "expected"), [(0, "Correcto"), (1, "Fallido")])
def test_ping_host_maps_process_status(monkeypatch, returncode, expected):
    monkeypatch.setattr(report.platform, "system", lambda: "Windows")
    captured = []

    def fake_run(command, **_kwargs):
        captured.append(command)
        return SimpleNamespace(returncode=returncode)

    monkeypatch.setattr(report.subprocess, "run", fake_run)
    assert report.ping_host("1.1.1.1") == expected
    assert captured == [["ping", "-n", "1", "1.1.1.1"]]


def test_ping_host_handles_execution_error(monkeypatch):
    monkeypatch.setattr(report.platform, "system", lambda: "Linux")

    def fail(*_args, **_kwargs):
        raise OSError("ping unavailable")

    monkeypatch.setattr(report.subprocess, "run", fail)
    assert report.ping_host() == "Fallido"


def test_folder_size_counts_files_and_honours_limit(tmp_path):
    root = tmp_path / "cache"
    root.mkdir()
    (root / "one.bin").write_bytes(b"a" * 10)
    nested = root / "nested"
    nested.mkdir()
    (nested / "two.bin").write_bytes(b"b" * 20)

    assert report.folder_size(root) == 30
    assert report.folder_size(root, max_items=1) in {10, 20}
    assert report.folder_size(tmp_path / "missing") == 0


def test_folder_size_skips_stat_errors(monkeypatch, tmp_path):
    root = tmp_path / "cache"
    root.mkdir()
    broken = root / "broken.bin"
    broken.write_bytes(b"content")
    original_stat = Path.stat

    def fake_stat(path, *args, **kwargs):
        if path == broken:
            raise OSError("locked")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", fake_stat)
    assert report.folder_size(root) == 0


def test_temp_locations_include_windows_caches_without_duplicates(monkeypatch, tmp_path):
    monkeypatch.setattr(report.platform, "system", lambda: "Windows")
    monkeypatch.setattr(report.tempfile, "gettempdir", lambda: str(tmp_path / "temp"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "profile"))

    paths = report.get_temp_locations()

    assert Path(tmp_path / "temp") in paths
    assert any("Chrome" in str(path) for path in paths)
    assert any("Firefox" in str(path) for path in paths)
    assert Path("C:/Windows/Temp") in paths
    assert len(paths) == len(set(paths))


def test_temp_locations_non_windows_only_use_system_temp(monkeypatch, tmp_path):
    monkeypatch.setattr(report.platform, "system", lambda: "Linux")
    monkeypatch.setattr(report.tempfile, "gettempdir", lambda: str(tmp_path))
    assert report.get_temp_locations() == [tmp_path]


class FakeProcess:
    def __init__(self, pid, name, memory, cpu_values, first_error=None, second_error=None):
        self.info = {"pid": pid, "name": name, "memory_percent": memory}
        self._cpu_values = iter(cpu_values)
        self._first_error = first_error
        self._second_error = second_error
        self._calls = 0

    def cpu_percent(self, interval=None):
        del interval
        self._calls += 1
        if self._calls == 1 and self._first_error:
            raise self._first_error
        if self._calls == 2 and self._second_error:
            raise self._second_error
        return next(self._cpu_values)


def test_collect_processes_samples_twice_sorts_and_filters(monkeypatch):
    good_cpu = FakeProcess(10, "cpu.exe", 5.0, [0.0, 80.0])
    good_mem = FakeProcess(11, "mem.exe", 70.0, [0.0, 10.0])
    idle = FakeProcess(0, "System Idle Process", 1.0, [0.0])
    inaccessible = FakeProcess(
        12,
        "denied.exe",
        1.0,
        [0.0],
        first_error=psutil.AccessDenied(pid=12),
    )
    disappears = FakeProcess(
        13,
        "gone.exe",
        1.0,
        [0.0],
        second_error=psutil.NoSuchProcess(pid=13),
    )
    monkeypatch.setattr(
        report.psutil,
        "process_iter",
        lambda _attrs: [good_cpu, good_mem, idle, inaccessible, disappears],
    )
    monkeypatch.setattr(report.time, "sleep", lambda _seconds: None)

    top_cpu, top_memory = report.collect_processes()

    assert top_cpu[:2] == [(10, "cpu.exe", 80.0, 5.0), (11, "mem.exe", 10.0, 70.0)]
    assert top_memory[:2] == [(11, "mem.exe", 10.0, 70.0), (10, "cpu.exe", 80.0, 5.0)]
    assert all(pid not in {0, 12, 13} for pid, *_rest in top_cpu)


def test_load_event_snapshot_missing_and_invalid_are_safe(monkeypatch, tmp_path):
    monkeypatch.setattr(report, "DATA_DIR", tmp_path)
    monkeypatch.setattr(report, "ensure_app_dirs", lambda: None)
    assert report.load_event_snapshot() == []

    (tmp_path / "event_report_snapshot.json").write_text("{", encoding="utf-8")
    assert report.load_event_snapshot() == []


def test_load_event_snapshot_honours_limit(monkeypatch, tmp_path):
    payload = {
        "events": [
            {
                "date": f"day-{index}",
                "level": "Error",
                "provider": "Disk",
                "event_id": index,
                "risk": "Alto",
                "interpretation": "Check disk",
            }
            for index in range(4)
        ]
    }
    import json

    (tmp_path / "event_report_snapshot.json").write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(report, "DATA_DIR", tmp_path)
    monkeypatch.setattr(report, "ensure_app_dirs", lambda: None)

    rows = report.load_event_snapshot(max_events=2)
    assert len(rows) == 2
    assert rows[0][0] == "day-0"


def test_collect_report_builds_all_sections(monkeypatch, tmp_path):
    monkeypatch.setattr(report.psutil, "boot_time", lambda: 1_700_000_000)
    monkeypatch.setattr(
        report.psutil,
        "virtual_memory",
        lambda: SimpleNamespace(total=16 * 1024**3, used=8 * 1024**3, percent=50.0),
    )
    monkeypatch.setattr(
        report.psutil,
        "swap_memory",
        lambda: SimpleNamespace(total=2 * 1024**3),
    )
    monkeypatch.setattr(report.psutil, "cpu_count", lambda logical=True: 8 if logical else 4)
    monkeypatch.setattr(report.psutil, "cpu_percent", lambda interval=0: 12.5)
    monkeypatch.setattr(
        report.psutil,
        "disk_partitions",
        lambda all=False: [SimpleNamespace(device="Disk0", mountpoint="C:/")],
    )
    monkeypatch.setattr(
        report.psutil,
        "disk_usage",
        lambda _mount: SimpleNamespace(total=500 * 1024**3, free=200 * 1024**3, percent=60.0),
    )
    monkeypatch.setattr(
        report.psutil,
        "net_if_addrs",
        lambda: {
            "Ethernet": [
                SimpleNamespace(family=report.socket.AF_INET, address="192.0.2.20"),
                SimpleNamespace(family=999, address="ignored"),
            ]
        },
    )
    monkeypatch.setattr(report.platform, "node", lambda: "TEST-PC")
    monkeypatch.setattr(report.platform, "system", lambda: "Windows")
    monkeypatch.setattr(report.platform, "release", lambda: "11")
    monkeypatch.setattr(report.platform, "version", lambda: "10.0")
    monkeypatch.setattr(report.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(report.platform, "processor", lambda: "Test CPU")
    monkeypatch.setattr(report.getpass, "getuser", lambda: "tester")
    monkeypatch.setattr(report.socket, "gethostname", lambda: "test-host")
    monkeypatch.setattr(report, "safe_gethostbyname", lambda _host: "192.0.2.10")
    monkeypatch.setattr(report, "get_default_gateway_windows", lambda: "192.0.2.1")
    monkeypatch.setattr(report, "ping_host", lambda: "Correcto")
    monkeypatch.setattr(
        report,
        "collect_processes",
        lambda: ([(10, "cpu.exe", 50.0, 5.0)], [(11, "mem.exe", 2.0, 60.0)]),
    )
    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setattr(report, "get_temp_locations", lambda: [cache, tmp_path / "missing"])
    monkeypatch.setattr(report, "folder_size", lambda path: 2048 if path == cache else 0)
    monkeypatch.setattr(
        report,
        "load_event_snapshot",
        lambda: [("today", "Error", "Disk", "7", "Alto", "Check disk")],
    )

    data = report.collect_report()

    assert ("Equipo", "TEST-PC") in data.system_rows
    assert data.disk_rows[0][0] == "Disk0"
    assert ("Adaptador: Ethernet", "192.0.2.20") in data.network_rows
    assert data.top_cpu[0][1] == "cpu.exe"
    assert data.top_memory[0][1] == "mem.exe"
    assert data.temp_summary[0][1] == "2.00 KB"
    assert data.temp_summary[1][1] == "No existe"
    assert data.event_summary[0][2] == "Disk"


def test_collect_report_skips_unreadable_disk_and_handles_network_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(report.psutil, "boot_time", lambda: 1_700_000_000)
    monkeypatch.setattr(
        report.psutil,
        "virtual_memory",
        lambda: SimpleNamespace(total=1, used=1, percent=100.0),
    )
    monkeypatch.setattr(report.psutil, "swap_memory", lambda: SimpleNamespace(total=0))
    monkeypatch.setattr(report.psutil, "cpu_count", lambda logical=True: None)
    monkeypatch.setattr(report.psutil, "cpu_percent", lambda interval=0: 0.0)
    monkeypatch.setattr(
        report.psutil,
        "disk_partitions",
        lambda all=False: [SimpleNamespace(device="Disk0", mountpoint="X:/")],
    )

    def fail_usage(_mount):
        raise PermissionError("denied")

    monkeypatch.setattr(report.psutil, "disk_usage", fail_usage)

    def fail_addresses():
        raise OSError("network")

    monkeypatch.setattr(report.psutil, "net_if_addrs", fail_addresses)
    monkeypatch.setattr(report.platform, "node", lambda: "PC")
    monkeypatch.setattr(report.platform, "system", lambda: "Windows")
    monkeypatch.setattr(report.platform, "release", lambda: "11")
    monkeypatch.setattr(report.platform, "version", lambda: "v")
    monkeypatch.setattr(report.platform, "machine", lambda: "x64")
    monkeypatch.setattr(report.platform, "processor", lambda: "")
    monkeypatch.setattr(report.getpass, "getuser", lambda: "user")
    monkeypatch.setattr(report.socket, "gethostname", lambda: "host")
    monkeypatch.setattr(report, "safe_gethostbyname", lambda _host: "No disponible")
    monkeypatch.setattr(report, "get_default_gateway_windows", lambda: "No disponible")
    monkeypatch.setattr(report, "ping_host", lambda: "Fallido")
    monkeypatch.setattr(report, "collect_processes", lambda: ([], []))
    monkeypatch.setattr(report, "get_temp_locations", lambda: [])
    monkeypatch.setattr(report, "load_event_snapshot", lambda: [])

    data = report.collect_report()

    assert data.disk_rows == []
    assert ("Adaptadores", "No disponible") in data.network_rows
    assert ("Procesador", "No disponible") in data.system_rows
    assert ("Núcleos físicos", "No disponible") in data.system_rows


def test_report_outputs_handle_empty_optional_sections():
    data = report.ReportData(
        generated_at="2026-08-30",
        system_rows=[("Equipo", "PC")],
        disk_rows=[],
        network_rows=[],
        top_cpu=[],
        top_memory=[],
        temp_summary=[],
        event_summary=[],
    )

    text = report.report_to_text(data)
    html = report.report_to_html(data)

    assert "Eventos recientes de Windows" not in text
    assert "Eventos recientes de Windows" not in html
    assert "<table" in report.table_html(["A"], [["<unsafe>"]])
    assert "&lt;unsafe&gt;" in report.table_html(["A"], [["<unsafe>"]])
