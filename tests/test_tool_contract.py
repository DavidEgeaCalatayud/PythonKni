import importlib
from pathlib import Path

import pytest

from main import ToolContractError, validate_tool_class
from tools.base_tool import BaseTool


def iter_tool_modules():
    tools_dir = Path(__file__).resolve().parents[1] / "tools"
    for path in sorted(tools_dir.glob("*_tool.py")):
        if path.name == "base_tool.py":
            continue
        yield f"tools.{path.stem}"


def test_every_discovered_tool_implements_base_tool_contract():
    modules = list(iter_tool_modules())
    assert modules

    for module_name in modules:
        module = importlib.import_module(module_name)
        tool_class = validate_tool_class(module.Tool, module_name)
        assert issubclass(tool_class, BaseTool)
        assert tool_class.setup_ui is not BaseTool.setup_ui
        assert tool_class.name.strip()
        assert tool_class.description.strip()
        assert tool_class.category.strip()


def test_contract_rejects_non_base_tool_classes():
    class InvalidTool:
        name = "Invalid"
        description = "Invalid"
        category = "Tests"

        def setup_ui(self):
            pass

    with pytest.raises(ToolContractError, match="inherit from BaseTool"):
        validate_tool_class(InvalidTool, "tests.invalid")


def test_contract_rejects_missing_setup_ui_override():
    class InvalidTool(BaseTool):
        name = "Invalid"
        description = "Invalid"
        category = "Tests"

    with pytest.raises(ToolContractError, match="implement setup_ui"):
        validate_tool_class(InvalidTool, "tests.invalid")


@pytest.mark.parametrize("attribute", ["name", "description", "category"])
def test_contract_rejects_empty_metadata(attribute):
    class InvalidTool(BaseTool):
        name = "Valid"
        description = "Valid"
        category = "Tests"

        def setup_ui(self):
            pass

    setattr(InvalidTool, attribute, "   ")
    with pytest.raises(ToolContractError, match=attribute):
        validate_tool_class(InvalidTool, "tests.invalid")
