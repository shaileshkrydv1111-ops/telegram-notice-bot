"""One-shot diagnostic for the Playwright/Chromium browser client.

Run this on any host (VPS or Replit) where ppup/ppupadm are failing:

    python3 diagnose_browser.py

It writes a full report to diagnose_browser_report.txt AND prints it to the
screen, so even if copy-pasting from the terminal is awkward you can just
`cat diagnose_browser_report.txt` and paste that whole file's contents back.

It does NOT touch database.json and is always safe to re-run.
"""

from __future__ import annotations

import subprocess
import sys
import traceback

REPORT_PATH = "diagnose_browser_report.txt"


def _section(title: str) -> str:
    return f"\n{'=' * 60}\n{title}\n{'=' * 60}\n"


def main() -> None:
    lines: list[str] = []

    lines.append(_section("1. Python / package versions"))
    lines.append(f"python3: {sys.version}")
    try:
        import playwright  # noqa: F401

        result = subprocess.run(
            [sys.executable, "-m", "pip", "show", "playwright"],
            capture_output=True,
            text=True,
        )
        lines.append(result.stdout.strip() or "(pip show returned nothing)")
    except ImportError:
        lines.append(
            "playwright is NOT installed in this Python environment.\n"
            "Fix: pip install -r requirements.txt"
        )

    lines.append(_section("2. Chromium launch test"))
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            lines.append("Chromium launched successfully.")
            browser.close()
    except Exception:  # noqa: BLE001
        lines.append("Chromium FAILED to launch. Full error below:\n")
        lines.append(traceback.format_exc())
        lines.append(
            "\nThis is almost always missing OS-level libraries.\n"
            "Fix: python3 -m playwright install --with-deps chromium\n"
            "(needs sudo/root on Ubuntu; installs both the browser binary "
            "and the required apt packages)."
        )

    lines.append(_section("3. ppup.ac.in fetch test"))
    try:
        from browser_client import get_html

        html = get_html("https://ppup.ac.in/notice-board", wait_selector="ul.notice")
        lines.append(f"OK - fetched {len(html)} bytes.")
    except Exception:  # noqa: BLE001
        lines.append("FAILED. Full error below:\n")
        lines.append(traceback.format_exc())

    lines.append(_section("4. ppupadm.samarth.edu.in fetch test"))
    try:
        from browser_client import get_html

        html = get_html(
            "https://ppupadm.samarth.edu.in/index.php/notifications/index",
            wait_selector="table",
        )
        lines.append(f"OK - fetched {len(html)} bytes.")
    except Exception:  # noqa: BLE001
        lines.append("FAILED. Full error below:\n")
        lines.append(traceback.format_exc())

    try:
        import browser_client

        browser_client.shutdown()
    except Exception:  # noqa: BLE001
        pass

    report = "\n".join(lines)
    print(report)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(report)
    print(_section(f"Report written to {REPORT_PATH}"))
    print(f"Run: cat {REPORT_PATH}   and paste the whole file back.")


if __name__ == "__main__":
    main()
