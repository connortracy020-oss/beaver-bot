# Tier 2b full crawl report

Run 6 (`tier2b`), 2026-10-29, 08:37–13:20 UTC (283 min). Plan: [tier2b-plan.md](tier2b-plan.md). Pilot:
[tier2b-pilot-report.md](tier2b-pilot-report.md). Generated numbers: [tier2b-metrics.md](tier2b-metrics.md).

**Update, 2026-10-29 evening: finished** (section 8). The owner lifted the false-alarm pause early; the rest of the
queue was fetched with 0 × 429, and Tier 2b is now in the weekly re-crawl. Tier 2b now holds 4,155 pages on 34
sites and 815 PDFs (647 with text).

**Result of run 6's first part: two-thirds done, then paused by a false alarm.**
- **Polite:** no rate limit (0 × 429), and no two requests closer than 3.0 s.
- **Paused:** three sites answered one unpublished page each with OSU's own "Access denied" page. The crawler
  misread them as blocks: it stopped those sites, and one of them paused all of OSU for 24 hours (until
  2026-10-30 13:19:56 UTC). The check is fixed; the stops stay until the owner decides (section 6).
- **Privacy:** the new sites carry far more lists of named students than the pilot showed: ASOSU minutes and member
  profiles, Honors showcase programs and thesis slides, award recipients, rosters. They were removed and are now out
  of scope (section 3).
- **Owner's decisions (2026-10-29, evening):** resume after the pause and then add Tier 2b to the weekly re-crawl
  (scheduled, section 6); the category mapping is approved and applied (section 5); duplicates are set aside
  (section 7).

## 1. Requests

| | |
|---|---:|
| Requests | 4,912: 4,643 × 200, 218 redirects, 44 × 404, 3 × 403, 1 × 503, 3 network errors |
| 429, 202 or real challenge pages | **0** |
| Closest two requests (start to start) | **3.015 s** (none under 3 s; median 3.35 s) |
| Stops | 3, all false alarms (section 6) |

## 2. What was stored

| | Fetched (pilot + full crawl) | Kept after the privacy fixes | Still queued |
|---|---:|---:|---:|
| Pages | 3,401 on 34 sites | 3,264 | 1,934 on 33 sites |
| PDFs | 1,328 | 595 with text | (found as pages are fetched) |

The plan estimated about 3,860 pages. Links found more: admissions has 852 known pages (estimate 550), business 373
(estimate about 160). The queue is roughly 1,934 pages plus their PDFs, about 2 hours at 3 s.

## 3. Privacy findings and fixes

All fixes ran offline, from saved copies; no request was sent.

1. **ASOSU (student government).**
   - **PDFs:** 629 PDFs, almost all senate, house and committee minutes and agendas, bills, budgets, mediation votes, election results and voter guides. They name student senators and candidates and record how they voted.
   - **Pages:** the site root holds a profile page for each student-government member ("/first-last"), plus committee, judicial and senate-records pages.
   - **Fix:** ASOSU keeps only its student-facing sections (about, contact, get involved, units, student resources, advocacy, and the overview pages of student government) and only its governing PDFs (constitution, statutes, code of conduct, judicial policies, unit rules, operations manual). **627 PDFs and 70 pages removed.**
2. **Honors College.**
   - **PDFs:** 112 of them were mostly research-showcase and lightning-talk programs, students' own thesis slides (some named after the student), and alumni newsletters from 1996 on.
   - **Pages:** research-showcase and thesis-fair pages list every presenter.
   - **Fix:** Honors keeps only its guides for students and parents (brochures, new-student and parent sessions, thesis checklist and posters, pedagogy). **123 PDFs and 20 pages removed.**
3. **Rosters elsewhere.** Current-PhD-student and TA rosters, student profiles, award-recipient pages, graphic-design student-show pages, faculty and team listings, advisory-board minutes.
   - **Fix:** URL rules for these on every Tier 2b site, and new roster headings ("Past recipients", "Award winners", "Presenters", "Senators", "Student profiles") dropped at extraction on every site. Lines like "2025-2026 winners: …" under an award's description are dropped too; the description stays. Every stored page, Tier 1 and 2 included, was re-extracted from its saved copy (41 min).
   - **Total:** 138 pages removed: 70 ASOSU, 20 Honors, 48 elsewhere. That includes the library's staff-awards page (Tier 1), which is only a list of winners by year.
4. **Minutes, agendas, election results and showcase programs as PDFs on any site:** 15 more removed (diversity council agendas, a conference agenda, three SharePoint packet links).
5. **Direct phone numbers next to a person's name** that only showed up once text was split into chunks (veterans benefits pages, agsci transfer guides, a waiver form): 20 phone numbers replaced by the existing scrub (`python -m osu_crawl.privacy scrub`).

**Privacy audit after the fixes: 0** personal emails or direct phones. **Tests: 83 pass**, including new ones for the 403 check, the roster and document rules, and the winners-line filter.

- **Removed and how it stays removed:** removed PDFs' text and chunks are deleted from the database. Their URLs are marked `student_records` or out of scope, so no crawl or re-crawl fetches them again.
- **data/raw:** this first cleanup also deleted the 765 PDFs' raw copies. The owner has since restated that data/raw is never deleted; `prune-documents` and `reprocess` now leave it alone.
- **Still there:** names in ordinary page text (a professor in a program description) stay, under the owner's "keep page text as published" decision.

## 4. Search

The retrieval eval with all data rebuilt offline (categories, link authority, structure map):

| | Before Tier 2b | After the pilot | Now |
|---|---:|---:|---:|
| Top 3 | 20/25 | 21/25 | **20/25** |
| Top 5 | 22/25 | 22/25 | **22/25** |

- **Same as before Tier 2b overall,** with about 3,300 more pages competing.
- **Gained:** "Do first-year students have to live on campus?" (miss → rank 5).
- **Lost:** "How do I set up a payment plan for my tuition?" (rank 5 → miss). A graduate-fellowship FAQ ("set up … tuition … payments") and an admissions tuition section now outrank Student Accounts' payment-plan page.
- **Small moves:** "What is a proctored exam for an online class?" 1 → 3 (a College of Health advising page about Ecampus now ranks first); the vaccine question 1 → 2.
- **Payment-plan miss, diagnosed (2026-10-29, evening):**
  - **Data:** the expected pages are stored and intact. They ranked 7th (Student Billing) and 12th (Payment Plans).
  - **Cause:** the question's "set up" and "tuition" matched a graduate-fellowship FAQ for departments ("the appointment has been set up … tuition waiver payments"). The Payment Plans page never says "tuition".
  - **Fix:** "set" joined the search stopwords, next to "get" and "up". The question now ranks 5th, and no other question moved: **top 3 20/25, top 5 23/25**.
  - **Still open:** the vocabulary gap behind it is what embeddings would fix (PROGRESS open question 1). No other ranking change was made; tuning on 25 questions would overfit.

## 5. Category mapping (approved 2026-10-29 and applied)

Before the mapping, the new sites had no category rule, so 2,406 of their 3,401 pages (71%) got none. Now every
Tier 2b page has a primary category, and only 54 pages in the whole dataset have none (navigation pages excluded on purpose). Categories don't affect
search ranking; they decide which office to suggest when the assistant can't answer. The mapping:

| Category | New sites | Tier 2b pages (applied) |
|---|---|---:|
| **New: Getting in (admissions, transfer, international)** | admissions, transfer, intoosu, internationalservices; graduate's future-student pages; colleges' admissions pages | 898 |
| Courses & degree requirements | the 12 colleges (default), honors, coreeducation, undergradresearch, graduate (current students) | 1,438 |
| Housing, dining & getting around, **renamed "Housing, dining & campus life"** | recsports, mu, clubs, asosu, see (cultural centers, craft center), publicsafety | 370 |
| Support, success & careers | familyresources, veterans (non-benefit pages), colleges' advising, career and internship pages | 239 |
| Rights, conduct & policies | policy, eoa, diversity (bias response) | 197 |
| Paying for college | veterans' GI Bill and benefit pages, graduate funding, colleges' scholarship pages | 69 |
| Health, counseling & crisis | cape (survivor advocacy) | 27 |
| Registration & classes | summer, commencement | 26 |

- **Why a new category:** applying, transferring credit, and visa or immigration questions are their own student tasks. Without it they would fall under "courses" or nothing, and the suggested office would be wrong.
- **Contacts for it:** [Office of Admissions](https://admissions.oregonstate.edu/contact-information), [Transfer Students](https://transfer.oregonstate.edu/contact-us), [Office of International Services](https://internationalservices.oregonstate.edu/international-osu/contact-ois).
- **Applied:** `assistant/categories.py` (with `tests/test_categories.py`) and [categories.md](categories.md). The answer layer picks up the new contacts from the categories; its code is unchanged.
- **Also added:** new contacts for campus life (Recreational Sports, Public Safety), support (Family Resource Center, Military & Veteran Resources) and rights (EOA reporting). Two new "split across offices" topics: transfer credit and veterans' education benefits.

## 6. The three stops: approved to resume

| Site | Page | Why the crawler stopped | What it was |
|---|---|---|---|
| commencement | `/2021-commencement` | 403 body of 19,640 bytes, under the 20 KB floor | OSU's Drupal "Access denied" page |
| familyresources | `/about-us` | 403 body of 16,276 bytes, under the floor | OSU's Drupal "Access denied" page |
| pharmacy | `/student-experience/our-campuses` | the word "captcha" in the page, read as a challenge: **all of OSU paused for 24 h** | OSU's Drupal "Access denied \| OSU College of Pharmacy"; the word came from its cookie banner's reCAPTCHA entry. No Cloudflare markers |

- **Fix:** `osu_crawl/fetcher.py` now recognizes OSU's own access-denied page at any size, and a cookie banner naming
  reCAPTCHA is no longer a challenge. Real challenges still stop the site and pause OSU. Tests: `tests/test_forbidden.py`.
  Of the 34 refusals saved since 2026-10-22, only these three are classified differently.
- **Not done without the owner:** the three sites stay in `data/logs/blocked.json` and the pause stays in
  `data/logs/cooldown.json`. Nothing has been sent since 13:19:56 UTC.
- **Owner's decision (2026-10-29):** resume once the pause ends.
  - **Command:** `python -m osu_crawl.crawl resume-tier2b`, with tests in `tests/test_resume_tier2b.py`.
  - **What it does:** it refuses before the pause ends, below a 3 s pace, or while another crawl runs. It clears only
    these three stops, and only while each recorded block is that day's 403. It marks their three unpublished
    pages as skipped and resumes run 6. A new pause or block makes it stop with exit 5.
  - **Scheduled:** one run at 2026-10-30 6:21 am Pacific (task `resume-tier2b-crawl`). After a clean run, Tier 2b
    joins the weekly re-crawl, the data is rebuilt, the eval is re-run, and this report gets a "Resume" section.
  - **Checked:** run by hand on 2026-10-29, it refused ("22.6 h left") and changed nothing.

## 7. Dedupe (2026-10-29, offline)

`osu_crawl/dedupe.py` runs in every rebuild (`python -m osu_crawl.weekly --rebuild-only`) and on its own
(`python -m osu_crawl.dedupe [apply]`). It changes what search sees, not what is stored. It never touches data/raw.

| Kind | Found | What happens |
|---|---:|---|
| Pages with identical text (Drupal "-0" copies, two paths to one page, e.g. Core Education `/students` and `/students-0`) | 9 | The most-linked copy keeps its chunks; the rest get `duplicate_of` and leave search |
| PDFs with identical bytes under two URLs (re-uploads, a space vs `%20` spelling, a `//` in the path) | 8 | Same |
| Chunk texts on 5 or more pages (transfer-table legends on ~350 admissions pages, catalog option boilerplate, "Loading...") | 114 texts, 2,221 copies | Kept once, on the most-linked page |

- **Shared text on fewer than 5 pages stays everywhere.** There the page around it matters (one major's option requirements vs another's). That threshold would have removed about 18,000 chunks.
- **Not changed:** 111 pages with no main text: unfinished templates, test pages, web forms, and live widgets such as library hours. A check on 2026-10-29 found that the backup extractor gets only site menus from them. They have no chunks, so search never returns them.
- **Search eval after dedupe:** top 3 20/25, top 5 22/25, with no question moving.

## 8. Resume and finish (2026-10-29, afternoon)

The owner asked whether the 24-hour all-of-OSU pause was OSU's rule. It is the project's own (OSU's robots.txt and
terms set no such wait), and its trigger was a false alarm (section 6), so the owner lifted it early at 11:49 am
Pacific. The scheduled 6:21 am run was disabled. `resume-tier2b` cleared the three false stops and resumed.

| | |
|---|---:|
| Requests | 3,166: 2,095 × 200, 858 redirects, 152 × 404, 38 × 403, 4 × 503, 19 network errors |
| 429, 202 or real challenge pages | **0** |
| 403s | all OSU's own "Access denied" page; that URL skipped, no site blocked |
| Closest two requests (start to start) | **3.03 s** (median 3.39 s) |
| Blocked sites afterwards | only classes.oregonstate.edu (since 2026-10-22) |
| Queue afterwards | empty for Tier 2b (6 Tier 1 pages wait for the weekly re-crawl) |

**Stopped once for privacy.** At 1:57 pm Claude Code stopped the crawl: it was storing one page per named person.
Removed offline, made out of scope with tests (`osu_crawl/scope.py`, `tests/test_scope.py`), then resumed:

| Removed | |
|---|---:|
| Honors `/envoy/<name>`: a profile per graduating student | 100 pages |
| Graduate `/story`, `/story-page`, `stories-…`: a profile per student | 103 pages |
| Diversity `/state-inclusive-excellence/<name>` | 5 pages |
| Veterans Gold Star memorial name list (and 50 queued member pages, never fetched) | 1 page |
| A past commencement ceremony page | 1 page |
| Graduate students' project executive summaries and a sample student paper; dissertation abstracts | 4 PDFs |
| Direct phone numbers found by the privacy audit | 2 (audit 0 afterwards) |

A look at everything stored after the restart found no other lists of named people.

**After the rebuild:** dedupe set aside 10 pages and 9 PDFs; the retrieval eval is unchanged (top 3 20/25, top 5
23/25); 95 tests pass. The weekly re-crawl now covers 59 sites, at most ~3,190 requests (about 2.7 h at 3 s;
[recrawl.md](recrawl.md)). It is still not scheduled.
