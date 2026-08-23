"""Compatibility adapter for the startup-manager plugin.

New code should import from :mod:`pythonkni.startup`.
"""

from pythonkni.startup.models import *  # noqa: F403
from pythonkni.startup.service import *  # noqa: F403
from pythonkni.startup.window import Tool as Tool
