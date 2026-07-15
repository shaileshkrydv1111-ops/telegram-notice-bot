"""Scraper for https://ancpatna.ac.in/news/examination

Structure (as of writing):
  <table id="...">
    <tr>
      <td>SN</td>
      <td>Title</td>
      <td>Date</td>
      <td><a href="https://ancpatna.ac.in/news/EXAMINATION/...">View</a></td>
    </tr>
    ...
  </table>

Each row links to a detail page; the actual PDF attachment (if any) is
found on that detail page behind a "View Attached Notice" style link.
"""

from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup

import config
from http_client import FetchError, get
from logger_setup import log
from notice import Notice

SITE_KEY = "ancpatna"
LIST_URL = "https://ancpatna.ac.in/news/examination"
BASE_URL = "https://ancpatna.ac.in"


def _fetch_detail_pdf(detail_url: str) -> str | None:
    try:
        response = get(detail_url)
    except FetchError as exc:
        log.warning("[ancpatna] Could not load detail page %s: %s", detail_url, exc)
        return None

    soup = BeautifulSoup(response.text, "lxml")
    pdf_link = soup.find("a", href=lambda h: h and h.lower().endswith(".pdf"))
    if pdf_link and pdf_link.get("href"):
        return urljoin(detail_url, pdf_link["href"])
    return None


def fetch_notices(known_ids: set[str] | None = None) -> list[Notice]:
    """Parse the examination notices table.

    Only the newest ``config.LIST_SCAN_LIMIT`` rows are considered (the
    table is already newest-first). A detail-page fetch (needed to find any
    PDF attachment) is only performed for brand-new notices or for the most
    recent ``config.DETAIL_RECHECK_LIMIT`` rows, so already-sent notices
    outside that window are not re-fetched every cycle.
    """
    known_ids = known_ids or set()

    response = get(LIST_URL)
    soup = BeautifulSoup(response.text, "lxml")

    table = soup.find("table")
    if table is None:
        log.warning("[ancpatna] Could not find the notices table; site layout may have changed.")
        return []

    body = table.find("tbody") or table
    notices: list[Notice] = []

    rows = body.find_all("tr")[: config.LIST_SCAN_LIMIT]
    for index, row in enumerate(rows):
        cells = row.find_all("td")
        if len(cells) < 4:
            continue

        title = cells[1].get_text(strip=True)
        date_text = cells[2].get_text(strip=True)
        link = cells[3].find("a")

        if not link or not link.get("href") or not title:
            continue

        detail_url = urljoin(BASE_URL, link["href"].strip())

        is_new = detail_url not in known_ids
        within_recheck_window = index < config.DETAIL_RECHECK_LIMIT

        if not is_new and not within_recheck_window:
            continue

        pdf_url = _fetch_detail_pdf(detail_url)

        notices.append(
            Notice(
                site_key=SITE_KEY,
                notice_id=detail_url,
                title=title,
                date_text=date_text or "Date not available",
                url=detail_url,
                pdf_url=pdf_url,
            )
        )

    log.info("[ancpatna] Parsed %d notice(s) from listing page.", len(notices))
    return notices
