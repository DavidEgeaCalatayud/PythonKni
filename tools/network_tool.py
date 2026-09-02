import sys

from pythonkni.network import fingerprint_inventory_window as _window
from pythonkni.network import service as _service


def _legacy_getattr(name):
    try:
        return getattr(_service, name)
    except AttributeError:
        raise AttributeError(f"module {_window.__name__!r} has no attribute {name!r}") from None


_window.__getattr__ = _legacy_getattr
sys.modules[__name__] = _window
