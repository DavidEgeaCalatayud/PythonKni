from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_CONFIG: dict[str, str] = {
    "theme": "Claro",
    "language": "Español",
}

VALID_THEMES = {"Claro", "Oscuro"}
VALID_LANGUAGES = {"Español", "Inglés"}
LEGACY_LANGUAGES = {
    "Ingles": "Inglés",
}


def normalize_config(config: dict[str, Any]) -> dict[str, str]:
    theme = config.get("theme")
    if theme not in VALID_THEMES:
        theme = DEFAULT_CONFIG["theme"]

    language = config.get("language")
    if isinstance(language, str):
        language = LEGACY_LANGUAGES.get(language, language)
    if language not in VALID_LANGUAGES:
        language = DEFAULT_CONFIG["language"]

    return {
        "theme": theme,
        "language": language,
    }


def load_config(config_file: Path) -> dict[str, str]:
    if not config_file.exists():
        return DEFAULT_CONFIG.copy()

    with config_file.open("r", encoding="utf-8") as file:
        raw_config: dict[str, Any] = json.load(file)

    return normalize_config(raw_config)


def save_config(config_file: Path, config: dict[str, str]) -> None:
    config_file.parent.mkdir(parents=True, exist_ok=True)
    normalized_config = normalize_config(config)
    with config_file.open("w", encoding="utf-8") as file:
        json.dump(normalized_config, file, indent=2, ensure_ascii=False)
