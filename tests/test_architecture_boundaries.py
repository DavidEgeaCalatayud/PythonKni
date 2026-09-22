import ast
import importlib
from pathlib import Path

import pytest

from tools.base_tool import BaseTool

ROOT = Path(__file__).resolve().parents[1]
DOMAINS = {
    "archive": "archive_tool.py",
    "camera_auditor": "camera_auditor_tool.py",
    "config": "config_window_tool.py",
    "converter": "converter_tool.py",
    "disk_analyzer": "disk_analyzer_tool.py",
    "duplicate": "duplicate_tool.py",
    "event_viewer": "event_viewer_tool.py",
    "network": "network_tool.py",
    "network_intelligence": "network_intelligence_tool.py",
    "network_monitor": "network_monitor_tool.py",
    "network_path": "network_path_tool.py",
    "pdf": "pdf_merge_tool.py",
    "process_manager": "process_manager_tool.py",
    "secure_transfer": "secure_transfer_tool.py",
    "startup": "startup_manager_tool.py",
    "system_report": "system_report_tool.py",
    "temp_cleaner": "temp_cleaner_tool.py",
    "web_recon": "web_recon_tool.py",
    "wifi": "wifi_tool.py",
}
SERVICE_MODULES = [ROOT / "pythonkni" / domain / "service.py" for domain in DOMAINS]
MODEL_MODULES = [ROOT / "pythonkni" / domain / "models.py" for domain in DOMAINS]
TOOL_WRAPPERS = [ROOT / "tools" / filename for filename in DOMAINS.values()]
INFRASTRUCTURE_MODULES = [
    ROOT / "pythonkni" / "infrastructure" / "archives.py",
    ROOT / "pythonkni" / "infrastructure" / "paths.py",
]


def imported_modules(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.append(node.module or "")
    return modules


@pytest.mark.parametrize("path", SERVICE_MODULES)
def test_business_services_do_not_depend_on_qt_or_window_modules(path):
    assert path.is_file(), path
    modules = imported_modules(path)
    assert not any(name == "PyQt5" or name.startswith("PyQt5.") for name in modules)
    assert "tools.worker" not in modules
    assert not any(name.endswith(".window") for name in modules)


@pytest.mark.parametrize("path", MODEL_MODULES)
def test_models_are_framework_independent(path):
    assert path.is_file(), path
    modules = imported_modules(path)
    assert not any(name == "PyQt5" or name.startswith("PyQt5.") for name in modules)
    assert not any(name == "tools" or name.startswith("tools.") for name in modules)


@pytest.mark.parametrize("path", INFRASTRUCTURE_MODULES)
def test_shared_infrastructure_is_framework_independent(path):
    assert path.is_file(), path
    modules = imported_modules(path)
    assert not any(name == "PyQt5" or name.startswith("PyQt5.") for name in modules)
    assert not any(name == "tools" or name.startswith("tools.") for name in modules)


def test_archive_service_depends_on_infrastructure_not_legacy_tools():
    modules = imported_modules(ROOT / "pythonkni" / "archive" / "service.py")
    assert "pythonkni.infrastructure.archives" in modules
    assert "tools.zip_7zip_utils" not in modules


def test_config_persistence_service_is_ui_framework_independent():
    modules = imported_modules(ROOT / "pythonkni" / "config" / "service.py")
    assert not any(name == "tools" or name.startswith("tools.") for name in modules)
    assert not any(name == "PyQt5" or name.startswith("PyQt5.") for name in modules)


def test_process_manager_window_does_not_own_psutil_integration():
    modules = imported_modules(ROOT / "pythonkni" / "process_manager" / "window.py")
    assert "psutil" not in modules


def test_legacy_app_paths_is_only_an_infrastructure_alias():
    content = (ROOT / "tools" / "app_paths.py").read_text(encoding="utf-8")
    assert "pythonkni.infrastructure" in content
    assert len(content.splitlines()) <= 10


@pytest.mark.parametrize("path", TOOL_WRAPPERS)
def test_legacy_tool_modules_are_thin_compatibility_adapters(path):
    content = path.read_text(encoding="utf-8")
    assert "pythonkni." in content
    assert len(content.splitlines()) <= 20


@pytest.mark.parametrize("domain", DOMAINS)
def test_every_domain_window_keeps_base_tool_contract(domain):
    module = importlib.import_module(f"pythonkni.{domain}.window")
    tool = module.Tool
    assert issubclass(tool, BaseTool)
    assert tool.setup_ui is not BaseTool.setup_ui


def test_all_declared_domains_have_models_service_window_layers():
    for domain in DOMAINS:
        package = ROOT / "pythonkni" / domain
        assert (package / "models.py").is_file()
        assert (package / "service.py").is_file()
        assert (package / "window.py").is_file()
