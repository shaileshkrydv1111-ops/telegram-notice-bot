"""Telegram Notice Bot -- entry point.

Continuously monitors three university notice-board websites and pushes
new/updated notices to Telegram. Each site has its own scraper module and
is checked independently, so one failing site never stops the others.
"""

from __future__ import annotations

import signal
import sys
import time
from dataclasses import dataclass

import browser_client
import config
import database
import pdf_utils
import telegram_sender
from http_client import FetchError, download
from logger_setup import log
from notice import Notice
from scrapers import ancpatna_scraper, ppup_scraper, ppupadm_scraper

SCRAPERS = {
    "ppup": ppup_scraper.fetch_notices,
    "ppupadm": ppupadm_scraper.fetch_notices,
    "ancpatna": ancpatna_scraper.fetch_notices,
}

_shutdown_requested = False


def _handle_shutdown_signal(signum, frame):  # noqa: ANN001
    global _shutdown_requested
    log.info("Received signal %s. Shutting down after the current cycle...", signum)
    _shutdown_requested = True


def run_self_test() -> bool:
    """Fetch each site once and verify Telegram credentials before starting
    the monitoring loop. Logs a clear working/failing status per source.
    Returns True only if every check succeeds.
    """
    log.info("=== Running startup self-test ===")
    all_ok = True

    db = database.load()
    for site in config.SITES:
        scraper = SCRAPERS[site.key]
        try:
            notices = scraper(database.known_ids(db, site.key))
            log.info(
                "[SELF-TEST] %-10s OK  - reachable, %d notice(s) found.",
                site.key,
                len(notices),
            )
        except FetchError as exc:
            all_ok = False
            log.error("[SELF-TEST] %-10s FAIL - %s", site.key, exc)
        except Exception as exc:  # noqa: BLE001 - self-test must not crash the process
            all_ok = False
            log.exception("[SELF-TEST] %-10s FAIL - unexpected error: %s", site.key, exc)

    if telegram_sender.verify_bot_credentials():
        log.info("[SELF-TEST] telegram   OK  - bot token and chat id verified.")
    else:
        all_ok = False
        log.error("[SELF-TEST] telegram   FAIL - check TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID.")

    if all_ok:
        log.info("=== Self-test passed. Starting monitoring loop. ===")
    else:
        log.error(
            "=== Self-test reported failures above. Monitoring will still start; "
            "a site that is down now may recover on the next cycle. ==="
        )
    return all_ok


def deliver_notice(notice: Notice) -> None:
    """Send one notice to Telegram using the required delivery rules."""
    message = notice.formatted_message()

    if not notice.pdf_url:
        telegram_sender.send_text_message(message)
        log.info("[%s] Sent text message: %s", notice.site_key, notice.title)
        return

    try:
        pdf_bytes = download(notice.pdf_url)
    except FetchError as exc:
        log.error(
            "[%s] Could not download PDF for '%s' (%s). Falling back to a text message.",
            notice.site_key,
            notice.title,
            exc,
        )
        telegram_sender.send_text_message(message)
        return

    if not pdf_utils.is_valid_pdf(pdf_bytes):
        log.warning(
            "[%s] Attachment for '%s' is not a valid PDF. Falling back to a text message.",
            notice.site_key,
            notice.title,
        )
        telegram_sender.send_text_message(message)
        return

    pages = pdf_utils.page_count(pdf_bytes)

    if 1 <= pages <= config.MAX_PDF_PAGES_FOR_IMAGES:
        images = pdf_utils.render_pages_to_images(pdf_bytes)
        telegram_sender.send_photo_media_group(images, message)
        log.info(
            "[%s] Sent %d-page PDF as image media group: %s",
            notice.site_key,
            pages,
            notice.title,
        )
    else:
        filename = notice.pdf_url.rsplit("/", 1)[-1] or "notice.pdf"
        telegram_sender.send_document(pdf_bytes, filename, message)
        log.info(
            "[%s] Sent %d-page PDF as document: %s",
            notice.site_key,
            pages,
            notice.title,
        )


def check_site(site_key: str, db: dict) -> None:
    """Check a single site, send any new/updated notices in chronological
    order, and persist state. All exceptions are caught here so a failure
    in one site never affects the others or stops the loop.
    """
    scraper = SCRAPERS[site_key]
    is_first_successful_check = not db.get(site_key)

    try:
        notices = scraper(database.known_ids(db, site_key))
    except FetchError as exc:
        log.error("[%s] Site unreachable after retries: %s", site_key, exc)
        return
    except Exception as exc:  # noqa: BLE001 - keep the loop alive no matter what
        log.exception("[%s] Unexpected scraper error: %s", site_key, exc)
        return

    if is_first_successful_check:
        # The very first time we successfully reach a site, its current
        # notices become the baseline: recorded as already-seen but never
        # delivered. Without this, a fresh deployment would blast every
        # notice currently on the page (which can be dozens) to Telegram as
        # if it were brand new. From the next cycle onward, only genuinely
        # new or changed notices are sent.
        for notice in notices:
            database.mark_sent(db, site_key, notice.notice_id, notice.content_hash)
        log.info(
            "[%s] First successful check: recorded %d existing notice(s) as baseline "
            "(not delivered). New notices from now on will be sent.",
            site_key,
            len(notices),
        )
        return

    new_or_updated = [
        n for n in notices if database.is_new_or_updated(db, site_key, n.notice_id, n.content_hash)
    ]

    if not new_or_updated:
        log.info("[%s] No new or updated notices.", site_key)
        return

    # Oldest first so Telegram receives them in chronological order.
    new_or_updated.sort(key=lambda n: n.sort_key)

    log.info("[%s] %d new/updated notice(s) to send.", site_key, len(new_or_updated))

    for notice in new_or_updated:
        try:
            deliver_notice(notice)
            database.mark_sent(db, site_key, notice.notice_id, notice.content_hash)
        except Exception as exc:  # noqa: BLE001 - one bad notice must not block the rest
            log.exception(
                "[%s] Failed to deliver notice '%s': %s. Will retry next cycle.",
                site_key,
                notice.title,
                exc,
            )


def run_monitoring_loop() -> None:
    db = database.load()

    while not _shutdown_requested:
        cycle_start = time.monotonic()
        log.info("--- Starting check cycle across %d site(s) ---", len(config.SITES))

        for site in config.SITES:
            if _shutdown_requested:
                break
            check_site(site.key, db)

        elapsed = time.monotonic() - cycle_start
        sleep_for = max(0.0, config.CHECK_INTERVAL_SECONDS - elapsed)
        log.info(
            "--- Cycle complete in %.1fs. Sleeping %.1fs until next check. ---",
            elapsed,
            sleep_for,
        )

        slept = 0.0
        while slept < sleep_for and not _shutdown_requested:
            time.sleep(min(1.0, sleep_for - slept))
            slept += 1.0

    log.info("Monitoring loop stopped.")


def main() -> int:
    signal.signal(signal.SIGTERM, _handle_shutdown_signal)
    signal.signal(signal.SIGINT, _handle_shutdown_signal)

    try:
        config.validate()
    except RuntimeError as exc:
        log.error(str(exc))
        return 1

    try:
        run_self_test()
        run_monitoring_loop()
    finally:
        browser_client.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
