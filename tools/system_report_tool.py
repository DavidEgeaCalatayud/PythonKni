"""Compatibility adapter for the system-report plugin.

New code should import from :mod:`pythonkni.system_report`.
"""

from pythonkni.system_report.models import *
from pythonkni.system_report.service import *
from pythonkni.system_report.window import ReportWorker, Tool
