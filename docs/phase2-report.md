# Phase 2 report: full Tier 1 crawl

Status: **done 2026-10-22** (run 2, `tier1`, finished 23:44 UTC).

The crawl ran in two legs. It was paused at 22:19 when the laptop was closed and resumed after the owner approved the "Access denied" rule. Crawling time was about 94 minutes in total.

- Generated numbers: [tier1-metrics.md](tier1-metrics.md)
- How OSU organizes information: [structure-map.md](structure-map.md)
- Rules: [crawl-policy.md](crawl-policy.md)

## 1. Counts (whole dataset: pilot + Phase 2)

| | Count |
|---|---|
| Sites | 20 Tier 1 sites, all finished. Nothing is left in the queue. |
| Pages stored | **3,048** |
| PDFs stored with text | **410** (2 are scans that would need OCR) |
| Documents and forms recorded | **1,707**. 1,411 PDF links, of which 1,016 are catalog print copies that aren't fetched. 145 external forms, 92 fillable PDFs, 32 behind OSU sign-in, 27 on-page web forms. None were submitted. |
| Chunks | 41,150: one per catalog course, otherwise median 117 words |
| Dates | 4,550 raw rows. 2,880 come from tables and 1,670 from text; 3,988 have an ISO date. 482 come from archived past-year calendars and are flagged. |
| Link graph | 325,530 links; menus for 19 sites; 1,383 pages placed in their site's menu |
| Requests | 4,531 over both phases (Phase 2: 4,313), always at least 2 s apart per site, plus robots.txt |
| Responses (Phase 2) | 4,211 × 200, 92 × 404, 8 × 503, 2 network errors |

Pages per site:

| Site | Pages |
|---|---:|
| catalog | 1,014 |
| ecampus | 379 |
| engineering | 339 |
| registrar | 300 |
| uhds | 189 |
| ds | 142 |
| library | 129 |
| technology | 119 |
| financialaid | 115 |
| success | 68 |
| counseling | 67 |
| studenthealth | 53 |
| holds | 38 |
| advising | 31 |
| studentlife | 20 |
| scs | 15 |
| finance | 14 |
| basicneeds | 8 |
| care | 7 |
| map | 1 (link only) |

## 2. Blocked, skipped and errors

**Blocked:** only `classes.oregonstate.edu`, from Phase 0. No site was blocked in Phase 2.

**Unblocked during Phase 2, with the owner's approval:**
- `registrar.oregonstate.edu` (pilot)
- `finance.oregonstate.edu` and `studentlife.oregonstate.edu`. Both had been stopped under the old second-403 rule. Their 403s were OSU's themed "Access denied" pages, now treated as per-page skips.

**Skipped**, with the reason recorded for each URL in the `skips` table:

| Reason | URLs | Notes |
|---|---:|---|
| Tier 3 (news, stories, events, podcasts) | 1,840 | mostly listed in sitemaps; never requested |
| Personal data | 1,364 | people, staff and directory pages. By site: engineering 958, finance 103, counseling 92, library 91, registrar 39, basicneeds 19, ecampus 16, ds 16, financialaid 10, scs 8, others ≤ 3. Never requested. |
| Duplicates | 477 | same canonical URL as a stored page |
| noindex | 446 | 440 are individual posts under `registrar /student-emails/`, which OSU marks `noindex, nofollow`. Fetched, not stored. That path is now excluded so re-crawls won't request them. |
| not a page / asset | 180 / 106 | sitemaps, feeds, `/cdn-cgi/`, email-as-link URLs; images, CSS, JS |
| Out of scope after redirect | 55 | redirect targets outside the approved sections |
| Unsupported type | 34 | .xlsx, .docx and similar |
| **Forbidden (themed "Access denied")** | **27** | Unpublished pages, each skipped individually. Bodies in `data/logs/refused/`. Examples: registrar `/policies-and-regulations`, finance `/student-accounts/tuition-reduction-schedule`, studentlife `/hsrc/mealbux`, ds `/documentation-requirements`. **44 content links on live OSU pages still point to these.** |
| robots.txt | 19 | every site's `/search`; catalog `/azindex/`, `/archives/`, `/search/`, `/pdf/…Catalog.pdf`; uhds `/admin/…` |
| Too large | 7 | over 5 MB of HTML or 25 MB of PDF |
| Login | 4 | registrar `/login`, library `/cas`, ecampus `/forms/proctoring/login`, `/forms/osu-everywhere.htm` |

**Errors:**
- 78 pages and 14 PDFs returned 404, mostly stale sitemap entries and broken OSU links.
- 8 pages returned 503 after retries.
- One processing error (a link with a non-web scheme on Library `/ask-librarian`) was fixed and the page re-fetched.

**Rule compliance:**
- robots.txt was obeyed: 19 URLs skipped without a request.
- At least 2 s per site and one request at a time, now logged with millisecond timestamps.
- No logins, no form submissions, no APIs.
- Nothing from people pages is stored.
- No images, CSS or JS were downloaded.

## 3. What changed during Phase 2

- **Narrower 403 rule** (approved): OSU's themed "Access denied" pages skip just that page. A CDN/firewall block page, a short-body 403 or a 403 on the home page still stops the site, as do 429s and challenges.
- **Incremental re-crawls:** `python -m osu_crawl.crawl recrawl` re-queues stored pages.
  - Pages whose sitemap `lastmod` isn't newer than our copy are skipped without a request.
  - The rest go out as conditional GETs (ETag / Last-Modified).
  - `text_hash` decides whether content really changed (`changed_at`).
  - Tested offline: 29 of 47 pages skipped with no request, the other 18 sent conditionally, none falsely marked changed.
- **Fixes:**
  - `registrar /student-emails/` excluded (noindex mass emails)
  - email-address "links" are ignored
  - non-web link schemes are ignored
  - the Registrar's own A–Z `site-index` pages get real titles and type `other`
  - "most linked" in the structure map counts only links from content pages, not hubs or indexes

## 4. Open questions

1. **Two scanned PDFs need OCR to be searchable:** an Engineering ECE program flowchart and a College of Education advising insert. Both are mostly images. I'd skip OCR rather than install Tesseract for two files.
2. **Tier 2.** Many Tier 1 pages link to these sites:
   - graduate.oregonstate.edu
   - admissions
   - scholarships
   - food.oregonstate.edu
   - transportation (parking and transit)
   - writingcenter
   - mysupport (the IT ticket portal; it probably needs sign-in)

   Count their sitemaps and plan a Tier 2 crawl?
3. **Re-crawl cadence:** weekly `recrawl`? Most Drupal pages carry a sitemap `lastmod`, so a quiet week costs few requests.
4. **Git:** nothing is committed yet. The code and docs (no data) could go into this private repo.
