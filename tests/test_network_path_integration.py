from __future__ import annotations

from types import SimpleNamespace

from pythonkni.network_path import integration
from pythonkni.network_path.models import PathEvent, PathEventSeverity


def event():
    return PathEvent(
        "logical",
        "route_changed",
        PathEventSeverity.WARNING,
        1000.0,
        "Route changed",
        "Route changed toward 8.8.8.8.",
        "8.8.8.8",
        3,
        "192.0.2.1",
    )


def test_persist_path_events_prefers_canonical_inbox(monkeypatch, tmp_path):
    published = []
    legacy = []
    monkeypatch.setattr(
        integration,
        "publish_path_events",
        lambda path, values: published.append((path, values)),
    )
    monkeypatch.setattr(
        integration,
        "append_legacy_events_jsonl",
        lambda path, values: legacy.append((path, values)),
    )
    values = (event(),)
    integration.persist_path_events(tmp_path / "fallback.jsonl", values)
    assert published and published[0][1] == values
    assert legacy == []


def test_persist_path_events_falls_back_without_crashing_monitor(monkeypatch, tmp_path):
    legacy = []

    def fail(*_args, **_kwargs):
        raise OSError("inbox unavailable")

    monkeypatch.setattr(integration, "publish_path_events", fail)
    monkeypatch.setattr(
        integration,
        "append_legacy_events_jsonl",
        lambda path, values: legacy.append((path, values)),
    )
    path = tmp_path / "fallback.jsonl"
    values = (event(),)
    integration.persist_path_events(path, values)
    assert legacy == [(path, values)]


def test_install_window_integration_replaces_persistence_hook():
    window_module = SimpleNamespace(append_events_jsonl=lambda *_args: None)
    integration.install_window_integration(window_module)
    assert window_module.append_events_jsonl is integration.persist_path_events
