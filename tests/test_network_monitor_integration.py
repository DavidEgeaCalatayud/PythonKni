from __future__ import annotations

from types import SimpleNamespace

from pythonkni.network_monitor import integration
from pythonkni.network_monitor.models import EventSeverity, MonitorEvent


def event() -> MonitorEvent:
    return MonitorEvent(
        event_id="event",
        kind="new_remote_host",
        severity=EventSeverity.INFO,
        timestamp=1000.0,
        title="New remote host",
        description="First observed remote host.",
        remote_ip="8.8.8.8",
    )


def test_persist_monitor_events_prefers_network_intelligence(monkeypatch, tmp_path):
    published = []
    legacy = []
    monkeypatch.setattr(
        integration,
        "publish_monitor_events",
        lambda path, events: published.append((path, events)),
    )
    monkeypatch.setattr(
        integration,
        "append_legacy_events_jsonl",
        lambda path, events: legacy.append((path, events)),
    )

    path = tmp_path / "events.jsonl"
    events = (event(),)
    integration.persist_monitor_events(path, events)

    assert published == [(integration.NETWORK_INTELLIGENCE_NOTIFICATIONS_FILE, events)]
    assert legacy == []


def test_persist_monitor_events_falls_back_without_crashing_monitor(monkeypatch, tmp_path):
    legacy = []

    def fail(*_args, **_kwargs):
        raise OSError("inbox unavailable")

    monkeypatch.setattr(integration, "publish_monitor_events", fail)
    monkeypatch.setattr(
        integration,
        "append_legacy_events_jsonl",
        lambda path, events: legacy.append((path, events)),
    )

    path = tmp_path / "events.jsonl"
    events = (event(),)
    integration.persist_monitor_events(path, events)
    assert legacy == [(path, events)]


def test_install_window_integration_replaces_only_event_persistence_hook():
    original = object()
    module = SimpleNamespace(append_events_jsonl=original)
    integration.install_window_integration(module)
    assert module.append_events_jsonl is integration.persist_monitor_events
