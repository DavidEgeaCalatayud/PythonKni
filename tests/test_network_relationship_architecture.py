import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULES = [
    ROOT / "pythonkni" / "network_intelligence" / "relationships.py",
    ROOT / "pythonkni" / "network_intelligence" / "relationship_store.py",
    ROOT / "pythonkni" / "network_intelligence" / "topology.py",
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


def test_relationship_and_topology_logic_remains_framework_independent():
    for path in MODULES:
        modules = imported_modules(path)
        assert not any(name == "PyQt5" or name.startswith("PyQt5.") for name in modules)
        assert not any(name == "tools" or name.startswith("tools.") for name in modules)
        assert not any(name.endswith(".window") for name in modules)
