"""Shared HTTP helper with automatic retries and browser-like headers.

Every scraper goes through this module so retry/backoff behaviour and
timeouts are consistent, and so a single site's outage can never take down
the whole process.
"""

from __future__ import annotations

import time

import requests

import config
from logger_setup import log

DEFAULT_HEADERS = {
    "User-Agent": config.USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


class FetchError(RuntimeError):
    """Raised when a URL could not be fetched after all retries."""


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    return session


_SESSION = _session()


def get(url: str, *, timeout: int | None = None, **kwargs) -> requests.Response:
    """GET a URL with retries + exponential backoff.

    Raises FetchError if every attempt fails. Callers (scrapers) should
    catch FetchError per-site so one dead site never stops the others.
    """
    timeout = timeout or config.REQUEST_TIMEOUT_SECONDS
    last_exc: Exception | None = None

    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            response = _SESSION.get(url, timeout=timeout, **kwargs)
            if response.status_code >= 500:
                raise requests.HTTPError(
                    f"Server error {response.status_code} for {url}"
                )
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_exc = exc
            delay = config.RETRY_BACKOFF_SECONDS * attempt
            log.warning(
                "Attempt %d/%d failed for %s (%s). Retrying in %ds...",
                attempt,
                config.MAX_RETRIES,
                url,
                exc,
                delay,
            )
            if attempt < config.MAX_RETRIES:
                time.sleep(delay)

    raise FetchError(f"Failed to fetch {url} after {config.MAX_RETRIES} attempts: {last_exc}")


def download(url: str, *, timeout: int | None = None) -> bytes:
    """Download binary content (e.g. a PDF) with the same retry policy."""
    response = get(url, timeout=timeout)
    return response.content
