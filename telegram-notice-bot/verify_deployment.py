"""One-shot deployment verification script.

Run this on the target host (VPS or Replit) AFTER installing dependencies
and configuring .env / secrets, to confirm:

  1. All three source websites are reachable and parse correctly from THIS
     host's network (this is the real point of running it on the VPS --
     ppupadm.samarth.edu.in blocks some data-center IPs, so this must be
     checked from the actual deployment host, not assumed from elsewhere).
  2. Telegram delivery works end-to-end for all three formatting cases:
       - plain text (no attachment)
       - PDF with 1-5 pages -> HD image media group
       - PDF with more than 5 pages -> original document
     using synthetic test PDFs generated on the spot, so the test is
     deterministic and does not depend on what's currently posted on any
     site.

This script does NOT touch database.json and does NOT affect the running
bot's dedupe state -- it is safe to run at any time, including while the
systemd service is active. It clearly labels every Telegram message it
sends with "[VERIFICATION]" so they're easy to identify/delete in the chat.

Usage:
    source venv/bin/activate   # or .pythonlibs on Replit
    python3 verify_deployment.py
"""

from __future__ import annotations

import sys
import traceback

import browser_client
import config
import pdf_utils
import telegram_sender
from notice import Notice
from scrapers import ancpatna_scraper, ppup_scraper, ppupadm_scraper

SITE_CHECKS = [
    ("ppup", "PPU Notice Board (ppup.ac.in)", ppup_scraper.fetch_notices),
    ("ppupadm", "PPU Samarth (ppupadm.samarth.edu.in)", ppupadm_scraper.fetch_notices),
    ("ancpatna", "A.N. College (ancpatna.ac.in)", ancpatna_scraper.fetch_notices),
]


def _make_test_pdf(num_pages: int) -> bytes:
    """Builds a tiny synthetic PDF with the given number of pages, purely
    for exercising the delivery pipeline deterministically."""
    import fitz  # PyMuPDF

    doc = fitz.open()
    for i in range(num_pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"Verification test PDF - page {i + 1} of {num_pages}")
    data = doc.tobytes()
    doc.close()
    return data


def check_sites() -> dict[str, bool]:
    print("\n=== 1. Site reachability & scraping (from THIS host) ===")
    results: dict[str, bool] = {}
    for key, label, fetch in SITE_CHECKS:
        try:
            notices = fetch(set())
            print(f"[OK]   {label}: reachable, {len(notices)} notice(s) parsed.")
            if notices:
                sample = notices[0]
                print(f"       e.g. \"{sample.title[:70]}\" | {sample.date_text} | {sample.url}")
            results[key] = True
        except Exception as exc:  # noqa: BLE001
            print(f"[FAIL] {label}: {exc}")
            results[key] = False
    return results


def check_telegram_delivery() -> bool:
    print("\n=== 2. Telegram delivery formats ===")
    ok = True

    try:
        if not telegram_sender.verify_bot_credentials():
            print("[FAIL] Telegram credentials check failed (see log above for detail).")
            return False
        print("[OK]   Telegram credentials verified.")
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] Telegram credentials check raised: {exc}")
        return False

    # Case 1: no attachment -> plain text message
    try:
        n1 = Notice(
            site_key="verify",
            notice_id="verify-text",
            title="[VERIFICATION] Plain text message (no attachment)",
            date_text="15-07-2026",
            url="https://example.com/verify/text",
        )
        telegram_sender.send_text_message(n1.formatted_message())
        print("[OK]   Sent plain text message.")
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] Plain text message: {exc}")
        ok = False

    # Case 2: 1-5 page PDF -> HD image media group
    try:
        n2 = Notice(
            site_key="verify",
            notice_id="verify-images",
            title="[VERIFICATION] 3-page PDF (expect: HD image media group)",
            date_text="15-07-2026",
            url="https://example.com/verify/images",
        )
        pdf_bytes = _make_test_pdf(3)
        pages = pdf_utils.page_count(pdf_bytes)
        assert 1 <= pages <= config.MAX_PDF_PAGES_FOR_IMAGES
        images = pdf_utils.render_pages_to_images(pdf_bytes)
        telegram_sender.send_photo_media_group(images, n2.formatted_message())
        print(f"[OK]   Sent {pages}-page PDF as image media group ({len(images)} image(s)).")
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] Short PDF -> image media group: {exc}")
        ok = False

    # Case 3: >5 page PDF -> original document
    try:
        n3 = Notice(
            site_key="verify",
            notice_id="verify-document",
            title="[VERIFICATION] 8-page PDF (expect: original PDF document)",
            date_text="15-07-2026",
            url="https://example.com/verify/document",
        )
        pdf_bytes = _make_test_pdf(8)
        pages = pdf_utils.page_count(pdf_bytes)
        assert pages > config.MAX_PDF_PAGES_FOR_IMAGES
        telegram_sender.send_document(pdf_bytes, "verification-test.pdf", n3.formatted_message())
        print(f"[OK]   Sent {pages}-page PDF as original document.")
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] Long PDF -> document: {exc}")
        ok = False

    return ok


def main() -> int:
    print("Telegram Notice Bot -- deployment verification")
    print("=" * 60)

    try:
        config.validate()
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] Configuration invalid: {exc}")
        return 1

    site_results = check_sites()
    telegram_ok = check_telegram_delivery()

    print("\n=== Summary ===")
    all_ok = telegram_ok
    for key, label, _ in SITE_CHECKS:
        status = "OK" if site_results.get(key) else "FAIL"
        print(f"  {label}: {status}")
        all_ok = all_ok and site_results.get(key, False)
    print(f"  Telegram delivery (3 formats): {'OK' if telegram_ok else 'FAIL'}")

    print()
    if all_ok:
        print("All checks passed on this host.")
    else:
        print("Some checks failed -- see [FAIL] lines above. A site FAIL is often an "
              "IP-level block (WAF) specific to this host's network; a Telegram FAIL "
              "usually means TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID are wrong.")
    return 0 if all_ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        sys.exit(1)
    finally:
        browser_client.shutdown()
