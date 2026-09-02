import sys
import types

from pythonkni.network import camera_handoff_window as _base_window
from pythonkni.network import fingerprint_inventory_window as _window
from pythonkni.network import service as _service


def _legacy_getattr(name):
    try:
        return getattr(_base_window, name)
    except AttributeError:
        try:
            return getattr(_service, name)
        except AttributeError:
            raise AttributeError(
                f"module {_window.__name__!r} has no attribute {name!r}"
            ) from None


class _LegacyNetworkModule(types.ModuleType):
    def __setattr__(self, name, value):
        if name not in self.__dict__:
            if hasattr(_base_window, name):
                setattr(_base_window, name, value)
                return
            if hasattr(_service, name):
                setattr(_service, name, value)
                return
        super().__setattr__(name, value)

    def __delattr__(self, name):
        if name not in self.__dict__:
            if hasattr(_base_window, name):
                delattr(_base_window, name)
                return
            if hasattr(_service, name):
                delattr(_service, name)
                return
        super().__delattr__(name)


_window.__getattr__ = _legacy_getattr
_window.__class__ = _LegacyNetworkModule
sys.modules[__name__] = _window
