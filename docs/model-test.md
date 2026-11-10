# First test with a real model: Claude Haiku 5.5

**Date:** 2026-11-09. **Who decided:** the project owner chose Claude Haiku 5.5 and approved paid calls. The key
stays in the `ANTHROPIC_API_KEY` environment variable on the owner's laptop; it is in no file.

**How to repeat it:** `.venv\Scripts\python -m beaverbot.check --eval` (add `--show` to print every answer,
`--spanish` for the Spanish questions). Full answers from each run are saved under `data/logs/` (private).

## What was asked

- The 35 questions the site itself suggests (the six on the home page plus the Topics questions).
- The 30 questions in `eval/questions.csv`: 25 that the pages answer, 5 that the assistant must decline. Two
  overlap with the site's list, so one run is 63 questions.
- The same 35 site questions in Spanish.

All of these are synthetic questions written from the stored pages. Real student questions from the survey are
the better test and haven't been run yet.

## Results (final settings)

| | English, 63 questions | Spanish, 35 questions |
|---|---|---|
| Answered with verified quotes | 58 | 35 |
| Correctly declined (own records, a person's contact details, live seat counts, graded work) | 4 | not in this set |
| Missed: said "I couldn't find this" when a page has the answer | 1 ("How much does an official transcript cost?") | 0 |
| Answer or decline matched the eval's expectation | 26 of 28 | not scored |
| Cited one of the eval's expected pages | 20 of 23 answered | not scored |
| Time per question | median 2.3 s, slowest 13 s | median 2.9 s, slowest 12 s |
| Typical answer length | 55 words (longest 126) | similar |
| Estimated cost | $0.033 | $0.021 |

Everything spent on 2026-11-09, including the first run and the retries while tuning, comes to about **$0.10**
of the $10 budget. At this rate one answer costs about a twentieth of a cent.

The second eval mismatch is "How do I reset my ONID password?". The eval expects a decline because no stored
page is a good source. The model answered from a College of Business technology guide (a 2023 PDF) that does
describe the steps. The quotes are real; whether that PDF is the page a student should be sent to is a judgment
call for the team.

## What the first run showed, and what changed

The first run answered 48 of 63. Besides the 4 correct declines, 11 questions failed: 6 were rejected by the
verifier, 4 came back "not found", and 1 was discarded for a banned word. Six of the eleven were re-run with the
raw model output printed. What that showed, and the fix for each kind:

| Problem | Seen in | Fix |
|---|---|---|
| The model wrote a sentence before its answer object, so the verifier rejected the format | 3 of the 6 inspected (finals week, last day to withdraw, parking permit cost) | The request now asks the API for the answer format as structured output, and a stray sentence around it is dropped |
| A quote that wasn't word for word, and a marker numbered wrongly | 1 (applying for housing) | The model gets one more try, told exactly which check failed. If the second try isn't better, the answer is still discarded |
| The model used "official" in its own sentence | 1 (ordering a transcript) | "an official transcript" becomes "a transcript" in the model's own sentences. Quotes and OSU's own labels ("Order Official Transcript") are untouched. "guaranteed" and "you should definitely" still discard the answer |
| Search returned the wrong pages: "counselor" matched admissions counselors, not counseling | 1 (seeing a counselor) | A short list of extra search words for known gaps (counselor, credits to graduate, food pantry, Duo code) |
| A question the hand-checked answers cover came back "not found" | payment plan for tuition | With a model, the hand-checked answers are now a fallback: used only when the model can't answer |

After these changes the same 63 questions gave the results in the table above. The five failures that weren't
inspected one by one all answered on the second run except the transcript cost question.

Answers were also taking 6 to 11 seconds. Setting the model's effort to "low" brought the median to about 2
seconds with no drop in quality on this set.

## Conversations (added later on 2026-11-09)

The first version sent every message through search, so "hi" got an office to contact. The site now lets the
model lead each turn ([site.md](site.md#how-a-conversation-turn-works)). `python -m beaverbot.check --talk` plays
the conversations in `eval/conversations.json` and prints every reply.

| | Run of 57 conversations, 168 turns |
|---|---|
| Sourced answers | 62 |
| Plain chat replies (greetings, clarifying questions, what it can't do) | 52 |
| Demo tool replies | 44 |
| "I don't know" with an office | 8 |
| Crisis resources | 2 |
| Time per turn | median 2.3 s, slowest 13.8 s |
| Model calls and estimated cost | 202 calls, $0.16 |

What reading the replies changed: questions about "my GPA" get "I can't see that" plus the general how, with a
source; opinion and off-topic questions get a chat reply and not an office; the model is told facts about the
site so it can answer "do you save what I type?"; demo replies are worded from the tool's result. These later
changes were spot-checked on single conversations, not on a second full run.

Still weak: a question whose first search lands on one college's page is sometimes answered for that college
only, and one turn can use only one demo tool ("add that and the writing classes" adds the whole suggestion).

## Things to know

- **The verifier is doing its job.** Every answer shown has quotes that exist word for word on the cited OSU
  page, and every number in it appears on that page. It can't judge whether the page is the best source or
  whether the answer is complete.
- **Search is the limit now, not the model.** When the right page is in the top five results the model answers
  well. When it isn't, the model correctly says it can't find it, or answers from a weaker page (the ONID case).
  Real survey questions will show how often that happens.
- **Dates:** the model is told today's date and gets the academic calendar's rows first for "when" questions, so
  it gives the next upcoming date and names the term.
- **Spanish:** the model answers in Spanish from the English pages, and the quotes it relies on stay in English
  on the source cards.
- **Before relying on it:** the owner should confirm Anthropic's current API terms say inputs aren't used for
  training (the project's rule, because OSU's robots.txt says `ai-train=no`), and set a spending limit on the key.
- **To go back to free and offline:** change `provider` to `"guide"` in `beaverbot.local.toml`.
