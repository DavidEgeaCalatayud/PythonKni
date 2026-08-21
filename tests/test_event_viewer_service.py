import sys
import threading

from pythonkni.event_viewer import service as events
from pythonkni.event_viewer.models import EventItem


def make_event_xml(provider, event_id, level, message, timestamp="2026-08-21T10:00:00.1234567Z"):
    return f"""
<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event">
  <System>
    <Provider Name="{provider}" />
    <EventID>{event_id}</EventID>
    <Level>{level}</Level>
    <Task>63</Task>
    <TimeCreated SystemTime="{timestamp}" />
    <EventRecordID>42</EventRecordID>
    <Channel>System</Channel>
    <Computer>TEST-PC</Computer>
    <Execution ProcessID="4" ThreadID="8" />
  </System>
  <RenderingInfo>
    <Message>{message}</Message>
    <Level>Rendered level</Level>
    <Task>Rendered task</Task>
  </RenderingInfo>
</Event>
""".strip()


def install_test_process(monkeypatch, script: str, captured: list) -> None:
    real_popen = events.subprocess.Popen

    def fake_popen(_command, **kwargs):
        process = real_popen(
            [sys.executable, "-c", script],
            stdout=kwargs.get("stdout"),
            stderr=kwargs.get("stderr"),
            shell=False,
        )
        captured.append(process)
        return process

    monkeypatch.setattr(events.subprocess, "Popen", fake_popen)


def test_build_event_query_contains_levels_and_time_window():
    query = events.build_event_query(hours=2, include_info=True)
    assert "Level=1" in query
    assert "Level=4" in query
    assert "7200000" in query


def test_run_wevtutil_drains_large_stdout_and_stderr_while_child_runs(monkeypatch):
    captured = []
    payload_size = 2_000_000
    install_test_process(
        monkeypatch,
        "import sys; "
        f"sys.stdout.buffer.write(b'x' * {payload_size}); sys.stdout.flush(); "
        f"sys.stderr.buffer.write(b'y' * {payload_size}); sys.stderr.flush()",
        captured,
    )
    monkeypatch.setattr(events, "WEVTUTIL_TIMEOUT_SECONDS", 5.0)
    monkeypatch.setattr(events, "WEVTUTIL_COMMUNICATE_SLICE_SECONDS", 0.05)

    output, warning = events.run_wevtutil("System", 24, 1000, False)

    assert warning == ""
    assert len(output) == payload_size
    assert output.startswith("xxxx")
    assert captured[0].poll() == 0


def test_run_wevtutil_cancel_kills_drains_and_reaps_child(monkeypatch):
    captured = []
    install_test_process(
        monkeypatch,
        "import sys, time; "
        "sys.stdout.buffer.write(b'x' * 200000); sys.stdout.flush(); time.sleep(10)",
        captured,
    )
    cancel_event = threading.Event()
    cancel_event.set()

    output, warning = events.run_wevtutil("System", 24, 1000, False, cancel_event=cancel_event)

    assert output == ""
    assert warning == "Cancelado por el usuario."
    assert captured[0].poll() is not None


def test_run_wevtutil_timeout_kills_drains_and_reaps_child(monkeypatch):
    captured = []
    install_test_process(monkeypatch, "import time; time.sleep(10)", captured)
    monkeypatch.setattr(events, "WEVTUTIL_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr(events, "WEVTUTIL_COMMUNICATE_SLICE_SECONDS", 0.02)

    output, warning = events.run_wevtutil("System", 24, 1000, False)

    assert output == ""
    assert "Tiempo agotado leyendo System" in warning
    assert captured[0].poll() is not None


def test_run_wevtutil_preserves_stderr_on_process_failure(monkeypatch):
    captured = []
    install_test_process(
        monkeypatch,
        "import sys; sys.stderr.write('wevtutil failure'); sys.exit(3)",
        captured,
    )

    output, warning = events.run_wevtutil("System", 24, 1000, False)

    assert output == ""
    assert "wevtutil failure" in warning
    assert captured[0].poll() == 3


def test_parse_kernel_power_event_marks_high_risk():
    parsed = events.parse_events_xml(
        make_event_xml("Microsoft-Windows-Kernel-Power", 41, 1, "Unexpected shutdown"),
        "System",
    )

    assert len(parsed) == 1
    event = parsed[0]
    assert event.provider == "Microsoft-Windows-Kernel-Power"
    assert event.event_id == "41"
    assert event.risk == "Alto"
    assert "apagó o reinició" in event.interpretation
    assert event.message == "Unexpected shutdown"
    assert event.record_id == "42"


def test_collect_events_sorts_by_risk_and_honours_limit(monkeypatch):
    monkeypatch.setattr(events, "is_windows", lambda: True)

    outputs = {
        "Application": make_event_xml("Application Hang", 1002, 3, "App stopped responding"),
        "System": make_event_xml("Microsoft-Windows-Kernel-Power", 41, 1, "Power loss"),
    }

    def fake_run(log_name, **kwargs):
        return outputs[log_name], ""

    monkeypatch.setattr(events, "run_wevtutil", fake_run)
    result = events.collect_events(["Application", "System"], hours=24, max_events=1)

    assert result.warnings == []
    assert len(result.events) == 1
    assert result.events[0].risk == "Alto"
    assert result.events[0].event_id == "41"


def test_events_html_escapes_untrusted_event_content():
    item = EventItem(
        date="21/08/2026",
        level="Error",
        level_number=2,
        provider="<script>alert(1)</script>",
        event_id="1000",
        category="App",
        message="<b>fallo & error</b>",
        risk="Medio",
        interpretation="Revisar <driver>",
        log_name="Application",
        record_id="1",
        computer="PC",
        process_id="10",
        thread_id="20",
    )

    html = events.events_to_html([item])
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "&lt;b&gt;fallo &amp; error&lt;/b&gt;" in html
    assert "Revisar &lt;driver&gt;" in html
