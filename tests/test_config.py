import json

import pytest

from tools.config_service import DEFAULT_CONFIG, load_config, save_config


def test_load_config_returns_defaults_when_file_does_not_exist(tmp_path):
    assert load_config(tmp_path / "config.json") == DEFAULT_CONFIG


def test_save_and_load_config_roundtrip(tmp_path):
    config_file = tmp_path / "settings" / "config.json"
    config = {"theme": "Oscuro", "language": "Ingles"}

    save_config(config_file, config)

    assert load_config(config_file) == config


def test_load_config_fills_missing_values_with_defaults(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"theme": "Oscuro"}), encoding="utf-8")

    loaded = load_config(config_file)

    assert loaded["theme"] == "Oscuro"
    assert loaded["language"] == DEFAULT_CONFIG["language"]


def test_load_config_raises_for_invalid_json(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text("{invalid", encoding="utf-8")

    with pytest.raises(ValueError):
        load_config(config_file)
