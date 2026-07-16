# Telegram Notice Bot

Monitors three Bihar university notice-board websites and pushes new or
updated notices to a Telegram chat, in chronological order, with no
duplicates.

Monitored sources:

1. `https://ppup.ac.in/notice-board` — Patliputra University notice board
2. `https://ppupadm.samarth.edu.in/index.php/notifications/index` — Patliputra University admission notifications (Samarth)
3. `https://ancpatna.ac.in/news/examination` — A.N. College Patna examination notices

## How it works

- Each site has its own scraper module in `scrapers/`. A failure fetching
  one site (timeout, 5xx, layout change) is caught and logged; it never
  stops the other two sites or the process.
- **ppup.ac.in** and **ppupadm.samarth.edu.in** are scraped with a real
  headless **Chromium browser** via Playwright (`browser_client.py`).
  Both sites are fetched from a single **persistent browser context** that
  is launched once and reused for every subsequent check (across every
  5-minute cycle), rather than a new browser per request. Each page load
  waits for the `load` event, then for the network to go idle, and (for
  the list pages) for the specific content selector to appear, before the
  HTML is read — so JS-rendered content is guaranteed to be present before
  parsing.
- **ancpatna.ac.in** continues to use plain `requests` via
  `http_client.py` — it already parses correctly without a browser, so
  there's no reason to pay the extra overhead there.
- Every non-browser fetch goes through `http_client.py`, which retries
  with exponential backoff before giving up on that cycle. The browser
  client uses the same retry/backoff policy and raises the same
  `FetchError` type, so `main.py`'s per-site error handling is identical
  regardless of which fetch mechanism a scraper uses.
- `database.json` stores a hash of each notice's title, date, and
  attachment URL, keyed by a stable notice URL. If the hash changes (the
  notice was edited) even though the URL stayed the same, it is treated as
  updated and re-sent. Writes are atomic (temp file + rename) so a crash
  mid-write can't corrupt the file.
- The main loop runs every `CHECK_INTERVAL_SECONDS` (default 300 = 5
  minutes). New/updated notices found in one cycle are sent oldest-first
  so Telegram always receives them in chronological order.
- On startup, `main.py` runs a self-test: it fetches all three sites once
  and verifies the Telegram bot token/chat id, logging OK/FAIL per source,
  before entering the monitoring loop.
- **Baseline on first contact:** the very first time each site is
  successfully checked (its section of `database.json` is empty), every
  notice currently on the page is recorded as already-seen but is **not**
  delivered to Telegram — this avoids blasting the entire existing notice
  list (which can be dozens of items) the moment the bot goes live. From
  that point on, only genuinely new or edited notices are sent. If a site
  is unreachable at first startup, it will do its own baseline pass
  automatically the first time it later becomes reachable.

## Message format

Every message/caption is exactly:

```
<Notice Title>

<Date>

<Notice URL>
```

Plain text only — no labels ("Title:", "Date:", "Source:"), no Markdown,
no HTML, no bold, no emojis, nothing extra.

## Delivery rules

- **No PDF attached** → plain Telegram text message.
- **PDF with 1–5 pages** → every page rendered to a high-quality image
  (PyMuPDF, configurable DPI) and sent as a single Telegram media group;
  the caption is attached to the first image only.
- **PDF with more than 5 pages** → the original PDF file is sent as a
  document with the caption attached.

## Project layout

```
telegram-notice-bot/
├── main.py                    # entry point: self-test + monitoring loop
├── config.py                  # env-driven configuration
├── notice.py                  # Notice data model (hash, sort key, formatting)
├── database.py                # JSON persistence, dedupe/update detection
├── http_client.py             # shared retrying HTTP GET/download (requests)
├── browser_client.py          # persistent Playwright Chromium client (ppup/ppupadm)
├── telegram_sender.py         # sendMessage / sendDocument / sendMediaGroup
├── pdf_utils.py                # PDF page count + high-quality rendering
├── logger_setup.py            # console + rotating file logging
├── scrapers/
│   ├── ppup_scraper.py        # Playwright (Chromium)
│   ├── ppupadm_scraper.py     # Playwright (Chromium)
│   └── ancpatna_scraper.py    # requests
├── database.json              # auto-created on first run
├── requirements.txt
├── .env.example
├── telegram-notice-bot.service # systemd unit for VPS deployment
└── README.md
```

## Setup

1. Copy the environment template and fill in your Telegram credentials:

   ```bash
   cp .env.example .env
   ```

   - `TELEGRAM_BOT_TOKEN` — from [@BotFather](https://t.me/BotFather)
   - `TELEGRAM_CHAT_ID` — the numeric chat/group/channel id that should
     receive notices (e.g. from [@userinfobot](https://t.me/userinfobot); for
     channels, add the bot as an admin and use the channel's `-100...` id)

2. Install dependencies, then download the Playwright Chromium browser
   (needed by the `ppup`/`ppupadm` scrapers — this is a one-time download,
   separate from the pip package):

   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```

   Headless Chromium also needs a handful of OS-level shared libraries
   (NSS, GTK, etc.) that aren't pulled in by pip. On a fresh Ubuntu VPS,
   install them in the same step with:

   ```bash
   playwright install --with-deps chromium
   ```

   (`--with-deps` runs `apt-get install` for the required libraries; it
   needs sudo/root. On Replit these system libraries are already
   provisioned in the environment.)

3. Run it:

   ```bash
   python3 main.py
   ```

   The bot logs a self-test result for each of the three sites and for the
   Telegram connection, then starts checking every 5 minutes forever.

## Running on Replit

This bot has no web preview — it is a background worker. Run it via a
configured workflow (`python3 main.py` from this directory) so it stays
running continuously. Configure `TELEGRAM_BOT_TOKEN` and
`TELEGRAM_CHAT_ID` as Replit Secrets rather than a `.env` file.

## Deploying on an Ubuntu VPS (systemd)

```bash
sudo mkdir -p /opt/telegram-notice-bot
sudo cp -r . /opt/telegram-notice-bot
cd /opt/telegram-notice-bot

python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/playwright install --with-deps chromium
# --with-deps installs the OS-level libraries headless Chromium needs
# (via apt-get) as well as the browser binary itself; requires sudo.

cp .env.example .env
nano .env   # fill in TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID

sudo cp telegram-notice-bot.service /etc/systemd/system/telegram-notice-bot.service
# Edit the User= and path fields in the unit file if you used a different
# location or deploy user.

sudo systemctl daemon-reload
sudo systemctl enable --now telegram-notice-bot
sudo systemctl status telegram-notice-bot
journalctl -u telegram-notice-bot -f
```

`Restart=always` in the unit file means systemd restarts the bot
automatically if it ever crashes, so it stays online 24×7.

## Notes on reliability

- Retries: every HTTP request (site pages, PDFs, Telegram API calls) and
  every browser page load (ppup/ppupadm) retries up to `MAX_RETRIES` times
  with increasing backoff before that attempt is given up on; it will
  simply be retried again on the next 5-minute cycle.
- The Playwright browser is launched once and kept open for the life of
  the process; it is closed cleanly on shutdown (`SIGTERM`/`SIGINT`, or
  process exit) via `browser_client.shutdown()`. If Chromium itself
  crashes mid-run, the next page-load attempt will fail with `FetchError`
  and be retried/logged like any other fetch failure — it does not crash
  the whole bot.
- `database.json` grows over time (one entry per notice ever sent per
  site). This is expected and intentional — it is the permanent
  duplicate-prevention record. Back it up if you redeploy to a new host so
  history isn't sent again.
- If a source website changes its HTML structure, that site's scraper may
  start returning zero notices or logging a warning. The other two sites
  are unaffected; check the logs and update the affected scraper's
  selectors.
- Some university sites front their servers with a WAF that can block
  requests from certain data-center IP ranges (unrelated to this code).
  If a site consistently self-test-fails with `403 Forbidden` from a given
  host, try again from a different network/VPS; the retry logic will pick
  it back up automatically once the site is reachable.

## Troubleshooting: ppup/ppupadm fail while ancpatna works

`ppup.ac.in` and `ppupadm.samarth.edu.in` are the only two sites that need
the Playwright Chromium browser; `ancpatna.ac.in` uses plain `requests` and
has no such dependency. So if ancpatna keeps working while the other two
fail, the browser itself is the problem on that host — almost always one of:

1. **Chromium's OS-level dependencies aren't installed.** Running only
   `playwright install chromium` downloads the browser binary but not the
   shared libraries it needs (`libnss3`, `libatk-1.0-0`, `libgbm1`, etc.).
   Without them, Chromium fails to launch entirely, so *every* fetch that
   goes through `browser_client.py` fails — which is exactly the "ppup and
   ppupadm both broken, ancpatna fine" pattern. Fix (needs sudo/root):

   ```bash
   sudo ./venv/bin/python3 -m playwright install --with-deps chromium
   # or, if not using a venv:
   sudo python3 -m playwright install --with-deps chromium
   ```

   `--with-deps` is required — plain `playwright install chromium` only
   fetches the browser binary, not the apt packages. Re-run
   `sudo systemctl restart telegram-notice-bot` afterward.

2. **`pip install -r requirements.txt` wasn't re-run after pulling this
   version**, so the `playwright` Python package itself is missing. This
   raises an `ImportError` on startup rather than a Chromium launch error.

3. **A per-site cause** — e.g. `ppupadm.samarth.edu.in`'s WAF blocking this
   specific host's IP (see above), or that site's page taking longer than
   `REQUEST_TIMEOUT_SECONDS` to render.

To tell these apart without guessing, run the built-in diagnostic script
from the project directory (same Python/venv the service uses):

```bash
python3 diagnose_browser.py
```

It launches Chromium standalone, then fetches both `ppup.ac.in` and
`ppupadm.samarth.edu.in` directly, and writes a full report to
`diagnose_browser_report.txt`. Paste that file's contents when asking for
help — "Chromium failed to launch" points to cause 1 above, an
`ImportError: No module named 'playwright'` points to cause 2, and a
`FetchError`/timeout only on `ppupadm` (with `ppup` succeeding) points to
cause 3.
