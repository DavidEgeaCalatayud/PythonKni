from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

DOMAINS = {
    "archive": {
        "sources": ["tools/archive_tasks.py", "tools/archive_tool.py"],
        "adapter": "tools/archive_tool.py",
        "companions": ["tools/archive_tasks.py"],
    },
    "converter": {
        "sources": ["tools/converter_outputs.py", "tools/converter_tool.py"],
        "adapter": "tools/converter_tool.py",
        "companions": ["tools/converter_outputs.py"],
    },
    "disk_analyzer": {
        "sources": ["tools/disk_analyzer_tool.py"],
        "adapter": "tools/disk_analyzer_tool.py",
        "companions": [],
    },
    "duplicate": {
        "sources": ["tools/duplicate_tool.py"],
        "adapter": "tools/duplicate_tool.py",
        "companions": [],
    },
    "network": {
        "sources": ["tools/network_tool.py"],
        "adapter": "tools/network_tool.py",
        "companions": [],
    },
    "process_manager": {
        "sources": ["tools/process_manager_tool.py"],
        "adapter": "tools/process_manager_tool.py",
        "companions": [],
    },
    "temp_cleaner": {
        "sources": ["tools/temp_cleaner_tool.py"],
        "adapter": "tools/temp_cleaner_tool.py",
        "companions": [],
    },
    "wifi": {
        "sources": ["tools/wifi_tool.py"],
        "adapter": "tools/wifi_tool.py",
        "companions": [],
    },
    "config": {
        "sources": [
            "tools/config_service.py",
            "tools/runtime_config.py",
            "tools/config_window_tool.py",
        ],
        "adapter": "tools/config_window_tool.py",
        "companions": ["tools/config_service.py", "tools/runtime_config.py"],
        "model_constants": {
            "DEFAULT_CONFIG",
            "VALID_THEMES",
            "VALID_LANGUAGES",
            "LEGACY_LANGUAGES",
        },
    },
}

QT_PREFIXES = ("PyQt5", "PySide")
RESTRICTED_MODULES = {"tools.base_tool", "tools.worker"}


def segment(source: str, node: ast.AST) -> str:
    lines = source.splitlines(keepends=True)
    return "".join(lines[node.lineno - 1 : node.end_lineno]).rstrip() + "\n"


def imported_module(node: ast.AST) -> str | None:
    if isinstance(node, ast.ImportFrom):
        return node.module or ""
    if isinstance(node, ast.Import) and len(node.names) == 1:
        return node.names[0].name
    return None


def top_names(node: ast.AST) -> set[str]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {node.name}
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        names: set[str] = set()
        for target in targets:
            for child in ast.walk(target):
                if isinstance(child, ast.Name):
                    names.add(child.id)
        return names
    return set()


def decorators(node: ast.ClassDef) -> set[str]:
    result = set()
    for decorator in node.decorator_list:
        if isinstance(decorator, ast.Name):
            result.add(decorator.id)
        elif isinstance(decorator, ast.Attribute):
            result.add(decorator.attr)
    return result


def imported_symbols(import_nodes: list[ast.AST]) -> tuple[set[str], set[str]]:
    restricted: set[str] = set()
    qt_symbols: set[str] = set()
    for node in import_nodes:
        module = imported_module(node) or ""
        if module.startswith(QT_PREFIXES):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    name = alias.asname or alias.name
                    restricted.add(name)
                    qt_symbols.add(name)
            else:
                for alias in node.names:
                    name = alias.asname or alias.name.split(".")[0]
                    restricted.add(name)
                    qt_symbols.add(name)
        if module in RESTRICTED_MODULES and isinstance(node, ast.ImportFrom):
            restricted.update(alias.asname or alias.name for alias in node.names)
    restricted.update({"BaseTool", "Worker", "QThread"})
    return restricted, qt_symbols


def uses_restricted(node: ast.AST, restricted: set[str]) -> bool:
    return any(isinstance(child, ast.Name) and child.id in restricted for child in ast.walk(node))


def clean_import_text(text: str, domain: str, legacy_modules: set[str], *, for_service: bool) -> str | None:
    try:
        node = ast.parse(text).body[0]
    except SyntaxError:
        return text
    module = imported_module(node) or ""
    if module in legacy_modules:
        return None
    if for_service and (module.startswith(QT_PREFIXES) or module in RESTRICTED_MODULES):
        return None
    return text


def dedupe(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        key = item.strip()
        if key and key not in seen:
            seen.add(key)
            result.append(item.rstrip() + "\n")
    return result


def build_domain(domain: str, spec: dict) -> None:
    package = ROOT / "pythonkni" / domain
    package.mkdir(parents=True, exist_ok=True)

    legacy_modules = {path.replace("/", ".")[:-3] for path in spec["sources"]}
    model_constants = set(spec.get("model_constants", set()))
    model_nodes: list[str] = []
    service_nodes: list[str] = []
    window_nodes: list[str] = []
    model_names: set[str] = set()
    service_names: set[str] = set()
    all_imports: list[str] = []
    service_imports: list[str] = []
    model_imports: list[str] = []

    seen_model_names: set[str] = set()
    seen_service_names: set[str] = set()

    for source_rel in spec["sources"]:
        source_path = ROOT / source_rel
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        import_nodes = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
        restricted, _qt_symbols = imported_symbols(import_nodes)

        for node in import_nodes:
            text = segment(source, node)
            all_imports.append(text)
            module = imported_module(node) or ""
            if not module.startswith(QT_PREFIXES) and not module.startswith("tools."):
                model_imports.append(text)
            clean = clean_import_text(text, domain, legacy_modules, for_service=True)
            if clean:
                service_imports.append(clean)

        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                continue

            names = top_names(node)
            is_model = False
            if isinstance(node, ast.ClassDef) and "dataclass" in decorators(node):
                is_model = True
            if names & model_constants:
                is_model = True

            if is_model:
                if names and names <= seen_model_names:
                    continue
                model_nodes.append(segment(source, node))
                model_names.update(names)
                seen_model_names.update(names)
                continue

            is_window = False
            if isinstance(node, ast.ClassDef) and node.name == "Tool":
                is_window = True
            elif uses_restricted(node, restricted):
                is_window = True

            if is_window:
                window_nodes.append(segment(source, node))
                continue

            if names and names <= seen_service_names:
                continue
            service_nodes.append(segment(source, node))
            service_names.update(names)
            seen_service_names.update(names)

    # Models: keep them framework-independent. Broad stdlib/third-party imports are harmless,
    # but never retain tools/PyQt imports.
    model_header = ["from __future__ import annotations\n"]
    for text in model_imports:
        if text.startswith("from __future__ import"):
            continue
        model_header.append(text)
    models_text = "".join(dedupe(model_header)) + "\n"
    if model_nodes:
        models_text += "\n".join(node.rstrip() for node in model_nodes) + "\n"
    else:
        models_text += '"""Domain has no dedicated value objects yet."""\n\n__all__: list[str] = []\n'
    (package / "models.py").write_text(models_text, encoding="utf-8")

    service_header = ["from __future__ import annotations\n"]
    for text in service_imports:
        if text.startswith("from __future__ import"):
            continue
        # Config runtime was merged into this service; its old intra-tools import is now local.
        if domain == "config" and (
            "tools.config_service" in text or "tools.runtime_config" in text
        ):
            continue
        service_header.append(text)
    if model_names:
        service_header.append(
            "from .models import (\n    " + ",\n    ".join(sorted(model_names)) + ",\n)\n"
        )
    service_text = "".join(dedupe(service_header)) + "\n"
    service_text += "\n".join(node.rstrip() for node in service_nodes) + "\n"
    (package / "service.py").write_text(service_text, encoding="utf-8")

    # Window: retain original imports for UI/runtime compatibility, but remove imports of the
    # legacy companion modules now merged into this package.
    window_header = ["from __future__ import annotations\n"]
    for text in all_imports:
        if text.startswith("from __future__ import"):
            continue
        try:
            inode = ast.parse(text).body[0]
            module = imported_module(inode) or ""
        except SyntaxError:
            module = ""
        if module in legacy_modules:
            continue
        window_header.append(text)
    if model_names:
        window_header.append(
            "from .models import (\n    " + ",\n    ".join(sorted(model_names)) + ",\n)\n"
        )
    if service_names:
        window_header.append(
            "from .service import (\n    " + ",\n    ".join(sorted(service_names)) + ",\n)\n"
        )
    window_header.extend(["from . import service as _service\n", "import sys as _sys\n", "import types as _types\n"])
    window_text = "".join(dedupe(window_header)) + "\n"
    window_text += "\n".join(node.rstrip() for node in window_nodes) + "\n\n"
    window_text += '''class _CompatibilityModule(_types.ModuleType):
    """Forward legacy monkeypatches to the separated service module."""

    def __setattr__(self, name, value):
        if hasattr(_service, name):
            setattr(_service, name, value)
        super().__setattr__(name, value)

    def __delattr__(self, name):
        if hasattr(_service, name):
            delattr(_service, name)
        super().__delattr__(name)


_sys.modules[__name__].__class__ = _CompatibilityModule
'''
    (package / "window.py").write_text(window_text, encoding="utf-8")
    (package / "__init__.py").write_text(
        f'"""{domain.replace("_", " ").title()} domain."""\n', encoding="utf-8"
    )

    adapter_path = ROOT / spec["adapter"]
    adapter_path.write_text(
        "import sys\n"
        f"from pythonkni.{domain} import window as _window\n\n"
        "sys.modules[__name__] = _window\n",
        encoding="utf-8",
    )
    for companion in spec["companions"]:
        companion_path = ROOT / companion
        companion_path.write_text(
            "import sys\n"
            f"from pythonkni.{domain} import service as _service\n\n"
            "sys.modules[__name__] = _service\n",
            encoding="utf-8",
        )


def update_architecture_tests() -> None:
    path = ROOT / "tests" / "test_architecture_boundaries.py"
    path.write_text('''import ast
import importlib
from pathlib import Path

import pytest

from tools.base_tool import BaseTool


ROOT = Path(__file__).resolve().parents[1]
DOMAINS = {
    "archive": "archive_tool.py",
    "config": "config_window_tool.py",
    "converter": "converter_tool.py",
    "disk_analyzer": "disk_analyzer_tool.py",
    "duplicate": "duplicate_tool.py",
    "event_viewer": "event_viewer_tool.py",
    "network": "network_tool.py",
    "pdf": "pdf_merge_tool.py",
    "process_manager": "process_manager_tool.py",
    "startup": "startup_manager_tool.py",
    "system_report": "system_report_tool.py",
    "temp_cleaner": "temp_cleaner_tool.py",
    "wifi": "wifi_tool.py",
}
SERVICE_MODULES = [ROOT / "pythonkni" / domain / "service.py" for domain in DOMAINS]
MODEL_MODULES = [ROOT / "pythonkni" / domain / "models.py" for domain in DOMAINS]
TOOL_WRAPPERS = [ROOT / "tools" / filename for filename in DOMAINS.values()]


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
''', encoding="utf-8")


def update_docs() -> None:
    path = ROOT / "docs" / "architecture.md"
    existing = path.read_text(encoding="utf-8") if path.exists() else "# Architecture\n"
    marker = "## Domain architecture"
    if marker in existing:
        existing = existing.split(marker, 1)[0].rstrip() + "\n\n"
    domains = ", ".join(sorted(DOMAINS))
    existing += f'''## Domain architecture

All user-facing domains now follow the same dependency direction:

```text
models.py  <-  service.py  <-  window.py  <-  tools/*_tool.py adapter
```

`models.py` contains framework-independent value objects. `service.py` owns domain,
OS and persistence logic and must not import Qt, workers or window modules.
`window.py` owns PyQt presentation and background-thread orchestration. The modules
under `tools/` are compatibility/discovery adapters only.

Migrated domains: {domains}.

The architecture boundary tests enumerate this full set so a new domain cannot
silently regress to a monolithic `tools/*_tool.py` implementation.
'''
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(existing, encoding="utf-8")


def cleanup_bootstrap() -> None:
    for rel in (
        "scripts/architecture_migration.py",
        ".github/workflows/architecture-migration.yml",
    ):
        path = ROOT / rel
        if path.exists():
            path.unlink()


def main() -> None:
    for domain, spec in DOMAINS.items():
        build_domain(domain, spec)
    update_architecture_tests()
    update_docs()
    cleanup_bootstrap()


if __name__ == "__main__":
    main()
