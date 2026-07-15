"""Scraper for https://ppupadm.samarth.edu.in/index.php/notifications/index

Structure (as of writing):
  <table id="newsTable">
    <tr>
      <td>Date</td>
      <td><a href="...pdf">Read Notice</a></td>
      <td>Title</td>
    </tr>
    ...
  </table>

The "Document" column links directly to the PDF on S3, so no detail-page
fetch is needed -- the list page has everything.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from browser_client import get_html
from logger_setup import log
from notice import Notice

SITE_KEY = "ppupadm"
LIST_URL = "https://ppupadm.samarth.edu.in/index.php/notifications/index"


def fetch_notices(known_ids: set[str] | None = None) -> list[Notice]:
    # known_ids is unused here -- this site's list page already includes the
    # direct PDF link and date for every row, so no per-item detail fetch
    # (and therefore no need for windowed re-checking) is required.
    html = get_html(LIST_URL, wait_selector="table")
    soup = BeautifulSoup(html, "lxml")

    table = soup.find("table")
    if table is None:
        log.warning("[ppupadm] Could not find the notifications table; site layout may have changed.")
        return []

    body = table.find("tbody") or table
    notices: list[Notice] = []

    for row in body.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 3:
            continue

        date_text = cells[0].get_text(strip=True)
        link = cells[1].find("a")
        title = cells[2].get_text(strip=True)

        if not link or not link.get("href") or not title:
            continue

        pdf_url = link["href"].strip()

        notices.append(
            Notice(
                site_key=SITE_KEY,
                notice_id=pdf_url,
                title=title,
                date_text=date_text or "Date not available",
                url=pdf_url,
                pdf_url=pdf_url,
            )
        )

    log.info("[ppupadm] Parsed %d notice(s) from listing page.", len(notices))
    return notices
