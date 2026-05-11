from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_CONFIG: dict[str, str] = {
    "theme": "Claro",
    "language": "Español",
}


def load_config(config_file: Path) -> dict[str, str]:
    if not config_file.exists():
        return DEFAULT_CONFIG.copy()

    with config_file.open("r", encoding="utf-8") as file:
        raw_config: dict[str, Any] = json.load(file)

    config = DEFAULT_CONFIG.copy()
    for key in DEFAULT_CONFIG:
        value = raw_config.get(key)
        if isinstance(value, str) and value:
            config[key] = value
    return config


def save_config(config_file: Path, config: dict[str, str]) -> None:
    config_file.parent.mkdir(parents=True, exist_ok=True)
    with config_file.open("w", encoding="utf-8") as file:
        json.dump(config, file, indent=2, ensure_ascii=False)
