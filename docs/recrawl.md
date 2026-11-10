# Weekly re-crawl

**One command, run by a person.** It's documented here and never scheduled automatically (owner's decision, batch 2
step 8). Each run contacts OSU, so run it only when you mean to.

```
.venv\Scripts\python -m osu_crawl.weekly --dry-run
.venv\Scripts\python -m osu_crawl.weekly
```

Run `--dry-run` first. It prints the plan and sends nothing. As of 2026-10-29, with Tier 2b added, the plan was:

| | |
|---|---:|
| Sites | 59 |
| Sitemap and robots.txt requests | ~141 |
| Pages skipped on their sitemap date (no request) | 6,026 |
| Pages asked conditionally | 1,758 |
| PDFs asked conditionally | 1,294 |
| **Most requests a run can send** | **~3,190 (about 2.7 h at 3 s each)** |

Most conditional requests come back `304 Not Modified`: no body, almost no work for OSU's servers.

## What a run does

1. **Preflight, offline.** The run stops (exit code in brackets) if:
   - OSU is paused after a rate limit (`data/logs/cooldown.json`) [3];
   - the global pace is under 3 s [4];
   - another crawl holds `data/logs/crawler.lock` [6].

   Blocked sites (`data/logs/blocked.json`) are left out. Only the owner unblocks a site.
2. **Sitemaps.** Each site's sitemap is re-read through the same polite fetcher (robots.txt, 3 s pace, pause on 429).
   - **Why first:** a stale sitemap date would make the crawl skip a page that changed.
   - **If a sitemap fails:** that site's old sitemap dates are cleared, so its pages get conditional requests instead of being skipped.
3. **Re-crawl** (`crawl recrawl`, Tier 1 + Tier 2). Every stored URL, plus last run's errors, goes back in the queue.
   - **Unchanged by sitemap:** a page whose sitemap date is no newer than our copy gets no request. That holds only for 28 days after we last fetched it (`SITEMAP_TRUST_DAYS`); after that it gets a conditional request anyway.
   - **Conditional requests:** everything else, PDFs included, sends the stored `ETag` / `Last-Modified`. A `304` means unchanged.
   - **Changed pages:** re-extracted, privacy-scrubbed, and re-chunked as before.
   - **New pages:** fetched when they appear in a sitemap or a link, within the same scope rules.
   - **Pages OSU took down:** a `404` or `410` on a stored page or PDF removes its chunks and dates from search and records `gone_at`. The row stays, so we know it existed.
   - **Same rules as every crawl:** robots.txt, ≥ 2 s per site and ≥ 3 s across OSU, no logins or forms, and any 429 or challenge pauses all of OSU for 24 h ([crawl-policy.md](crawl-policy.md)). A run that hits a pause stops; nothing is retried automatically.
4. **Rebuild, offline:**
   - privacy audit (should find 0);
   - owners and categories ([categories.md](categories.md));
   - link authority for ranking;
   - dedupe: duplicate pages and PDFs, and boilerplate chunks found on 5+ pages, are kept once in search (`osu_crawl/dedupe.py`);
   - `docs/recrawl-metrics.md`;
   - structure map;
   - retrieval eval ([retrieval-eval.md](retrieval-eval.md)).

   `--rebuild-only` runs just this step.
5. **Report.** [recrawl-report.md](recrawl-report.md) (counts and the latest changed pages), plus the full
   summary in `data/logs/recrawl-<time>.json`.

## After a run

- **Exit 0:** read `docs/recrawl-report.md`.
  - **Retrieval:** if the eval's top-3 score dropped, look at what changed.
  - **Privacy:** a privacy finding above 0 means the scrubber missed something. Review it before anything else.
- **Exit 3:** OSU rate-limited us, or we were already paused. Nothing more is sent until the pause in `cooldown.json` ends. Tell the owner; don't delete the file to hurry it.
- **A new blocked site:** it stays blocked. The owner decides whether to unblock it, as with registrar in the pilot.
- **Interrupted (Ctrl+C or a closed laptop):** run the same command again. The crawl resumes its unfinished run, and the rebuild runs again.

## Not done automatically, on purpose

- No schedule: no cron job, scheduled task, or loop.
- No retry after a 429, a challenge, or a block.
- No new sites: scope changes go through `osu_crawl/scope.py` and the owner.
