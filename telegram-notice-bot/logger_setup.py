"""Application-wide logging setup."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

import config


def setup_logging() -> logging.Logger:
    logger = logging.getLogger("notice_bot")
    if logger.handlers:
        # Already configured (e.g. re-imported); avoid duplicate handlers.
        return logger

    logger.setLevel(config.LOG_LEVEL)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    try:
        config.LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            config.LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError:
        logger.warning("Could not create log file at %s; logging to console only.", config.LOG_FILE)

    logger.propagate = False
    return logger


log = setup_logging()
