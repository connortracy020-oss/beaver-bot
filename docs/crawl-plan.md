# Crawl plan (Phase 0)

Status: **approved 2026-10-22**; pilot and full Tier 1 crawl done the same day. See [pilot-report.md](pilot-report.md), [phase2-report.md](phase2-report.md) and [structure-map.md](structure-map.md).
Prepared 2026-10-22. Independent student class project, not affiliated with Oregon State University.

## 1. Summary

- **Tier 1 is about 2,830 HTML pages across 15 hosts**, counted from OSU's own sitemaps after removing people pages, news and out-of-scope sections. Linked PDFs come on top of that, probably a few hundred. Four small student-support sites found on OSU's Current Students hub would add 88 pages if you approve them.
- **OSU's A-Z index is gone.** `oregonstate.edu/siteindex.php` returns 404, and no current page links to a replacement. Domains came instead from OSU's own hub pages (homepage, Current Students, Contact, Academics, Future Students, Student Life, Technology) and the catalog's college and department list. That gave **76 OSU hosts**.
- **No OSU terms page forbids crawling.** Acceptable-use policy 08-005 bars circumventing security and degrading performance, which our rules already cover. Trademark rules affect the app's name and look, not the crawl. Details are in [crawl-policy.md](crawl-policy.md).
- **One host blocked us:** `classes.oregonstate.edu` (Schedule of Classes) answered robots.txt with a bot-protection 202. We stopped after that single request. Two more hosts are excluded: `guides.library` (its robots.txt bars AI crawlers) and `fa.` (TLS error).
- **Proposed pilot:** about 200 pages from Registrar, Catalog and Ecampus. These three sites run on three different platforms.

## 2. How domains were found

1. `oregonstate.edu` homepage, `/current`, `/contact`, `/academics` and `/future` gave the outgoing links. Raw copies are in `data/discovery/links-*.json`.
2. `catalog.oregonstate.edu/college-departments/` lists every college, school and department (1,626 links).
3. The front pages of `studentlife`, `technology`, `registrar` and `financialaid` were read for their navigation.
4. Every Tier 1 host's `/robots.txt` and `/sitemap.xml` (or the sitemaps robots.txt lists) were read to count pages.
5. Each starting URL was requested once to confirm it resolves. Redirects, titles, robots meta tags and caching headers were recorded in `data/discovery/start-urls.json`.

Two A-Z lists do still exist. The catalog's `/azindex/` is **disallowed by robots.txt**, so we skip it. IT's "A-Z Services & Software" (`technology.oregonstate.edu/services`) is in scope.

## 3. Domains

### Tier 1: all start URLs verified (HTTP 200)

Columns: **listed** = sitemap URLs; **in scope** = what the scope rules keep; **people** = PII pages skipped; **news** = Tier 3, skipped; **other** = sections outside student scope.

| Topic | Host | Start URL(s) | Listed | **In scope** | People | News | Other |
|---|---|---|---:|---:|---:|---:|---:|
| Registrar + academic calendar | registrar.oregonstate.edu | `/`, `/osu-academic-calendar` | 240 | **194** | 35 | 8 | 3 |
| Course catalog | catalog.oregonstate.edu | `/` | 1,929 | **1,023** | 1 | 0 | 905¹ |
| Advising | advising.oregonstate.edu | `/` | 38 | **32** | 3 | 2 | 1 |
| Financial aid | financialaid.oregonstate.edu | `/` | 136 | **124** | 10 | 2 | 0 |
| Billing (Student Accounts) | finance.oregonstate.edu | `/student-accounts` | 177 | **14** | 102 | 0 | 61² |
| Disability Access Services | ds.oregonstate.edu | `/` | 171 | **144** | 15 | 12 | 0 |
| Student life (Dean of Students) | studentlife.oregonstate.edu | `/` | 21 | **21** | 0 | 0 | 0 |
| Student conduct | scs.oregonstate.edu³ | `/` | 23 | **16** | 7 | 0 | 0 |
| Student health | studenthealth.oregonstate.edu | `/` | 57 | **57** | 0 | 0 | 0 |
| Counseling (CAPS) | counseling.oregonstate.edu | `/` | 137 | **67** | 60 | 10 | 0 |
| Housing & dining | uhds.oregonstate.edu | `/` | 208 | **191** | 0 | 17 | 0 |
| Library | library.oregonstate.edu | `/` | 249 | **130** | 87 | 31 | 1 |
| IT help | technology.oregonstate.edu | `/`, `/help-desks` | 122 | **102** | 0 | 17 | 3 |
| Engineering (student pages) | engineering.oregonstate.edu | `/academics`, `/student-life/...` | 2,240 | **326** | 810 | 802 | 302⁴ |
| Ecampus (student pages) | ecampus.oregonstate.edu | `/students/current/`, `/ask-ecampus/` | 1,785 | **393** | 6 | 861 | 525⁵ |
| Campus map | map.oregonstate.edu | `/` | 0 | **link only**⁶ | | | |
| **Total** | | | **7,533** | **2,834** | 1,136 | 1,762 | 1,801 |

1. Catalog `/miscadmin/<n>/`: 905 numbered sitemap entries. The one sampled returns **404**, so they're excluded.
2. Finance: only `/student-accounts`, `/student-resources` and `/emergency-loans`. Payroll, treasury and the other employee sections are out.
3. `scs.oregonstate.edu` serves pages, but its sitemap lists them under `sccs.oregonstate.edu`. The pilot will check which host is canonical.
4. Engineering: only `/academics`, `/student-life`, `/tools-services` and the department current-student sections (`/EECS/myeecs`, `/CCE/mycce`, `/MIME/mymime`, `/NSE/mynse`, `/CBEE/mycbee`). About 800 `/about/people` profiles and about 800 stories are skipped.
5. Ecampus: only `/students`, `/services`, `/soc`, `/tuition`, `/ask-ecampus`, `/forms` and `/contact`. The 411 `/online-degrees` marketing pages look like Tier 2 (admissions).
6. The map is a JavaScript app with no readable HTML, and its building data comes from an API. We store the URL and any `map.oregonstate.edu/?building=...` links that pages point to, nothing more.

### Proposed Tier 1 additions (need your OK)

All four are linked from OSU's Current Students hub and fit "student life", "advising" or "financial" support.

| Host | What | In scope |
|---|---|---:|
| success.oregonstate.edu | Academic Success Center (tutoring, study skills) | 69 |
| holds.oregonstate.edu | Holds @ OSU (what a registration hold means and how to clear it) | 2 |
| care.oregonstate.edu | Student Care (Dean of Students) | 8 |
| basicneeds.oregonstate.edu | Basic Needs Center (food, housing insecurity) | 9 |

### Tier 2: found, not counted yet

Their sitemaps get counted only after you approve Tier 2.

- **Admissions:** `admissions`, `gradschool`, `transfer`, `newstudents`, `internationalservices`, `intoosu`, `visitosu`
- **Clubs and organizations:** `clubs`, `asosu`, `gogreek`, `recsports`
- **Career services:** `experience.oregonstate.edu` (OSU Experience; the career pages live under `/career`)
- **Parking and transit:** not linked from any hub page we read. We'll report the host if Tier 1 pages link to it, rather than guess.
- **Other colleges:** `agsci`, `business`, `education`, `www.forestry`, `health`, `liberalarts`, `pharmacy`, `vetmed`, `science`, `ceoas`, `honors`; also `osucascades.edu` (separate domain), `portland`, `hmsc`
- **Other student services:** `veterans`, `summer`, `commencement`, `uesp`, `studentaffairs`, `ecampus /online-degrees`

### Tier 3: skipped unless you ask

`news`, `today`, `events`, plus every `/all-stories`, `/feature-story`, `/news`, `/stories`, `/events` and `/podcasts` section on Tier 1 hosts.

### Never crawled

| Host | Reason |
|---|---|
| canvas, my.oregonstate.edu, beaverhub, login, onid, outlook, Microsoft and Google sign-in | Login required |
| directory.oregonstate.edu | People directory (PII) |
| classes.oregonstate.edu | Blocked by bot protection |
| guides.library.oregonstate.edu | robots.txt bars AI crawlers |
| fa.oregonstate.edu | TLS failure |
| search.oregonstate.edu | Site search: a JavaScript app, and `/search/` is disallowed everywhere |

## 4. robots.txt and terms, in brief

Full version: [crawl-policy.md](crawl-policy.md).

- 20 Drupal hosts serve the **same standard Drupal robots.txt**. It blocks admin, search and login paths, has no crawl-delay, and has a `/sitemap.xml` that robots.txt doesn't list.
- Catalog disallows `/azindex/`, `/search/`, `/pdf/` and `/course-search/api`.
- LibGuides bars AI crawlers and sets crawl-delay 10. We skip it.
- `library.` and `map.` have no robots.txt.
- No OSU page prohibits crawling. The acceptable-use policy forbids circumventing security or degrading performance. The trademark policy rules out OSU names, logos and colors that imply affiliation.
- We obey robots.txt, use 2 s minimum gaps, stop on 403/429/challenge, never log in, never submit forms, and never call APIs.

## 5. Pilot (Phase 1): about 200 pages, three platforms

| Host | Platform | ~Pages | Why |
|---|---|---:|---|
| registrar.oregonstate.edu | Drupal (the template ~20 OSU sites share) | 80 | Academic calendar and deadlines (date extraction), forms, PDFs, policy pages |
| catalog.oregonstate.edu | CourseLeaf | 60 | Course descriptions, degree requirements, academic regulations. A very different template. |
| ecampus.oregonstate.edu | Custom static `.htm` + WordPress | 60 | Ask Ecampus FAQ pages (FAQ extraction), student services. No ETag or Last-Modified. |

Inside each host the pilot takes the homepage, then pages breadth-first by link depth, then a sample of the remaining sitemap sections, so every major template shows up. The pilot report will include:

- sample records and per-page extraction checks (title, breadcrumb, headings, main text vs. boilerplate)
- page-type and date-extraction precision, judged by hand on about 30 pages
- error, skip and blocked counts, plus anything surprising

## 6. Full Tier 1 crawl (Phase 2): order and timing

**Order** (most-asked student topics first, biggest last, so a stopped run still covers the essentials):

1. registrar
2. financialaid
3. finance (student accounts)
4. ds
5. studentlife
6. scs
7. studenthealth
8. counseling
9. uhds
10. advising
11. technology
12. library
13. ecampus
14. engineering
15. catalog
16. map (links only)

**Scheduling**
- One worker with **one request in flight at a time across all of OSU**.
- Round-robin between hosts: at least 2 s on any one host (from the end of the last response), and at least 0.5 s between any two requests overall. That keeps us at or below 2 requests/s even though most hosts sit on the same Drupal and Cloudflare infrastructure.
- About 3,200 requests (pages + PDFs) should take **about 60 to 90 minutes**. The catalog (1,023 pages × ~2.3 s ≈ 40 min) sets the lower bound.

**Resumable**
- Every URL is a `frontier` row with a state (`queued`, `fetched`, `not_modified`, `skipped`, `error`, `blocked`).
- A restart picks up the queued rows. `crawl_runs` and `fetch_log` record each run.

**Incremental re-crawls**
1. Drupal sitemaps carry `lastmod` for 99% of URLs, so a page whose `lastmod` is no newer than our `retrieved_at` isn't requested at all.
2. Otherwise, a conditional GET: `If-Modified-Since` (every Drupal host sends Last-Modified) and `If-None-Match` (Catalog and Engineering also send ETags). A 304 means unchanged.
3. Ecampus and map send neither header, so we compare hashes.
4. Drupal pages embed per-request tokens, so the raw-bytes hash changes on every fetch. A separate `text_hash` of the extracted main text decides whether the content really changed (`changed_at`).

## 7. Processing pipeline

**Discovery**
- Seeds are the start URLs plus in-scope sitemap URLs.
- We follow in-scope links found in a page's main content and its site navigation, up to depth 4, to catch pages the sitemaps miss.
- Links to other OSU hosts are recorded in `links` but only crawled if that host is in the approved tier.

**HTML extraction**
- trafilatura for the main text.
- lxml for title, `<link rel=canonical>`, `<html lang>`, breadcrumb (Drupal `nav.breadcrumb`, CourseLeaf `#breadcrumb`), and the h1–h4 heading tree with ids for deep links.
- Main menu structure for the navigation hierarchy.
- Contact blocks from the page footer.

**Owning office**
- The site name from the title suffix (e.g. "… | Office of the Registrar | Oregon State University"), checked against the per-host office in `scope.py`.

**Page type**
- Rule-based, with the signals stored so they can be reviewed:

| Type | Signals |
|---|---|
| policy | "policy", "code", "rights", "regulation", "standards" in URL, title or headings |
| how-to | "how to", "steps", numbered instructions, "apply", "request" |
| form | page contains a form, or links mainly to forms and PDFs |
| contact | "contact", "hours", "location", phone or address blocks |
| deadline/calendar | "deadline", "calendar", "dates", tables of dates |
| faq | "FAQ", question-shaped headings, accordions |
| news | news sections (normally skipped as Tier 3) |
| other | none of the above |

**Chunks**
- Split at h2/h3 boundaries into roughly 200–450-word pieces. Long sections break at paragraph boundaries with a one-sentence overlap.
- Tables stay whole where possible.
- Each chunk keeps its `heading_path` and nearest heading `anchor`, so answers can link to `page#section`.

**Documents**
- PDFs on `*.oregonstate.edu` that robots.txt allows are fetched (25 MB cap) and read with PyMuPDF.
- `fillable_pdf` = the PDF has form widgets. `needed_ocr` = no text layer.
- Web forms are recorded with their purpose and owner and **never submitted**. That covers on-page `<form>`s other than site search, plus links to Qualtrics, Adobe Sign, Microsoft or Google Forms and Drupal webforms.
- External form hosts are recorded, not fetched. Forms behind SSO become `login_required`.

**Dates**
- Regexes for month-day-year, numeric dates, "week N", weekdays and term names ("Winter 2027"), near words like "deadline", "last day" and "due".
- The registrar's calendar tables are parsed row by row.
- Everything is stored raw with its context sentence or row, and `date_iso` only when unambiguous, for human review.

**Links**
- Every `<a>` on fetched pages, with anchor text and region (main, nav, breadcrumb, sidebar, footer). This feeds the "most-linked" and "hub vs. leaf" analysis.

## 8. Database schema

Full DDL: [`osu_crawl/schema.sql`](../osu_crawl/schema.sql). It is validated, and FTS5 with porter stemming works (a search for "deadlines" matches "deadline"). The database will be `data/osu.sqlite` (gitignored).

| Table | Purpose |
|---|---|
| `pages` | url, canonical_url, domain, title, breadcrumb (JSON), headings (JSON tree), nav_path, main_text, language, last_modified, etag, retrieved_at, content_hash, text_hash, http_status, page_type (+signals), owning_office, template, meta_robots, raw_path, first_seen_at, changed_at |
| `chunks` + `chunks_fts` | page_id *or* document_id, seq, heading_path, anchor, text, token_estimate. FTS5 index kept in sync by triggers. |
| `documents` | PDFs and forms: url, title, purpose, kind (pdf / fillable_pdf / web_form / external_form / login_required), form_host, owning_office, found_on_page_id, hashes, page_count, needed_ocr, text |
| `links` | from_url, to_url, anchor_text, region, is_internal, nofollow |
| `dates` | page or document, context, date_text, date_iso, term, heading_path, reviewed |
| `frontier`, `crawl_runs`, `fetch_log` | Resumable crawl state and the request log |
| `skips`, `blocked_hosts` | Every skip with its reason (robots / noindex / login / pii / out_of_scope / tier3 / too_large), and hosts that refused us |

## 9. Structure map (after Phase 2)

`docs/structure-map.md` plus `docs/structure-map.json`. Both hold structure only (URLs, titles, counts), no page text. For each host:

- navigation hierarchy (main menu tree)
- major sections (first path segment, with page counts)
- page-type counts
- most-linked pages (in-degree from main-content links, so global menus don't dominate)
- hubs vs. leaves (out-degree to same-host content vs. text length)
- how forms are organized (by office, kind and the page that links them)
- common templates (Drupal content types, CourseLeaf page kinds, Ecampus layouts, by fingerprint)

## 10. Phase 0 counts

| | Count |
|---|---|
| Requests made | **110**, to 28 hosts, over about 6.5 minutes |
| Request breakdown | 95 × 200, 10 × 404 (sitemaps or robots missing, the old A-Z page, the sampled `/miscadmin/` URL), 3 redirects, 1 × 202 (**blocked**), 1 TLS error |
| Pages stored as dataset content | 0. Hub and terms pages were only read for links and policy text. |
| PDFs | 0. No sitemap lists PDFs; they'll be found through links. |
| Skipped for robots / PII | None fetched. Counted from sitemaps: 1,158 people pages (Tier 1 + proposed) and 30 `oregonstate.edu/human/` profiles. Catalog `/azindex/` and `/pdf/` are disallowed by robots.txt. |
| Blocked hosts | 1: `classes.oregonstate.edu` |
| Errors | 1: `fa.oregonstate.edu` TLS |

## 11. Open questions — decided

**2026-10-22: the owner approved the proposed default for each question below.** In short:
- Tier 1 includes the four additions.
- Engineering is limited to student sections.
- Ecampus excludes `/online-degrees`.
- The full catalog is in.
- The Schedule of Classes is link-only.
- `guides.library` is skipped.
- Cloudflare-hidden emails are not decoded.
- Page text is kept as published, with no individuals in structured fields.
- The app avoids OSU marks.
- OCR waits until scanned PDFs are counted.

Item 1 (contact email) is still pending.


1. **Your OSU email for the User-Agent.** Required before Phase 1. Phase 0 ran with "contact email not yet set".
2. **Approve the Tier 1 list?** Specifically:
   - the four proposed additions (success, holds, care, basicneeds)
   - Engineering limited to its student sections (~326 pages)
   - Ecampus without `/online-degrees`
   - the full catalog (all 1,023 course and program pages)
3. **Schedule of Classes is blocked.** The app can describe courses from the catalog and link to `classes.oregonstate.edu` for sections and times. Is that acceptable?
4. **Library guides.** OK to skip `guides.library.oregonstate.edu` because its robots.txt bars AI crawlers?
5. **Office emails are hidden by Cloudflare.** OSU's Drupal sites show every email, role mailboxes included, as "[email protected]" (Cloudflare email obfuscation). Decoding it would mean reversing an anti-scraping measure, so I propose **not** decoding it. The app would link to each office's contact page and keep phone numbers and office names. OK?
6. **Names inside ordinary page text** (e.g. "contact Jane Doe, 541-737-…"). I propose we keep page text as published so citations stay accurate, but never pull individuals into structured contact fields, and keep skipping people and listing pages. Or would you rather redact personal names and emails from the stored text?
7. **App name and look.** OSU's trademark rules claim its name, marks and color scheme. Pick a name without "OSU", "Oregon State" or "Beaver", or ask Trademark Licensing first? Either way the app should say clearly that it is not affiliated.
8. **OCR.** Tesseract isn't installed. I'll count scanned PDFs during the pilot and only ask you to install it if any show up.
