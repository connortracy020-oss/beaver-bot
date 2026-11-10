# Beaver Bot: how a connected version would work, and how it would stay safe

Beaver Bot is an independent student project. It is not affiliated with Oregon State University (OSU), and OSU has
not reviewed or agreed to anything in this document. This is a proposal for discussion.

## 1. Summary

Today Beaver Bot answers student questions from OSU's public web pages. It also has a demo of a signed-in version
that could show a student their own registration, bill, housing and more in one place, and help with simple tasks.
The demo uses made-up students and sample data only. This document describes how a real version would have to work
so that OSU's information technology (IT) and security staff can judge it. The demo was built to follow this design,
so most of what is described here can be seen working.

Three principles run through everything:

1. **Beaver Bot proposes, the student decides.** Nothing changes until the student reads a plain summary of the
   change and presses Confirm themselves.
2. **Records come from the system, not the AI model.** The artificial intelligence (AI) model writes sentences. The
   numbers, dates and class lists in each panel are read from the connected system by the server.
3. **Nothing is hidden.** Every panel says which system the information came from, whether it is sample data, and
   the time it was read.

## 2. The connected systems

Each system sits behind its own small connector (an adapter) with three jobs: read, plan a change, and carry out a
confirmed change. We have only seen these systems as a signed-in student sees them. We do not know what interfaces
they offer to other software. OSU IT would need to confirm that for each one.

Phases: **1** read-only, **2** planning (drafts that stay inside Beaver Bot), **3** confirmed actions.

| System | What Beaver Bot reads | What it could change, with the student's confirmation | Risk | What OSU would need to provide or confirm | Phase |
|---|---|---|---|---|---|
| Registration (Register for Classes) | Schedule, holds, when registration opens, credit totals | Phase 2: a plan and cart kept in Beaver Bot. Phase 3: register, drop, swap section, grading choice, withdraw | High: affects enrollment, aid and transcripts | Whether the registration system offers an interface for reading and for changes; which rules it enforces itself | 1, 2, then 3 |
| Advising (BeaverHub) | Advisor's name and office, open times, booked meetings | Book, move or cancel a meeting | Low: easy to reverse | Whether appointment times can be read and booked by another program | 1, then 3 |
| Degree audit (MyDegrees) | Progress, what is still needed, "what if I changed majors" | Nothing | Medium: grades are shown | Whether the audit can be read by another program, and how fresh it is | 1 |
| Billing (myBill) | Balance, due date, statements, payment plan status | Join a payment plan. Paying stays on the payment provider's own page | High: money | Whether balances can be read; whether plan sign-up can be offered or must stay a link | 1; plan sign-up in 3 only if approved |
| Housing (MyUHDS) | Room, mailbox number, maintenance requests | File or cancel a maintenance request | Medium: address and mailbox combination | Whether room details and requests can be read and filed by another program | 1, then 3 |
| ID card (MyCard) | Card status, balances, recent purchases | Nothing. Adding money stays on the card provider's page | Medium: spending history | Whether balances and activity can be read | 1 |
| Parking | Permits, vehicles, citations, permits for sale | Join or leave a waitlist; add or remove a vehicle. Buying and paying stay on the parking site | Low: little personal data | Whether the parking system offers any interface | 1, then 3 |
| Careers (Handshake) | Job listings, saved jobs, career appointments | Save a job; book or cancel career advising. Applying stays on the careers site | Low: nothing is sent to employers | Whether OSU's agreement allows another program to read or act | 1, then 3 |
| Library | Loans, requests, fines, room bookings | Book or cancel a study room | Low: easy to reverse | Whether the account and room booking can be reached by another program | 1, then 3 |
| Coursework (Canvas) | What is due and when | Nothing. It never submits work and does not read grades | Medium: course activity | Whether a read-only, per-student permission can be granted | 1 |
| Health, counseling and disability services | Only that an appointment or a letter exists, and where to see it | Nothing | High: the most private records | Whether even this much may be shown; the safe default is a plain link | 1, or links only |

**Payments.** Beaver Bot never shows a card or bank form. It shows a hand-off that says where the payment happens,
and the student pays on the payment provider's own page.

**The light-touch rule.** For health, counseling and disability services, Beaver Bot never shows a reason, a
diagnosis, notes or which accommodations someone has.

## 3. Sign-in, sessions, permissions and confirmations

**Sign-in.** OSU students sign in through OSU's single sign-on, which runs on Microsoft Entra. A real Beaver Bot
would send the student to OSU's own sign-in page and get back a one-time code (a standard flow called OpenID
Connect authorization code with Proof Key for Code Exchange, or PKCE). The student types their password and does
their two-step check on OSU's page only. Beaver Bot never sees a password.

The demo imitates that round trip. The student is sent to a separate practice page that says it is not OSU's. It
lists locked, made-up accounts and has no password field. The browser comes back with a one-time code that works
once, for one minute, and only for the browser that started the sign-in.

**Sessions.** After sign-in the server keeps the session. The browser holds only a random session id in a cookie
that page scripts cannot read (HttpOnly), that is sent only over a secure connection (Secure), and that other sites
cannot cause to be sent (SameSite=Strict). A new id is issued at every sign-in. The session ends after 20 minutes
without activity, with a warning two minutes before, and after 8 hours no matter what. Signing out deletes it on
the server.

**Permissions.**

- *Identity only from the session.* The server decides which student a request is about from the session. If a
  browser sends a student id, it is ignored.
- *Least privilege.* A real version would ask each system for the smallest permission that does the job, read-only
  wherever possible. In the demo, five systems are read-only and refuse any change.
- *Separate sandboxes.* In the demo every visitor gets their own copy of the sample data, so two people trying it
  never see each other's changes.

**Confirmations.** Every change follows the same path:

1. **Proposal.** The server works out what the change would do: what will happen, what will not change, warnings,
   and anything blocking it, with the reason and the next step.
2. **Review.** The student reads that summary. Nothing has changed yet.
3. **Single-use token.** The summary comes with a random confirmation token that lasts five minutes. The student's
   own click sends it back.
4. **The server carries it out.** It first re-runs the checks. If what would happen is no longer what the student
   read, the change is refused and the student is asked to review it again. The token is marked used before
   anything happens, so it cannot run twice, and each session makes one change at a time.
5. **History and undo.** The change is listed in a history. The latest change in each system can be undone where
   the real system would allow it. A withdrawal cannot.

Some changes need an extra "it's really me" approval first: withdrawing from a class, a drop that takes a student
below full-time (12 credits), and joining a payment plan. Showing the mailbox combination needs it too. The
approval lasts five minutes and covers one such change or one look at the combination. An Undo that would take a
student below full-time needs it as well. A real version would send the student back through OSU's
sign-in for a fresh two-step check. In the demo it is an Approve button.

## 4. How data moves

**Example A: "Add Vector Calculus to my winter plan."**

1. The browser sends the question. The session cookie goes with it. No student id is sent.
2. The server finds the session and reads the student's record from the registration connector.
3. The server sends the AI model the question, the recent conversation, short excerpts from public OSU pages, and a
   text summary of the record.
4. The model replies with a request: "add this class section." It cannot do anything else with it.
5. The server, not the model, turns that request into a proposal. It checks prerequisites, time conflicts, credit
   limits and holds.
6. The browser shows the proposal, marked as set up by Beaver Bot. The confirmation token goes to this screen only.
7. The student presses Confirm. The server checks the session, the anti-forgery token and the confirmation token,
   re-runs the checks, makes the change and records it in the history.

**Example B: "When is the last day to drop a class?"**

1. The browser sends the question.
2. The server searches its stored copy of OSU's public pages.
3. The model gets the question and those excerpts, and writes an answer with a link to the page.
4. No student record is needed, and nothing changes.

**What the AI model is and isn't sent.** It is sent the question, the conversation, page excerpts and, when signed
in, a summary of the student's record. It is never sent a session id, an anti-forgery token, a confirmation token
or a password. Text from pages and text from the student's record are both labeled as content, never instructions. The only thing the model can cause is a proposal, and in the demo only
five kinds: add a class to the plan, add several, remove one, book the advisor, cancel that meeting.

## 5. Risks and how they are handled

| Risk | What could happen | How it's prevented |
|---|---|---|
| Stolen password or phishing | Someone tricks a student into typing a password | Beaver Bot has no password field. Sign-in happens only on OSU's page, with OSU's two-step check |
| Session theft | Someone copies the session id and acts as the student | The cookie can't be read by scripts and is sent only over a secure connection; a new id at each sign-in; short time limits; extra approval for high-impact changes |
| Cross-site request forgery (CSRF) | Another website quietly sends a request as the student | SameSite=Strict cookie, a secret token required on every change, and requests from another site's address (Origin) are refused |
| One student seeing another's data | A changed id in a request shows someone else's record | Identity comes only from the session. Ids sent by the browser are ignored |
| The AI being tricked by text (prompt injection) | Text on a page or in a record says "drop all classes" and the model obeys | Such text is treated as untrusted. The model can only create a proposal, which the student sees and must confirm |
| The AI making a change by itself | The model acts without the student | The model never receives a confirmation token, so it cannot confirm anything |
| Replayed or double-submitted confirmation | A double click or a resent request runs a change twice | Each token works once, expires in five minutes, and is marked used before the change runs |
| Script injection in displayed text | Text typed into a form runs as code in the browser | The page builds text as text, never as code; a content security policy (CSP) allows scripts only from Beaver Bot itself |
| Clickjacking | The site is hidden inside another page to steal clicks | The site refuses to load inside a frame (frame-ancestors 'none') |
| Over-collection and logging | Student data piles up in logs or storage | The log holds only the method, path and status. No address, no question, no record. Records are read when needed and not stored |
| An idle shared computer | The next person at a lab computer finds an open session | Sign-out after 20 minutes idle, with a warning; an 8-hour hard limit; sign-out ends the session on the server |
| Brute force and abuse | Automated guessing or flooding | Per-minute limits on sign-in, questions, approvals and changes; long random ids and tokens; a cap on request size; the server answers only to its own address |
| AI vendor training on student data | Records end up in a vendor's training data | A written agreement with the vendor before any real data: no training on it, minimal retention |
| Sensitive details | Health, disability, pay, tax or a mailbox combination is exposed | Light-touch rule for health and disability; pay and tax records are not connected; the combination is random for each visitor and stays hidden until a fresh approval, which shows it once |

## 6. What OSU would need to provide

- **An application registration** with OSU's sign-in system, so Beaver Bot can use OSU's sign-in page.
- **Interface access for each system**, to be confirmed one by one. If a system has no suitable interface, Beaver
  Bot would show a link to it and nothing more.
- **An agreement with the AI vendor** that fits the Family Educational Rights and Privacy Act (FERPA): no training
  on student data and minimal retention.
- **A security review** by OSU's security staff before any real data is connected.
- **An accessibility review**, including screen reader and keyboard use.

**A suggested rollout.**

| Phase | What students get | What it needs |
|---|---|---|
| 0 (today) | Answers from public pages; a demo with sample data | Nothing from OSU |
| 1: read-only | Their own information in one place, from a few low-risk systems first | Sign-in registration, read access, the vendor agreement, both reviews |
| 2: planning | Drafts such as a class plan, kept in Beaver Bot. Nothing is written to OSU systems | A further review of how drafts are stored |
| 3: confirmed actions | Low-risk actions first (book a study room, book an advisor); registration last | Write access per system, a pilot with a small group, a way to turn it off quickly |

**What the student team would bring:** the working demo, the connector design, the tests, this document, and the
time to make the changes OSU's reviewers ask for. Hosting, support and long-term ownership would need to be agreed.

## 7. What the demo proves and what it doesn't

**It shows** that the design can be built and used: the sign-in round trip, server-side sessions, the
review-and-confirm step, the extra approval, history and undo, and plain explanations when something is blocked.

**It does not show** that any of this works with OSU's real systems.

- All data is made up. No real student record is used anywhere.
- No real system is connected. Each connector returns invented data in the shape we expect.
- The sign-in and the extra approval are simulated. No password, phone or code is involved.
- Sessions live in the memory of one small server and are lost when it restarts. A real version would need shared
  storage, an encrypted connection (HTTPS) set up by the host, and monitoring.
- The demo's limits on repeated requests are basic and count by network address.
- The security work was checked by the student team with an AI code review, which found eleven issues that were
  then fixed and given tests. It has not been reviewed by security professionals. We expect a real review to find
  things we missed.
