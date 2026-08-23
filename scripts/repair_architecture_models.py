from __future__ import annotations

import ast
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOMAINS = {
    "archive": ["tools/archive_tasks.py", "tools/archive_tool.py"],
    "converter": ["tools/converter_outputs.py", "tools/converter_tool.py"],
    "disk_analyzer": ["tools/disk_analyzer_tool.py"],
    "duplicate": ["tools/duplicate_tool.py"],
    "network": ["tools/network_tool.py"],
    "process_manager": ["tools/process_manager_tool.py"],
    "temp_cleaner": ["tools/temp_cleaner_tool.py"],
    "wifi": ["tools/wifi_tool.py"],
    "config": ["tools/config_service.py", "tools/runtime_config.py", "tools/config_window_tool.py"],
}


def main_source(path: str) -> str:
    return subprocess.check_output(
        ["git", "show", f"origin/main:{path}"], text=True, encoding="utf-8"
    )


def decorator_name(decorator: ast.expr) -> str | None:
    if isinstance(decorator, ast.Call):
        decorator = decorator.func
    if isinstance(decorator, ast.Name):
        return decorator.id
    if isinstance(decorator, ast.Attribute):
        return decorator.attr
    return None


def is_dataclass(node: ast.ClassDef) -> bool:
    return any(decorator_name(item) == "dataclass" for item in node.decorator_list)


def segment_with_decorators(source: str, node: ast.ClassDef) -> str:
    lines = source.splitlines(keepends=True)
    start = min([node.lineno] + [item.lineno for item in node.decorator_list])
    return "".join(lines[start - 1 : node.end_lineno]).rstrip() + "\n"


def import_segment(source: str, node: ast.AST) -> str:
    lines = source.splitlines(keepends=True)
    return "".join(lines[node.lineno - 1 : node.end_lineno]).rstrip() + "\n"


def imported_module(node: ast.AST) -> str:
    if isinstance(node, ast.ImportFrom):
        return node.module or ""
    if isinstance(node, ast.Import) and len(node.names) == 1:
        return node.names[0].name
    return ""


def dedupe(items: list[str]) -> list[str]:
    result = []
    seen = set()
    for item in items:
        key = item.strip()
        if key and key not in seen:
            seen.add(key)
            result.append(item.rstrip() + "\n")
    return result


def remove_classes(source: str, names: set[str]) -> str:
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    ranges = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name in names:
            start = min([node.lineno] + [item.lineno for item in node.decorator_list])
            ranges.append((start, node.end_lineno))
    for start, end in sorted(ranges, reverse=True):
        del lines[start - 1 : end]
    return "".join(lines)


def add_model_import(service: str, names: set[str]) -> str:
    if not names:
        return service
    import_text = "from .models import (\n    " + ",\n    ".join(sorted(names)) + ",\n)\n"
    lines = service.splitlines(keepends=True)
    insert_at = 1 if lines and lines[0].startswith("from __future__ import") else 0
    lines.insert(insert_at, import_text)
    return "".join(lines)


def repair_domain(domain: str, paths: list[str]) -> None:
    dataclasses: list[str] = []
    names: set[str] = set()
    imports: list[str] = ["from __future__ import annotations\n"]

    for path in paths:
        source = main_source(path)
        tree = ast.parse(source)
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = imported_module(node)
                if module.startswith("PyQt5") or module.startswith("PySide") or module.startswith("tools"):
                    continue
                if module == "__future__":
                    continue
                imports.append(import_segment(source, node))
            elif isinstance(node, ast.ClassDef) and is_dataclass(node):
                names.add(node.name)
                dataclasses.append(segment_with_decorators(source, node))

    if not names:
        return

    package = ROOT / "pythonkni" / domain
    models = "".join(dedupe(imports)) + "\n" + "\n".join(item.rstrip() for item in dataclasses) + "\n"
    (package / "models.py").write_text(models, encoding="utf-8")

    service_path = package / "service.py"
    service = remove_classes(service_path.read_text(encoding="utf-8"), names)
    service = add_model_import(service, names)
    service_path.write_text(service, encoding="utf-8")

    model_tree = ast.parse(models)
    model_classes = {node.name for node in model_tree.body if isinstance(node, ast.ClassDef)}
    service_tree = ast.parse(service)
    service_classes = {node.name for node in service_tree.body if isinstance(node, ast.ClassDef)}
    assert names <= model_classes, (domain, names - model_classes)
    assert not (names & service_classes), (domain, names & service_classes)


def cleanup() -> None:
    for rel in (
        "scripts/repair_architecture_models.py",
        ".github/workflows/repair-architecture-models.yml",
    ):
        path = ROOT / rel
        if path.exists():
            path.unlink()


def main() -> None:
    for domain, paths in DOMAINS.items():
        repair_domain(domain, paths)
    cleanup()


if __name__ == "__main__":
    main()
