import sys

from pythonkni.network_intelligence import service as _service
from pythonkni.network_intelligence import temporal_history_window as _history_center
from pythonkni.network_intelligence import window as _window

_window.Tool = _history_center.Tool


def _legacy_getattr(name):
    try:
        return getattr(_service, name)
    except AttributeError:
        raise AttributeError(f"module {_window.__name__!r} has no attribute {name!r}") from None


_window.__getattr__ = _legacy_getattr
sys.modules[__name__] = _window
