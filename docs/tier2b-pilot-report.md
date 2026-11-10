# Tier 2b pilot report

Run 5 (`tier2b-pilot`), 2026-10-29, 08:01:46–08:12:02 UTC (10.2 min). Plan: [tier2b-plan.md](tier2b-plan.md).
Generated numbers: [tier2b-pilot-metrics.md](tier2b-pilot-metrics.md).

**Result: clean.**
- **Rate limits and blocks:** none.
- **Pace:** never under 3 s.
- **Privacy:** the audit finds 0 personal emails or phones.
- **Search:** no worse.

The pilot found officer lists and placeholder text. Both are now filtered on every site, old data included.
**The full crawl needs the owner's approval** (section 6).

## 1. Requests

| | |
|---|---:|
| Requests | 182: 160 × 200, 4 × 404, the rest redirects |
| 429, 403 or challenge pages | **0** |
| Closest two requests (start to start) | **3.07 s** (none under 3 s) |
| Redirects that led out of scope | 11, not followed (no request sent) |

The 11 out-of-scope redirects:
- 10 agsci department pages that redirect to their own sites (`bpp.`, `bee.oregonstate.edu`);
- graduate `/admissions`, which redirects to `gradadmissions.oregonstate.edu`.

## 2. What was stored

| | |
|---|---:|
| Pages fetched | 149 on 34 sites; main content found on 149 of 149 |
| Pages kept after the checks below | **135** (564 chunks) |
| PDFs | 8 (61 pages) |
| Forms recorded (never submitted) | 20 external, 4 web forms, 3 behind sign-in, 119 PDF links |

- **Sample titles:** "Military & Veteran Resources", "Financing Your Education", "Major, Minors and Options", "Tuition".
- **Generic titles:** a few department pages have titles like "UNDERGRADUATE" or "Frequently Asked Questions". Their section path and owning office still say whose they are.

## 3. Privacy findings and fixes

1. **Club pages list student officers by name.** For example, "KSA 2023-2024 Club Officers: President: …". And most club pages are unfinished templates (see 2).
   - **Fix:** `clubs.oregonstate.edu` now keeps only its main Student Organizations page. 9 club pages were removed.
2. **Placeholder text.** "Lorem ipsum" filler appeared on club pages, and also in 16 Tier 1 engineering chunks.
   - **Fix:** extraction now drops it on every site. 29 chunks are gone.
3. **Rosters of named people inside pages.** Examples: ASOSU's student advisory board, the Residence Hall Association's "Meet the team" (Tier 1), an engineering staff list (Tier 1).
   - **Fix:** extraction now drops sections headed like a roster: "Officers", "Meet the team", "Staff directory", "Executive board", "Committee members". Student-advisory-board pages are out of scope on the new sites.
   - **Result:** affected pages on all tiers were re-extracted from their saved copies, no new requests. The example names are gone.
   - **Still there:** names that appear in ordinary page text, such as a professor mentioned in a program description, stay, under the owner's earlier "keep page text as published" decision.
4. **Empty pages.** Drupal `/group/<id>` pages had no content and are now out of scope.

Privacy audit after the fixes: **0** personal emails or direct phones. Tests: 76 pass, including new ones for these filters.

## 4. Search

The retrieval eval after the pilot, with categories and link authority rebuilt offline:

| | Before | After |
|---|---:|---:|
| Top 3 | 20/25 | **21/25** |
| Top 5 | 22/25 | 22/25 |

- **Working already:** "How do I use my GI Bill benefits?" finds the Registrar's VA FAQ and Ecampus answers.
- **Not yet:** "What do I need to keep my F-1 visa status?" finds nothing useful. The pilot fetched only 6 international-services pages; the full crawl adds about 90.

## 5. Other changes from the pilot

- **Office names:** confirmed from each site's own name (e.g. "Office of Graduate Education", "Military & Veteran Resources", "University Policies and Standards").
- **Start page:** business's `/student-life` start page was a 404; it's replaced.
- **Not in scope yet:** graduate admissions lives on its own site, `gradadmissions.oregonstate.edu`. It's a candidate for later.

## 6. The full crawl: decision needed

- **Size:** about **3,860 pages** (the plan's 4,040, minus the club pages) plus their PDFs. That's about 4,300 requests, **about 4 hours** at 3 s, with the all-of-OSU pause on any 429.
- **After it:**
  - Tier 2b joins the weekly re-crawl.
  - The new sites get mapped to categories. Admissions, transfer, international and graduate pages don't fit the 11 categories cleanly; I'll propose a mapping.
  - The eval is re-run.
- **Command, once approved:** `.venv\Scripts\python -m osu_crawl.crawl tier2b`. It is resumable; Ctrl+C is safe.
