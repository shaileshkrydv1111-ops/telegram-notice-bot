---
name: scraper bot WAF blocks and baseline seeding
description: Lessons for building site-monitoring/notification bots (e.g. Telegram notice bots) - WAF-blocked sources and first-run flood prevention.
---

## WAF-blocked sources

Some institutional sites (observed: a `samarth.edu.in` admissions portal
behind AWS ELB/WAF) return 403 to the whole domain (even the root page,
even with realistic browser headers, `Referer`, and cookies from a prior
request) from certain data-center egress IPs. This is an IP-reputation
block, not a header/user-agent problem — do not waste time iterating on
headers or session/cookie handshakes to bypass it.

**Why:** confirmed by testing: root domain and target page both 403 from
the Replit sandbox IP with multiple realistic browser header sets and
warmed-up cookies; other sites on the same task worked fine with the same
approach.

**How to apply:** build the scraper correctly (retries, backoff, isolated
per-site error handling) and document the limitation rather than trying to
defeat the WAF. It commonly works from a different network (e.g. the
user's actual VPS). Design monitoring bots so one source's persistent
failure never blocks the others, and so the source self-heals (picks up
normal operation, including any first-run baseline) automatically the
first time it becomes reachable.

## Baseline seeding on first contact

A site-monitoring bot that alerts on "new" items must not treat "not yet
in my database" as "new" the very first time it checks a site — many
notice-board pages render their *entire* historical archive (hundreds to
thousands of items) on one page with no pagination. Naively diffing
against an empty database on first deploy sends the whole backlog to the
destination (e.g. floods a Telegram channel with dozens of messages).

**Why:** discovered by shipping a first version that, on first run,
correctly found ~60+ "new" notices per site and dispatched all of them
before this was caught and the workflow was stopped mid-flood.

**How to apply:** when a site's tracking namespace is empty (never
successfully checked before), record everything currently found as
already-seen (baseline) without delivering it, then only start delivering
from the next check onward. Apply this per-site independently, since sites
may become reachable for the first time at different times (e.g. one
site is WAF-blocked initially and only becomes reachable later — it should
seed its own baseline then, not flood on that later first success).

Also cap how much of an unpaginated "full archive" page is scanned/detail-
fetched per cycle (e.g. only the newest N list entries, with a smaller
"recheck window" of the very newest M entries getting a full detail-page
refetch even if already known, to catch edits) — otherwise every cycle
re-fetches a detail page for every historical item, which is slow and
hammers the source site for no benefit.
