# Telegram Notice Bot Project

A monorepo containing a standalone Python bot (`telegram-notice-bot/`) that monitors three university notice-board websites and pushes new/updated notices to Telegram, plus the workspace's default API server and design canvas scaffolding.

## Run & Operate

- `cd telegram-notice-bot && python3 main.py` — run the Telegram notice bot (also wired to the "Telegram Notice Bot" workflow)
- `pnpm --filter @workspace/api-server run dev` — run the API server (port 5000)
- `pnpm run typecheck` — full typecheck across all packages
- `pnpm run build` — typecheck + build all packages
- `pnpm --filter @workspace/api-spec run codegen` — regenerate API hooks and Zod schemas from the OpenAPI spec
- `pnpm --filter @workspace/db run push` — push DB schema changes (dev only)
- Required env: `DATABASE_URL` — Postgres connection string
- Required secrets for the bot: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`

## Stack

- pnpm workspaces, Node.js 24, TypeScript 5.9
- API: Express 5
- DB: PostgreSQL + Drizzle ORM
- Validation: Zod (`zod/v4`), `drizzle-zod`
- API codegen: Orval (from OpenAPI spec)
- Build: esbuild (CJS bundle)
- Telegram bot: Python 3.11, requests, BeautifulSoup4, PyMuPDF (see `telegram-notice-bot/README.md`)

## Where things live

- `telegram-notice-bot/` — self-contained Python bot (not part of the pnpm workspace). See its own README for full details, systemd deployment, and env vars.
- `telegram-notice-bot/scrapers/` — one independent scraper module per monitored site.
- `telegram-notice-bot/database.json` — dedupe/update-detection state, auto-created.

## Architecture decisions

- The notice bot is a plain Python background worker (no web preview), run via a dedicated Replit workflow rather than an "artifact" since it has no UI.
- Each site has its own scraper so one site failing (timeouts, layout changes, WAF blocks) never affects the others.
- On a site's first successful check, its current notices are recorded as a baseline but not delivered, to avoid flooding the chat with the entire existing notice list on first deploy.

## Product

- Telegram bot that watches ppup.ac.in, ppupadm.samarth.edu.in, and ancpatna.ac.in for new/updated notices and posts them to a configured Telegram chat within 5 minutes of publication, with PDFs delivered as images (≤5 pages) or documents (>5 pages).

## User preferences

_Populate as you build — explicit user instructions worth remembering across sessions._

## Gotchas

- `ppupadm.samarth.edu.in` sits behind an AWS WAF that returns 403 to some data-center egress IPs regardless of headers/cookies — not fixable in code. It self-heals: the bot will seed its baseline automatically the first time it becomes reachable. Verify from the actual deployment host if this site keeps failing self-test.

## Pointers

- See the `pnpm-workspace` skill for workspace structure, TypeScript setup, and package details
