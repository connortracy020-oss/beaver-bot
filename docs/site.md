# The Beaver Bot site

The website students use. It was built on 2026-11-09 from the team's build template and the approved mockup
(`demo/index.html`, kept unchanged). Beaver Bot is an independent student project, not affiliated with Oregon
State University.

## Run it

```
.venv\Scripts\python -m beaverbot
```

That one command starts the whole site at http://localhost:8765 and opens it in your browser. The first run also
builds the sample class database if it is missing (a few seconds). Ctrl+C stops it.

| What | Command |
|---|---|
| Run the site | `.venv\Scripts\python -m beaverbot` (`--port N`, `--host 0.0.0.0` to share on your network, `--no-open`) |
| Rebuild the sample class database | `.venv\Scripts\python -m beaverbot.demo.generate` (or `python -m beaverbot --rebuild-demo`) |
| Ask a batch of questions and see how they come out | `.venv\Scripts\python -m beaverbot.check` (`--eval`, `--spanish`, `--show`) |
| Play whole conversations and read every reply | `.venv\Scripts\python -m beaverbot.check --talk` (`--only "part of a name"`) |
| Tests | `.venv\Scripts\python -m unittest discover -s tests -t .` |

It needs no new dependencies: the server is Python's standard library, and the front end is plain HTML, CSS and
JavaScript with no build step and nothing loaded from another site. That is what lets the laptop backup run with
no internet.

## Choosing how answers are written

One line in `beaverbot.local.toml` (copy `beaverbot.example.toml`; the local file is gitignored):

| `provider` | What it does | Cost |
|---|---|---|
| `"guide"` (default) | Offline. Dates from the academic calendar, steps and direct quotes from OSU's pages, plus the hand-checked answers in `beaverbot/pinned.json` | free |
| `"anthropic"` | Claude writes the answer from the same page excerpts. Also needs `allow_paid_calls = "yes"`, the SDK (`pip install -r requirements-model.txt`) and the `ANTHROPIC_API_KEY` environment variable | paid |

The same settings can be given as environment variables (`ASSISTANT_PROVIDER`, `ASSISTANT_ALLOW_PAID_CALLS`,
`ASSISTANT_MODEL`, `ASSISTANT_EFFORT`), which win over the file. The key is only ever read from the environment.
On this laptop the owner chose Claude Haiku 5.5 on 2026-11-09 ([model-test.md](model-test.md)).

Whichever provider writes the answer, the order of steps and the checks are the same
([answer-layer.md](answer-layer.md)): crisis first, then the guard, then search, then the provider, then the
quote verifier. An answer that fails the verifier is never shown.

## How a conversation turn works

Every message goes through `beaverbot/talk.py`. The crisis keyword check runs first and never involves a model.
After that it depends on the provider.

**With a model (`"anthropic"`).** The model runs the conversation. It is given the last eight messages, the page
excerpts a search found for the new message, and (in the demo) the made-up student's sample record. It picks one
of six actions:

| Action | When | What the site checks before showing it |
|---|---|---|
| `answer` | The student wants something about OSU and the excerpts have it | Every quote must be on the cited page (the verifier), and the site's banned words must not appear |
| `search` | The excerpts are missing, off topic or about a special case | Runs another search with the model's wording, up to two times, and keeps what was already found |
| `chat` | Greetings, thanks, small talk, "what can you do", a complaint, a vague message, saying what it can't do | Must state nothing about OSU: no numbers the student didn't give, no web addresses, no names of offices, sites or programs the student hasn't used, no "OSU has/offers/requires" |
| `tool` | Signed in to the demo and asking about their own registration, advisor, plan, bill or degree | Runs one sample-data tool (`beaverbot/demo/intents.py`). The model then words the result as a reply to what the student said; it may use only numbers and names that are in the result or the sample record, or the tool's own fixed sentence is shown |
| `not_found` | A real question the pages don't answer | Shows the model's one sentence if it passes the `chat` check, then the right office |
| `crisis` | The student may be in danger, even if no keyword matched | Shows OSU's crisis resources, the same as the keyword check |

A reply that fails its check goes back to the model once, with the reasons. If the second try fails too, the
student gets exact quotes from the page, a hand-checked answer, or "I don't know" with an office. The unchecked
text is never shown. A turn costs one to four model calls.

A demo reply also carries a one-line summary of the card under it (which classes or times were shown). The
browser keeps that in the conversation it sends back, so "change the second one" or "is that based on my
classes?" can be answered.

Three more things help the model get it right. The excerpts on either side of the best search result come along,
so it sees the start of a rule and not only the middle. When a hand-checked answer exists for the question, the
model is shown it as a head start. And two replies stay fixed whatever the model would say: live seat counts, and
contact details for a named person.

**Without a model (the default), or when the model can't be reached.** Plain rules handle the turn: patterns for
greetings and thanks, the demo's wording patterns, then the offline answer pipeline. A short message that isn't a
question gets "tell me a little more" with suggestions, not an office. This is less flexible than a model, and it
is what keeps the site working with no internet.

**What is sent and kept.** The browser sends the last eight messages (700 characters each at most) with every new
message. The server removes emails, phone numbers and ID numbers from them, uses them for that one reply and
drops them. With a model connected they go to the model's API along with the page excerpts; in the demo the
made-up student's sample record goes too. Nothing real about a student is ever in that record.

`python -m beaverbot.check --talk` plays the conversations in `eval/conversations.json` (58 of them, 177 turns:
small talk, follow-ups, typos, Spanish, complaints, off-topic and trick messages, and the demo) and prints every
reply, so the whole set can be read before a demo.

**Search and the live backup** are described in [answer-quality.md](answer-quality.md): the model can search our
stored pages up to four ways per question, pages from the office that owns a topic rank first, and a local
embedding model adds meaning-based matches. A Brave search of OSU's own sites is the backup, off by default
(`live_search = "on"` in `beaverbot.local.toml`), and its answers are labeled "Live search".

## What is in it

| Part | Where | Notes |
|---|---|---|
| Conversation | `/` | Reads like texting. Orange bubbles on the right, Beaver Bot on the left, a thought bubble while it works, answers that stream in. It replies to greetings, thanks and vague messages like a person would, and remembers the last few messages. |
| Sources | under each answer | One numbered card per OSU page, with a short quote and "last checked". Citation chips in the text jump to the card. |
| "I don't know" | same | Says so, and names the office for that topic with a link. The mascot looks confused. |
| Crisis | same | OSU's crisis resources, quoted from the stored page, with call buttons. Calm colors, no animation. Always first, never a model. |
| Under an answer | same | Helpful / Not helpful, Copy, Share, Save, Read aloud, Report a wrong answer, and three questions to ask next. |
| Topics | `/topics` | The 12 categories, each with questions, OSU's most-linked pages and the office to contact. Also a small Topics menu in the question bar. |
| Deadlines | `/deadlines` | Dates from the Registrar's academic calendar only, with filters. |
| Offices | `/offices` | Every office the assistant refers students to. |
| Saved | `/saved` | Answers saved on this device (the browser's storage). No account. |
| About | `/about` | The not-affiliated notice, how answers work, privacy, and how the site is running. |
| Spanish | the ES button | The whole interface, the site's questions, and answers. Offline, answers have Spanish wording around quotes that stay in English; a model answers in Spanish. Links go to OSU's English pages. |
| Accessibility | the sliders button | Text size (4 steps), light / dark / match device, higher contrast, extra spacing, reduce motion, read aloud with speed. Saved on the device. |
| Demo layer | Sign in | Made-up students and invented classes. A side panel for each connected system (classes and registration for every term, advisor, degree progress, bill, housing, ID card, parking, jobs, library, coursework, health and access), each showing where its data comes from. See [demo-build-plan.md](demo-build-plan.md). |

## The mascot

The Beaver Bot logo, redrawn in the site palette so its parts can move (`beaverbot/static/js/mascot.js`).

| Mood | When | What it does |
|---|---|---|
| Resting | by default | Blinks now and then. Eyes follow the pointer. |
| Listening | while you type | Ears perk, antenna leans in, eyes watch the question box. |
| Thinking | while it searches | Looks up, one brow raised, the circuit lines run, a thought bubble shows the step. |
| Happy | an answer arrived | Smiling eyes and a small bounce. |
| Confused | it doesn't know | Head tilt, uneven brows, drooping antenna. |
| Calm | a crisis question | Steady and attentive. No bounce, no tracking, no sparkle. |
| Sleepy | left alone for 75 seconds on the home screen | Eyes closed, slow breathing, "z z z". Wakes when you come back. |
| Small reactions | thumbs up, thumbs down, a class added, a click | A wink, a sheepish droop, a hop with a few sparks, a surprised blink. |

With reduced motion on (the device setting or the site's own switch) the face still changes but nothing
animates, and the eyes stay still.

## Privacy and safety rules the site enforces

- **Nothing is saved**, except a rating or a report the student chose to send (`beaverbot/feedback.py`, stored in
  `data/feedback.sqlite`). A rating stores up or down, the day, the topic and the cited page links: not the
  question and nothing about who clicked. A report stores the question (with contact details and ID numbers
  removed), the answer and an optional note, and the dialog says so before sending.
- **Questions never appear in a URL** or in the server log. The log prints the method, the path and the status.
- **Students are warned not to type private details**, under the question bar and again when the text looks like
  an email, a phone number or an ID number.
- **The databases stay on the server.** Both are opened read-only, are never served as files (there are tests for
  this), and only short quotes and links leave.
- **No requests to OSU, with one owner-approved exception.** The site reads the stored pages only. The one module
  that can make a web request is the live backup (`beaverbot/live.py`), which is off by default and follows the
  crawler's rules; a test checks that no other module in `beaverbot/` can.
- **Banned words.** Beaver Bot's own wording never uses "guaranteed", "you should definitely" or "official"
  (tested on the site's text and on the hand-checked answers; a model's answer that uses one is discarded).
  A quote from OSU's page can contain them, because quotes are exact.
- **Demo sign-in** goes to a separate practice page with ready-made sample accounts and no password field. The
  session lives on the server; the browser holds only a cookie its scripts can't read. Every change is written
  out by the server, reviewed and confirmed by the student, and can be undone where a real system would allow.
  Each visitor gets their own copy of the sample data. See [osu-integration-and-security.md](osu-integration-and-security.md).

## Decisions made during the build

The team asked for these calls to be made and written down.

- **No framework.** A standard-library server and hand-written front end. Fewer moving parts, nothing to install,
  works offline, and free to host anywhere that runs Python.
- **The site wraps the existing pipeline** (`beaverbot/answers.py` calls `assistant.answer.answer`). It adds two
  things in front of the provider: calendar rows for date questions, and a stricter relevance check so an
  off-topic question gets "I don't know" instead of a loosely related quote.
- **An offline provider that reads well** (`assistant/guide.py`), because the old one could only return two raw
  quotes. It still only copies text, so everything it says passes the verifier.
- **Ten hand-checked answers** (`beaverbot/pinned.json`) for the most common questions, in English and Spanish.
  Each is re-verified against the stored page every time it is used, and dropped if the page no longer has the
  quote. Offline they are used first. With a model they are shown to the model as a head start and used as a
  fallback when its own answer fails the checks.
- **The model leads the conversation** (`beaverbot/talk.py`), because the first version treated every message as
  a search and answered "hi" with an office to contact. See "How a conversation turn works" above.
- **Answers are verified before they stream.** The words you see arriving have already passed the verifier.
- **Answer markup** is a few plain markers (`+ ` step, `- ` item, `> ` quote, `## ` heading, `**bold**`, `[n]`)
  that the page turns into elements itself. Page text or model output is never inserted as HTML.
- **Times New Roman** throughout, as the owner asked, made modern with size, spacing and layout.
- **The demo layer is English only** for now. Spanish covers the interface, questions and answers.
- **Sharing** copies the answer, its sources and a link that re-asks the question. Nothing is stored to share.

## Files

```
beaverbot/
  __main__.py      run the site
  server.py        HTTP server, routes, streaming
  talk.py          one conversation turn: talk, answer, search or use a demo tool
  demo/hub.py      demo sign-in, server-side sessions, proposals and their single-use tokens
  demo/systems.py  one adapter per connected system: read, plan a change, apply a confirmed change
  answers.py       the site pipeline around assistant/answer.py
  pinned.py/.json  hand-checked answers
  content.py       topics, deadlines, offices, the site's questions
  spanish.py       Spanish detection, glossary and fixed wording
  feedback.py      ratings and reports
  check.py         batch question testing
  config.py        settings
  demo/            sample data: schema.sql, generate.py, store.py, finder.py, audit.py, intents.py
  static/          index.html, css/, js/ (app, chat, render, mascot, pages, settings, i18n, ui, demo/)
assistant/guide.py               the offline provider
assistant/anthropic_provider.py  the Claude provider (paid, locked by default)
tests/test_site.py, tests/test_demo_data.py
```

## How it looks (design pass, 2026-11-10)

The team's choices stay: creamy orange, charcoal and cream, Times New Roman, the texting-style chat with the bar at
the bottom, and the logo. Everything else about the look was rebuilt around a few rules, written at the top of
`static/css/base.css`:

- **Paper, not boxes.** Surfaces sit on a grained cream page and are lifted with warm shadows instead of outlines.
- **One accent.** Orange is for the main action in view and for the mascot. Your own messages are charcoal.
- **Three kinds of control.** A solid button with an edge that presses down, an outlined button, and an underlined
  link. Only the suggestion chips are round. A status is a flat tag with a dot. "Sample data" is a rubber stamp.
- **Type does the work.** Large tight headlines, italics for Beaver Bot's own asides, small letter-spaced labels,
  and lined-up figures for money, credits and times.

What changed, and where it lives:

| Piece | What it is now | Files |
|---|---|---|
| Objects | The bill is a till receipt with a torn edge and dotted leaders. The ID card is a card that tilts. A parking permit is a hang tag with the zone letter. Advisor times are tear-off tabs. A review is a slip with a perforation above the button. | `static/css/look.css`, `static/js/hub/objects.js`, `briefs.js` |
| The plan | The week is the hero, in the team's colours, with each class row matched to its blocks by a swatch. A class can be dragged to another time to swap its section. | `static/js/hub/planner.js`, `demo/parts.js` |
| Motion | Rows and week blocks glide to their new places, credits count up, a confirmed change gets a stamp and a slip flies to "What I've done". All of it is off when reduced motion is on. | `planner.js`, `hub/core.js`, `look.css` |
| The mascot | It lives in the question bar: watches the pointer and the caret, holds an umbrella while searching and a pencil while writing, squints at a clash, dozes when idle, pops up on a new card, taps a changed row, builds a small dam while the chat is empty. It can be clicked, stroked, double-clicked for a tail slap, and dragged to a corner (arrow keys work too). On crisis answers and health, counselling and disability topics it stays still. | `static/js/buddy.js`, `mascot.js`, `static/css/buddy.css` |
| Layout | On a wide screen the connected sites are a desk beside the conversation that follows what is being talked about. A panel with several sections becomes tabs (arrow keys move between them). A tab on the question bar says what is being worked on. | `hub/core.js`, `hub/main.js`, `look.css` |

Nothing here imitates how an OSU page, card or permit looks: every object is Beaver Bot's own drawing.

**Not done or not checked:** the look has only been checked in the app's built-in browser, not on a real phone or in
Safari or Firefox. Animations could not be watched while they play in that browser, only their end states, so their
timing is untested by eye. No screen-reader pass. The mascot's dragging is pointer-only apart from the arrow keys.
