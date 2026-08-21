from __future__ import annotations

from pathlib import Path

from tools.config_service import load_config, normalize_config, save_config
from tools.language_manager import LanguageManager
from tools.theme_manager import ThemeManager


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
