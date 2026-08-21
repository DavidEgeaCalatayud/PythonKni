from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content.rstrip() + "\n", encoding="utf-8")


def replace_required(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"No se encontró el bloque esperado: {label}")
    return text.replace(old, new, 1)


def create_packages() -> None:
    write(
        "pythonkni/__init__.py",
        '''"""Core application package.

Domain packages keep business logic independent from the PyQt compatibility
adapters under :mod:`tools`.
"""''',
    )
    for domain in ("event_viewer", "startup", "system_report", "pdf"):
        write(
            f"pythonkni/{domain}/__init__.py",
            f'''"""Domain package for {domain.replace("_", " ")}."""''',
        )


def split_startup() -> None:
    source = read("tools/startup_manager_tool.py")
    constants_start = source.index("RUN_KEY =")
    model_start = source.index("@dataclass\nclass StartupItem:")
    exception_start = source.index("\n\nclass StartupTransactionError", model_start)
    ui_marker = source.index(
        "# ---------------------------------------------------------------------------\n# Interfaz PyQt5"
    )
    tool_start = source.index("class Tool(BaseTool):", ui_marker)

    constants = source[constants_start:model_start].rstrip()
    model_block = source[model_start:exception_start].strip()
    service_body = source[exception_start:ui_marker].strip()
    window_body = source[tool_start:].strip()

    old_open_folder = """def open_folder(path: str | Path) -> None:
    folder = Path(path)
    if folder.is_file():
        folder = folder.parent
    if not folder.exists():
        raise FileNotFoundError(str(folder))

    if platform.system() == "Windows":
        os.startfile(str(folder))  # type: ignore[attr-defined]
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
"""
    new_open_folder = '''def open_folder(path: str | Path) -> None:
    """Open a folder with the platform shell without depending on Qt."""
    folder = Path(path)
    if folder.is_file():
        folder = folder.parent
    if not folder.exists():
        raise FileNotFoundError(str(folder))

    system = platform.system()
    if system == "Windows":
        os.startfile(str(folder))  # type: ignore[attr-defined]
    elif system == "Darwin":
        subprocess.Popen(["open", str(folder)])
    else:
        subprocess.Popen(["xdg-open", str(folder)])
'''
    service_body = replace_required(
        service_body, old_open_folder, new_open_folder, "startup.open_folder"
    )

    models = f"""from __future__ import annotations

import uuid
from dataclasses import dataclass, field


{model_block}
"""
    write("pythonkni/startup/models.py", models)

    service = f"""from __future__ import annotations

import errno
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import winreg  # type: ignore
except ImportError:  # pragma: no cover - only available on Windows
    winreg = None  # type: ignore

from .models import StartupItem


{constants}


{service_body}
"""
    write("pythonkni/startup/service.py", service)

    window = f"""from __future__ import annotations

import csv
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tools.base_tool import BaseTool
from tools.theme_manager import ThemeManager

from .models import StartupItem
from .service import (
    collect_startup_items,
    disable_folder_item,
    disable_registry_item,
    enable_folder_item,
    enable_registry_item,
    extract_executable_path,
    is_windows,
    open_folder,
    run_regedit_at_key,
)


{window_body}
"""
    write("pythonkni/startup/window.py", window)

    wrapper = '''"""Compatibility adapter for the startup-manager plugin.

New code should import from :mod:`pythonkni.startup`.
"""

from pythonkni.startup.models import *
from pythonkni.startup.service import *
from pythonkni.startup.window import Tool
'''
    write("tools/startup_manager_tool.py", wrapper)


def split_event_viewer() -> None:
    source = read("tools/event_viewer_tool.py")
    model_start = source.index("@dataclass\nclass EventItem:")
    service_marker = source.index(
        "# ---------------------------------------------------------------------------\n# Utilidades de lectura y diagnóstico"
    )
    worker_marker = source.index(
        "# ---------------------------------------------------------------------------\n# Hilo de carga"
    )
    worker_start = source.index("class EventWorker(QThread):", worker_marker)

    model_block = source[model_start:service_marker].strip()
    service_body = source[source.index("def is_windows()", service_marker) : worker_marker].strip()
    window_body = source[worker_start:].strip()

    old_setup = """    def setup_ui(self):
        self.setWindowTitle(self.name)
        self.resize(1350, 780)
        self.events: list[EventItem] = []
        self.visible_events: list[EventItem] = []
        self.worker: EventWorker | None = None
        self.setup_ui()
        ThemeManager.apply_theme(QApplication.instance())

    def setup_ui(self) -> None:
"""
    new_setup = """    def setup_ui(self) -> None:
        self.setWindowTitle(self.name)
        self.resize(1350, 780)
        self.events: list[EventItem] = []
        self.visible_events: list[EventItem] = []
        self.worker: EventWorker | None = None
        ThemeManager.apply_theme(QApplication.instance())

"""
    window_body = replace_required(window_body, old_setup, new_setup, "event_viewer.Tool.setup_ui")
    window_body = replace_required(
        window_body,
        "    finished = pyqtSignal(object)\n",
        "    result_ready = pyqtSignal(object)\n",
        "EventWorker signal",
    )
    window_body = replace_required(
        window_body,
        "            self.finished.emit(result)\n",
        "            self.result_ready.emit(result)\n",
        "EventWorker emit",
    )
    window_body = replace_required(
        window_body,
        "        self.worker.finished.connect(self.on_events_loaded)\n",
        "        self.worker.result_ready.connect(self.on_events_loaded)\n",
        "EventWorker connection",
    )

    models = f"""from __future__ import annotations

from dataclasses import dataclass


{model_block}
"""
    write("pythonkni/event_viewer/models.py", models)

    service = f"""from __future__ import annotations

import html
import json
import platform
import re
import subprocess
import threading
import time
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Iterable

from tools.app_paths import DATA_DIR, ensure_app_dirs

from .models import EventItem, EventResult

try:
    from reportlab.lib import colors as rl_colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

    _REPORTLAB_AVAILABLE = True
except ImportError:
    _REPORTLAB_AVAILABLE = False


EVENT_SNAPSHOT_FILE = DATA_DIR / "event_report_snapshot.json"

LEVEL_NAMES = {{
    1: "Crítico",
    2: "Error",
    3: "Advertencia",
    4: "Información",
    5: "Verbose",
}}

RISK_ORDER = {{
    "Alto": 3,
    "Medio": 2,
    "Bajo": 1,
    "Normal": 0,
}}

SUPPORTED_LOGS = ["Application", "System", "Security"]


{service_body}
"""
    write("pythonkni/event_viewer/service.py", service)

    window = f"""from __future__ import annotations

import csv
import subprocess
import threading
from collections import Counter
from datetime import datetime
from pathlib import Path

from PyQt5.QtCore import QThread, Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tools.base_tool import BaseTool
from tools.theme_manager import ThemeManager

from .models import EventItem, EventResult
from .service import (
    RISK_ORDER,
    _REPORTLAB_AVAILABLE,
    clean_text,
    collect_events,
    events_to_html,
    events_to_pdf,
    save_events_snapshot,
)


RISK_COLORS = {{
    "Alto": QColor("#ffcccc"),
    "Medio": QColor("#ffe5b4"),
    "Bajo": QColor("#fff7cc"),
    "Normal": QColor("#d9f2d9"),
}}


{window_body}
"""
    write("pythonkni/event_viewer/window.py", window)

    wrapper = '''"""Compatibility adapter for the Windows Event Viewer plugin.

New code should import from :mod:`pythonkni.event_viewer`.
"""

from pythonkni.event_viewer.models import *
from pythonkni.event_viewer.service import *
from pythonkni.event_viewer.window import EventDetailDialog, EventWorker, Tool
'''
    write("tools/event_viewer_tool.py", wrapper)


def split_system_report() -> None:
    source = read("tools/system_report_tool.py")
    model_start = source.index("@dataclass\nclass ReportData:")
    service_start = source.index("def format_bytes", model_start)
    worker_start = source.index("class ReportWorker(QThread):", service_start)

    model_block = source[model_start:service_start].strip()
    service_body = source[service_start:worker_start].strip()
    window_body = source[worker_start:].strip()

    window_body = replace_required(
        window_body,
        "    finished = pyqtSignal(object)\n",
        "    result_ready = pyqtSignal(object)\n",
        "ReportWorker signal",
    )
    window_body = replace_required(
        window_body,
        "            self.finished.emit(collect_report())\n",
        "            self.result_ready.emit(collect_report())\n",
        "ReportWorker emit",
    )
    window_body = replace_required(
        window_body,
        "        self.worker.finished.connect(self.on_report_ready)\n",
        "        self.worker.result_ready.connect(self.on_report_ready)\n",
        "ReportWorker connection",
    )

    models = f"""from __future__ import annotations

from dataclasses import dataclass, field


{model_block}
"""
    write("pythonkni/system_report/models.py", models)

    service = f"""from __future__ import annotations

import getpass
import html
import json
import os
import platform
import socket
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path

import psutil
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from tools.app_paths import DATA_DIR, ensure_app_dirs

from .models import ReportData


{service_body}
"""
    write("pythonkni/system_report/service.py", service)

    window = f"""from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from tools.base_tool import BaseTool
from tools.theme_manager import ThemeManager

from .models import ReportData
from .service import collect_report, report_to_html, report_to_pdf, report_to_text


{window_body}
"""
    write("pythonkni/system_report/window.py", window)

    wrapper = '''"""Compatibility adapter for the system-report plugin.

New code should import from :mod:`pythonkni.system_report`.
"""

from pythonkni.system_report.models import *
from pythonkni.system_report.service import *
from pythonkni.system_report.window import ReportWorker, Tool
'''
    write("tools/system_report_tool.py", wrapper)


def split_pdf() -> None:
    service = read("tools/pdf_tasks.py")
    write("pythonkni/pdf/service.py", service)

    window = read("tools/pdf_merge_tool.py")
    window = replace_required(
        window,
        "from tools.pdf_tasks import (",
        "from pythonkni.pdf.service import (",
        "PDF service import",
    )
    write("pythonkni/pdf/window.py", window)

    write(
        "tools/pdf_tasks.py",
        '''"""Compatibility adapter for PDF business operations.

New code should import from :mod:`pythonkni.pdf.service`.
"""

from pythonkni.pdf.service import *
''',
    )
    write(
        "tools/pdf_merge_tool.py",
        '''"""Compatibility adapter for the PDF Toolkit plugin.

New code should import from :mod:`pythonkni.pdf`.
"""

from pythonkni.pdf.service import *
from pythonkni.pdf.window import Tool
''',
    )


def update_tests() -> None:
    event_test = read("tests/test_event_viewer_service.py")
    event_test = event_test.replace(
        "from tools import event_viewer_tool as events",
        "from pythonkni.event_viewer import service as events\n"
        "from pythonkni.event_viewer.models import EventItem",
    )
    event_test = event_test.replace("events.EventItem(", "EventItem(")
    write("tests/test_event_viewer_service.py", event_test)

    startup_test = read("tests/test_startup_manager_transactions.py")
    startup_test = startup_test.replace(
        "import tools.startup_manager_tool as startup",
        "import pythonkni.startup.service as startup",
    )
    write("tests/test_startup_manager_transactions.py", startup_test)

    system_test = read("tests/test_system_report_qt.py")
    system_test = system_test.replace(
        "from tools import system_report_tool as report",
        "from pythonkni.system_report import service as report\n"
        "from pythonkni.system_report.models import ReportData\n"
        "from pythonkni.system_report import window as report_window",
    )
    system_test = system_test.replace("return report.ReportData(", "return ReportData(")
    system_test = system_test.replace("tool = report.Tool()", "tool = report_window.Tool()")
    system_test = system_test.replace("report.QFileDialog,", "report_window.QFileDialog,")
    system_test = system_test.replace("report.QMessageBox,", "report_window.QMessageBox,")
    write("tests/test_system_report_qt.py", system_test)

    pdf_test = read("tests/test_pdf_pages.py")
    pdf_test = pdf_test.replace(
        "from tools.pdf_merge_tool import parse_page_list, parse_page_spec",
        "from pythonkni.pdf.service import parse_page_list, parse_page_spec",
    )
    write("tests/test_pdf_pages.py", pdf_test)


def add_architecture_tests() -> None:
    write(
        "tests/test_architecture_boundaries.py",
        """import ast
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
""",
    )


def update_architecture_doc() -> None:
    write(
        "docs/architecture.md",
        """# Architecture

PythonKni is a PyQt5 desktop application with a dynamic tool loader. The core
architecture now separates domain logic from Qt windows for the largest tools.

## Dependency rule

The preferred dependency direction is:

`models.py` → standard-library/domain data only

`service.py` → models + infrastructure libraries, **never PyQt5**

`window.py` → PyQt5 + models + services

`tools/*_tool.py` → thin compatibility adapter exposing `Tool` to the dynamic loader

This lets business rules run in unit tests without constructing a QApplication
and prevents UI code from becoming the owner of persistence, parsing, operating
system calls, or document transformations.

## Current layout

- `main.py`: application entry point and dynamic tool menu.
- `pythonkni/event_viewer/`
  - `models.py`: `EventItem` and `EventResult`.
  - `service.py`: Windows event collection, parsing, risk classification and exports.
  - `window.py`: Qt worker, detail dialog and tool window.
- `pythonkni/startup/`
  - `models.py`: startup-entry domain model.
  - `service.py`: registry/startup-folder discovery and transactional enable/disable logic.
  - `window.py`: startup-manager Qt window.
- `pythonkni/system_report/`
  - `models.py`: report data model.
  - `service.py`: collection and TXT/HTML/PDF rendering.
  - `window.py`: report worker and Qt window.
- `pythonkni/pdf/`
  - `service.py`: PDF parsing, splitting, merging, OCR and reorder tasks.
  - `window.py`: PDF Toolkit Qt window.
- `tools/*_tool.py`: loader-compatible adapters. The four migrated tools contain
  no business implementation there.
- `tools/worker.py`: reusable asynchronous Qt worker infrastructure.
- `tools/app_paths.py`: application-specific filesystem paths.
- `assets/`: static UI assets.

## Migration strategy

The loader still discovers `tools/*_tool.py`, so the refactor does not change the
plugin contract or menu behavior. New or substantially modified tools should put
domain code under `pythonkni/<domain>/` first and keep the legacy module as an
adapter. Remaining tools can be migrated incrementally with the same pattern.

A `models.py` module is used when a domain has stable data structures. Domains
without a useful model should not create placeholder classes merely to satisfy a
folder convention.
""",
    )


def main() -> None:
    create_packages()
    split_startup()
    split_event_viewer()
    split_system_report()
    split_pdf()
    update_tests()
    add_architecture_tests()
    update_architecture_doc()


if __name__ == "__main__":
    main()
