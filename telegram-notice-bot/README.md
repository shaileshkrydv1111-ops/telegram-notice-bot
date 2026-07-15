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
- Every fetch goes through `http_client.py`, which retries with
  exponential backoff before giving up on that cycle.
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
├── http_client.py             # shared retrying HTTP GET/download
├── telegram_sender.py         # sendMessage / sendDocument / sendMediaGroup
├── pdf_utils.py                # PDF page count + high-quality rendering
├── logger_setup.py            # console + rotating file logging
├── scrapers/
│   ├── ppup_scraper.py
│   ├── ppupadm_scraper.py
│   └── ancpatna_scraper.py
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

2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

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

- Retries: every HTTP request (site pages, PDFs, Telegram API calls)
  retries up to `MAX_RETRIES` times with increasing backoff before that
  attempt is given up on; it will simply be retried again on the next
  5-minute cycle.
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
