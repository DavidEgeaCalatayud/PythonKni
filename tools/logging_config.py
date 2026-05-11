import logging
from logging.handlers import RotatingFileHandler

from tools.app_paths import LOG_DIR, ensure_app_dirs


def setup_logging() -> None:
    ensure_app_dirs()

    log_file = LOG_DIR / "pythonkni.log"
    root_logger = logging.getLogger()

    if root_logger.handlers:
        return

    root_logger.setLevel(logging.INFO)

    formatter = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)
