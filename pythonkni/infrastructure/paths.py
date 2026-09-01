from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "PythonKni"


def _user_base_dir() -> Path:
    base = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA")
    if base:
        return Path(base) / APP_NAME
    return Path.home() / f".{APP_NAME.lower()}"


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ASSETS_DIR = PROJECT_ROOT / "assets"

APP_DIR = _user_base_dir()
CONFIG_DIR = APP_DIR
DATA_DIR = APP_DIR / "data"
LOG_DIR = APP_DIR / "logs"
CAMERA_REPORTS_DIR = DATA_DIR / "camera_audits"
NETWORK_INTELLIGENCE_REPORTS_DIR = DATA_DIR / "network_intelligence_reports"

CONFIG_FILE = CONFIG_DIR / "config.json"
SCAN_HISTORY_FILE = DATA_DIR / "scan_history.txt"
NETWORK_INTELLIGENCE_DB = DATA_DIR / "network_intelligence.sqlite3"


def ensure_app_dirs() -> None:
    for path in (
        CONFIG_DIR,
        DATA_DIR,
        LOG_DIR,
        CAMERA_REPORTS_DIR,
        NETWORK_INTELLIGENCE_REPORTS_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)
