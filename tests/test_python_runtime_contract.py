from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_PYTHON = "3.13.15"
SUPPORTED_PYTHON = ">=3.13,<3.14"
RUFF_TARGET = "py313"
RUNTIME_WORKFLOWS = (
    ROOT / ".github" / "workflows" / "ci.yml",
    ROOT / ".github" / "workflows" / "release.yml",
    ROOT / ".github" / "workflows" / "oui-registry-maintenance.yml",
)


def test_pyproject_declares_python_313_contract():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["requires-python"] == SUPPORTED_PYTHON
    assert project["tool"]["ruff"]["target-version"] == RUFF_TARGET


def test_workflows_share_exact_canonical_python_runtime():
    runtime_pin = f'python-version: "{CANONICAL_PYTHON}"'

    for workflow in RUNTIME_WORKFLOWS:
        content = workflow.read_text(encoding="utf-8")
        assert runtime_pin in content, workflow
        assert "3.10.11" not in content, workflow
