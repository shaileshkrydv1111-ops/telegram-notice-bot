"""One-off live test: send REAL, currently-live notices from all three sites
through the actual production delivery pipeline (main.deliver_notice).

- No dummy PDFs, no example.com URLs, no [VERIFICATION] labels.
- Fetches each site's real current notices (empty known_ids -> everything
  on the page right now is returned).
- Sends the single most recent real notice per site, using the exact
  production message format and PDF-size delivery rules.
- Does NOT read or write database.json, so the running bot's dedupe/
  baseline state is completely untouched.
"""

from __future__ import annotations

from http_client import FetchError
from logger_setup import log
from main import deliver_notice
from scrapers import ancpatna_scraper, ppup_scraper, ppupadm_scraper

SCRAPERS = {
    "ppup": ppup_scraper.fetch_notices,
    "ppupadm": ppupadm_scraper.fetch_notices,
    "ancpatna": ancpatna_scraper.fetch_notices,
}


def main() -> None:
    for site_key, scraper in SCRAPERS.items():
        print(f"\n=== {site_key} ===")
        try:
            notices = scraper(set())
        except FetchError as exc:
            print(f"[{site_key}] FAIL - site unreachable: {exc}")
            continue
        except Exception as exc:  # noqa: BLE001
            print(f"[{site_key}] FAIL - unexpected scraper error: {exc}")
            continue

        if not notices:
            print(f"[{site_key}] FAIL - no notices parsed from live page.")
            continue

        notices.sort(key=lambda n: n.sort_key, reverse=True)
        latest = notices[0]
        print(f"[{site_key}] Found {len(notices)} real notice(s). Sending most recent:")
        print(f"    title: {latest.title}")
        print(f"    date : {latest.date_text}")
        print(f"    url  : {latest.url}")
        print(f"    pdf  : {latest.pdf_url or '(none)'}")

        try:
            deliver_notice(latest)
            print(f"[{site_key}] OK - delivered via production pipeline.")
        except Exception as exc:  # noqa: BLE001
            print(f"[{site_key}] FAIL - delivery error: {exc}")


if __name__ == "__main__":
    main()
