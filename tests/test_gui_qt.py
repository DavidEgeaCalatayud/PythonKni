import json
import time

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMessageBox, QPushButton

import main
from tools.config_window_tool import Tool as ConfigTool
from tools.converter_tool import Tool as ConverterTool
from tools.language_manager import LanguageManager
from tools.theme_manager import ThemeManager
from tools.worker import Worker


def test_menu_loads_discovered_plugins(qtbot):
    window = main.MenuWindow()
    qtbot.addWidget(window)
    window.show()

    qtbot.waitUntil(lambda: not window.loader_thread.isRunning(), timeout=10000)
    qtbot.waitUntil(lambda: len(window.findChildren(QPushButton)) >= 10, timeout=3000)

    labels = {button.text() for button in window.findChildren(QPushButton)}
    assert "Analizador de Disco" in labels
    assert "Gestor de Procesos" in labels
    assert "Configuracion" in labels


def test_loader_emits_import_errors(qtbot, monkeypatch):
    monkeypatch.setattr(main.os, "listdir", lambda _path: ["broken_tool.py"])

    def fail_import(_module_name):
        raise RuntimeError("plugin roto")

    monkeypatch.setattr(main.importlib, "import_module", fail_import)
    loader = main.LoaderThread()

    with qtbot.waitSignal(loader.tools_loaded, timeout=3000) as blocker:
        loader.start()

    loader.wait()
    normal_tools, config_tool, errors = blocker.args
    assert normal_tools == []
    assert config_tool is None
    assert len(errors) == 1
    assert "tools.broken_tool" in errors[0]
    assert "plugin roto" in errors[0]


def test_worker_can_be_started_and_cancelled(qtbot):
    def slow_task(worker):
        while True:
            worker.check_cancelled()
            time.sleep(0.005)

    worker = Worker(slow_task)
    with qtbot.waitSignal(worker.started, timeout=2000):
        worker.start()

    qtbot.waitUntil(worker.isRunning, timeout=1000)
    with qtbot.waitSignal(worker.cancelled, timeout=3000):
        worker.cancel()

    assert worker.wait(2000)


def test_converter_defers_close_until_active_worker_is_cancelled(qtbot, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: None)

    def slow_conversion(worker=None):
        while True:
            worker.check_cancelled()
            time.sleep(0.005)

    window = ConverterTool()
    qtbot.addWidget(window)
    window.show()
    window._start_conversion("Procesando...", slow_conversion, (), "Terminado")
    worker = window._worker
    qtbot.waitUntil(worker.isRunning, timeout=1000)

    with qtbot.waitSignal(worker.finished, timeout=3000):
        window.close()
        assert window.isVisible()
        assert window._close_when_worker_finishes is True

    qtbot.waitUntil(lambda: not window.isVisible(), timeout=3000)


def test_config_window_applies_and_persists_theme_and_language(qtbot, monkeypatch, tmp_path):
    import tools.config_window_tool as config_window

    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_window, "CONFIG_FILE", config_path)
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)

    ThemeManager.set_theme("Claro")
    LanguageManager.set_language("Español")

    window = ConfigTool()
    qtbot.addWidget(window)
    window.show()
    window.theme_combobox.setCurrentText("Oscuro")
    window.language_combobox.setCurrentText("Inglés")

    qtbot.mouseClick(window.save_button, Qt.LeftButton)

    assert ThemeManager.get_theme() == "Oscuro"
    assert LanguageManager.get_language() == "Inglés"
    assert window.save_button.text() == "Save changes"
    assert json.loads(config_path.read_text(encoding="utf-8")) == {
        "theme": "Oscuro",
        "language": "Inglés",
    }

    ThemeManager.set_theme("Claro")
    LanguageManager.set_language("Español")
