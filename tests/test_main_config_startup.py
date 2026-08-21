import main

from tools.language_manager import LanguageManager
from tools.theme_manager import ThemeManager


def test_configure_managers_loads_preferences_before_qapplication(tmp_path, monkeypatch):
    config_file = tmp_path / "config.json"
    config_file.write_text(
        '{"theme": "Oscuro", "language": "Inglés"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(main, "CONFIG_FILE", config_file)

    config = main.configure_managers()

    assert config == {"theme": "Oscuro", "language": "Inglés"}
    assert ThemeManager.get_theme() == "Oscuro"
    assert LanguageManager.get_language() == "Inglés"
