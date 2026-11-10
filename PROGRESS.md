# Progress

Independent student class project: an assistant that answers questions from Oregon State University's **public** web pages and always links to OSU's page. Not affiliated with OSU.
Built so far: the crawl, the structure map, categories, keyword retrieval with an eval, an answer layer with a quote verifier, and (2026-11-09) the whole Beaver Bot website with its demo layer. It runs free and offline by default; the owner approved Claude Haiku 5.5 for answers on 2026-11-09. Nothing behind a login is touched.

**Run the site:** `.venv\Scripts\python -m beaverbot` ([docs/site.md](docs/site.md)).

## Status

| Phase | State |
|---|---|
| 0. Plan | Done 2026-10-22. **Approved** with proposed defaults ([docs/crawl-plan.md](docs/crawl-plan.md) §11) |
| 1. Pilot (~200 pages: registrar, catalog, ecampus) | Done 2026-10-22. [docs/pilot-report.md](docs/pilot-report.md). Owner approved: resume registrar, keep archives, keep text, go to Phase 2 |
| 2. Full Tier 1 crawl | **Done 2026-10-22 23:44 UTC** (run 2). 3,048 pages, 410 PDFs, 1,707 documents/forms. [docs/phase2-report.md](docs/phase2-report.md) |
| Structure map | **Done.** [docs/structure-map.md](docs/structure-map.md) (summary), structure-map.generated.md (per site), structure-map.json |
| Batch 2, Step 1: privacy scrub | **Done 2026-10-23.** `privacy.py` added to the pipeline; 446 stored records scrubbed (1,057 personal emails, 409 direct phones; log `data/logs/scrub-20261023T041414.json`); `tests/test_privacy.py` |
| Batch 2, Step 2: verify | **Done.** PDFs chunked by detected headings (270/410); crawl logs show 0 × 429, 0 CDN/challenge pages, pacing ≥ 2 s per site; dates carry `authority` (155 authoritative / 482 archived / 3,765 mentions) with views `deadlines` and `date_mentions`; `link_only` table (2 scanned PDFs, map, Schedule of Classes) |
| Batch 2, Step 3: repo hygiene | **Done.** Contact moved to config only (`crawler.toml` / `OSU_CRAWLER_CONTACT`); README with the stay-private note; `docs/AI-USE.md`. Nothing pushed; no remote |
| Batch 2, Step 4: Tier 2 | **Done 2026-10-24 23:59 UTC** (run 4, `resume-tier2`, exit 0, 30.5 min). Tier 2 now holds 335 pages + 81 PDFs (+281 pages, +75 PDFs this run); 0 × 429/403/challenge; min gap 3.08 s between requests; privacy audit 0; 12 tests OK. [docs/tier2-report.md](docs/tier2-report.md). Pilot (run 3) was stopped by a rate limit: [docs/tier2-pilot-report.md](docs/tier2-pilot-report.md) |
| Batch 2, Step 5: categories and questions | **Done 2026-10-26.** [docs/categories.md](docs/categories.md): 11 categories with example question, main sources, contact office, and "no clear owner" lists. `page_categories` table (`python -m assistant.categories`). `owning_office` now names the office running the site, not a section label (337 pages fixed). [eval/questions.csv](eval/questions.csv): 30 synthetic questions (25 answerable, 5 to decline) |
| Batch 2, Step 6: retrieval | **Done 2026-10-26.** `python -m assistant.retrieve` (SQLite FTS5, BM25, titles weighted 3×, link-authority prior, PDFs × 0.8). Eval: **top 3 20/25 (80%), top 5 22/25 (88%)** ([docs/retrieval-eval.md](docs/retrieval-eval.md)). No embeddings; see open question 1 |
| Batch 2, Step 7: answer layer | **Done 2026-10-26, no paid calls.** Provider interface, offline `extractive` provider, answer JSON with chunk IDs and exact quotes, verifier, crisis path, guard, refusal path, question redaction ([docs/answer-layer.md](docs/answer-layer.md)). 23 verifier tests on fake outputs + 17 pipeline tests |
| Batch 2, Step 8: recrawl | **Done 2026-10-26 (not run, not scheduled).** `python -m osu_crawl.weekly [--dry-run]` ([docs/recrawl.md](docs/recrawl.md)). Dry run: ≤ ~1,430 requests, about 1.2 h at 3 s |
| Tier 2b (rest of Tier 2) | **Done 2026-10-29; in the weekly re-crawl.** 4,155 pages on 34 sites and 815 PDFs (647 with text). Run 6 paused on three false-alarm 403s (OSU's own "Access denied" page; check fixed); the owner lifted the project's 24 h pause early and the rest was fetched (3,166 requests, 0 × 429, min gap 3.03 s). Privacy: ASOSU minutes and member profiles, Honors showcase programs, thesis slides and student profiles, graduate student stories, rosters and award winners were removed and are out of scope (audit 0). [docs/tier2b-report.md](docs/tier2b-report.md) |
| Demo prototype | **Second draft 2026-11-09, approved by the team.** Scripted, one working question, no AI behind it. First draft kept as `demo/prototype-v1.html`; approved version is `demo/index.html`. Both are kept unchanged for the record |
| The website | **Built 2026-11-09** in `beaverbot/`: one command, no new dependencies, works with no internet. Conversation with streamed answers, numbered sources with "last checked", the "I don't know" path with the right office, the calm crisis path, helpful / not helpful, copy, share, save on this device, read aloud, report a wrong answer, next questions, Topics, Deadlines, Offices, Saved and About pages, Spanish, light and dark, text size and other accessibility settings, laptop and phone layouts, and the animated mascot. [docs/site.md](docs/site.md) |
| Offline answers | **Done.** A new offline provider (`assistant/guide.py`) answers date questions from the academic calendar's rows, how-to questions with the page's own steps, and the rest with exact quotes. Nine hand-checked answers in English and Spanish (`beaverbot/pinned.json`) cover the most common questions and are re-verified on every use. A stricter relevance check gives off-topic questions "I don't know" |
| Demo layer | **Built 2026-11-09.** Locked demo sign-in and two-step step, a "Sample data" banner, five made-up students, the 11 popups plus a BeaverHub tool finder, and the class finder conversation. Sample database `data/demo.db`: 8,435 catalog courses, 747 programs, 71,202 invented sections, rebuilt in about 6 seconds with a fixed seed. [docs/demo-build-plan.md](docs/demo-build-plan.md) |
| Model | **Claude Haiku 5.5 connected 2026-11-09 on the owner's instruction** (`assistant/anthropic_provider.py`, the official SDK, key from the `ANTHROPIC_API_KEY` environment variable, choice recorded in the gitignored `beaverbot.local.toml`). First test results: [docs/model-test.md](docs/model-test.md) |
| Conversation | **Reworked 2026-11-09 after the owner's feedback that it didn't feel like a conversation.** With the model connected, every message goes through `beaverbot/talk.py`: the model sees the last eight messages and chooses to talk, answer with quotes, search again, use a demo tool, or say it doesn't know. Chat replies may state nothing about OSU, answers still pass the quote verifier, and demo replies are worded from the tool's result. 58 test conversations in `eval/conversations.json`. [docs/site.md](docs/site.md) |
| Answer quality | **Search reworked 2026-11-09.** A 176-question test set in student wording (`eval/student-questions.csv`). An expected page in the top 5: 33% before, 61% now (topic ownership plus a local embedding model combined with keywords). With Haiku, 100 of 158 answers cite an expected page and 10 are graded wrong. A Brave Search backup limited to OSU's sites exists, off by default. [docs/answer-quality.md](docs/answer-quality.md) |
| Demo rebuild | **Rebuilt 2026-11-10 after the owner's review.** Server-side sessions with a redirect-style practice sign-in, a per-visitor sandbox, one adapter per connected system, and review-and-confirm with Undo and history for every change; every term's classes are editable. Security review findings fixed and tested. [docs/demo-build-plan.md](docs/demo-build-plan.md), [docs/osu-integration-and-security.md](docs/osu-integration-and-security.md) |
| Categories for Tier 2b | **Done 2026-10-29 (owner-approved).** 12 categories: new "Getting in: admissions, transfer & international" (898 pages); "Housing, dining & getting around" renamed "Housing, dining & campus life"; the rest of the new sites mapped into existing categories. Every Tier 2b page now has a primary category (before: 71% had none). [docs/categories.md](docs/categories.md) |
| Dedupe | **Done 2026-10-29.** `osu_crawl/dedupe.py`, run in every rebuild. Search now holds each duplicate once: 9 pages with identical text (Drupal "-0" copies, two paths to one page), 8 PDFs with identical bytes, and 2,221 boilerplate chunks repeated on 5 or more pages (mostly transfer-table legends and catalog option text). Records stay and get `duplicate_of`; data/raw is untouched. The search eval is unchanged. Afterwards "set" was added as a search stopword (like "get"); that fixed the payment-plan miss with no other question moving: **top 3 20/25, top 5 23/25** |

**Tests:** 272 pass (`python -m unittest discover -s tests -t .`): the 95 from before, 29 for the sample-database generator (`tests/test_demo_data.py`), 50 for the site (`tests/test_site.py`) 33 for the conversation step (`tests/test_talk.py`) 11 for the live backup and topic ownership (`tests/test_live.py`) 50 for the demo sign-in, sessions and changes (`tests/test_hub.py`) and 4 for the demo's Spanish (`tests/test_demo_spanish.py`). No network, no real logs touched, and no model calls: the model is tested separately with `python -m beaverbot.check`. Tests that need `data/` are skipped on a fresh clone.

## Before any request to OSU

- **Content signals (2026-10-29):** OSU's robots.txt now sets `ai-train=no, use=reference` on every site checked. The owner decided to proceed under them: no training on the data, reference-style quotes with links only, and only model APIs that don't train on inputs ([docs/crawl-policy.md](docs/crawl-policy.md) §7).
- **Tier 2 and Tier 2b are complete.** Don't re-run `resume-tier2` or `resume-tier2b`; they have nothing left to fetch. The scheduled task `resume-tier2b-crawl` is disabled. The first weekly re-crawl (now Tiers 1, 2 and 2b) still needs the owner's go-ahead; run `python -m osu_crawl.weekly --dry-run` first.
- **Blocked:** only `classes.oregonstate.edu` (bot protection). No pause is active; the owner lifted the false-alarm pause early on 2026-10-29 ([docs/crawl-policy.md](docs/crawl-policy.md) §8).
- **Pace:** the crawler keeps ≥ 3 s between any two OSU requests (`min_global_delay_s`) and pauses all of OSU for 24 h on any 429 or challenge. Never lower either.

## Changes to stored data on 2026-10-26 (offline, from saved pages)

- **Titles:** 238 Ask Ecampus answers were all titled "Ask Ecampus"; now "Ask Ecampus: <the question>". An inline `<style>` was removed from one title; soft hyphens were stripped from page text and joined back in PDF text (247 items re-extracted from `data/raw`).
- **Archived:** 3 old `[DRAFT]` calendars (2022–23) and 11 past-term calendar tabs (`/simple-tabs/fall-2019` … `winter-24-25`) are now flagged, so search and dates skip them.
- **Excluded:** two unpublished Drupal "Clone of …" registrar pages, plus site-index and style-guide pages, get no category and aren't returned by search.
- **New columns and tables:** `pages.gone_at` and `documents.gone_at` (set when a re-crawl gets 404/410); `page_categories`; `page_authority`.

## Changes to stored data on 2026-10-29 (offline, from saved pages)

- **Removed for privacy:** 765 PDFs and 138 pages that name individual students or list people ([docs/tier2b-report.md](docs/tier2b-report.md) §3). Every stored page was re-extracted under the new roster filters; 20 direct phone numbers were scrubbed.
- **data/raw:** the raw copies of those 765 PDFs were deleted along with them. The owner has since restated that data/raw is never deleted, so `prune-documents` and `reprocess` now leave it alone.
- **Categories and dedupe:** see the rows above. New columns: `pages.duplicate_of`, `documents.duplicate_of`.

## Open questions

1. **Embeddings:** keyword search hits 80% in the top 3 on the synthetic set. Of the misses:
   - two are vocabulary gaps ("counselor" vs. "counseling"; "credits to graduate" vs. AR 25);
   - one ranks a related page first ("food pantry").

   The synthetic questions favor keyword search because they were written from the pages. Proposal: decide after the survey's real questions are added. Add embeddings if real top 5 falls under ~80%. That needs a downloaded local model (~100 MB), so it needs your approval.
2. **Which model:** decided 2026-11-09: Claude Haiku 5.5, with the owner's key in the `ANTHROPIC_API_KEY` environment variable. The SDK is an optional dependency (`requirements-model.txt`). Still for the owner: confirm Anthropic's current API terms say inputs aren't used for training (the project's rule since OSU's `ai-train=no` signal), and set a spending limit on the key. Test spend so far is in [docs/model-test.md](docs/model-test.md).
3. **Real survey questions:** add them as `origin=real` after removing personal details. Should they be committed to the repo or kept local?
4. **Carried over:** career job-shadow-host pages (109), 52 skipped `.docx` templates, `data/raw` holds unscrubbed copies, and some skip-log and link-only URLs contain names in slugs ([docs/tier2-report.md](docs/tier2-report.md) §7).

5. **From the site build (2026-11-09):**
   - The team has final say on the design. Everything not in the build template was a judgment call, listed in [docs/site.md](docs/site.md).
   - "official" is a banned word, but OSU's own pages use it ("official transcript"). Beaver Bot never says it in its own words; an exact quote from OSU's page can still contain it. Is that the rule the team wants?
   - The demo layer (popups, class finder) is in English only. Spanish covers the interface, questions and answers.
   - "Biosphere" and "Connect" in the BeaverHub tool list have no description: the public pages don't say what they are.
   - The nine hand-checked answers in `beaverbot/pinned.json` were written by Claude from the stored pages. A person on the team should read them once.
   - Hosting isn't set up (private online link, public GitHub). The git history still holds personal emails, so the README's "keep this repository private" steps apply before publishing. Nothing from this build is committed.

## Next steps

- Owner and team: click through the site (`python -m beaverbot`), ask your own sample questions, and send design changes.
- Owner: review [docs/categories.md](docs/categories.md) and [eval/questions.csv](eval/questions.csv); add survey questions; decide on the open questions; approve (or not) the first weekly re-crawl.
- Then: mass question testing with `python -m beaverbot.check --eval` after the survey questions are in, and embeddings only if real questions need them.
- Before the demo: pick the five questions (the six on the home page all work), rehearse on the laptop with Wi-Fi off in offline mode, and decide who hosts the private link.
