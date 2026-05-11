import os
import importlib
import logging
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QPushButton, QWidget, QLabel
from PyQt5.QtCore import Qt, QThread, pyqtSignal

from tools.logging_config import setup_logging


logger = logging.getLogger(__name__)


class LoaderThread(QThread):
    tools_loaded = pyqtSignal(list, object)  # (normal_tools, config_tool)

    def run(self):
        tools_dir = os.path.join(os.path.dirname(__file__), "tools")

        normal_tools = []
        config_tool = None

        for file in os.listdir(tools_dir):
            if file.endswith("_tool.py") and file != "base_tool.py":
                module_name = f"tools.{file[:-3]}"
                try:
                    module = importlib.import_module(module_name)
                    tool_class = getattr(module, "Tool")
                except Exception:
                    logger.exception("Error loading tool module %s", module_name)
                    continue

                if "config" in file.lower():
                    config_tool = tool_class
                else:
                    normal_tools.append(tool_class)

        normal_tools.sort(key=lambda cls: cls.name.lower())

        # Emitir señal con los resultados
        self.tools_loaded.emit(normal_tools, config_tool)


class MenuWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Navaja Multiusos")
        self.setGeometry(100, 100, 600, 400)

        self.setStyleSheet(
            """
            QMainWindow {
                background-color: #1e1e1e;
            }
            QPushButton {
                background-color: #2b2b2b;
                color: white;
                font-size: 18px;
                font-weight: bold;
                border-radius: 10px;
                padding: 10px;
            }
            QPushButton:hover {
                background-color: #3d3d3d;
            }
            QLabel {
                color: white;
                font-size: 20px;
                font-weight: bold;
            }
            """
        )

        self.layout = QVBoxLayout()
        self.label_loading = QLabel("Cargando herramientas...")
        self.label_loading.setAlignment(Qt.AlignCenter)
        self.layout.addWidget(self.label_loading)

        container = QWidget()
        container.setLayout(self.layout)
        self.setCentralWidget(container)

        # Lanzar hilo que carga los tools
        self.loader_thread = LoaderThread()
        self.loader_thread.tools_loaded.connect(self.on_tools_loaded)
        self.loader_thread.start()

    def on_tools_loaded(self, normal_tools, config_tool):
        """Recibimos la lista desde el hilo y generamos los botones"""
        # Eliminar mensaje de cargando
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

    def open_tool(self, tool_class):
        self.window = tool_class()
        self.window.show()


if __name__ == "__main__":
    setup_logging()
    app = QApplication([])

    from tools.theme_manager import ThemeManager

    ThemeManager.apply_theme(app)

    window = MenuWindow()
    window.show()
    app.exec_()
