"""
Central configuration for the Telegram Notice Bot.

All tunables are read from environment variables (via a local .env file in
development, or real environment variables / systemd EnvironmentFile in
production). Nothing here should be hardcoded secrets.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

# Load .env if present. In production (systemd) real env vars are used and
# this is a harmless no-op if no .env file exists.
load_dotenv(BASE_DIR / ".env")


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Required environment variable '{name}' is not set. "
            f"Copy .env.example to .env and fill it in."
        )
    return value


# --- Telegram -----------------------------------------------------------
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

# --- Scheduling -----------------------------------------------------------
CHECK_INTERVAL_SECONDS: int = _get_int("CHECK_INTERVAL_SECONDS", 300)

# --- HTTP -----------------------------------------------------------------
REQUEST_TIMEOUT_SECONDS: int = _get_int("REQUEST_TIMEOUT_SECONDS", 30)
MAX_RETRIES: int = _get_int("MAX_RETRIES", 4)
RETRY_BACKOFF_SECONDS: int = _get_int("RETRY_BACKOFF_SECONDS", 5)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# --- Storage ----------------------------------------------------------------
DATABASE_FILE: Path = BASE_DIR / os.getenv("DATABASE_FILE", "database.json")

# --- Logging ----------------------------------------------------------------
LOG_FILE: Path = BASE_DIR / os.getenv("LOG_FILE", "logs/bot.log")
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()

# --- PDF rendering ------------------------------------------------------
PDF_RENDER_DPI: int = _get_int("PDF_RENDER_DPI", 200)
MAX_PDF_PAGES_FOR_IMAGES: int = 5

# --- Scraper scan limits -------------------------------------------------
# Some source sites (e.g. ppup.ac.in) render their *entire* historical
# notice archive on one page (1500+ entries) rather than just recent ones.
# Fetching a detail page per entry every cycle would be slow and hammer the
# site. We only ever need to look at the newest entries:
#   LIST_SCAN_LIMIT       -- how many of the newest list entries to consider
#                             at all (new notices are always near the top).
#   DETAIL_RECHECK_LIMIT  -- of those, how many to re-fetch the detail page
#                             for even if already sent, so an edit to a
#                             recently-published notice (same URL, changed
#                             content) is still caught. Entries already sent
#                             and older than this window are assumed
#                             immutable, which keeps every cycle fast.
LIST_SCAN_LIMIT: int = _get_int("LIST_SCAN_LIMIT", 60)
DETAIL_RECHECK_LIMIT: int = _get_int("DETAIL_RECHECK_LIMIT", 20)

# Telegram hard limit for a single media group.
TELEGRAM_MAX_MEDIA_GROUP_SIZE: int = 10


@dataclass(frozen=True)
class SiteConfig:
    key: str
    name: str
    url: str


SITES: list[SiteConfig] = [
    SiteConfig(
        key="ppup",
        name="Patliputra University - Notice Board",
        url="https://ppup.ac.in/notice-board",
    ),
    SiteConfig(
        key="ppupadm",
        name="Patliputra University Admission - Samarth Notifications",
        url="https://ppupadm.samarth.edu.in/index.php/notifications/index",
    ),
    SiteConfig(
        key="ancpatna",
        name="A.N. College Patna - Examination Notices",
        url="https://ancpatna.ac.in/news/examination",
    ),
]


def validate() -> None:
    """Fail fast at startup if mandatory configuration is missing."""
    missing = []
    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not TELEGRAM_CHAT_ID:
        missing.append("TELEGRAM_CHAT_ID")
    if missing:
        raise RuntimeError(
            "Missing required environment variables: "
            + ", ".join(missing)
            + ". Copy .env.example to .env and fill in the values."
        )
