from __future__ import annotations

from types import SimpleNamespace

import pytest

from pythonkni.network_path import window
from pythonkni.network_path.backend import TrippyPrivilegesRequired
from pythonkni.network_path.models import (
    HopHost,
    HopProbe,
    HopStats,
    PathEvent,
    PathEventSeverity,
    PathHistoryPoint,
    PathUpdate,
    TraceProtocol,
    TraceRequest,
    TraceSnapshot,
)


@pytest.fixture
def tool(qtbot, monkeypatch):
    monkeypatch.setattr(window, "ensure_app_dirs", lambda: None)
    instance = window.Tool()
    qtbot.addWidget(instance)
    return instance


def make_update():
    hosts = (HopHost("8.8.8.8", "dns.google"),)
    probe = HopProbe(1, hosts, 1, 1, 0.0, 31.0)
    snapshot = TraceSnapshot(
        1000.0,
        "8.8.8.8",
        "8.8.8.8",
        "dns.google",
        TraceProtocol.ICMP,
        None,
        (probe,),
        True,
    )
    stats = HopStats(1, hosts, 3, 3, 0.0, 31.0, 30.0, 28.0, 33.0, 1.5, "Destination")
    event = PathEvent(
        "event",
        "latency_spike",
        PathEventSeverity.WARNING,
        1000.0,
        "Latency spike",
        "RTT increased.",
        "8.8.8.8",
        1,
        "8.8.8.8",
    )
    history = PathHistoryPoint(1000.0, "8.8.8.8", 31.0, 0.0, 1, True, 1)
    return PathUpdate(snapshot, (stats,), (event,), (history,), 1)


def test_tool_builds_controls_tabs_and_protocol_port_state(tool):
    assert tool.tabs.count() == 3
    assert tool.path_table.columnCount() == 10
    assert tool.interval_combo.currentData() == 1.0
    assert tool.ttl_spin.value() == 30
    assert tool.port_spin.isEnabled() is False
    assert window._format_ms(None) == "—"
    assert window._format_ms(12.34) == "12.3 ms"

    tool.protocol_combo.setCurrentIndex(1)
    assert tool._protocol_value() == "udp"
    assert tool.port_spin.isEnabled() is True


def test_request_from_controls_uses_single_target_and_options(tool):
    tool.target_input.setText("Example.com")
    tool.protocol_combo.setCurrentIndex(2)
    tool.port_spin.setValue(8443)
    tool.ttl_spin.setValue(40)
    request = tool._request_from_controls()
    assert request.target == "example.com"
    assert request.protocol is TraceProtocol.TCP
    assert request.port == 8443
    assert request.max_ttl == 40


def test_start_validation_error_does_not_create_worker(tool, monkeypatch):
    messages = []
    monkeypatch.setattr(window, "show_error", lambda *args: messages.append(args))
    tool.target_input.setText("10.0.0.0/24")
    tool.start_analysis()
    assert tool.worker is None
    assert messages
    assert "único" in tool.status_label.text()


def test_start_stop_and_reset_manage_worker_state(tool, monkeypatch):
    started = []
    monkeypatch.setattr(
        tool, "start_managed_worker", lambda worker, cancel=None: started.append(worker)
    )
    tool.target_input.setText("8.8.8.8")
    tool.start_analysis()
    assert len(started) == 1
    assert tool.worker is started[0]
    assert isinstance(tool.worker._args[0], TraceRequest)
    assert tool.start_button.isEnabled() is False

    tool.worker = SimpleNamespace(isRunning=lambda: True)
    tool.start_analysis()
    assert len(started) == 1

    cancelled = []
    tool.worker = SimpleNamespace(isRunning=lambda: True, cancel=lambda: cancelled.append(True))
    tool.stop_analysis()
    assert cancelled == [True]
    assert "Deteniendo" in tool.status_label.text()

    tool.reset_event.clear()
    tool.reset_stats()
    assert tool.reset_event.is_set() is True
    assert "seguir" in tool.status_label.text()

    tool._analysis_cancelled()
    assert "detenido" in tool.status_label.text()
    tool._analysis_finished()
    assert tool.worker is None
    assert tool.start_button.isEnabled() is True


def test_reset_when_idle_only_clears_views(tool):
    tool.alert_rows = [["x"]]
    tool.alert_table.setRowCount(1)
    tool.reset_stats()
    assert tool.alert_rows == []
    assert tool.alert_table.rowCount() == 0
    assert tool.reset_event.is_set() is False
    assert "reiniciadas" in tool.status_label.text()


def test_update_path_renders_hops_history_alerts_and_chart(tool):
    update = make_update()
    tool._update_path(update)
    assert tool.path_table.rowCount() == 1
    assert tool.path_table.item(0, 1).text() == "dns.google"
    assert tool.path_table.item(0, 3).text() == "0.0%"
    assert tool.history_table.item(0, 1).text() == "31.0 ms"
    assert tool.alert_table.item(0, 2).text() == "latency_spike"
    assert tool.rtt_chart._points == (31.0,)
    assert "TTL 1" in tool.status_label.text()

    tool._clear_views()
    assert tool.path_table.rowCount() == 0
    assert tool.rtt_chart._points == ()


def test_analysis_failure_adds_elevation_guidance(tool, monkeypatch):
    messages = []
    monkeypatch.setattr(window, "show_error", lambda *args: messages.append(args))
    tool._analysis_failed(TrippyPrivilegesRequired("admin required"))
    assert "Ejecutar como administrador" in messages[0][2]
    assert "fallido" in tool.status_label.text()

    tool._analysis_failed(RuntimeError("other"))
    assert messages[-1][2] == "other"


def test_rtt_chart_accepts_missing_samples(tool):
    tool.rtt_chart.set_points((1.0, None, 4.0))
    assert tool.rtt_chart._points == (1.0, None, 4.0)


def test_run_path_analyzer_emits_update_and_persists(monkeypatch):
    emitted = []
    history = []
    events = []
    snapshot = TraceSnapshot(
        1.0,
        "8.8.8.8",
        "8.8.8.8",
        "dns.google",
        TraceProtocol.ICMP,
        None,
        (HopProbe(1, (HopHost("8.8.8.8"),), 1, 1, 0.0, 10.0),),
        True,
    )

    class FakeBackend:
        def info(self):
            return SimpleNamespace(version="0.13.0")

        def trace_once(self, request, *, stop_event):
            del request, stop_event
            return snapshot

    monkeypatch.setattr(window, "TrippyBackend", FakeBackend)
    monkeypatch.setattr(window, "append_events_jsonl", lambda path, values: events.append(values))
    monkeypatch.setattr(window, "append_history_jsonl", lambda path, point: history.append(point))

    class CancelEvent:
        def __init__(self):
            self.wait_calls = 0

        def is_set(self):
            return False

        def wait(self, _seconds):
            self.wait_calls += 1
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

    reset_event = SimpleNamespace(is_set=lambda: False, clear=lambda: None)
    with pytest.raises(RuntimeError, match="cancel"):
        window._run_path_analyzer(
            FakeWorker(),
            TraceRequest("8.8.8.8", interval_seconds=0.5),
            reset_event,
        )
    assert len(emitted) == 1
    assert len(history) == 1
    assert len(events) == 1


def test_run_path_analyzer_applies_reset_before_next_trace(monkeypatch):
    states = []

    class FakeState:
        def __init__(self):
            states.append(self)

        def observe(self, snapshot):
            del snapshot
            return SimpleNamespace(events=(), history=())

    class FakeBackend:
        def info(self):
            return None

        def trace_once(self, request, *, stop_event):
            del request, stop_event
            return SimpleNamespace()

    class ResetEvent:
        def __init__(self):
            self.active = True

        def is_set(self):
            return self.active

        def clear(self):
            self.active = False

    class Worker:
        def __init__(self):
            self.cancel_event = SimpleNamespace(wait=lambda _seconds: True)
            self.checks = 0

        def check_cancelled(self):
            self.checks += 1
            if self.checks > 1:
                raise RuntimeError("stop")

        def report_progress(self, _value):
            pass

    monkeypatch.setattr(window, "PathState", FakeState)
    monkeypatch.setattr(window, "TrippyBackend", FakeBackend)
    with pytest.raises(RuntimeError, match="stop"):
        window._run_path_analyzer(Worker(), TraceRequest("8.8.8.8"), ResetEvent())
    assert len(states) == 2
