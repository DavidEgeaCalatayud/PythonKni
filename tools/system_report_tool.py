"""Compatibility adapter for the system-report plugin.

New code should import from :mod:`pythonkni.system_report`.
"""

from pythonkni.system_report.models import *  # noqa: F403
from pythonkni.system_report.service import *  # noqa: F403
from pythonkni.system_report.window import ReportWorker as ReportWorker
from pythonkni.system_report.window import Tool as Tool
