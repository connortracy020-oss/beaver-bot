# Tier 2 pilot report

Run 3 (`tier2-pilot`), 2026-10-23, 04:29:50–04:30:56 UTC.

**Result: stopped by OSU's rate limit after 66 seconds.** 54 of the planned 150 pages were stored.

All Tier 2 sites are blocked, and every OSU site is paused until **2026-10-24 04:30 UTC**. No request has been sent to OSU since the stop. **A decision is needed before anything else is crawled** (section 5).

Generated numbers: [tier2-pilot-metrics.md](tier2-pilot-metrics.md). Plan: [tier2-plan.md](tier2-plan.md).

## 1. What happened

| Time (UTC) | Event |
|---|---|
| 04:29:50 | Pilot starts. The six sites take turns, each at least 2 s apart. |
| 04:29:50–04:30:53 | 68 requests, all answered normally (64 × 200, 4 × 301) |
| 04:30:53.7 | food.oregonstate.edu: **HTTP 429**. Site blocked. |
| 04:30:54.3 | transportation: **HTTP 429**. Site blocked. |
| 04:30:54.9 | scholarships: **HTTP 429**. Site blocked. |
| 04:30:55.5 | writingcenter: **HTTP 429**. Site blocked. |
| 04:30:56.2 | career: **HTTP 429**. Site blocked; nothing left to crawl, so the run ends. |

**Evidence** (saved bodies in `data/logs/refused/*-429-*.html`):
- **What the 429 pages are:** five small (5.7–5.9 KB) Cloudflare pages titled *"Just a moment…"*, reading *"Enable JavaScript and cookies to continue"*. That's Cloudflare's challenge in front of OSU's sites. The crawler never tries to solve challenges.
- **Rate before the first 429:** 65 requests in the preceding 60 s, across all six sites (1.12 requests/s overall). Each site individually was ≥ 2 s apart, within our per-site rule.
- **One shared limit:** five different sites returned 429 within 3 s of each other. The limit is shared across OSU's sites and counts all our requests together, not per site.
- **Why Tier 1 didn't trip it:** the Tier 1 crawl averaged 0.75 requests/s with no 429. In this pilot, six small sites taking turns pushed the combined rate higher.

**The crawler followed the rules:** each site stopped at its first 429, nothing was retried, and no challenge was attempted. **But it reacted per site, not per limit.** The other four sites received one request each in the 3 s after the first 429. That's fixed (section 4).

## 2. Counts

| | Count |
|---|---|
| Requests | 73: 64 × 200, 4 × 301, **5 × 429** |
| Pages stored | **54**: career 13, transportation 12, food 11, writingcenter 9, scholarships 8, experience 1 |
| PDFs stored | 6: 3 Writing Center handouts, 3 Scholarship Office forms and terms |
| Forms recorded (never submitted) | 8 behind sign-in (parking permits, Handshake…), 7 external (Qualtrics, booking), 1 web form, 19 PDF links |
| Chunks | 183 from pages (median ~190 tokens), plus PDF chunks |
| Dates | 60, **all stored as mentions**; none of these sites is an authoritative date source |
| Skipped | 1 people page, 1 news/event page, 10 non-page links, 4 duplicates |
| Blocked | 5 sites (all by the 429s above) |
| Still queued | 194 URLs (pages + PDFs), never requested |

## 3. Quality of what was stored

- **Main content:** found on 54 of 54 pages. Our text vs. trafilatura: median ratio 1.08.
- **Templates:** the same OSU Drupal theme as Tier 1 (`drupal:page`, accordions, one webform). Nothing new for the extractor.
- **Privacy:** re-audit after the pilot finds **0** personal emails or direct phones in stored text. The scrub step runs during extraction.
- **Expected gaps:**
  - `food /menus-and-nutrition` has no text: the menus load with JavaScript, as predicted.
  - 3 Writing Center "tools for writers" index pages are short link lists.
- **Example PDF titles:** "Printable PDF Scholarship Appeal Form", "Terms and Conditions for the Finley Academic Excellence Scholarship", "Translanguaging Strategies for the Writing Process".

## 4. What changed in the crawler (code only, tested offline)

1. **A global pace across all OSU sites:** at least **3 s between any two requests**, whichever site (`min_global_delay_s`, about 20 per minute). That's under a third of the rate that tripped the limit. The per-site 2 s floor stays.
2. **A pause across all of OSU on any 429 or challenge:**
   - The site that answered is blocked for good, as before.
   - **Every `*.oregonstate.edu` site is paused for 24 hours.** The pause is written to `data/logs/cooldown.json` at once and survives restarts.
   - No paused site is contacted, robots.txt included. Their URLs stay queued.
   - Only a person can lift the pause early, by deleting that file.
3. **The real incident is recorded:** `cooldown.json` holds the pause until **2026-10-24 04:30:53 UTC**. I confirmed offline that the crawler now refuses every OSU site, Tier 1 included.
4. **Tests:** 31 fetcher checks pass, including the global gap across sites, the zone pause sending no requests, and the pause surviving restarts.

The policy doc is updated to match.

## 5. Decision (owner, 2026-10-23)

**Option 1 chosen:**
1. After the pause ends at 2026-10-24 04:30:53 UTC, unblock the five Tier 2 sites.
2. Finish Tier 2 at the 3 s global pace, with the all-of-OSU pause.
3. **If any 429 recurs, stop and end Tier 2.**

This is implemented as one guarded command:

```
.venv\Scripts\python -m osu_crawl.crawl resume-tier2
```

What the command enforces:
- It refuses to send anything before the pause ends.
- It refuses if the global pace is below 3 s.
- It unblocks only the five rate-limited sites (classes.oregonstate.edu stays blocked).
- It runs the full `tier2` phase.
- If a 429 or challenge comes back, all of OSU is paused at once, `data/logs/tier2-ended.json` is written, and the command will never run again.

Tested in `tests/test_resume_tier2.py`.

### Options that were offered

Under your rule, all five Tier 2 sites are blocked for good until you say otherwise. Options:

1. **(Recommended) Resume after the pause, more slowly.**
   - After 2026-10-24 04:30 UTC, unblock the five sites and finish the pilot, then the remaining ~190 URLs.
   - Use the new 3 s global pace (about 25 minutes in all) with the pause-everything-on-429 rule.
   - If a single 429 recurs, everything stops again and Tier 2 ends there.
2. **Ask OSU first.** Email OSU's web team (University Information Technology / web services) to describe the project and ask what request rate they'd accept. Our User-Agent already gives your contact.
3. **Stop Tier 2 here.** Keep the 54 pages and 6 PDFs, and link to the rest of these sites.

Tier 1 re-crawls (`crawl recrawl`) are also paused until the cooldown ends, and they'll use the slower global pace from now on. A full Tier 1 re-crawl at 3 s takes about 4 hours. Most pages are skipped by their sitemap date, so a typical weekly run will be much shorter.
