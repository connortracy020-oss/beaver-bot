# Tier 2 plan

Status: **pilot approved and run 2026-10-23; stopped by OSU's rate limit** after 54 pages. See [tier2-pilot-report.md](tier2-pilot-report.md).
Graduate and admissions sites are left out, as asked. The same rules as Tier 1 apply: [crawl-policy.md](crawl-policy.md).

## 1. Domains

Each domain was found from links on OSU's own Tier 1 pages, then checked by fetching its robots.txt and home page.

| Topic | Host | Linked from Tier 1 | Home page (verified 200) | robots.txt | Sitemap URLs | **In scope** |
|---|---|---:|---|---|---:|---:|
| Scholarships | scholarships.oregonstate.edu | 301 links | "Scholarship Office" | standard Drupal | 13 | **13** |
| Food | food.oregonstate.edu | 291 | "Food @ OSU" (UHDS dining) | standard Drupal | 43 | **43** |
| Transportation and parking | transportation.oregonstate.edu | 48 | "Transportation Services" | standard Drupal | 86 | **79** |
| Writing center | writingcenter.oregonstate.edu (cwl.oregonstate.edu redirects here) | 98 | "Writing Center" | standard Drupal | 35 | **27** |
| Career services | career.oregonstate.edu | 71 | "Career Development Center" | standard Drupal | 109 | **72** |
| Career services (hub) | experience.oregonstate.edu `/career` only | — | "Career Advancement · OSU Experience" | standard Drupal | 6 | **1** |
| **Total** | | | | | **292** | **235** |

**Basic needs** is already covered by Tier 1 (`basicneeds.oregonstate.edu`, and Student Life's food-security pages). OSU has unpublished the older HSRC food pages, which return "Access denied".

## 2. robots.txt and terms

- **robots.txt:** all six hosts serve OSU's standard Drupal file. It has no crawl-delay (we use 2 s), names no bots, and adds no extra rules. Search, admin and login paths are disallowed.
- **Site terms:** two sites have their own terms pages. Both are terms for using a *service*, not the website, and neither restricts reading public pages:
  - `food /terms-and-conditions` covers Orange Cash (the ID-card spending account).
  - `transportation /terms-and-conditions` covers buying a parking permit (OSU Standard 07-025, refunds, payroll deduction).
  - `transportation /privacy-policy` says the site logs visitors' IP addresses for reporting. That's standard, and our User-Agent identifies us.
- **University-wide terms** are unchanged from Tier 1 (acceptable use 08-005, web disclaimer, trademarks).

## 3. Scope rules

Same shared rules as Tier 1. Staff and people pages, login pages and news/stories/events are never fetched.

| Host | Left out, besides the shared rules | Why |
|---|---|---|
| transportation | `/motorpool`, `/service-vehicle-permits` | departmental vehicle fleet, not student-facing |
| writingcenter | `/employment`, staff `/directory/*` (6) | jobs; people pages |
| career | `/employers`, `/faculty-staff-tools`, `/alumni`, `/hello-world`, `/work-in-progress`, `/directory/*` (18), `/all-stories` | other audiences; placeholder pages; people pages; news |
| experience | everything except `/career` | the rest is a general hub (`/halloween`, `/community`) |

**Sign-in portals and vendor tools.** These are recorded as links when pages link to them, and never fetched:
- parking permits: `aims.parking.oregonstate.edu` (sign-in, now on the login list)
- Handshake job listings (sign-in, now on the login list)
- Writing Center booking: `osuwritingcenter.as.me`
- shuttle tracker: `osushuttles.flexigo.com`
- career guides: `oregon-state.careercenterguides.com`
- the Qualtrics forms

## 4. Pilot (~150 pages), then the rest

| Host | Pilot pages | PDFs | Rest after the pilot |
|---|---:|---:|---:|
| scholarships | 13 (all) | 3 | 0 |
| writingcenter | 27–28 (all) | 3 | 0 |
| career | 45 | 4 | ~27 |
| transportation | 40 | 4 | ~39 |
| food | 23 | 1 | ~20 |
| experience `/career` | 1 | 0 | 0 |
| **Total** | **150** | **≤ 15** | **~85** + PDFs |

**How it runs:**
- **Commands:** the pilot is `python -m osu_crawl.crawl tier2-pilot`; the rest is `python -m osu_crawl.crawl tier2`, run after you've seen the pilot results.
- **Pacing:** one request at a time, at least 2 s per site; about 5 minutes for the pilot.
- **Same pipeline as Tier 1:** personal contacts are scrubbed before storage, PDFs are chunked by section, all dates are stored as raw mentions (none of these sites is authoritative), and the full 403/429/challenge rules apply.

**Pilot report** (same shape as the Tier 1 pilot):
- counts, errors, skips and blocks
- sample records
- extraction quality per template
- a privacy re-audit, which must find 0
- anything surprising

**Also queued:** Registrar `/commencement-faqs`. A bug in the news rule wrongly skipped it in Tier 1 ("/newstudent" and similar lookalikes were treated as news; now fixed). It will be fetched on the next `crawl tier1` run, which is one request.

## 5. Open questions

1. **Experience:** is `/career` alone right for `experience.oregonstate.edu`, or should its `/wellbeing` page come too?
2. **Career alumni pages** are left out as not current-student. Include them?
3. **Food:** most dining "menus" are probably loaded by JavaScript, so we'd get locations and hours but maybe not daily menus. The pilot will show how much is there.
