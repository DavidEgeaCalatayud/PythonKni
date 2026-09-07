import sys

from pythonkni.network_path import integration as _integration
from pythonkni.network_path import window as _window

_integration.install_window_integration(_window)
sys.modules[__name__] = _window
