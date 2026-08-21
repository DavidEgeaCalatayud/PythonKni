import importlib
import inspect
import logging
import os
import sys

from PyQt5.QtCore import QThread, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from tools.app_paths import ASSETS_DIR, CONFIG_FILE
from tools.base_tool import BaseTool
from tools.config_service import DEFAULT_CONFIG
from tools.logging_config import setup_logging
from tools.runtime_config import apply_runtime_config, load_runtime_config
from tools.theme_manager import ThemeManager


logger = logging.getLogger(__name__)


class ToolContractError(TypeError):
    """Raised when a dynamically discovered tool violates the BaseTool contract."""


def validate_tool_class(tool_class, module_name="<tool>"):
    if not inspect.isclass(tool_class):
        raise ToolContractError(f"{module_name}.Tool must be a class")
    if not issubclass(tool_class, BaseTool):
        raise ToolContractError(f"{module_name}.Tool must inherit from BaseTool")
    if tool_class.setup_ui is BaseTool.setup_ui:
        raise ToolContractError(f"{module_name}.Tool must implement setup_ui()")

    for attribute in ("name", "description", "category"):
        value = getattr(tool_class, attribute, None)
        if not isinstance(value, str) or not value.strip():
            raise ToolContractError(f"{module_name}.Tool.{attribute} must be a non-empty string")

    return tool_class


def discover_tool_classes(tools_dir=None):
    """Discover loader-compatible tools synchronously.

    Keeping discovery in a normal function lets the GUI loader and the packaged
    executable smoke test exercise exactly the same dynamic-import path.
    """
    if tools_dir is None:
        tools_dir = os.path.join(os.path.dirname(__file__), "tools")

    normal_tools = []
    config_tool = None
    load_errors = []

    for file in os.listdir(tools_dir):
        if not file.endswith("_tool.py") or file == "base_tool.py":
            continue

        module_name = f"tools.{file[:-3]}"
        try:
            module = importlib.import_module(module_name)
            tool_class = validate_tool_class(getattr(module, "Tool"), module_name)
        except Exception as error:
            logger.exception("Error loading tool module %s", module_name)
            load_errors.append(f"{module_name}: {error}")
            continue

        if "config" in file.lower():
            config_tool = tool_class
        else:
            normal_tools.append(tool_class)

    normal_tools.sort(key=lambda cls: cls.name.lower())
    return normal_tools, config_tool, load_errors


def run_packaging_smoke_test() -> int:
    """Validate the frozen bundle without starting the Qt event loop."""
    try:
        normal_tools, config_tool, load_errors = discover_tool_classes()
    except Exception:
        logger.exception("Packaged tool discovery failed")
        return 1

    if load_errors or not normal_tools or config_tool is None:
        logger.error(
            "Packaging smoke test failed: normal_tools=%s config_tool=%s errors=%s",
            len(normal_tools),
            config_tool is not None,
            load_errors,
        )
        return 1

    required_assets = (ASSETS_DIR / "spinner.gif",)
    missing_assets = [str(path) for path in required_assets if not path.is_file()]
    if missing_assets:
        logger.error("Packaging smoke test is missing assets: %s", missing_assets)
        return 1

    return 0


class LoaderThread(QThread):
    tools_loaded = pyqtSignal(list, object, list)  # (normal_tools, config_tool, load_errors)

    def run(self):
        normal_tools, config_tool, load_errors = discover_tool_classes()
        self.tools_loaded.emit(normal_tools, config_tool, load_errors)


class MenuWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Navaja Multiusos")
        self.setGeometry(100, 100, 600, 400)

        self.layout = QVBoxLayout()
        self.label_loading = QLabel("Cargando herramientas...")
        self.label_loading.setAlignment(Qt.AlignCenter)
        self.layout.addWidget(self.label_loading)

        container = QWidget()
        container.setLayout(self.layout)
        self.setCentralWidget(container)

        self.loader_thread = LoaderThread()
        self.loader_thread.tools_loaded.connect(self.on_tools_loaded)
        self.loader_thread.start()

    def on_tools_loaded(self, normal_tools, config_tool, load_errors):
        """Recibimos la lista desde el hilo y generamos los botones."""
        self.layout.removeWidget(self.label_loading)
        self.label_loading.deleteLater()

        for tool_class in normal_tools:
            btn = QPushButton(tool_class.name)
            btn.clicked.connect(lambda checked, cls=tool_class: self.open_tool(cls))
            self.layout.addWidget(btn)

        if config_tool:
            btn = QPushButton(config_tool.name)
            btn.clicked.connect(lambda checked, cls=config_tool: self.open_tool(cls))
            self.layout.addWidget(btn)

        if load_errors:
            QMessageBox.warning(
                self,
                "Herramientas no cargadas",
                "Algunas herramientas no se han podido cargar:\n\n" + "\n".join(load_errors),
            )

    def open_tool(self, tool_class):
        self.window = tool_class()
        self.window.show()


def configure_managers():
    """Carga la configuración persistida antes de crear la interfaz Qt."""
    try:
        return load_runtime_config(CONFIG_FILE)
    except (OSError, ValueError):
        logger.exception("No se pudo cargar la configuración: %s", CONFIG_FILE)
        config = DEFAULT_CONFIG.copy()
        apply_runtime_config(config)
        return config


if __name__ == "__main__":
    if "--smoke-test" in sys.argv:
        raise SystemExit(run_packaging_smoke_test())

    setup_logging()
    configure_managers()

    app = QApplication([])
    ThemeManager.apply_theme(app)

    window = MenuWindow()
    window.show()
    app.exec_()
