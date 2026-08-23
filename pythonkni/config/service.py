from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from tools.language_manager import LanguageManager
from tools.theme_manager import ThemeManager

from .models import (
    DEFAULT_CONFIG,
    LEGACY_LANGUAGES,
    VALID_LANGUAGES,
    VALID_THEMES,
)


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
    """Persist config atomically so the previous valid file survives failures."""
    config_file.parent.mkdir(parents=True, exist_ok=True)
    normalized_config = normalize_config(config)

    fd, temp_name = tempfile.mkstemp(
        prefix=f".{config_file.name}.",
        suffix=".tmp",
        dir=config_file.parent,
        text=True,
    )
    os.close(fd)
    temp_file = Path(temp_name)

    try:
        with temp_file.open("w", encoding="utf-8", newline="\n") as file:
            json.dump(normalized_config, file, indent=2, ensure_ascii=False)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())

        os.replace(temp_file, config_file)
    except Exception:
        try:
            temp_file.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def apply_runtime_config(config: dict[str, str]) -> None:
    """Sincroniza los managers globales con una configuración ya validada."""
    ThemeManager.set_theme(config["theme"])
    LanguageManager.set_language(config["language"])


def load_runtime_config(config_file: Path) -> dict[str, str]:
    """Carga la configuración persistida y la aplica antes de crear la UI."""
    config = load_config(config_file)
    apply_runtime_config(config)
    return config


def save_runtime_config(config_file: Path, config: dict[str, str]) -> dict[str, str]:
    """Guarda valores canónicos y actualiza ambos managers en la misma ruta."""
    normalized_config = normalize_config(config)
    save_config(config_file, normalized_config)
    apply_runtime_config(normalized_config)
    return normalized_config


logger = logging.getLogger(__name__)
