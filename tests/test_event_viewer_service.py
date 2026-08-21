from tools import event_viewer_tool as events


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


def test_build_event_query_contains_levels_and_time_window():
    query = events.build_event_query(hours=2, include_info=True)
    assert "Level=1" in query
    assert "Level=4" in query
    assert "7200000" in query


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
    item = events.EventItem(
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
