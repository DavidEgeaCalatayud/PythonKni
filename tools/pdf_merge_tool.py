"""Compatibility adapter for the PDF Toolkit plugin.

New code should import from :mod:`pythonkni.pdf`.
"""

from pythonkni.pdf.service import *  # noqa: F403 - legacy compatibility re-export
from pythonkni.pdf.window import Tool as Tool
