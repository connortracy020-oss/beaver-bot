# Crawl policy

What OSU's robots.txt files and website terms allow, and the rules this crawler follows because of them.
All sources were read on **2026-10-22**. Cached copies are in `data/discovery/robots/` and `data/discovery/text/`, both gitignored.

This is an independent student class project. It is **not affiliated with Oregon State University**.

## 1. OSU's website terms

OSU has no single "terms of use" page for its websites. The homepage footer links to Copyright, Privacy Disclaimer, Accessibility Statement and Non-discrimination Statement. Not one of them mentions automated access, crawling or reuse of content. The pages that apply:

| Source | What it says | What it means for us |
|---|---|---|
| [Official Web Disclaimer and Privacy Statement](https://oregonstate.edu/official-web-disclaimer) | Many people write the content, and its accuracy isn't guaranteed. Unless noted otherwise, it may not represent official OSU statements. Use it "at your own risk." OSU logs each visitor's IP address, browser, pages and time. | Every answer cites and links the official page and shows the date it was retrieved, and tells students to check that page. OSU will see our requests, which is why the User-Agent names the project and gives a contact. |
| [Copyright / DMCA](https://oregonstate.edu/digital-millennium-copyright-act) (`/copyright` redirects here) | OSU has a DMCA agent at the Office of Information Security for infringement claims. | Treat page text as copyrighted. Keep it privately for search and citation. The app quotes short excerpts and links to the page; it never republishes whole pages. |
| [University Policy 08-005, Acceptable Use of Computing Resources](https://policy.oregonstate.edu/UPSM/08-005_acceptable_use_computing_resources) (revised 2023-02-15) | Covers "anyone using university computing resources," including students and visitors. Users must not "circumvent or attempt to circumvent the security mechanisms" (5.1.3d) or degrade or damage performance (5.1.3e), and must follow copyright law (5.1.3g). The Code of Student Conduct extends to virtual environments (2.2). | These rules bind us both as visitors and as OSU students. So: never work around a block, challenge, rate limit or 403/429. Send one request at a time, at least 2 s apart. Stop a host as soon as it pushes back. |
| [Trademark Licensing](https://communications.oregonstate.edu/trademark-licensing) and [FAQs](https://communications.oregonstate.edu/trademark-licensing/faqs) | OSU claims its names, logos, seals, mascots and slogans. It also claims "the university's color scheme in combination with facts or wording that implies an association". Anyone must get approval before using its indicia, and the marks may not imply endorsement. Businesses may not use indicia in a name, website or URL without written permission. | Don't store or reuse logos, images, stylesheets or colors. The app needs its own name and look, plus a visible "not affiliated with OSU" notice. A name containing "OSU", "Oregon State" or "Beaver" may need permission (see open questions in the plan). |
| [Directory Information (Registrar)](https://registrar.oregonstate.edu/directory-information) | Student names, ONID emails, majors and similar details count as FERPA "directory information" that OSU may release. Students can restrict them. | This backs up our rule to skip directories and people pages entirely. Even when OSU may publish something, we have no reason to collect it. |

## 2. robots.txt, host by host

Fetched with our own User-Agent. None names our bot, so the `User-agent: *` group applies everywhere.

| Host(s) | robots.txt | Crawl-delay | Sitemap | Notable rules |
|---|---|---|---|---|
| oregonstate.edu, registrar, advising, financialaid, finance, ds, studentlife, scs, studenthealth, counseling, uhds, technology, uit, engineering, policy, communications, success, holds, care, basicneeds (20 hosts) | 200, the **standard Drupal file** (identical on every one) | none, so we use 2 s | not listed, but `/sitemap.xml` exists | Disallows `/admin/`, `/search/`, `/user/login`, `/user/register`, `/user/password`, `/user/logout`, `/node/add/`, `/comment/reply/`, `/core/`, `/profiles/`, `/media/oembed` |
| catalog.oregonstate.edu (CourseLeaf) | 200 | none | listed | Disallows `/azindex/` (the catalog's A-Z index), `/search/`, `/course-search/api`, `/course-search/build`, `/pdf/` (PDF editions of the catalog), `/archives/`, `/courseleaf/`, `/cim/`, `/ribbit/`, `/images/`, `/css/`, `/js/` and other admin paths |
| ecampus.oregonstate.edu | 200 | none | 8 listed (one is plain text) | Disallows `/campaign/`, `/crm/`, `/includes/*.htm|json|php`, `/staff/portal/`, `/online-degrees/promotion/`, two affiliate form pages |
| guides.library.oregonstate.edu (LibGuides) | 200 | **10 s** | listed | Blocks about 20 named bots outright, **including AI crawlers**: GPTBot, ChatGPT-User, CCBot, Google-Extended, Applebot-Extended, Gemini-Deep-Research, Bytespider, Amazonbot and others. `*` also disallows `az.php?`, `go.php`, `srch.php` and similar. |
| library.oregonstate.edu | **404** (no file) | none, so we use 2 s | none | RFC 9309 treats a missing file as permission. We still apply the same exclusions (login, search, people). |
| map.oregonstate.edu | 404 | none, so we use 2 s | none | JavaScript app. Its data comes from an API we will not call. |
| classes.oregonstate.edu (Schedule of Classes) | **HTTP 202** | n/a | n/a | A 202 for robots.txt is what bot-protection services return before a JavaScript check. **Treated as a block. Stopped and not retried.** |
| fa.oregonstate.edu | TLS error (incomplete certificate chain) | n/a | n/a | We don't turn off certificate checks. Treated as disallow-all. Student billing is on finance.oregonstate.edu anyway. |

No page we sampled carried `<meta name="robots" content="noindex/nofollow">` or an `X-Robots-Tag` header. The crawler still checks both on every page.

## 3. Rules the crawler enforces

Implemented in [`osu_crawl/fetcher.py`](../osu_crawl/fetcher.py), [`osu_crawl/config.py`](../osu_crawl/config.py) and [`osu_crawl/scope.py`](../osu_crawl/scope.py).

**Identification**
- User-Agent: `OSUStudentAssistantResearch/0.1 (independent student class project, not affiliated with OSU; contact: <your OSU email>)`. The crawl won't start until `contact_email` is set in `crawler.toml`.

**robots.txt**
- Read before any other request to a host. Cached for 24 h.
- Its own redirects are followed by hand, and each hop is paced and checked.
- Parsed with Protego (Google-style matching: `*`, `$`, longest match wins).
- Crawl-delay and Request-rate are honored whenever they exceed our floor.
- A 5xx or network failure is retried with backoff. If it still fails, nothing on that host is fetched for the rest of the run (RFC 9309: unreachable means disallowed).
- A 403/429, a 202 or a challenge page means the host is blocked.

**Pacing**
- One crawler process at a time: a lock file in `data/logs/` stops a second crawl or discovery run from starting.
- One request at a time across all hosts, with **at least 3 s between any two requests to OSU, whichever site** (`min_global_delay_s`). OSU's sites share one Cloudflare rate limit: the Tier 2 pilot tripped it at 1.12 requests/s overall while every site was within its own 2 s gap (raised from 0.5 s on 2026-10-23).
- At least **2 s between the end of one response and the next request** to the same host, plus jitter, or the crawl-delay if longer.
- Pacing state persists across runs.

**Errors**
- 5xx: exponential backoff (5 s, 10 s, 20 s, honoring Retry-After in seconds or as a date), then that URL is marked as an error.
- Five 5xx responses or five network errors in a row stop the host for the rest of the run. Its URLs stay queued for a later run.
- 429, 202, or **any** 4xx/5xx carrying a captcha/challenge page (e.g. AWS WAF's 405 CAPTCHA): the host is marked **blocked**. The block is written to `data/logs/blocked.json` immediately and sticks across runs until a person clears it. No retries, no workarounds.
- **Pause across all of OSU:** the same 429/202/challenge also pauses **every `*.oregonstate.edu` site for 24 hours**, so one rate-limit answer costs one request, not one per site. The pause is written to `data/logs/cooldown.json` and survives restarts; only a person can lift it early. Paused sites get no request at all (not even robots.txt), and their URLs stay queued.
- **403 (rules approved by the owner on 2026-10-22, after the pilot and again during Phase 2).** Nothing is retried. The body of every refusal is saved to `data/logs/refused/` for review.
  - **OSU's own themed "Access denied" page** skips **that URL only**, with **no limit per host**. This is the Drupal page titled "Access denied | <Office> | Oregon State University" (or "| OSU College of …"), with no CDN, firewall or challenge-interstitial markers, which is how OSU answers for an unpublished page. Logged as `forbidden`.
    - **Fixed 2026-10-29 (§8):** it is recognized at any size (small sites' pages are 16–20 KB), and a cookie banner that lists reCAPTCHA no longer counts as a challenge. Real challenges (`cf-chl`, `challenge-platform`, "Just a moment…", AWS WAF) still stop the host and pause OSU.
  - **Any other full-page 403** (at least 20 KB of HTML) skips that URL once per host. That allowance is kept in `data/logs/forbidden.json`; the pilot's unexplained 403 is registrar's one. A **second such 403 blocks the host**.
  - The host is **blocked** at once on:
    - a 403 on robots.txt or the home page
    - a 403 with a short or non-HTML body
    - a 403 carrying a CDN or firewall block page (Cloudflare "cf-error", "Ray ID", "used Cloudflare to restrict access") or a captcha/challenge
- A page that fails to process is rolled back, logged to `data/logs/errors.log` and skipped. Each URL is committed all-or-nothing, so Ctrl+C never leaves half a page.

**Redirects**
- Followed by hand, so every hop is checked against robots.txt, pacing, the host allow-list, path scope, Tier 3, people pages and assets before it is requested.
- A redirect into a login or SSO system (login.oregonstate.edu, Canvas, MyOregonState, Microsoft or Google sign-in, `/user/login`, `/saml`, `/idp/`, and so on) is recorded as login-required and never followed.

**noindex / nofollow**
- `noindex` or `none` (meta tag or X-Robots-Tag, on pages and PDFs): nothing is stored and the raw file is deleted.
- `nofollow`: neither its links nor its PDFs are followed.
- `rel="nofollow"` links aren't followed.

**Public pages only**
- No logins, no form submissions, no APIs. That rules out the catalog's `/course-search/api`, the map's data API and site search.

**Data minimization**
- Skipped and logged as `pii`:
  - `directory.oregonstate.edu`
  - every `/directory/<name>`, `/directory-profile/`, `/people/`, `/profiles/`, `/bios/`, `/human/` and `/staff/<name>` page
  - staff, faculty, leadership, team, members, ambassadors, advisory-board and subject/scheduling-contact listing pages
  - a short explicit list of listing pages found in the Engineering sitemap (`config.PII_PATHS`)
  - Cloudflare's `/cdn-cgi/` endpoints
- **Lists of named people (added after the Tier 2b crawl, 2026-10-29):** out of scope, removed from stored data, never fetched again:
  - ASOSU's per-member profile pages, committee, senate, judicial and records pages (ASOSU keeps only its student-facing sections);
  - research-showcase and thesis-fair presenter pages, student profiles, current-PhD-student and TA rosters, award-recipient pages, student-show pages, faculty and team listings;
  - advisory-board minutes and agendas;
  - (resume, 2026-10-29) Honors `/envoy/<name>` graduate profiles, graduate-school student stories, Diversity's `/state-inclusive-excellence/<name>` profiles, the Gold Star memorial's member and name-list pages, and past commencement ceremony pages.
- **PDFs that are records about named students** (taken out of the database; their files in data/raw are kept): minutes, agendas, election results, voter guides, research-showcase and lightning-talk programs, and students' own work (project executive summaries, dissertation abstracts), on every site. ASOSU keeps only its governing documents; Honors only its guides for students and parents. Logged as `student_records`.
- **Roster sections inside pages** ("Officers", "Meet the team", "Past recipients", "Presenters", "Senators", …) are dropped at extraction.
- Office contact details are kept. Individuals' names, emails and phone numbers aren't collected into structured fields.

**No branding**
- Images, logos, CSS, JS and fonts are never downloaded.
- Raw HTML is stored only so it can be re-parsed, and is never served.

**Private storage**
- `data/` (raw HTML/PDFs, the SQLite DB, logs) and `crawler.toml` are gitignored.
- Every page record keeps its URL, retrieved date and SHA-256 content hash.

## 4. Skipped or blocked so far (Phase 0)

| What | Why |
|---|---|
| classes.oregonstate.edu | Blocked: robots.txt returned HTTP 202 (bot protection). Stopped after that one request. |
| fa.oregonstate.edu | TLS certificate failure. Not retried with checks off. |
| guides.library.oregonstate.edu | Our choice: robots.txt bars every named AI crawler. Our bot isn't named, but this project feeds an AI assistant, so we respect the intent. |
| catalog.oregonstate.edu `/azindex/`, `/pdf/`, `/course-search/api` | robots.txt disallows them. |
| ~1,150 `/directory/<name>`-style URLs across Tier 1 sitemaps, plus 30 `oregonstate.edu/human/<name>` profiles | PII. Counted from sitemaps only, never fetched. |
| oregonstate.edu/siteindex.php (the old A-Z index) | HTTP 404. OSU appears to have retired it. |

## 5. Blocks and skips in the pilot (Phase 1)

| What | Why |
|---|---|
| registrar.oregonstate.edu | **Stopped** after HTTP 403 on `/faqs-fall-term-start-tuition-refund-and-dropwithdraw-dates`, reached by redirect from a sitemap URL ending `-0`. Most likely one unpublished page. The owner decides whether to resume; see pilot-report section 2. |
| catalog `/pdf/2026-2027_OSU_Catalog.pdf` | robots.txt |
| 54 people/staff URLs | PII (directory profiles, staff bios, faculty/subject-contact listings, student ambassadors) |
| registrar `/log-emails-sent-students-student-communications` | Tier 3: a feed of mass emails naming individuals; excluded, data deleted |
| ecampus `/students/going-online-podcast/` and 863 Ecampus news URLs | Tier 3 |
| 60 catalog "Download Page (PDF)" print copies | duplicates of HTML pages already stored |


## 6. Tier 2 pilot (2026-10-23): rate limit

All five Tier 2 sites answered HTTP 429 (Cloudflare "Just a moment…" challenge) within 3 s, after 65 requests in 60 s across sites. Each site is blocked, and every OSU site is paused until 2026-10-24 04:30:53 UTC. Details and evidence: [tier2-pilot-report.md](tier2-pilot-report.md).

| Host | Status |
|---|---|
| scholarships, food, transportation, writingcenter, career (`.oregonstate.edu`) | were blocked (HTTP 429 challenge); unblocked by the owner's decision and finished on 2026-10-24 (run 4, no 429) |
| all `*.oregonstate.edu` | were paused until 2026-10-24 04:30:53 UTC; the pause has ended and none is active |

## Re-crawls

The weekly re-crawl (`python -m osu_crawl.weekly`, run by hand; [recrawl.md](recrawl.md)) follows every rule above. It also keeps its load low:
- **Sitemap dates:** a page whose sitemap date is no newer than our copy gets no request, for up to 28 days after we fetched it.
- **Conditional requests:** every other stored page and PDF sends its `ETag` / `Last-Modified`, so unchanged ones come back as a bodiless `304`.
- **Pages OSU removed:** a `404`/`410` takes the page out of search; it is not retried more than once per run.

## 7. New robots.txt with content signals (found 2026-10-29)

Every OSU site checked on 2026-10-29 serves the same Cloudflare-managed robots.txt (4,703 bytes). That includes 40 Tier 3 candidates, plus registrar and career, which we had already crawled. Our copies from 2026-10-22 to 2026-10-24 didn't have it.

- **Our bot:** `User-agent: *` still has `Allow: /`. Our bot isn't named, so crawling is permitted, and the per-site `Disallow` lines are the usual Drupal ones.
- **Content signals for `*`:** `search=yes, ai-train=no, use=reference`. The file says accessing the site means agreeing to abide by them.
  - `search`: building a search index and returning links and short excerpts.
  - `ai-train`: training or fine-tuning AI models. **Not allowed.**
  - `ai-input`: using the content to ground AI answers. **Not set:** the file says it then "neither grants nor restricts permission".
  - `use=reference`: AI systems may consume the content for reference, not in full.
- **Named AI training crawlers are disallowed outright:** ClaudeBot, anthropic-ai, GPTBot, CCBot, Google-Extended, Applebot-Extended, Bytespider, meta-externalagent and others.

**How this project lines up:**
- **No training:** we never train or fine-tune on OSU content, and any model connected later must be one whose API terms don't train on inputs.
- **Reference use:** answers are short exact quotes with a link to the official page; pages are never reproduced in full.
- **Owner decision (2026-10-29): proceed under these terms.** Crawling, re-crawls and the answer layer continue, with three standing commitments:
  1. **No training.** The data is never used to train or fine-tune any model.
  2. **Reference only.** Answers quote short exact excerpts and link to the official page; pages are never reproduced in full.
  3. **No-training model APIs only.** Any model connected later must be one whose API terms don't train on the inputs we send.

## 8. Tier 2b full crawl (2026-10-29): three stops and an all-of-OSU pause

Run 6 sent 4,912 requests at ≥ 3.0 s apart, with **no 429 or rate limit**. Three sites answered one page each with HTTP 403. The crawler stopped each site, as its rules say. It read the pharmacy one as a challenge, so it also **paused all of OSU until 2026-10-30 13:19:56 UTC**. The saved bodies (`data/logs/refused/20261029T*`) show all three are **OSU's own Drupal "Access denied" pages for unpublished pages**, not blocks:

| Site | Page | Why the crawler stopped | What it actually was |
|---|---|---|---|
| commencement | `/2021-commencement` | 403 body of 19,640 bytes, under the 20 KB floor | Drupal "Access denied \| Commencement \| Oregon State University" |
| familyresources | `/about-us` | 403 body of 16,276 bytes, under the 20 KB floor | Drupal "Access denied \| Family Resource Center \| Oregon State University" |
| pharmacy | `/student-experience/our-campuses` | "captcha" in the page, read as a challenge (pause of all OSU) | Drupal "Access denied \| OSU College of Pharmacy"; the word came from its cookie banner's reCAPTCHA entry. No Cloudflare markers |

- **Code fix:** the 403 check now recognizes these pages (`osu_crawl/fetcher.py`, `tests/test_forbidden.py`). All 34 saved refusals since 2026-10-22 are classified as before, apart from these three.
- **Status:** the three sites stay blocked in `data/logs/blocked.json`, and the pause stays in `data/logs/cooldown.json` until it ends on its own. No request has been sent since.
- **Owner's decision (2026-10-29):** resume after the pause. The guarded `python -m osu_crawl.crawl resume-tier2b` clears only these three stops, and only while each recorded block is that day's 403. It refuses before the pause ends; it was scheduled once for 2026-10-30 6:21 am Pacific.
- **Pause lifted early (owner, 2026-10-29 11:49 am Pacific):** the owner asked whether the 24 h pause was OSU's rule or the project's. It is the project's own (OSU's robots.txt and terms set no such wait), and its trigger was the false alarm above, so the owner chose to lift it early. The lift is logged as `pause_lifted` in `data/logs/crawl-tier2b.jsonl`; the scheduled run was disabled. The resumed crawl sent 3,166 requests, min gap 3.03 s, **0 × 429, no challenge, no new block**. Its 38 HTTP 403s were all OSU's "Access denied" page (that URL skipped only).
- **Stopped mid-run by Claude Code for privacy (2026-10-29 1:57 pm):** the crawl was storing one page per named person on several sites. It was stopped, the pages were removed offline, the rules were tightened (see Data minimization above and [tier2b-report.md](tier2b-report.md) §8), and the crawl was resumed.

