# Demo build plan

**Built on 2026-11-09.** The real site is in `beaverbot/` and is described in [site.md](site.md). This file is the
plan it was built from, with a section below on what was built and where it differs. Design choices come from the
team's build template.

## What was built (2026-11-09)

Run it with `.venv\Scripts\python -m beaverbot`, then press **Sign in**.

**Sign-in.** A Beaver Bot popup with `demo.student@example.com` and a dotted password already filled in. Both
fields are locked and are not password fields, so nothing real can be typed and the browser never offers to save
anything. **Continue** leads to a "Two-step verification" step with Approve and Deny, in Beaver Bot's own look.
Nothing is sent. A "Sample data. Demo: no real accounts." banner then stays under the top bar, with a student
switcher, a **Demo tools** menu and sign out. Demo changes live in that browser tab only.

**Five made-up students**, each built from a real catalog program and showing a different situation:

| Student | Program | What they show |
|---|---|---|
| Juniper Alder | Computer Science, sophomore | An advising hold blocks registration; nothing booked; 3 requirements left this year |
| Mateo Rivers | Business Administration, junior, transfer | Transfer credit ("Satisfied by"), a payment plan, an appointment to move, what-if Computer Science |
| Priya Cedar | Psychology, senior, Ecampus | A past-due balance blocks registration; online sections only |
| Devon Brook | Kinesiology, first-year | First registration, on campus, a hold that doesn't block |
| Tessa Fern | Mechanical Engineering, senior | 3 requirements left, and a D+ where the major needs a C: the confusing audit line |

**The 11 popups.** Each opens from the Demo tools menu, from a card in the conversation, or from another popup.

| # | Popup | Ask in the chat |
|---|---|---|
| 1 | The nudge after sign-in ("Registration opens Monday at 7:00 AM, but a hold is blocking you. Book your advisor?") and the Registration and holds popup | "When can I register?" |
| 2 | Advisor appointment: pick a time and it is booked; pick another and it moves, with no cancel-first | "Book my advisor" |
| 3 | Pre-registration checklist: holds, advisor, classes, time, each with its next step | "Am I ready to register?" |
| 4 | What I still need: the actual classes, whether each is offered in winter and whether prerequisites are covered | "What do I still need?" |
| 5 | What if I switched majors: type a program, see what already counts | "What if I switched to computer science?" |
| 6 | Winter plan: a clash-free term on a week grid, with the reason for each class, printable | "Build my winter plan" |
| 7 | Class finder: class, then times and days, then lecture and linked recitation pairs | "Find me a class", "I need MTH 254 in the morning" |
| 8 | My schedule: week grid, add and drop, and "Simulate registration" (blocked while a hold is active) | "Show my schedule" |
| 9 | Find a form: what it's for, who gets it, a preview filled with the sample student, a link to OSU's copy | "I need the form to change my grading basis" |
| 10 | Billing: balance, due date, and the one place to pay | "What's my balance?" |
| 11 | Degree checklist with a plain-language note on every line | "Explain my degree audit" |
| + | Find a BeaverHub tool: the Resources list in plain words, with the overlapping names grouped | "Where do I find my class schedule in BeaverHub?" |

Questions about OSU itself still go to the real answers and their sources while signed in, and a crisis question
always gets the crisis resources first. Signed out, "What's my balance?" gets the normal decline plus an offer to
see how it could work with sample data.

**The class finder** checks open seats, prerequisites (against the student's record), restrictions and clashes
with the classes already in the plan, and pairs each lecture with a linked section that also fits. It shows up
to three options that differ in time of day. If nothing fits it says so and shows the closest ones with what
doesn't match. "Add to my plan" changes only the sample schedule, with an undo.

**The database** (`data/demo.db`, 24 MB, built in about 6 seconds by `python -m beaverbot.demo.generate`, seed
20261109, same rows on every rebuild):

| | Rows |
|---|---:|
| Courses from the public catalog | 8,435 |
| Prerequisite rules | 7,332 |
| Programs (majors, minors, options, certificates) | 747 |
| Program requirements | 7,538 |
| Invented sections across Fall 2026, Winter 2027 and Spring 2027 | 71,202 |
| Linked recitation and lab pairs | 23,506 |
| Fictional instructors | 520 |
| BeaverHub tool names mapped | 123 |
| Forms with a public OSU link | 30 |

**Where it differs from the plan below.**
- Extra tables: `meta`, `requirement_courses` (the courses that satisfy each requirement), `advisor_slots`,
  `transactions` and `forms`. The schema is `beaverbot/demo/schema.sql`.
- Dates that should feel current (registration day, appointments, due dates) are stored as offsets and turned
  into real dates when served, so the demo reads correctly on whatever day it is shown.
- 100 of the 747 programs have no requirements, because their catalog pages have no course list table. Only 94
  programs have a sample plan, so "this year" is known for those. What-if lists only programs with requirements.
- Prerequisites are parsed simply (AND between groups, OR inside one), so a nested rule can read as met too easily.
- A class taken for the major also counts for the Core Education category it carries, as in the real audit.
- "Biosphere" and "Connect" have no plain-language description: the stored public pages don't say what they are.
- The demo layer is in English only.

## Rebuilt 2026-11-10: sign-in, sessions and every popup

The owner reviewed the first popups and said it was hard to know what they were doing, and that the classes Beaver
Bot gave for another term couldn't be edited. The demo layer was rebuilt around one rule: **Beaver Bot proposes, the
student decides.**

- **One source of truth.** The sample student's state lives on the server, in a sandbox that belongs to one visitor
  (`beaverbot/demo/hub.py`). The browser keeps none of it. Every panel and every chat answer reads the same store.
- **Sign-in the way a real version would work.** The browser goes to a separate practice sign-in page (Beaver Bot's
  own look, ready-made sample accounts, no password field) and comes back with a one-time code that is swapped for a
  server-side session. A real version would send students to OSU's own sign-in the same way.
- **One adapter per connected system** (`beaverbot/demo/systems.py`): registration, advising, degree progress,
  billing, housing, ID card, parking, careers, library, coursework, and health and access. Each returns sample data
  in the shape a real integration would, and names its source and as-of time.
- **Every change is reviewed first.** The server writes out what will happen, what won't change, warnings, and any
  block with its reason and next step. The student confirms; the result is shown with Undo and kept in a session
  history. A request made in chat arrives as the same review card. The model cannot confirm anything.
- **Every term is editable.** Fall (under way: withdraw or change grading until the deadline), Winter (plan, cart,
  register, drop) and Spring (plan). A class can be swapped to another section, given a different recitation or lab,
  moved to another term, switched between A-F and S/U, given different credits where the course allows, put in the
  cart, or removed. Classes show Planned, In cart, Registered, Waitlisted or Withdrawn, with a weekly calendar that
  marks clashes and credits against full-time (12) and the limit (19).
- **Cases handled with a reason and a next step:** holds, registration not open yet, missing prerequisites and
  corequisites, restricted sections, time conflicts, full sections and waitlists, required linked sections, the
  credit limit, duplicate courses, dropping below full-time, the withdrawal deadline and W grades, sold-out parking
  permits, low Dining Dollars, classes that fail when several are registered at once, an expired session, and
  network errors. Demo controls can jump to registration week and reset the sample data.
- **Payments** are only ever a hand-off to the payment site. There is no card or bank form anywhere.
- **Sensitive details:** health, counseling and disability services show only that something exists. The mailbox
  combination is hidden until a fresh approval and shown once.

Checked in a real browser at laptop and phone widths, in light and dark. Two independent AI reviews (security, and a
fresh-eyes read of the experience) found problems that were then fixed; the security ones each have a test in
`tests/test_hub.py`. How OSU could run this for real is in
[osu-integration-and-security.md](osu-integration-and-security.md).

**Spanish:** buttons and headings are translated in the page, and the sentences the server writes (reviews, block
reasons, results, notes) are translated by `beaverbot/demo/es.py` when the page is in Spanish. A test walks through
the demo and fails if any of about 400 sentences is left in English. Names of classes, people, buildings, forms and
OSU systems stay as those systems show them, and month abbreviations stay in English.

**Not done yet:** tabs and option groups work with Tab and Enter but not arrow keys. The
whole flow has not been tried with a screen reader.

## Second review, 2026-11-10: the schedule in the chat

The owner tried the demo as Juniper and reported four problems. All four were reproduced in a browser and fixed.

- **"Take a look at the card below", but no card.** Most replies had only a button under them. Now a suggested plan,
  the student's classes, and class finder results each get a real card written by the server
  (`beaverbot/demo/draft.py`, `chat_card`). For every other tool the model is told there is only a button, and a
  reply that mentions a card anyway is thrown out and the tool's own sentence is used (`talk.py`, `CARD_TOOLS`).
- **Scrolling.** The wheel only worked while the pointer was over the conversation itself, the keyboard didn't
  scroll at all, and a single short reply drew a scroll bar with nothing to scroll. Now the wheel moves the
  conversation from anywhere on the page, Page Up and Page Down work even from the question box, the arrow keys,
  Home and End work when nothing is being typed, and the empty scroll bar is gone (`chat.js`, `scrolling`). The
  practice sign-in page could not scroll on a short window; it can now.
- **Hard to read.** A review of several classes was one paragraph per class. Reviews and chat cards now show one
  row per class: code and name, a line for each meeting, credits, then a total and a week view
  (`systems.class_row`, `static/js/hub/rows.js`).
- **No clear way to edit.** The suggested schedule is now an editable list right in the chat
  (`static/js/hub/planner.js`). Every class has Swap section (other lectures, and the recitation or lab), Replace
  (other classes that meet the same requirement) and Remove, and there is an Add a class button with a search.
  Credits, the full-time and 19-credit marks, time clashes and the week view update after every edit. "Review and
  add to my plan" comes after editing and leads to the same review, confirm and undo as before. Typing "add them
  all" uses the list as edited, and that review card has its own "Edit this list first" button.

The list being edited is a draft held by the page, like a form. The server works out what it looks like each time
and changes nothing until the student confirms. Checked as Juniper in English and as Mateo in Spanish, in light
and dark, at laptop and phone widths.

**Not done yet:** the class finder's cards and "your classes" card point to the side panel for further editing
rather than being editable in place. Seat counts in the side panel are still English in Spanish mode. The
translations have not been read by a Spanish speaker.

## Third review, 2026-11-10: a card for every answer, and the plan as a working draft

- **A card under every connected-site answer.** The server only sent card data for three kinds of answer, so the
  rest showed a bare button while the reply said "see the card below". Every tool reply now carries a card read
  from the visitor's sandbox (`draft.chat_card`), drawn as a short version of that site's panel
  (`static/js/hub/briefs.js`). Housing, ID card, parking, careers, library, coursework and health and access can
  now be asked about in chat (read only). A test runs every tool for every sample student and fails if a reply
  has no card, or if the page has nothing to draw one with.
- **The suggested plan is a working draft kept on the server** with the rest of the visitor's sandbox
  (`draft.save`, `draft.edit`). The card's buttons and follow-ups in the chat edit the same list. "Swap chem for
  something earlier" lists that class's other sections, earliest first, each with "Swap in this one"; picking one
  (by button or by saying "use the 9:00 AM one") replaces that class and shows the whole plan again with the
  changed row marked and an Undo. A course can never be in the draft twice. An older plan card is marked "Older
  version" and can't be edited or confirmed.
- **Questions before the first plan.** A short multiple-choice panel in the chat asks about time of day, days,
  time between classes, credits, in person or online, and times to keep open. Every question can be left at "No
  preference", and "Skip, just build it" skips them all. The answers show as chips on the plan card; tapping them
  reopens the questions and rebuilds. When no open section fits, the card says which class bent and why. The
  class finder reuses the answers and doesn't ask again. Answers are kept by Beaver Bot in the session. In a real
  version they would be stored by Beaver Bot too, never written into a university system.

**Not done yet:** the same kind of questions for advisor booking, parking, dining, library rooms and careers.
"Time between classes" is checked and pointed out, but the plan is not rebuilt around it. "Times to keep open"
offers three set choices; anything typed under Other is kept as a note and not used to pick sections. When the
model's Spanish wording fails its checks, the fallback sentence is English.

## Fourth review, 2026-11-10: the sites agree with each other

An audit across all five sample students found places where the demo contradicted itself. Fixed:

- **The chat can ask for what the panels can.** Booking a study room, a maintenance request, a parking waitlist
  or vehicle, saving a job, a career appointment, the payment plan, registering, withdrawing and more are now chat
  tools (`beaverbot/demo/actions.py`). Words become the same change a button makes, then go through the same
  review, confirm and undo. Swapping a registered class's section, its linked section, its credits and moving it
  to another term stay panel-only on purpose.
- **One hand-off pattern.** Paying a bill, adding money to the ID card, buying a parking permit and applying to a
  job all work the same way: review, a line saying the real version opens the other site with it filled in, then
  a pretend step marked Sample data that updates the sample data and can be undone. There is no card or bank form.
- **One source for each fact.** Where a student lives decides housing, the room and dining lines on the bill, and
  which parking permit they can get (`systems.lives_on_campus`). The tuition line is built from the credits being
  taken. Card purchases only come from an account that had money, and an online student has none. Online
  students see a short note on parking, the library and the ID card.
- **Layout.** Nothing in a side panel can be wider than the panel; checked for every panel at 2000 pixels wide and
  at phone width.

`tests/test_consistency.py` checks all of this for every sample student, and fails if a panel gains an action the
chat has no tool for.

## The plan as written before the build

## Prototypes

Both are single HTML files that open in a browser. Their answers are scripted, with no AI or database behind them.
The one working question is "How do I set up a payment plan?" Its facts come from OSU's Payment Plans page and the
Academic Catalog, as crawled on 2026-10-22, and it links to both.

| Version | File | What it is |
|---|---|---|
| 1, first draft (2026-11-09) | [`demo/prototype-v1.html`](../demo/prototype-v1.html) | Homepage with the logo, question box at the top, popular questions, a grid of 12 topic buttons, and a separate answer page |
| 2, current (2026-11-09) | [`demo/index.html`](../demo/index.html) | One-screen chat with the question bar fixed at the bottom. Reads like a text conversation: the student's messages are bubbles on the right, Beaver Bot replies on the left |

**Team feedback on version 1:**

- It was hard to get around. The question bar should sit at the bottom so answers have the space above it.
- The topic grid took too much room and wasn't very helpful. It is now a small Topics menu in the question bar.
- Text should be Times New Roman, including answers.
- It should read like a texting conversation, the way ChatGPT does, in our own design.
- Drop the payment estimator.

## BeaverHub-style features (simulated)

The demo shows what a real, connected version could do. It uses a made-up student and never touches a real account.
OSU's own systems were looked at read-only on 2026-11-09 to learn their structure. No personal data was kept.

### Demo sign-in

1. "Sign in" opens a Beaver Bot popup with a demo account already filled in (`demo.student@example.com`). The fields
   are locked, so nobody can type a real password.
2. "Continue" opens a simulated two-step verification popup with an Approve button. It uses Beaver Bot's look and
   the words "two-step verification," never OSU's login page or Duo's name or logo.
3. The student lands signed in as the sample student. A "Demo: sample data, no real accounts" banner stays visible.

Nothing is sent or saved, and there is no real account system behind it.

### What BeaverHub and its connected tools contain

| Section | What it does |
|---|---|
| Home | Registration-time banner, week view with assignments, holds card, featured links |
| Success Team | Advisor cards and support offices; appointments are booked here |
| Appointments | Upcoming, past and cancelled; to reschedule you cancel first, then book again |
| Tasks | Assigned tasks and success plans |
| Academics | GPA, credits, standing, holds, links out |
| Finances | Balance, meal plan money, this term's transactions, links out |
| Resources | One long A-Z list with search and 9 filters (All, Favorites, Academic, Technology, Financial, Wellness, Transportation, Getting Involved, Accessibility) |
| Contact Support | Type, category, subject, description; suggests articles while you type |
| Registration | Separate older system: register, check status, search classes, view past schedules |
| MyDegrees Checklist | Requirement blocks marked done, in progress or "Still needed," with course popups |
| MyDegrees What-If | A long form showing how a different major would count |
| MyDegrees Planner | Term-by-term plans by the student or advisor, locked or unlocked |

### Pain points the popups should fix

- BeaverHub is mostly a list of links that send you to other systems, some asking you to sign in again.
- Resource names overlap. Class search appears as "Look Up Classes," "Course Search" and "Schedule of Classes:
  Scheduler." Billing appears as "Pay My Bill," "Student Billing," "View Student Account Information," "View Account
  Statements" and "Account Summary by Term."
- A hold says to talk to an advisor, but booking is on a different tab.
- Registration asks for a term before it tells you anything.
- "Still needed: see section" makes you scroll around instead of saying what to take next.
- The degree audit is a dated snapshot, and What-If takes a whole form for one question.
- GPA lines and red "not met" marks can look alarming with no explanation.

### Connected sites seen (read-only, structure only)

Looked at with the owner's sign-in on 2026-11-09 and 10, so the sample student's popups match the real layouts. No
personal data was kept, nothing was paid, booked, submitted or changed, and every number below is a layout detail,
not a real student's value.

**myBill (TouchNet).** Home: balance with Activity, Enroll in Payment Plan and Make Payment buttons, the latest eBill
(statement date and amount), a profile setup panel (authorized users, personal profile, payment profile, consents,
auto bill pay) and term balances. A long announcement covers bill dates, the due date, the $85 late fee on unpaid
balances over $500, card fees (3%, $3 minimum, none for eCheck) and refund timing. Account Activity: a balance, then
one expandable row per term, filterable by full history, since the last statement, or a date range, with Excel and PDF
export. Statements: statement date, due date, amount, View. Payment Plans: "not yet enrolled... Enroll Now."
Auto Bill Pay: pays each bill a set number of days before it's due, up to a chosen maximum, from a saved method.

**MyUHDS.** Cards for mailing address (with mailbox number and combination), room key and room assignment, services
(ResNet registration, maintenance request) and requests (housing disability accommodation, information release).
Sidebar: movie streaming, TV, Roompact, staff directory. Maintenance request form: urgent-issue warning with Public
Safety's number, "is this a network problem?", phone, receipt email, building (every residence and dining hall), area,
location, description, JPG/PNG photos up to 15 MB.

**MyCard (Transact).** Home: photo, Add Money, one card per account (OrangeCash, the dining plan) with Active and
available balance, then the last 30 days: pending, then posted transactions by date with location, time and amount.
Account details: available balance, credit limit, pending, account balance, transactions. Activity filter: last day,
week, month, three months, custom range. Credentials: the ID card, Active.

**Parking (AIMS).** Public tiles: buy a permit, visitor permit, claim a permit invitation, pay or appeal a citation,
bike map, parking maps, cart. Signed in: account number and balance, sidebar with Account, Vehicles, Tickets, Permits,
Fees, Wallet, and carpool create or join. Each page has an empty state ("no active permits", "no vehicles", "no unpaid
tickets") plus citation lookup by citation number or plate. Ordering lists permit types, each possibly "Sold Out - Join
Waiting List," with a zone note and a map link.

**Handshake.** Home: welcome, profile checklist (resume, profile, job preferences), career center (book appointment,
collections, events), "Top jobs for you" cards (employer, industry, title, pay, job type, location, posted date, Save),
suggested searches, career fairs, employer events with "going" counts, on-campus jobs, collections, guidance events.
Job page: apply-by date, Save, Share, Apply, at a glance (pay, location, type, dates, work authorization), description,
"you match some qualifications" by year and major, the employer, similar jobs. Appointments: Request appointment and
past appointments. Nav: Jobs, Career center, Inbox, Events, People, Employers, Feed, notifications.

**Library.** 1Search account: Overview, Loans, Requests, Fines + fees, Blocks + messages, Personal details, each with
an empty state. Study rooms (LibCal): pick a location, then search by time or by space with category, capacity (up to
6, 8 or 48), floor, date, from/until, accessible, monitor, window, and "View confirmed bookings."

**Canvas.** Dashboard of course cards with items due, a to-do list, calendar, inbox. The grade percentages and the
to-do ring seen there came from the owner's browser extension, not Canvas, so don't copy them as Canvas features.

**Register for Classes (Banner).** Pick a term from "Terms Open for Registration," then Continue. A term the student
can't register for yet returns only "Term not eligible for registration," with no reason: no mention of the hold or the
registration time. Beaver Bot should explain why in plain words. An open term shows four tabs: Cart (the student's
saved plan with each class's title, details, hours, CRN, schedule type, instructor, grade mode, View Sections and Add,
plus Add All), Find Classes (the class search), Enter CRNs (CRN boxes, "+ Add Another CRN," "Add to Summary") and
Schedule and Options (title, details, credit hours, CRN, schedule type, grade mode, level, date, status, message).
Below sits a weekly calendar of the schedule, and a Summary with each class's status ("Registered") and an Action
dropdown ("None" or "Withdraw Course"). Nothing changes until Submit. Totals line: registered hours, billing hours,
CEUs, minimum and maximum credits. A warning appears that a request won't be processed if credits drop below the
term minimum.

### Popups to build, all with sample data

1. "Registration opens Monday at 7 AM, but a hold is blocking you. Book your advisor?"
2. Book or reschedule an advisor appointment in one step, inside the chat.
3. A pre-registration checklist: holds cleared, advisor met, classes picked, time known.
4. "You have 3 requirements left this year. Here's what to take in winter."
5. "What if I switched to computer science?" answered in the chat, with no form.
6. "Build my winter plan," a simple term plan to bring to an advisor.
7. Class finder: pick a class, times and days, then see lecture and linked recitation pairs that fit.
8. Simulated add/drop on the sample schedule.
9. Find a form: the right form, what it's for, who it goes to, a preview filled with the sample student, and a link
   to OSU's copy. Nothing is ever submitted.
10. Billing: balance, due date, and the one right place to pay.
11. Plain-language notes on confusing audit lines.

### Resource names to map in plain language

Academic Advising, Academic Calendar, Academic Catalog, Academic Regulations, Academic Standing, Academic Success
Center, Academics for Student Athletes, Account Summary by Term, Advance Standing Report, Associated Students of
OSU, Athletic Events, Baccalaureate Core Courses, Basic Needs Center, Biosphere, Box, Canvas, Career Development
Center, Center for Advancing Financial Education, Center for Advocacy Prevention & Education, Fraternity & Sorority
Life, Change Credits, Change Grading Basis, Emergency Loan Eligibility, Check Your Registration Status, Clubs &
Organizations, Colleges and Departments, Collegiate Recovery, Commencement, Community Engagement & Leadership,
Connect, Cost of Attendance, Counseling & Psychological Services, Course Search, Craft Center, Cultural Resource
Centers, DAS Forms, DAS Testing Center, Degree Partnership Program, Direct Deposit, Directory, Disability Access
Services, Diversity & Cultural Engagement, Duo, Ecampus, Educational Opportunities Program, Emergency Loans, FERPA,
Final Exams, Financial Aid, Financial Aid Portal, Financial Literacy, Food@OSU, ONID, Google Drive, Graduation
Preparation, Handshake, Health Insurance, Holcomb Center for Military & Veteran Resources, Honors College Advising,
Library tutorials, guides, study rooms and workshops, Look Up Classes, Math & Statistics Learning Center, Math
Placement Test, Microsoft Office 365, My Class Schedule, My Profile, My Textbooks, MyDegrees, MyUHDS, Office of
Advocacy, International Services, Dean of Students, Registrar, On Campus Employment, Orange Cash, Order Official
Transcript, Oregon Residency Affidavits, OSU Alerts, Campus Map, OSU Email, Events Calendar, Parking &
Transportation, Pay My Bill, Petition for Late Change of Registration, Priority Registration, Public Safety,
Recreational Sports, Register/Add/Drop Classes, SafeRide, Schedule of Classes: Scheduler, ScholarDollars,
Scholarships, Service Desk, Student Financial Services Agreement, Software List, Enrollment Verification, Statement
of Degree, Student Billing, Student Care, Student Community Standards, Student Consent to Release, Student Health
Services, Student Jobs, Student Learning Experience Survey, Study Abroad, Tax Information, 1098T Forms, Third-Party
Billing, Transfer Credit Tools, TRiO, Tuition & Fee Tables, Tutoring Services, Planned Educational Leave,
Undergraduate Research, University Housing & Dining, University Ombuds, Unofficial Transcripts, Veterans tuition
forms, View Account Statements, Withdrawal from Term Survey, Workday, Writing Center, Zoom.

## Class finder with a dummy class database

A student says which class they need and what times suit them. Beaver Bot looks through a database of made-up class
sections and offers the ones that fit.

### Where the fields come from

The course facts are real and public. The sections are invented.

| Data | Source |
|---|---|
| Subject, number, title, credits, description, prerequisites, Ecampus availability | The public catalog pages already stored (about 8,000 course codes) |
| Majors, minors and their required courses | The public catalog program pages already stored |
| Term, CRN, section, seats, waitlist, days, times, campus, instructor, room | Generated. Never copied from OSU's live schedule |
| Student names, IDs, grades, holds, advisors | Made up. Nothing from a real student's account |

`classes.oregonstate.edu` stays blocked and is not a source.

### What real class data looks like (seen in MyDegrees, 2026-11-09)

The Course Information popup shows the course line, description and prerequisites, then one row per section:
term, CRN, section, seats open out of total, waitlist, meeting times, campus. The generator should copy these
general patterns only:

- **Section numbers show the campus:** 000-399 Corvallis, 400-499 Ecampus, 500-599 Cascades, 600-699 INTO.
- **Lectures:** large sections (about 45 to 150 seats), such as Mon/Wed/Fri 50 minutes or Tue/Thu 80 minutes.
- **Labs and recitations:** small sections (about 15 to 24 seats), often one 110-minute meeting on one day.
- **Start times:** spread through the day, from 8:30 am into the evening.
- **Ecampus sections:** meeting time "To be announced," about 75 seats.
- **Variable credits:** some courses list a range, such as "0 or 4" or "1-16."
- **Past and future terms:** past terms are view only.

The degree checklist has blocks (major, core education, upper-division), each with requirements. A requirement is
either met (course, title, grade, credits, term, and sometimes a "Satisfied by" transfer course), in progress, or
"Still needed: 1 Class in X," sometimes with a choice of courses.

### What the class search shows (seen in OSU's registration site, 2026-11-09)

This is the fullest view of a class, so the dummy data should match its fields.

**Search filters:** term (picked first), subject, course number or range, keyword (all words, any words, exact
phrase, without a word), attribute, campus, level, building, session, meeting days, start and end time, open
sections only.

**Results table, one row per section:** title, subject, course number, section, credits, CRN, term, instructor,
meeting days and times (shown as a week strip), instructional method, campus, seats open out of total, schedule
type, attributes, and a button for linked sections.

**Class details popup tabs:** class details (including grade mode), bookstore links, course description, attributes,
restrictions, instructor and meeting times (start and end dates, building, room), enrollment and waitlist,
corequisites, prerequisites, mutual exclusion, cross-listed courses, linked sections, fees, catalog link.

**Patterns to copy:**

- A lecture carries the credits. Its recitations or labs are separate 0-credit sections.
- Linked sections are listed as options, and a student must pick one with the lecture.
- Recitations often run hourly through an afternoon, about 35 seats each.
- Attributes mark what a class counts for, such as a Core Education category.
- Some sections have a course fee. Some list no instructor.
- One subject can be large: math alone had 306 sections in one term.

Register for Classes was not seen. It stopped at a sign-in screen, so the simulated add/drop flow is designed from
the page descriptions.

### Database

A separate file, `data/demo.db` (gitignored), so sample data never mixes with the crawled pages.

| Table | Holds |
|---|---|
| `courses` | Catalog facts for each course |
| `prerequisites` | Parsed course and minimum-grade rules, plus corequisites |
| `course_attributes` | What each course counts for, such as Core Education categories |
| `programs` | Majors and minors |
| `program_requirements` | Blocks, requirements and the courses that satisfy each |
| `terms` | Demo terms, with view-only flags |
| `sections` | CRN, section number, schedule type, instructional method, campus, session, credits, grade mode, instructor, seats, waitlist, fee, restrictions |
| `meetings` | Days, start and end times, start and end dates, building and room for each section |
| `linked_sections` | Which recitations or labs can be paired with each lecture |
| `students` | A handful of made-up students with different majors and situations |
| `student_courses` | Their completed, in-progress and planned classes |
| `student_holds`, `student_tasks`, `appointments`, `balances` | Sample BeaverHub-style data |
| `resources` | One plain-language entry per BeaverHub tool, with a link to where it lives |

Rough size: every course gets sections in each demo term, likely 50,000 to 100,000 section rows. SQLite handles
that easily. The generator uses a fixed random seed, so the data is the same on every rebuild.

### Conversation

1. Which class or requirement? A course code, a name ("calculus"), or "what do I still need?"
2. When? Morning, afternoon or evening, days to avoid, and on campus or online.
3. Beaver Bot filters sections by time, days, campus, open seats, prerequisites and restrictions, avoids conflicts
   with the student's other classes, and pairs each lecture with a linked lab or recitation that also fits.
4. It shows up to 3 options. If nothing fits, it says so and offers the closest ones.
5. "Add to my plan" changes only the sample student's demo schedule.

### Rules

- A "Sample data" label appears wherever dummy sections or student data show up. Times and seats are invented and
  must never be presented as OSU's real schedule.
- Answers about real policies still come from the public pages, with links to the official source.
- Nothing from a real student's account goes into the database, code, screenshots or test data.
- Instructor names are clearly fictional.
