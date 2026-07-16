"""Persistent Playwright (Chromium) browser client.

Used only by the two scrapers that need real browser rendering --
ppup.ac.in and ppupadm.samarth.edu.in. ancpatna.ac.in continues to use the
plain requests-based http_client, since it already works fine without a
browser and there is no reason to pay the extra overhead there.

A single Chromium instance and a single persistent BrowserContext are
launched lazily on first use and then reused for every subsequent fetch,
across the whole life of the process (i.e. across every 5-minute scheduler
cycle) -- we never spin up a fresh browser per request. This is both much
faster than a cold launch every cycle and makes the bot look like one
long-lived returning session rather than a burst of fresh anonymous
visitors.

Raises the *same* FetchError class used by http_client so main.py's
per-site error handling (`except FetchError`) works uniformly regardless
of whether a site is fetched via requests or via the browser.
"""

from __future__ import annotations

import threading
import time

from playwright.sync_api import Browser, BrowserContext, Playwright, sync_playwright

import config
from http_client import FetchError
from logger_setup import log

__all__ = ["FetchError", "get_html", "shutdown"]

_lock = threading.Lock()
_playwright: Playwright | None = None
_browser: Browser | None = None
_context: BrowserContext | None = None

# Strip the most obvious headless/automation tells before any page script
# runs, so sites that sniff `navigator.webdriver` etc. see a normal browser.
_STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
"""


def _ensure_context() -> BrowserContext:
    """Return the persistent BrowserContext, launching Chromium on first
    call. Safe to call repeatedly; the browser is only launched once.
    """
    global _playwright, _browser, _context
    with _lock:
        if _context is not None:
            return _context

        log.info("[browser] Launching persistent Chromium instance...")
        _playwright = sync_playwright().start()
        try:
            _browser = _playwright.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001
            # This is almost always a missing-OS-dependency error on a
            # fresh Linux host (libnss3, libatk, libgbm, etc. not
            # installed), not a Python/pip problem. Surface a clear,
            # actionable message instead of a bare Playwright traceback,
            # since `pip install playwright` alone does not pull these in.
            log.error(
                "[browser] Chromium failed to launch: %s\n"
                "This is usually caused by missing OS-level libraries, not a pip issue.\n"
                "Fix: run `python3 -m playwright install --with-deps chromium` "
                "(needs sudo on Ubuntu) and restart the bot. "
                "See README.md 'Troubleshooting: Chromium fails to launch on a VPS'.",
                exc,
            )
            try:
                _playwright.stop()
            except Exception:  # noqa: BLE001
                pass
            _playwright = None
            raise
        _context = _browser.new_context(
            user_agent=config.USER_AGENT,
            viewport={"width": 1366, "height": 768},
            locale="en-US",
        )
        _context.add_init_script(_STEALTH_INIT_SCRIPT)
        log.info("[browser] Chromium launched; persistent context ready.")
        return _context


def get_html(url: str, *, timeout: int | None = None, wait_selector: str | None = None) -> str:
    """Navigate to `url` in the persistent browser context and return the
    fully-rendered HTML after the page has finished loading.

    Waits for the `load` event and network-idle before reading the DOM, so
    JS-rendered content is present. If `wait_selector` is given, also waits
    for that selector to appear -- a stronger guarantee that the specific
    content we care about has rendered, not just that *some* load event
    fired.

    Retries up to config.MAX_RETRIES times with the same exponential
    backoff used by the requests-based http_client, and raises FetchError
    (shared with http_client) if every attempt fails, so callers can catch
    one exception type regardless of fetch mechanism.
    """
    timeout_ms = (timeout or config.REQUEST_TIMEOUT_SECONDS) * 1000
    last_exc: Exception | None = None

    for attempt in range(1, config.MAX_RETRIES + 1):
        page = None
        try:
            context = _ensure_context()
            page = context.new_page()
            page.goto(url, wait_until="load", timeout=timeout_ms)
            page.wait_for_load_state("networkidle", timeout=timeout_ms)
            if wait_selector:
                page.wait_for_selector(wait_selector, timeout=timeout_ms)
            html = page.content()
            page.close()
            return html
        except Exception as exc:  # noqa: BLE001 - playwright raises its own exception types
            last_exc = exc
            if page is not None:
                try:
                    page.close()
                except Exception:  # noqa: BLE001
                    pass
            delay = config.RETRY_BACKOFF_SECONDS * attempt
            log.warning(
                "[browser] Attempt %d/%d failed for %s (%s). Retrying in %ds...",
                attempt,
                config.MAX_RETRIES,
                url,
                exc,
                delay,
            )
            if attempt < config.MAX_RETRIES:
                time.sleep(delay)

    raise FetchError(f"Failed to load {url} via browser after {config.MAX_RETRIES} attempts: {last_exc}")


def shutdown() -> None:
    """Close the persistent browser cleanly. Safe to call multiple times
    and safe to call even if the browser was never launched.
    """
    global _playwright, _browser, _context
    with _lock:
        if _context is not None:
            try:
                _context.close()
            except Exception:  # noqa: BLE001
                pass
            _context = None
        if _browser is not None:
            try:
                _browser.close()
            except Exception:  # noqa: BLE001
                pass
            _browser = None
        if _playwright is not None:
            try:
                _playwright.stop()
            except Exception:  # noqa: BLE001
                pass
            _playwright = None
            log.info("[browser] Persistent Chromium instance shut down.")
