# Answer quality: measuring and fixing search

**Date:** 2026-11-09. **Why:** the owner found that most answers were wrong or "I couldn't find it" even when the
answer was in our data. "What are the tiers to the meal plans at OSU?" got "I couldn't find", although Housing &
Dining's dining-plans page is stored with 2026-27 prices. The cause was search: it only matched exact words. The
student said "meal plan"; OSU's page says "dining plan".

## The test set

`eval/student-questions.csv`: 176 questions in everyday student wording, written without copying OSU's headlines.
158 have an answer in our data, each with the page or pages a careful person would send the student to (every URL
was checked to exist in the database). 18 are marked as not in our data. 39 are priority questions: the add/drop
deadline, payment plans, tutoring, dining plans and changing majors, several wordings each. An AI helper drafted
the set from the stored pages; nobody on the team has reviewed it yet.

```
.venv\Scripts\python -m beaverbot.evalset --variant all       # search only: free, offline
.venv\Scripts\python -m beaverbot.evalset --answers --grade   # the whole site with the configured model (paid)
```

## Search: is an expected page in the top results?

One search with the student's own words, 158 questions.

| Setting | Top 1 | Top 3 | Top 5 | Top 10 | Priority, top 5 |
|---|---|---|---|---|---|
| Before: keyword only | 12.7% | 22.2% | 32.9% | 44.9% | 30.8% |
| + OSU's wording for the topic added to the search | 13.3% | 25.9% | 34.2% | 47.5% | 41.0% |
| + pages on the owning office's site ranked first | 19.6% | 31.6% | 41.8% | 50.6% | 53.8% |
| + meaning-based search combined with keywords (now) | 31.0% | 52.5% | 60.8% | 73.4% | 66.7% |

On the older 25-question set (OSU's own wording) the top 1 / 3 / 5 went from 11 / 20 / 23 to 15 / 22 / 24 of 28.

## Answers: the whole site with Claude Haiku 5.5

Each question was asked once as a new conversation, using our database only (the live web backup is off in test
runs). Grades are by the same model comparing the reply with the test set's notes, so treat them as a guide.
"Partly" mostly means the reply was right but left out a detail the notes list, or answered for a narrower group.

| Run | What was on | Cites an expected page | Correct | Partly | Wrong | "I don't know" | Cost |
|---|---|---|---|---|---|---|---|
| 1 | search tool + owning office | 78 of 158 | not graded | | | 11 | $0.26 |
| 2 | + a search is required before giving up | 85 | 90 | 50 | 14 | 4 | $0.30 |
| 3 | + meaning-based search | 100 | 90 | 56 | 10 | 2 | $0.25 |

Priority questions (39): 15 correct in run 3. After the answer prompt was told to include the specifics a student
acts on, a re-run of those 39 only gave 20 correct, 15 partly and 4 wrong ($0.06). The full set was not re-run
after that last prompt change.

There is no answer run from before any change: the first full run already had the search tool and owning-office
ranking. The search table above is the before-and-after for search itself.

Of the 18 questions not in our data, run 3 declined 6, gave an answer judged fine for 9 (the topic turned out to
be covered on another office's page) and answered 3 wrongly.

## What changed

1. **The model searches for itself** (`beaverbot/talk.py`). It can put up to three wordings in one search and has
   four wordings per question, over our stored pages only. It must search at least once before saying it doesn't
   know. Crisis is still first and the quote verifier is unchanged.
2. **Topic ownership** (`assistant/owners.py`). 31 topics, each with the student wording that signals it, OSU's
   own words (added to the search), and the site of the office that owns it (its pages score double).
3. **Meaning-based search** (`assistant/semantic.py`). BAAI/bge-small-en-v1.5, free, run on this computer through
   fastembed. The 61,216 excerpts took about 45 minutes to embed on the laptop while other jobs were running. Only
   public page text and the question go into it, locally. Keyword and meaning rankings are merged by position.
   Without the index or the library, search stays keyword-only.
4. **The live web backup** (`beaverbot/live.py`, off by default). See below.
5. **Office cards.** "I don't know" shows the office for the question's own topic. A dining question shows
   University Housing & Dining Services only.

## The live web backup (Brave Search)

Used only when the model, after searching our pages, still says it can't find an answer.

- One search request goes to Brave with the redacted question plus `site:oregonstate.edu`. Nothing else about the
  student is sent. The key is read from `BRAVE_SEARCH_API_KEY` in the environment and is never written or logged.
- Results are dropped unless they are public `https://*.oregonstate.edu` pages: no login sites, people
  directories, `classes`, `guides.library`, rosters, profiles or minutes, and nothing our scope rules exclude.
- If we store the page, the answer uses our stored copy. If not, at most one page is read live through the
  crawler's own fetcher: our User-Agent, robots.txt, 3 seconds between requests to OSU, `blocked.json` and
  `cooldown.json` honoured, a stop on any 429 or challenge, and the privacy scrub on the text. Nothing is stored
  and no links are followed.
- The answer is labeled "Live search", and a page read live shows today's date as its checked date.
- Results are cached for a week. Searches are counted per month in `data/logs/brave-usage.json`. It stops at 90%
  of the monthly limit. Test runs force it off.
- **The limit:** Brave's pricing page (read 2026-11-09) does not show a 2,000-search free tier. It lists $5 per
  1,000 requests against a monthly free credit. The default limit is therefore 1,000 a month (stop at 900);
  change `brave_monthly_limit` in `beaverbot.local.toml` once the owner confirms what the account gives.
- **Tried once for real:** a search on fraternity and sorority recruitment returned 10 OSU results; the first was
  not stored and was read live after robots.txt, more than 3 seconds apart. Searches used so far: 1. It has not
  yet produced an answer on the site itself, because the test questions tried were answered from our own pages.

## Still weak

- Dates: asked in November, "the add/drop deadline" gets winter's date, and "next fall" was read as fall 2026.
- Answers sometimes come from a college's page when the owning office's page exists but ranks lower.
- Data gaps (no owning-office page stored): on-campus tuition rates, Fraternity & Sorority Life, Athletics
  tickets, study abroad, the bookstore. The Academic Success Center has no tutoring page of its own. Adding sites
  is a separate decision for the owner.
- The grader is a model. A person should read a sample of the "partly" answers.

## Subject questions and "answer first" (2026-11-10)

A student asked "where are the study rooms for math at osu" and got "Math-specific study rooms aren't listed on OSU's
pages, but the Valley Library…". The Mathematics and Statistics Learning Center page was stored the whole time.

- **Cause in search:** the words "study rooms" outweighed "math", so all of the first results were library pages.
  `assistant/owners.py` now has subject topics (math, chemistry, physics, CS and engineering). A question that names
  a subject and is about studying it or getting help pulls in that subject's help center and ranks it first. A
  question that only names the subject ("math placement test") is left alone.
- **Search before admitting a gap:** if an answer would say something wasn't found and no search ran that turn, it is
  sent back to search with other wordings first (`talk.py`, `GAP_RE`).
- **Answer first, no source talk:** the prompt now says to lead with the best answer and mention anything missing
  briefly at the end, in the student's words. A reply that mentions pages, a database or searching is sent back once
  for a rewrite (`SOURCE_TALK_RE`). The offline quotes mode now opens with "Here's what I found:".
- **Fallback:** when the model's answer fails its quote checks, the fallback now uses the student's own question and
  the first results, so it no longer swaps in an unrelated hand-checked answer.
- Five questions for this pattern were added to `eval/student-questions.csv`.

Checked by asking the math question three times in English and three in Spanish with Haiku: every model answer led
with the learning center and none mentioned sources. One English run before the last fix fell back to quotes. Answers
still vary from run to run in which details they include.
