# Tier 2b plan: the rest of Tier 2

The sites listed as Tier 2 in [crawl-plan.md](crawl-plan.md) that we haven't crawled yet. ("Tier 3" stays the name for
news and events, which we still skip.)

**Status: done 2026-10-29, and in the weekly re-crawl** ([tier2b-report.md](tier2b-report.md) §8). 4,155 pages
on 34 sites and 815 PDFs, with no rate limit. Three false-alarm stops paused it; the owner lifted the pause early.
Privacy rules were tightened during it (ASOSU, Honors, graduate student stories, rosters). Earlier steps: the pilot
([tier2b-pilot-report.md](tier2b-pilot-report.md)); discovery on 2026-10-29 (robots.txt with 42 requests, and
sitemaps for 36 sites).

All of these sites carry OSU's new content-signal robots.txt (`ai-train=no, use=reference`). The owner decided to
proceed under it ([crawl-policy.md](crawl-policy.md) §7). Our bot isn't named; `User-agent: *` allows `/`.

## 1. What the sitemaps list

36 sites list 51,418 URLs. 27,212 survive the crawler's existing rules: no people pages, no news or events, no
login links. Most of the rest are research, outreach and marketing, which the proposal below leaves out.

## 2. Proposal: about 3,900 pages

### A. Getting in and moving through (≈ 1,180 pages)

| Site | Pages | Rule |
|---|---:|---|
| admissions | ≈ 550 | Whole site. About 360 are the official transfer-credit tables for each community college ("does my class transfer?"). |
| graduate (sitemap uses the alias `gradschool`) | ≈ 170 | Whole site. The 5,105-entry people directory is already skipped. |
| transfer, internationalservices, intoosu, summer, honors | ≈ 420 | Whole site |
| commencement | ≈ 35 | Leave out past ceremonies (`/class-…`, `/ceremony-archive`, speaker pages) |

### B. Campus life, safety and support (≈ 1,100 pages)

| Site | Pages | Rule |
|---|---:|---|
| veterans, cape (survivor advocacy), familyresources (student parents), recsports, undergradresearch, policy (university policies) | ≈ 520 | Whole site |
| see (Student Experience & Engagement: cultural centers under `/dce`, civic engagement, craft center) | ≈ 120 | Leave out advisory-board minutes |
| eoa (discrimination and sexual-misconduct reporting) | ≈ 21 | Leave out `/annual-report`, `/workforce-insights` |
| publicsafety | ≈ 43 | Leave out `/osu-jobs` |
| coreeducation | ≈ 20 | Student pages, curriculum and articulation tables only; leave out faculty and implementation resources |
| asosu (student government), mu (Memorial Union), diversity | ≈ 200 | Leave out test pages, `/faculty-recruitment`, `/data` |
| clubs | 1 | **Changed after the pilot:** the main page only. Club pages were mostly unfinished templates, and some listed student officers by name ([tier2b-pilot-report.md](tier2b-pilot-report.md)) |

### C. The other colleges (≈ 1,650 pages)

business, liberalarts, health, agsci, education, ceoas, forestry, science, vetmed, pharmacy, math, integrative biology.

- **Kept:** only paths that read as student-facing: `undergraduate`, `graduate`, `academics`, `programs`, `advising`, `admissions`, `scholarships`, `students`, `majors`, `minors`, `internships`, `careers`, `faq`, `student-services` and similar.
- **Left out:** research, news, impact stories, blogs, faculty and people pages, alumni, giving, events.
- **Also left out:**
  - business continuing-education courses (225);
  - health's class-by-class PAC pages (the catalog has those courses);
  - internship "spotlight" stories;
  - agsci's extension and research stations;
  - vetmed's pet memorial and diagnostic lab.

### Not crawled

| Site | Why |
|---|---|
| leadership | President, provost and trustees (board actions, speeches): not student-facing |
| bee, dce, eecs, cce, gradschool | Redirects to agsci, see, engineering (already crawled) and graduate |

## 3. Cost and effect

- **Requests:** about 3,900 pages, plus their PDFs (estimated 300–600). That's about 4,500 requests: **about 4 hours at 3 s each**, run like Tier 2 with the all-of-OSU pause on any 429.
- **Weekly re-crawl:** grows to roughly double. Most pages get skipped on their sitemap date.
- **Search quality:** more pages compete for the top 5. After the crawl, the retrieval eval is re-run. If it drops, rules get tightened before anything else.

## 4. Steps

1. **Code (offline):**
   - the scope rules above in `osu_crawl/scope.py`, with a `tier2b-pilot` and a `tier2b` phase;
   - a generic alias rewrite for sitemap hosts (`gradschool` → `graduate`);
   - tests.
2. **Pilot, about 150 pages across all three groups.** Check: main content found, people and officer pages skipped, privacy audit 0, the retrieval eval unchanged or better. **Report, then stop for approval.**
3. **Full crawl,** about 4 h, after approval. Then categories, the structure map and the reports are rebuilt.

## 5. Decisions (owner)

- [x] Approve the pilot (step 2): approved 2026-10-29 with the defaults.
- [x] Approve the full crawl: approved 2026-10-29; run 6 paused with 1,934 pages left ([tier2b-report.md](tier2b-report.md) §6).
- [x] Clear the three false-alarm stops and resume after the pause ends: approved 2026-10-29; the owner then lifted the pause early the same day, `resume-tier2b` finished, and Tier 2b joined the weekly re-crawl.
- [x] Category mapping for the new sites: approved 2026-10-29 and applied ([tier2b-report.md](tier2b-report.md) §5).
