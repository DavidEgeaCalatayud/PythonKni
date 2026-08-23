from __future__ import annotations
import json
import os
import tempfile
from pathlib import Path
from typing import Any
import logging

DEFAULT_CONFIG: dict[str, str] = {
    "theme": "Claro",
    "language": "Español",
}
VALID_THEMES = {"Claro", "Oscuro"}
VALID_LANGUAGES = {"Español", "Inglés"}
LEGACY_LANGUAGES = {
    "Ingles": "Inglés",
}
