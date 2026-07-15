"""JSON-backed persistence for already-sent notices.

Structure of database.json:

{
  "ppup": {
    "https://ppup.ac.in/details/56726": {
      "hash": "sha256...",
      "sent_at": "2026-07-14T10:00:00"
    }
  },
  "ppupadm": { ... },
  "ancpatna": { ... }
}

Each site has its own namespace keyed by notice_id (a stable URL). The
stored hash lets us detect an updated notice even when the URL is
unchanged -- if the new hash differs from the stored one, the notice is
treated as new/updated and re-sent.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from typing import Any

import config
from logger_setup import log

_lock = threading.Lock()


def _empty_db() -> dict[str, Any]:
    return {site.key: {} for site in config.SITES}


def load() -> dict[str, Any]:
    if not config.DATABASE_FILE.exists():
        log.info("No existing database found at %s; creating a new one.", config.DATABASE_FILE)
        db = _empty_db()
        save(db)
        return db

    try:
        with open(config.DATABASE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Make sure every configured site has a namespace, even if the file
        # predates a newly added site.
        for site in config.SITES:
            data.setdefault(site.key, {})
        return data
    except (json.JSONDecodeError, OSError) as exc:
        log.error(
            "database.json is corrupt or unreadable (%s). Starting from an empty database "
            "to avoid crashing; the corrupt file is preserved for inspection.",
            exc,
        )
        backup_path = str(config.DATABASE_FILE) + ".corrupt"
        try:
            os.replace(config.DATABASE_FILE, backup_path)
        except OSError:
            pass
        db = _empty_db()
        save(db)
        return db


def save(db: dict[str, Any]) -> None:
    """Atomic write: write to a temp file then rename, so a crash mid-write
    never corrupts database.json."""
    config.DATABASE_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(config.DATABASE_FILE.parent), prefix=".database_", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(db, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, config.DATABASE_FILE)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def known_ids(db: dict[str, Any], site_key: str) -> set[str]:
    return set(db.get(site_key, {}).keys())


def is_new_or_updated(db: dict[str, Any], site_key: str, notice_id: str, content_hash: str) -> bool:
    entry = db.get(site_key, {}).get(notice_id)
    if entry is None:
        return True
    return entry.get("hash") != content_hash


def mark_sent(db: dict[str, Any], site_key: str, notice_id: str, content_hash: str) -> None:
    with _lock:
        db.setdefault(site_key, {})[notice_id] = {
            "hash": content_hash,
            "sent_at": datetime.now(timezone.utc).isoformat(),
        }
        save(db)
