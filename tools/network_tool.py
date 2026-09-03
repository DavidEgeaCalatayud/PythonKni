import sys

from pythonkni.network import camera_handoff_window as _window
from pythonkni.network import service as _service
from pythonkni.network import service_intelligence_window as _service_intelligence_window

_window.__dict__["PortScanner"] = _service_intelligence_window.PortScanner
_window.__dict__["Tool"] = _service_intelligence_window.Tool


def _legacy_getattr(name):
    try:
        return getattr(_service, name)
    except AttributeError:
        raise AttributeError(f"module {_window.__name__!r} has no attribute {name!r}") from None


_window.__getattr__ = _legacy_getattr
sys.modules[__name__] = _window
