import sys

from pythonkni.infrastructure.paths import NETWORK_INTELLIGENCE_NOTIFICATIONS_FILE
from pythonkni.network_intelligence.temporal_notifications import publish_monitor_events
from pythonkni.network_monitor import window as _window

_legacy_append_events_jsonl = _window.append_events_jsonl


def _publish_events(path, events):
    try:
        publish_monitor_events(NETWORK_INTELLIGENCE_NOTIFICATIONS_FILE, events)
    except Exception:
        _legacy_append_events_jsonl(path, events)


_window.append_events_jsonl = _publish_events
sys.modules[__name__] = _window
