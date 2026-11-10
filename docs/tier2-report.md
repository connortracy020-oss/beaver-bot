# Tier 2 report

Run 4 (`tier2`), started by `python -m osu_crawl.crawl resume-tier2`, 2026-10-24, 23:28:39–23:59:06 UTC (30.5 min). Exit code **0**.

**Result: Tier 2 finished normally.** No 429, no 403, no challenge page. The frontier for the six Tier 2 hosts is empty (0 URLs still queued).

This run was started by a scheduled Claude Code task at the owner's request, after the all-of-OSU pause in `data/logs/cooldown.json` had ended (2026-10-24 04:30:53 UTC). Generated numbers: [tier2-metrics.md](tier2-metrics.md). Background: [tier2-pilot-report.md](tier2-pilot-report.md).

## 1. What happened

| Time (UTC) | Event |
|---|---|
| 23:28:38 | Lock check passed (no `crawler.lock`, no other crawler). The command unblocked the five rate-limited sites (scholarships, food, transportation, writingcenter, career). classes.oregonstate.edu stays blocked. |
| 23:28:39–23:30:39 | robots.txt fetched once per site: 5 × 200 |
| 23:28:43–23:59:06 | 491 page/PDF requests, one at a time, ≥ 3 s apart |
| 23:59:06 | Queue empty; run ends. `tier2-ended.json` was **not** written, since there was no 429. |

## 2. Counts

**Stored per Tier 2 host** (totals in the database, pilot included, with this run's share in brackets):

| Host | Pages | PDFs |
|---|---|---|
| career.oregonstate.edu | 184 (+171) | 8 (+8) |
| transportation.oregonstate.edu | 69 (+57) | 48 (+48) |
| food.oregonstate.edu | 41 (+30) | 0 |
| writingcenter.oregonstate.edu | 27 (+18) | 19 (+16) |
| scholarships.oregonstate.edu | 13 (+5) | 6 (+3) |
| experience.oregonstate.edu | 1 (+0) | 0 |
| **Total** | **335 (+281)** | **81 (+75)** |

Two of the 75 new PDFs are stored as link-only: they're scanned, and OCR is skipped by policy. The console reports 73 documents with text, plus `documents_link_only: 2`.

Whole database now: 3,383 pages across 26 hosts (structure map regenerated). There are 858 chunks from Tier 2 pages.

**Requests this run**

| | Count |
|---|---|
| robots.txt | 5 × 200 |
| Page/PDF HTTP requests (log lines, every redirect hop included) | 491: 440 × 200, 38 × 301, 5 × 302, 8 × 404 |
| Final outcomes in `fetch_log` | 448: 440 × 200, 8 × 404 |
| Network errors | 0 |
| 403 / 429 / challenge | **0** |

**404s (8):** recorded as errors and not retried.
- transportation `/parking/citations` and `/parking/osu-beaver-bus`
- writingcenter `/node/26`
- career `/media/1146`, `/media/426`, `/media/236`, `/node/341` and `/academia.edu` (the last is a malformed relative link on a career page)

**Skips this run, by reason:**
- **unsupported_type 53:** 52 `.docx` and 1 `.pptx`, mostly Career Development Center worksheets and templates. Never downloaded.
- **duplicate 31**
- **out_of_scope 5:** food `/dining` and `/catering` (redirect to uhds), two transportation visitor pages, service-vehicle permits
- **robots 5:** `/search` on each site
- **too_large 2:** Writing Center slide decks of 53 MB and 47 MB. Each was rejected on its `Content-Length` header and the body was not downloaded.
- **login 1:** transportation `/parking/parking-permits` redirects to sign-in, so it was recorded and not followed.
- **tier3 1:** a Career news story

**Forms recorded on Tier 2 pages (never submitted):** 18 external, 8 behind sign-in, 2 web forms, 3 fillable PDFs.

## 3. Blocks, 429s and challenges

- **None this run.** There are no 403/429 events in `data/logs/crawl-tier2.jsonl`, and no new files in `data/logs/refused/`; the newest are still the five pilot 429 pages from 2026-10-23 04:30.
- **`data/logs/blocked.json` now holds only** `classes.oregonstate.edu` (robots.txt returned 202 on 2026-10-22). The guarded command removed the five Tier 2 sites, as the owner decided.
- **`data/logs/cooldown.json` is unchanged:** it still holds the expired pause (until 2026-10-24 04:30:53 UTC), with the pilot reason. There is no new pause.
- **`data/logs/forbidden.json` is unchanged:** one registrar URL from the Tier 1 pilot.
- **`data/logs/tier2-ended.json` is absent:** Tier 2 wasn't ended by a 429. It finished.

## 4. Pacing check

Computed from the `started` and `ts` fields in `crawl-tier2.jsonl`:

| | Value |
|---|---|
| Requests with a `started` time | 489 |
| Minimum gap, start to start | **3.079 s** (two transportation pages) |
| Minimum gap, end of one request to start of the next | **3.001 s** |
| Median gap, start to start | 3.548 s |
| Gaps under 3 s | **0** |
| robots.txt requests (logged with `ts` only) | each followed by ≥ 3.07 s before the next request; each came ≥ 3.57 s after the previous request ended |
| The 2 `too_large` requests (logged with `ts` only, at header time) | 3.29 s and 9.74 s after the previous request ended; next request ≥ 3.19 s later |

**Overall rate:** 496 requests in 30.5 min, about 0.27 requests/s. That's a quarter of the 1.12 requests/s that tripped the limit in the pilot.

## 5. Privacy and tests

- **`privacy audit`:** `{'records': 0, 'emails': 0, 'phones': 0}`. No scrub was needed.
- **`python -m unittest discover tests`:** **12 tests, OK** (15 s). The tests use temporary directories. I checked that they didn't create or change anything in the real `data/logs/`.
- **`report tier2`:** wrote `docs/tier2-metrics.md`.
- **`structure`:** regenerated `docs/structure-map.json` and `docs/structure-map.generated.md` (3,383 pages, 26 hosts).

## 6. Things worth noting

- **Career job-shadow pages:** 109 of career's 184 pages are `/job-shadow-host/<employer>` pages (Nike, Amazon, US Forest Service…). They name organisations, not people, so the PII rule didn't skip them. Each is about one chunk. They may be noise for a student-questions assistant; the owner may want them excluded or down-weighted at retrieval time.
- **Food still has no PDFs, and menus are empty:** menus load with JavaScript, as the pilot found.
- **experience.oregonstate.edu has one URL** (`/career`), stored in the pilot. Nothing new was found there.
- **Pacing log gap:** the fetcher logs an oversized response before its `started` field is added, so those 2 log lines carry only `ts`. Pacing was still enforced by `_wait_turn`, and the gaps in section 4 confirm it. A one-line logging fix would make the log complete.
- **The `academia.edu` link:** a career page links to `academia.edu` without a scheme. The crawler resolved it as a relative path and got a 404. That's harmless, and it was one extra request.

## 7. Open questions for the owner

1. **Job-shadow pages:** keep, exclude, or down-weight the 109 career job-shadow host pages?
2. **Word templates:** the 52 skipped `.docx` files are Career worksheets and templates. Record them as link-only documents, so the assistant can point to them?
3. **Expired pause:** `cooldown.json` still holds the expired pause from the pilot. It has no effect now. Keep it as a record, or archive it? I didn't touch it.
4. **Next steps:** Tier 2 is complete. Steps 5–8 (categories and question set, retrieval prototype, answer layer, documented recrawl) haven't started.
