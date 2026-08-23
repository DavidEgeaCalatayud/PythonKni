"""Compatibility adapter for the Windows Event Viewer plugin.

New code should import from :mod:`pythonkni.event_viewer`.
"""

from pythonkni.event_viewer.models import *  # noqa: F403 - legacy compatibility re-export
from pythonkni.event_viewer.service import *  # noqa: F403 - legacy compatibility re-export
