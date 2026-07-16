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

If Chromium crashes mid-run (e.g. OOM-killed on a memory-constrained VPS),
the broken context/browser is detected on the next call, torn down, and
re-launched automatically -- the bot never gets stuck in a permanently
broken state.

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

# Chromium launch flags required for reliable headless operation on a Linux
# VPS or container:
#
#   --disable-dev-shm-usage   Most important. /dev/shm is only 64 MB on many
#                             VPS hosts; Chromium uses it for inter-process
#                             shared memory and is OOM-killed mid-page without
#                             this flag, producing "Connection closed while
#                             reading from the driver" errors.
#
#   --no-sandbox              Required when the process runs as root (the
#   --disable-setuid-sandbox  default on many VPS setups). Without it,
#                             Chromium refuses to start.
#
#   --disable-gpu             No GPU on a headless VPS; skips the GPU process
#   --disable-software-       entirely and avoids related crashes.
#   rasterizer
_CHROMIUM_ARGS = [
    "--disable-dev-shm-usage",
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-gpu",
    "--disable-software-rasterizer",
]


def _teardown_locked() -> None:
    """Close everything. Must be called with _lock held."""
    global _playwright, _browser, _context
    for obj, method in [(_context, "close"), (_browser, "close"), (_playwright, "stop")]:
        if obj is not None:
            try:
                getattr(obj, method)()
            except Exception:  # noqa: BLE001
                pass
    _context = None
    _browser = None
    _playwright = None


def _ensure_context() -> BrowserContext:
    """Return the persistent BrowserContext, launching Chromium on first
    call. Safe to call repeatedly; the browser is only launched once.

    If the browser previously crashed (context is set but browser process is
    gone), the stale objects are torn down and a fresh browser is launched.
    """
    global _playwright, _browser, _context
    with _lock:
        # Fast path: healthy context already running.
        if _context is not None:
            return _context

        log.info("[browser] Launching persistent Chromium instance...")
        try:
            _playwright = sync_playwright().start()
            _browser = _playwright.chromium.launch(
                headless=True,
                args=_CHROMIUM_ARGS,
            )
            _context = _browser.new_context(
                user_agent=config.USER_AGENT,
                viewport={"width": 1366, "height": 768},
                locale="en-US",
            )
            _context.add_init_script(_STEALTH_INIT_SCRIPT)
            log.info("[browser] Chromium launched; persistent context ready.")
            return _context
        except Exception as exc:  # noqa: BLE001
            # Tear down whatever was partially created so the next call
            # gets a clean slate.
            _teardown_locked()
            log.error(
                "[browser] Chromium failed to launch: %s\n"
                "Fix: run `sudo python3 -m playwright install --with-deps chromium` "
                "and restart the bot.",
                exc,
            )
            raise


def _reset_browser() -> None:
    """Tear down a crashed browser so the next call re-launches cleanly."""
    with _lock:
        log.warning("[browser] Resetting crashed browser instance...")
        _teardown_locked()


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

    If a browser crash ("Connection closed" error) is detected during a
    retry, the stale browser is torn down so the *next* attempt gets a
    freshly launched instance rather than re-hitting the broken context.
    """
    timeout_ms = (timeout or config.REQUEST_TIMEOUT_SECONDS) * 1000
    last_exc: Exception | None = None

    for attempt in range(1, config.MAX_RETRIES + 1):
        page = None
        try:
            context = _ensure_context()
            page = context.new_page()
            resp = page.goto(url, wait_until="load", timeout=timeout_ms)
            # Fail fast on hard 4xx blocks (403, 401, 404) — waiting for a
            # content selector on a 403 page just wastes 30 s per attempt.
            if resp is not None and resp.status in (401, 403, 404):
                raise FetchError(
                    f"Server returned HTTP {resp.status} for {url}. "
                    f"This usually means the university's server is blocking "
                    f"this host's IP address. Check connectivity with: "
                    f"curl -I {url}"
                )
            page.wait_for_load_state("networkidle", timeout=timeout_ms)
            if wait_selector:
                page.wait_for_selector(wait_selector, timeout=timeout_ms)
            html = page.content()
            page.close()
            return html
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if page is not None:
                try:
                    page.close()
                except Exception:  # noqa: BLE001
                    pass

            # "Connection closed" means the Chromium process died (OOM,
            # crash, etc.). Reset now so the next attempt starts fresh.
            exc_str = str(exc).lower()
            if "connection closed" in exc_str or "browser has been closed" in exc_str:
                _reset_browser()

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
    with _lock:
        if _playwright is None and _browser is None and _context is None:
            return
        _teardown_locked()
        log.info("[browser] Persistent Chromium instance shut down.")
