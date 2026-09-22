from __future__ import annotations

from pathlib import Path
from types import ModuleType

from pythonkni.infrastructure.paths import NETWORK_INTELLIGENCE_NOTIFICATIONS_FILE
from pythonkni.network_intelligence.temporal_notifications import publish_path_events

from .models import PathEvent
from .service import append_events_jsonl as append_legacy_events_jsonl


def persist_path_events(path: Path, events: tuple[PathEvent, ...]) -> None:
    """Publish path events canonically, retaining JSONL only as failure recovery."""
    try:
        publish_path_events(NETWORK_INTELLIGENCE_NOTIFICATIONS_FILE, events)
    except Exception:
        append_legacy_events_jsonl(path, events)


def install_window_integration(window_module: ModuleType) -> None:
    """Route the window persistence hook through the canonical event pipeline."""
    window_module.append_events_jsonl = persist_path_events
