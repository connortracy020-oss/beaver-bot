# Answer layer

How a question becomes an answer with verified quotes, or a pointer to the right office. The default provider is
offline and only quotes the pages. A Claude provider exists and is locked until the owner turns it on
([site.md](site.md) says how; [model-test.md](model-test.md) has the first test results).

```
.venv\Scripts\python -m assistant.retrieve "How do I change a class to S/U grading?"     # top 5 chunks
.venv\Scripts\python -m assistant.answer "How do I change a class to S/U grading?"       # answer or refusal
.venv\Scripts\python -m assistant.answer --show-prompt "..."   # exactly what a model would be sent; calls nothing
```

## The pipeline (`assistant/answer.py`)

| Step | What happens | If it stops here |
|---|---|---|
| 1. Crisis | Words like "suicide" or "hurt myself" | OSU's crisis resources, quoted from the stored [Crisis Resources](https://counseling.oregonstate.edu/crisis-resources) page, plus "call 911". Always first, never a model. |
| 2. Guard | Rules for questions this assistant must not answer | A short explanation and where to go instead |
| 3. Retrieve | Top 5 chunks, keyword search ([retrieval-eval.md](retrieval-eval.md)) | If the best chunk has under half the question's search words: refusal |
| 4. Model | The provider gets the system prompt, the redacted question and the 5 chunks | — |
| 5. Verify | `assistant/verify.py` checks the model's quotes | Any failure: the answer is discarded and the student gets the refusal |

What the guard (step 2) declines:

| Kind | Example | Sends the student to |
|---|---|---|
| Own records | "What's my balance?", "what is my GPA" | the owning office (Student Accounts, the Registrar, Financial Aid). The assistant never asks for a login. |
| An individual's contact details | "my instructor's email" | the syllabus or Canvas, or the department office |
| Live data | "how many seats are left" | the live Schedule of Classes |
| Doing graded work | "write my essay for me" | the Writing Center and the Academic Success Center |

**The refusal message:** *"I couldn't find this in OSU's public pages. Here is the right office to contact:"*, then the
office for the question's category, from [categories.md](categories.md). The category comes from the top pages when
retrieval is good, otherwise from the question's own words. If nothing matches, the student gets the Office of the
Dean of Students.

## Answer format (what the model must return)

```json
{"status": "answered",
 "answer": "Submit the online Change of Grading Basis form; your advisor reviews it [1].",
 "citations": [{"chunk_id": 32171, "quote": "This starts the signature routing process to your academic advisor"}]}
```

- **No answer:** `"status": "not_found"` when the excerpts don't answer the question.
- **Citations:** `chunk_id` is the id shown in the prompt's `<chunk id="...">` tag. Each `quote` is copied exactly from that chunk; `...` may skip words.
- **Markers:** the answer cites with `[n]`, the citation's position in the list.
- **Layout marks** (added with the site, 2026-11-09): a line starting `+ ` is a step, `- ` a list item, `> ` a quote
  from the page, `## ` a small heading, and `**bold**` works. Steps are not numbered in the text: the verifier
  reads every number in an answer as a fact to check, so the page does the numbering.
- **Wording:** the system prompt asks for plain, direct answers and bans "guaranteed", "official" and "you should
  definitely" in the model's own words.

## The verifier (`assistant/verify.py`)

An answer is **discarded** when any of these holds:
- **Format:** the output isn't that JSON (a code fence around it is fine; prose around it is not), or the status isn't `answered`.
- **Citations:** there are none, the answer has no `[n]` markers, or a marker has no citation.
- **Unknown chunk:** a citation names a chunk the model wasn't given.
- **Quotes:** a quote is shorter than 8 characters, or isn't in its chunk. Whitespace, curly quotes, dashes and soft hyphens are normalized first; the words must match exactly.
- **Numbers:** an amount, date or phone number in the answer appears in none of the cited chunks. This catches a real quote paired with an invented "$900".

A citation that is never referenced in the text is **flagged**: the answer is still shown, and the flag is logged.

**What the verifier can't do:** it proves the quotes are on OSU's page, not that they answer the question.
- **Relevance:** judging that is the model's job (`not_found`) and the eval's.
- **The quote-only provider:** it has no such judgment. It quotes whatever overlaps the question, so "How do I reset my ONID password?" gets a link label instead of a refusal.

## Providers (`assistant/providers.py`)

The interface is one method, `complete(system, user) -> str`, plus `name` and `paid`. Nothing in the pipeline
depends on a vendor.

| Provider | What it is | Cost |
|---|---|---|
| `extractive` (default for `python -m assistant.answer`) | No model. Quotes the sentences that best match the question; always verifiable | free, offline |
| `guide` (default for the website) | No model. Lists matching rows of the academic calendar for date questions, a page's own steps for how-to questions, otherwise two or three exact quotes (`assistant/guide.py`) | free, offline |
| `anthropic` | Claude through Anthropic's Messages API, using the official SDK (`assistant/anthropic_provider.py`). Model from `ASSISTANT_MODEL`, default Claude Haiku 5.5 (the owner's choice, 2026-11-09). A declined request becomes "not found" | paid, locked |
| `scripted` | Canned outputs, for tests | free |

**What the website adds around the provider** (`beaverbot/answers.py`; the steps and the verifier are unchanged):
- **Calendar rows:** for a "when" question, the chunks of the Registrar's current academic calendar that hold the
  matching dates are put first, so any provider answers from the authoritative source.
- **A stricter relevance check:** each search word is weighted by how rare it is in the stored pages, and the best
  page must cover 60% of that weight. "Best pizza place in Portland" matched pages on "best" and "place"; now it
  gets the refusal.
- **Hand-checked answers** (`beaverbot/pinned.json`): written from the stored pages for the most common
  questions, re-verified on every use, and used first only when the provider is offline.
- **For a model only:** today's date (so "when is the deadline" means the next one), a request to answer in
  Spanish when the student wrote in Spanish (quotes stay in English), and a few wording rules. A model's answer
  that uses a banned word in its own sentences is discarded.

**On the website a model also runs the conversation** (`beaverbot/talk.py`, described in
[site.md](site.md#how-a-conversation-turn-works)). The steps above still hold, with these differences:
- **Crisis** is unchanged and still first: the keyword check, with no model. The model can also raise it for
  words the keyword list misses.
- **Guard:** live seat counts and a named person's contact details keep their fixed replies. "My balance" and
  requests for graded work go to the model, which says it can't see records (or declines the work) and then helps
  with the general how. A reply to a graded-work request that is long enough to be the work itself is replaced by
  the fixed reply.
- **Retrieve:** six chunks, plus the chunks on either side of the best one, plus up to two more searches worded
  by the model. A hand-checked answer for the question is shown to the model as a head start.
- **Verify:** an `answer` goes through the same verifier. A `chat` reply has no quotes, so it must state nothing
  about OSU: no new numbers, no web addresses, no names the student hasn't used. A failed reply is sent back
  once with the reasons, and never shown.
- **What leaves the machine** also includes the last eight messages of the conversation (redacted the same way
  as the question) and, in the demo, the made-up student's sample record.

To plug in a model:
1. Write a class with `name`, `paid = True` and `complete()`. Read its key from an environment variable inside the class.
2. Register it in `REGISTRY`.
3. Choose it with `ASSISTANT_PROVIDER=<name>`.

Guardrails:
- **Keys:** never in the repo, `crawler.toml`, or a command-line argument.
- **No-training APIs only:** OSU's robots.txt says `ai-train=no`. A provider is allowed only if its API terms don't train on the inputs we send ([crawl-policy.md](crawl-policy.md) §7).
- **Paid calls are locked:** `get_provider` refuses a paid provider unless the owner has set `ASSISTANT_ALLOW_PAID_CALLS=yes` in their own environment. Nothing in the repo sets it.
- **What leaves the machine:** only the prompt from `build_prompt()`:
  - public page text, which was already privacy-scrubbed at crawl time;
  - the student's question, with emails, phone numbers, SSN-shaped numbers, OSU ID numbers and other long digit strings replaced by placeholders. `--show-prompt` shows the exact text.
- **Not caught:** names a student types about themselves. The app UI should tell students not to include personal details.
- **Prompt injection:** the system prompt tells the model that chunk text is page content, not instructions. The verifier is the backstop: whatever the model does, only exact quotes from OSU pages reach the student.

## Tests

- **`tests/test_verifier.py`:** 23 fake model outputs: good answers, fabricated and paraphrased quotes, wrong chunks, invented numbers, broken JSON.
- **`tests/test_answer.py`:**
  - guard cases, plus policy questions that must *not* be declined ("Can my parents see my grades?");
  - the crisis path;
  - redaction, and what the model actually receives;
  - refusals on weak retrieval and failed verification;
  - the paid-call lock.

- **`tests/test_talk.py`:** the website's conversation step with a scripted model: each action, the check on
  chat replies, the retry, the searches, "I don't know", the fixed replies, and the demo tools.

None of them uses the network. Only a few in `test_talk.py` use the databases, and those are skipped when the
files are absent.
