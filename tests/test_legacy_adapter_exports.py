from tools.event_viewer_tool import (
    EventDetailDialog,
    EventWorker,
    Tool as EventViewerTool,
)
from tools.pdf_merge_tool import Tool as PdfTool
from tools.startup_manager_tool import Tool as StartupTool
from tools.system_report_tool import ReportWorker, Tool as SystemReportTool


def test_legacy_window_exports_remain_available():
    assert EventDetailDialog is not None
    assert EventWorker is not None
    assert EventViewerTool is not None
    assert PdfTool is not None
    assert StartupTool is not None
    assert ReportWorker is not None
    assert SystemReportTool is not None
