from __future__ import annotations

from types import SimpleNamespace

import pytest

from pythonkni.network_monitor import window
from pythonkni.network_monitor.capture import PacketCaptureError
from pythonkni.network_monitor.models import (
    ConnectionObservation,
    EndpointScope,
    EventSeverity,
    HostActivity,
    MonitorEvent,
    MonitorHistoryPoint,
    MonitorSnapshot,
    MonitorUpdate,
    NetworkAdapter,
    PcapCaptureResult,
    ProcessActivity,
    TrafficSample,
)


class FakeCapture:
    def __init__(self, _path):
        self.available = False
        self.active = False
        self.start_calls = 0
        self.stop_calls = 0

    def start(self):
        self.start_calls += 1
        self.active = True
        return "capture.etl"

    def stop(self):
        self.stop_calls += 1
        self.active = False
        return PcapCaptureResult("capture.etl", "capture.pcapng")


@pytest.fixture
def tool(qtbot, monkeypatch, tmp_path):
    monkeypatch.setattr(window, "ensure_app_dirs", lambda: None)
    monkeypatch.setattr(window, "NETWORK_MONITOR_CAPTURES_DIR", tmp_path / "captures")
    monkeypatch.setattr(window, "PktmonCapture", FakeCapture)
    monkeypatch.setattr(
        window,
        "list_adapters",
        lambda: (
            NetworkAdapter("Ethernet", ("192.168.1.10",), True, 1000, 1500, 1, 2),
            NetworkAdapter("Wi-Fi", (), False, 0, 0, 3, 4),
        ),
    )
    instance = window.Tool()
    qtbot.addWidget(instance)
    return instance


def observation():
    return ConnectionObservation(
        transport="tcp",
        family="ipv4",
        local_ip="192.168.1.10",
        local_port=50000,
        remote_ip="8.8.8.8",
        remote_port=443,
        status="ESTABLISHED",
        pid=10,
        process_name="chrome.exe",
        adapter="Ethernet",
        scope=EndpointScope.PUBLIC,
        protocol="HTTPS",
        hostname="dns.google",
    )


def update():
    connection = observation()
    snapshot = MonitorSnapshot(1000.0, "Ethernet", TrafficSample(2048, 1024), (connection,))
    return MonitorUpdate(
        snapshot=snapshot,
        processes=(ProcessActivity(10, "chrome.exe", 1, 1, ("8.8.8.8",), ("HTTPS",)),),
        hosts=(
            HostActivity(
                "8.8.8.8",
                "dns.google",
                EndpointScope.PUBLIC,
                1,
                ("chrome.exe",),
                (443,),
                asn="AS15169",
                prefix="8.8.8.0/24",
            ),
        ),
        events=(
            MonitorEvent(
                "event",
                "new_external_connection",
                EventSeverity.WARNING,
                1000.0,
                "New external connection",
                "chrome.exe connected to 8.8.8.8:443/tcp.",
            ),
        ),
        history=(MonitorHistoryPoint(1000.0, 2048, 1024, 1, 1, 1),),
    )


def test_tool_builds_adapter_and_monitor_views(tool):
    assert tool.adapter_combo.count() == 3
    assert tool._adapter_value(1) == "Ethernet"
    assert "Wi-Fi" in tool.adapter_combo.itemText(2)
    assert tool.tabs.count() == 5
    assert tool.host_table.columnCount() == 9
    assert tool.pcap_start_button.isEnabled() is False
    assert window._format_rate(-1) == "0 B/s"
    assert window._format_rate(1024) == "1.0 KB/s"
    assert "MB/s" in window._format_rate(2 * 1024**2)
    assert "GB/s" in window._format_rate(2 * 1024**3)


def test_refresh_adapters_preserves_selection_and_reports_failure(tool, monkeypatch):
    tool.adapter_combo.setCurrentIndex(1)
    tool.refresh_adapters()
    assert tool._adapter_value() == "Ethernet"

    def fail():
        raise RuntimeError("adapter failure")

    monkeypatch.setattr(window, "list_adapters", fail)
    tool.refresh_adapters()
    assert "adapter failure" in tool.status_label.text()


def test_update_monitor_renders_all_tabs_and_alerts(tool):
    tool._update_monitor(update())
    assert tool.connection_table.rowCount() == 1
    assert tool.connection_table.item(0, 2).text() == "dns.google"
    assert tool.process_table.item(0, 0).text() == "chrome.exe"
    assert tool.host_table.item(0, 2).text() == "AS15169"
    assert tool.host_table.item(0, 3).text() == "8.8.8.0/24"
    assert tool.history_table.rowCount() == 1
    assert tool.alert_table.item(0, 2).text() == "new_external_connection"
    assert "1 socket" in tool.status_label.text()
    tool._clear_tables()
    assert tool.alert_table.rowCount() == 0
    assert tool.alert_rows == []


def test_start_and_stop_monitor_manage_worker_state(tool, monkeypatch):
    started = []
    monkeypatch.setattr(
        tool, "start_managed_worker", lambda worker, cancel=None: started.append(worker)
    )
    tool.asn_check.setChecked(True)
    tool.start_monitoring()
    assert len(started) == 1
    assert tool.worker is started[0]
    assert tool.worker._args == (window.ALL_ADAPTERS, True)
    assert tool.start_button.isEnabled() is False
    tool.worker = SimpleNamespace(isRunning=lambda: True)
    tool.start_monitoring()
    assert len(started) == 1

    cancelled = []
    tool.worker = SimpleNamespace(isRunning=lambda: True, cancel=lambda: cancelled.append(True))
    tool.stop_monitoring()
    assert cancelled == [True]
    assert "Stopping" in tool.status_label.text()
    tool._monitor_cancelled()
    assert "stopped" in tool.status_label.text()
    tool._monitor_finished()
    assert tool.worker is None
    assert tool.start_button.isEnabled() is True


def test_monitor_failure_is_presented(tool, monkeypatch):
    messages = []
    monkeypatch.setattr(window, "show_error", lambda *args: messages.append(args))
    tool._monitor_failed(RuntimeError("boom"))
    assert messages
    assert "boom" in tool.status_label.text()


def test_pcap_controls_and_callbacks(tool, monkeypatch):
    started = []
    monkeypatch.setattr(
        tool, "start_managed_worker", lambda worker, cancel=None: started.append(worker)
    )
    tool.capture.available = True
    tool._sync_pcap_buttons()
    assert tool.pcap_start_button.isEnabled() is True

    tool.start_pcap()
    assert tool.pcap_worker is started[-1]
    tool.start_pcap()
    assert len(started) == 1
    tool._pcap_started("capture.etl")
    assert "system-wide" in tool.status_label.text()
    tool._pcap_worker_finished()

    tool.capture.active = True
    tool._sync_pcap_buttons()
    assert tool.pcap_stop_button.isEnabled() is True
    tool.stop_pcap()
    assert len(started) == 2
    tool._pcap_stopped(PcapCaptureResult("a.etl", "a.pcapng"))
    assert "a.pcapng" in tool.status_label.text()
    tool._pcap_worker_finished()


def test_pcap_failure_adds_permission_guidance(tool, monkeypatch):
    messages = []
    monkeypatch.setattr(window, "show_error", lambda *args: messages.append(args))
    tool._pcap_failed(PacketCaptureError("access denied"))
    assert "elevated" in messages[0][2]
    tool._pcap_failed(RuntimeError("other"))
    assert messages[-1][2] == "other"


def test_run_monitor_emits_update_and_persists_history(monkeypatch):
    emitted = []
    history = []
    events = []
    snap = MonitorSnapshot(1.0, "Ethernet", TrafficSample(), ())
    monkeypatch.setattr(window, "PERSIST_HISTORY_EVERY_SAMPLES", 1)
    monkeypatch.setattr(window, "load_known_assets", lambda path: (_ for _ in ()).throw(OSError()))
    monkeypatch.setattr(window, "collect_snapshot", lambda *args, **kwargs: (snap, object()))
    monkeypatch.setattr(window, "append_events_jsonl", lambda path, values: events.append(values))
    monkeypatch.setattr(window, "append_history_jsonl", lambda path, point: history.append(point))

    class CancelEvent:
        def wait(self, _seconds):
            return True

    class FakeWorker:
        cancel_event = CancelEvent()

        def __init__(self):
            self.checks = 0

        def check_cancelled(self):
            self.checks += 1
            if self.checks > 1:
                raise RuntimeError("cancel")

        def report_progress(self, value):
            emitted.append(value)

    with pytest.raises(RuntimeError, match="cancel"):
        window._run_monitor(FakeWorker(), "Ethernet", True)
    assert len(emitted) == 1
    assert len(events) == 1
    assert len(history) == 1


def test_pcap_task_helpers_delegate_after_cancellation_check():
    checks = []
    worker = SimpleNamespace(check_cancelled=lambda: checks.append(True))
    capture = FakeCapture(None)
    assert window._start_pcap(worker, capture) == "capture.etl"
    result = window._stop_pcap(worker, capture)
    assert result.pcapng_path == "capture.pcapng"
    assert checks == [True, True]
