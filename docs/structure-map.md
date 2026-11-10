# How OSU organizes student information (structure map)

Built from the full Tier 1 crawl on 2026-10-22: 20 sites, 3,048 pages, 410 PDFs, 1,707 documents and forms, and 325,530 links.

- **Per-site detail** (menus, sections, most-linked pages, hubs, forms, templates): [structure-map.generated.md](structure-map.generated.md)
- **Machine-readable export:** [structure-map.json](structure-map.json)
- **Regenerate both:** `python -m osu_crawl.structure`

The map holds structure only: URLs, titles and counts.

## 1. The big picture

**OSU organizes by office, not by student task.** Each office runs its own site, on its own subdomain, with its own menu. A student question usually crosses several of them:

| Student task | Sites that hold the answer |
|---|---|
| "How much do I owe and when?" | finance (Student Accounts, billing, payment plans), financialaid (aid, costs), registrar (tuition refund deadlines in the calendar), ecampus (/tuition), uhds (room and board rates) |
| "How do I register / why can't I?" | registrar (registration, priority registration, calendar), holds (37 hold types), advising, catalog (requirements), ecampus (/soc), classes.oregonstate.edu (**blocked**, link only) |
| "I need help" | counseling (crisis, 24/7), studenthealth, care (Student Care), basicneeds, success (tutoring, coaching), ds (DAS) |
| "Where do I live/eat?" | uhds (housing options, apply, rates, dining) |

That points to **task-based categories for our app, with the office kept as metadata** (`owning_office` on every page and document). Every answer should still cite the office's own page.

## 2. How each kind of site is laid out

- **Audience menus.** DAS, Student Community Standards, Student Care and the Registrar split the top menu by audience: *Students / Faculty & Staff / Parents & Family / Community*. Our app can use audience as a filter, so a student isn't shown instructor guidance.
- **Process menus.**
  - Financial Aid walks through a process: *Getting Started, Financial Aid Process, Scholarships, Costs, Finding More Funds*.
  - UHDS walks through a decision: *Housing Options, Apply, Rates + Guides, Campus Living, Dining*.
- **Catalogs** (hub-heavy, deep):
  - The Academic Catalog is college, then department, then program (810 program pages under `/college-departments`), with courses by subject (167 subjects, one chunk per course).
  - IT is a *Services & Software* A–Z (53 services, 36 software pages).
  - Holds @ OSU is one hub with 37 hold pages.
  - Ask Ecampus is 18 category hubs over 237 Q&A answers.
- **Flat office sites.** Advising, Counseling, Student Health, Student Life, Basic Needs, Care, SCS and Finance are mostly leaf pages with few hubs. Most pages answer one thing, which suits section-level retrieval.

Hub vs. leaf counts by site are in the generated file. Overall: 83 hubs, and 2,159 leaf pages with real text and few links.

## 3. Where each kind of content lives

| Page type | Pages | Concentrated in |
|---|---|---|
| FAQ | 359 | Ecampus (241 Ask Ecampus answers), Engineering (42), Registrar (23), Technology (12) |
| How-to | 371 | Catalog (77; admission, degree-partnership and "how to apply" program pages), Engineering (62), Registrar (39), DAS (38), UHDS (32), Financial Aid (25) |
| Policy | 121 | Catalog regulations (43), Registrar (19), Engineering (15), DAS student handbook (13), Library (9), Student Health policies (8) |
| Deadline / calendar | 58 | **Registrar (38)**: the academic calendar and its archives. Every other office links to it (87 pages link to the calendar from their content). |
| Form hub | 45 | Registrar `/forms`, Financial Aid's file-location page (lists 100 documents), DAS Forms, Counseling "Waiting Room Forms" |
| Contact | 29 | UHDS (10), Student Health (6), Library (3) |
| Other | 2,065 | Mostly catalog program and course pages (894) and descriptive service pages |

**Dates have one source of truth.** The Registrar's academic calendar supplies 2,880 dated table rows (482 of them from archived past-year calendars, flagged). Other sites mention deadlines in passing (1,670 text rows, mostly "Week N" or "finals week" relative dates) and link back to the calendar.

## 4. How forms are organized

Forms are spread across many systems. No single OSU forms index covers them all:

| System | Forms found | Where |
|---|---|---|
| Qualtrics | 67 | everywhere: UHDS, Engineering, Counseling, DAS… |
| OSU sign-in forms (Banner/DocuSign on prodapps.isadm) | 27 | Registrar petitions and requests, Financial Aid |
| Google Forms | 27 | Engineering, Counseling, Student Care… |
| Microsoft Forms | 17 | Finance, Counseling, Engineering |
| Maxient (incident/conduct reporting) | 14 | Student Community Standards, Student Care |
| Fillable PDFs | 92 | **Financial Aid (69)**, Registrar (7), Advising (5) |
| On-page web forms (Drupal webform) | 27 | Library, Ecampus, Student Health |

Our app should have a **form finder** that ignores these systems. Index forms by office and purpose (`documents.purpose`, `owning_office`, `kind`), mark which need OSU sign-in (`login_required`), and link out. We never submit them.

## 5. Templates

- **19 Drupal sites share one theme ("Madrone").** The same building blocks recur: accordion sections (217 pages), simple tabs, and per-site content types (`hold`, `individual-service`, `software`, `student-handbook-page`, `microcredential`, `option`). One extractor covers them all.
- **The catalog runs on CourseLeaf:** `program` (746), `course-list` (229), `courselist-page`.
- **Ecampus has its own templates:** `ask-answer`, `htm-page`, `page`.
- **The campus map is a JavaScript app**, stored as a link only.

## 6. Cross-site links and gaps

- **Most-linked other OSU sites:**
  - the catalog (from Registrar 350×, Engineering 228×)
  - the Registrar (from almost every office)
  - `classes.oregonstate.edu`, the Schedule of Classes, linked from 332 pages. It is **blocked by bot protection**, so our app can only link to it.
- **Sites we didn't crawl that many pages point to.** These are Tier 2 candidates:
  - `graduate.oregonstate.edu` (192 links from Engineering)
  - `admissions.oregonstate.edu`
  - `scholarships.oregonstate.edu` (36 from Financial Aid)
  - `food.oregonstate.edu` (98 from UHDS)
  - `mysupport.oregonstate.edu` (117 from Technology; likely the IT ticket system)
  - `transportation.oregonstate.edu` (parking and transit; 20 from DAS)
  - `writingcenter.oregonstate.edu`
  - `see.oregonstate.edu`
  - `myhealth.oregonstate.edu` (patient portal, sign-in)
- **Dead ends:**
  - 44 content links point at pages OSU has unpublished. They answer with a themed "Access denied", for example Registrar `policies-and-regulations` and Finance `tuition-reduction-schedule`.
  - 92 links or sitemap entries return 404.

  The app should never send students to these.

## 7. A starting set of categories for our app

Task first, with audience and office as filters:

1. **Registration & classes**: registering, adding/dropping/withdrawing, holds, priority registration, overrides
2. **Dates & deadlines**: the academic calendar (current terms first; archived terms only on request)
3. **Courses & degree requirements**: catalog programs, courses, core education, academic regulations
4. **Paying for college**: tuition and fees, billing and payment plans, financial aid, scholarships, emergency funds, 1098-T
5. **Housing & dining**: options, applying, rates, move-in, dining plans
6. **Health, counseling & crisis**: Student Health, CAPS, 24/7 crisis resources, wellbeing
7. **Accessibility**: DAS accommodations, testing, the student handbook
8. **Support & success**: advising, tutoring and coaching, the Writing Center, the library, Basic Needs, Student Care
9. **Rights, conduct & policies**: Code of Student Conduct, academic integrity, FERPA and privacy, reporting
10. **Technology help**: accounts and passwords, Duo, software, where to get help
11. **Online (Ecampus) students**: audience filter over all of the above, plus the Ask Ecampus FAQ

Cross-cutting tools: **form finder** (section 4) and **who to contact** (office contact blocks, 42% of pages carry one).
