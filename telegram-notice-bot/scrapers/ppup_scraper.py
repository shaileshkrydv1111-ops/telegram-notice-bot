"""Scraper for https://ppup.ac.in/notice-board

Structure (as of writing):
  <ul class="notice">
    <li><a href="//ppup.ac.in/details/56726"><strong>Title</strong></a>
        <br/><span>Updated On : 14-07-2026</span></li>
    ...
  </ul>

Each list item links to a detail page which contains the actual PDF link
(if any) and an authoritative "Updated On" date.
"""

from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup

import config
from browser_client import FetchError, get_html
from logger_setup import log
from notice import Notice

SITE_KEY = "ppup"
LIST_URL = "https://ppup.ac.in/notice-board"
BASE_URL = "https://ppup.ac.in"


def _fetch_detail(detail_url: str) -> tuple[str | None, str | None]:
    """Returns (pdf_url, updated_on_text) from a notice detail page.

    Best-effort: if the detail page can't be parsed, returns (None, None)
    and the caller falls back to the list-page data.
    """
    try:
        html = get_html(detail_url)
    except FetchError as exc:
        log.warning("[ppup] Could not load detail page %s: %s", detail_url, exc)
        return None, None

    soup = BeautifulSoup(html, "lxml")

    pdf_url = None
    pdf_link = soup.find("a", href=lambda h: h and h.lower().endswith(".pdf"))
    if pdf_link and pdf_link.get("href"):
        pdf_url = urljoin(detail_url, pdf_link["href"])

    updated_on = None
    for p in soup.find_all("p"):
        text = p.get_text(strip=True)
        if text.lower().startswith("updated on"):
            updated_on = text.split(":", 1)[-1].strip()
            break

    return pdf_url, updated_on


def fetch_notices(known_ids: set[str] | None = None) -> list[Notice]:
    """Parse the notice-board list page.

    The page renders the site's *entire* historical archive (1000+ items),
    not just recent notices, so we only look at the newest
    ``config.LIST_SCAN_LIMIT`` entries (the list is already newest-first).
    A detail-page fetch (needed to find the PDF link and authoritative
    date) is only performed for entries that are either brand new
    (``notice_id`` not in ``known_ids``) or within the most recent
    ``config.DETAIL_RECHECK_LIMIT`` entries, so previously-sent notices can
    still be caught if edited shortly after publishing, without re-fetching
    detail pages for the entire archive on every cycle.
    """
    known_ids = known_ids or set()

    html = get_html(LIST_URL, wait_selector="ul.notice")
    soup = BeautifulSoup(html, "lxml")

    notice_list = soup.find("ul", class_="notice")
    if notice_list is None:
        log.warning("[ppup] Could not find the notice list container; site layout may have changed.")
        return []

    notices: list[Notice] = []
    for index, li in enumerate(notice_list.find_all("li")[: config.LIST_SCAN_LIMIT]):
        anchor = li.find("a")
        if anchor is None:
            continue

        href = anchor.get("href", "").strip()
        if not href:
            continue
        # href values look like "//ppup.ac.in/details/56726" -- urljoin needs
        # a scheme, so normalise protocol-relative URLs explicitly.
        if href.startswith("//"):
            detail_url = "https:" + href
        else:
            detail_url = urljoin(BASE_URL, href)

        strong = anchor.find("strong")
        title = (strong.get_text(strip=True) if strong else anchor.get_text(strip=True)).strip()
        if not title:
            continue

        span = li.find("span")
        list_date = span.get_text(strip=True).replace("Updated On :", "").strip() if span else ""

        is_new = detail_url not in known_ids
        within_recheck_window = index < config.DETAIL_RECHECK_LIMIT

        if not is_new and not within_recheck_window:
            # Already sent and outside the recheck window: assume immutable
            # and skip entirely -- no detail fetch, not re-evaluated at all.
            continue

        pdf_url, detail_date = _fetch_detail(detail_url)
        date_text = detail_date or list_date or "Date not available"

        notices.append(
            Notice(
                site_key=SITE_KEY,
                notice_id=detail_url,
                title=title,
                date_text=date_text,
                url=detail_url,
                pdf_url=pdf_url,
            )
        )

    log.info(
        "[ppup] Parsed %d notice(s) from listing page (scanned top %d of the archive).",
        len(notices),
        config.LIST_SCAN_LIMIT,
    )
    return notices
