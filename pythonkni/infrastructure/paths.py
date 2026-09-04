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
NETWORK_INTELLIGENCE_AUTOMATIC_SNAPSHOTS_DIR = NETWORK_INTELLIGENCE_REPORTS_DIR / "scheduled"
NETWORK_MONITOR_DIR = DATA_DIR / "network_monitor"
NETWORK_MONITOR_CAPTURES_DIR = NETWORK_MONITOR_DIR / "captures"

CONFIG_FILE = CONFIG_DIR / "config.json"
SCAN_HISTORY_FILE = DATA_DIR / "scan_history.txt"
NETWORK_INTELLIGENCE_DB = DATA_DIR / "network_intelligence.sqlite3"
NETWORK_INTELLIGENCE_SCHEDULE_FILE = DATA_DIR / "network_intelligence_schedule.json"
NETWORK_INTELLIGENCE_NOTIFICATIONS_FILE = DATA_DIR / "network_intelligence_notifications.json"
NETWORK_INTELLIGENCE_RETENTION_FILE = DATA_DIR / "network_intelligence_retention.json"
NETWORK_MONITOR_EVENTS_FILE = NETWORK_MONITOR_DIR / "events.jsonl"
NETWORK_MONITOR_HISTORY_FILE = NETWORK_MONITOR_DIR / "history.jsonl"


def ensure_app_dirs() -> None:
    for path in (
        CONFIG_DIR,
        DATA_DIR,
        LOG_DIR,
        CAMERA_REPORTS_DIR,
        NETWORK_INTELLIGENCE_REPORTS_DIR,
        NETWORK_INTELLIGENCE_AUTOMATIC_SNAPSHOTS_DIR,
        NETWORK_MONITOR_DIR,
        NETWORK_MONITOR_CAPTURES_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)
