from __future__ import annotations

from pathlib import Path

from tools.language_manager import LanguageManager
from tools.theme_manager import ThemeManager

from .service import load_config, normalize_config, save_config


def apply_runtime_config(config: dict[str, str]) -> None:
    """Synchronize UI managers with already validated configuration values."""
    ThemeManager.set_theme(config["theme"])
    LanguageManager.set_language(config["language"])


def load_runtime_config(config_file: Path) -> dict[str, str]:
    """Load persisted configuration and apply it before the UI is created."""
    config = load_config(config_file)
    apply_runtime_config(config)
    return config


def save_runtime_config(config_file: Path, config: dict[str, str]) -> dict[str, str]:
    """Persist canonical values and update runtime UI managers."""
    normalized_config = normalize_config(config)
    save_config(config_file, normalized_config)
    apply_runtime_config(normalized_config)
    return normalized_config
