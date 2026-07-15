"""Independent scraper modules -- one per monitored website.

Each scraper exposes a single function, fetch_notices() -> list[Notice],
and is fully isolated: an exception raised by one scraper must never
propagate into another site's check. main.py is responsible for catching
per-site errors.
"""
