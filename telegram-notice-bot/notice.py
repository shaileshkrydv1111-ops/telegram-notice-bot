"""Shared Notice data model used by every scraper."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime

from dateutil import parser as date_parser


@dataclass
class Notice:
    site_key: str
    notice_id: str  # stable identifier (detail URL or direct PDF URL)
    title: str
    date_text: str  # exact text as shown on the website
    url: str  # the URL that should appear in the outgoing message
    pdf_url: str | None = None

    @property
    def content_hash(self) -> str:
        """Hash of the fields that matter for "did this notice change".

        Used to detect an updated notice even when notice_id (URL) stays
        the same -- if the title, date, or attached PDF changes, the hash
        changes and the notice is treated as new/updated.
        """
        raw = f"{self.title.strip()}|{self.date_text.strip()}|{self.pdf_url or ''}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @property
    def sort_key(self) -> datetime:
        """Best-effort parsed datetime for chronological ordering.

        Falls back to datetime.min so unparsable dates sort first rather
        than crashing the run.
        """
        try:
            return date_parser.parse(self.date_text, dayfirst=True, fuzzy=True)
        except (ValueError, OverflowError):
            return datetime.min

    def formatted_message(self) -> str:
        """Exact required format: title, blank line, date, blank line, url."""
        return f"{self.title.strip()}\n\n{self.date_text.strip()}\n\n{self.url.strip()}"
