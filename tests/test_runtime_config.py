import json

from tools.language_manager import LanguageManager
from tools.runtime_config import apply_runtime_config, load_runtime_config, save_runtime_config
from tools.theme_manager import ThemeManager


def test_apply_runtime_config_updates_both_managers():
    apply_runtime_config({"theme": "Oscuro", "language": "Inglés"})

    assert ThemeManager.get_theme() == "Oscuro"
    assert LanguageManager.get_language() == "Inglés"


def test_load_runtime_config_applies_saved_preferences(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(
        json.dumps({"theme": "Oscuro", "language": "Ingles"}),
        encoding="utf-8",
    )

    loaded = load_runtime_config(config_file)

    assert loaded == {"theme": "Oscuro", "language": "Inglés"}
    assert ThemeManager.get_theme() == "Oscuro"
    assert LanguageManager.get_language() == "Inglés"


def test_save_runtime_config_persists_and_applies_both_settings(tmp_path):
    config_file = tmp_path / "config.json"

    saved = save_runtime_config(
        config_file,
        {"theme": "Oscuro", "language": "Ingles"},
    )

    assert saved == {"theme": "Oscuro", "language": "Inglés"}
    assert json.loads(config_file.read_text(encoding="utf-8")) == saved
    assert ThemeManager.get_theme() == "Oscuro"
    assert LanguageManager.get_language() == "Inglés"
