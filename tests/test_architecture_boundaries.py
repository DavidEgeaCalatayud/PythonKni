import ast
from pathlib import Path

import pytest

from tools.base_tool import BaseTool


ROOT = Path(__file__).resolve().parents[1]
SERVICE_MODULES = [
    ROOT / "pythonkni" / "event_viewer" / "service.py",
    ROOT / "pythonkni" / "startup" / "service.py",
    ROOT / "pythonkni" / "system_report" / "service.py",
    ROOT / "pythonkni" / "pdf" / "service.py",
]
TOOL_WRAPPERS = [
    ROOT / "tools" / "event_viewer_tool.py",
    ROOT / "tools" / "startup_manager_tool.py",
    ROOT / "tools" / "system_report_tool.py",
    ROOT / "tools" / "pdf_merge_tool.py",
]


@pytest.mark.parametrize("path", SERVICE_MODULES)
def test_business_services_do_not_import_pyqt(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        assert not any(name == "PyQt5" or name.startswith("PyQt5.") for name in names)


@pytest.mark.parametrize("path", TOOL_WRAPPERS)
def test_legacy_tool_modules_are_thin_compatibility_adapters(path):
    content = path.read_text(encoding="utf-8")
    assert "pythonkni." in content
    assert len(content.splitlines()) <= 20


def test_windows_keep_base_tool_contract():
    from pythonkni.event_viewer.window import Tool as EventTool
    from pythonkni.pdf.window import Tool as PdfTool
    from pythonkni.startup.window import Tool as StartupTool
    from pythonkni.system_report.window import Tool as ReportTool

    for tool in (EventTool, PdfTool, StartupTool, ReportTool):
        assert issubclass(tool, BaseTool)
        assert tool.setup_ui is not BaseTool.setup_ui
