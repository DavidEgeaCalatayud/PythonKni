import tools.config_window_tool as config_window
from tools.language_manager import LanguageManager
from tools.runtime_config import apply_runtime_config
from tools.theme_manager import ThemeManager


def test_config_window_reports_save_failure_without_applying_changes(tmp_path, monkeypatch, qtbot):
    config_file = tmp_path / "config.json"
    monkeypatch.setattr(config_window, "CONFIG_FILE", config_file)
    apply_runtime_config({"theme": "Claro", "language": "Español"})

    critical_messages = []
    information_messages = []
    monkeypatch.setattr(
        config_window.QMessageBox,
        "critical",
        lambda *args: critical_messages.append(args),
    )
    monkeypatch.setattr(
        config_window.QMessageBox,
        "information",
        lambda *args: information_messages.append(args),
    )

    tool = config_window.Tool()
    qtbot.addWidget(tool)
    tool.theme_combobox.setCurrentText("Oscuro")
    tool.language_combobox.setCurrentText("Inglés")

    def fail_save(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(config_window, "save_runtime_config", fail_save)

    tool.save_changes()

    assert critical_messages
    assert "No se pudo guardar" in critical_messages[0][2]
    assert information_messages == []
    assert ThemeManager.get_theme() == "Claro"
    assert LanguageManager.get_language() == "Español"
    assert not config_file.exists()
