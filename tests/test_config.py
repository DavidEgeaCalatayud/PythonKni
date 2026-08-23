import json

import pytest

import tools.config_service as config_service
from tools.config_service import DEFAULT_CONFIG, load_config, save_config


def test_load_config_returns_defaults_when_file_does_not_exist(tmp_path):
    assert load_config(tmp_path / "config.json") == DEFAULT_CONFIG


def test_save_and_load_config_roundtrip(tmp_path):
    config_file = tmp_path / "settings" / "config.json"
    config = {"theme": "Oscuro", "language": "Inglés"}

    save_config(config_file, config)

    assert load_config(config_file) == config


def test_load_config_fills_missing_values_with_defaults(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"theme": "Oscuro"}), encoding="utf-8")

    loaded = load_config(config_file)

    assert loaded["theme"] == "Oscuro"
    assert loaded["language"] == DEFAULT_CONFIG["language"]


def test_load_config_normalizes_legacy_english_value(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(
        json.dumps({"theme": "Oscuro", "language": "Ingles"}),
        encoding="utf-8",
    )

    loaded = load_config(config_file)

    assert loaded == {"theme": "Oscuro", "language": "Inglés"}


def test_save_config_writes_canonical_language_value(tmp_path):
    config_file = tmp_path / "config.json"

    save_config(config_file, {"theme": "Claro", "language": "Ingles"})

    stored = json.loads(config_file.read_text(encoding="utf-8"))
    assert stored["language"] == "Inglés"


def test_load_config_rejects_unknown_theme_and_language(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(
        json.dumps({"theme": "Neon", "language": "Klingon"}),
        encoding="utf-8",
    )

    assert load_config(config_file) == DEFAULT_CONFIG


def test_load_config_raises_for_invalid_json(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text("{invalid", encoding="utf-8")

    with pytest.raises(ValueError):
        load_config(config_file)


def test_save_config_fsyncs_before_atomic_replace(tmp_path, monkeypatch):
    config_file = tmp_path / "config.json"
    calls = []
    real_replace = config_service.os.replace

    def tracked_fsync(fd):
        calls.append(("fsync", fd))

    def tracked_replace(source, destination):
        calls.append(("replace", str(source)))
        return real_replace(source, destination)

    monkeypatch.setattr(config_service.os, "fsync", tracked_fsync)
    monkeypatch.setattr(config_service.os, "replace", tracked_replace)

    save_config(config_file, {"theme": "Oscuro", "language": "Inglés"})

    assert [name for name, _value in calls] == ["fsync", "replace"]
    assert load_config(config_file) == {"theme": "Oscuro", "language": "Inglés"}


def test_save_config_preserves_previous_file_when_dump_fails(tmp_path, monkeypatch):
    config_file = tmp_path / "config.json"
    previous = '{"theme": "Claro", "language": "Español"}\n'
    config_file.write_text(previous, encoding="utf-8")

    def broken_dump(_config, handle, **_kwargs):
        handle.write('{"theme": "Oscuro"')
        handle.flush()
        raise OSError("simulated write failure")

    monkeypatch.setattr(config_service.json, "dump", broken_dump)

    with pytest.raises(OSError, match="simulated write failure"):
        save_config(config_file, {"theme": "Oscuro", "language": "Inglés"})

    assert config_file.read_text(encoding="utf-8") == previous
    assert list(tmp_path.glob(".config.json.*.tmp")) == []


def test_save_config_rolls_back_temp_when_replace_fails(tmp_path, monkeypatch):
    config_file = tmp_path / "config.json"
    previous = '{"theme": "Claro", "language": "Español"}\n'
    config_file.write_text(previous, encoding="utf-8")

    def broken_replace(source, destination):
        assert source.parent == config_file.parent
        assert destination == config_file
        raise OSError("simulated replace failure")

    monkeypatch.setattr(config_service.os, "replace", broken_replace)

    with pytest.raises(OSError, match="simulated replace failure"):
        save_config(config_file, {"theme": "Oscuro", "language": "Inglés"})

    assert config_file.read_text(encoding="utf-8") == previous
    assert list(tmp_path.glob(".config.json.*.tmp")) == []
