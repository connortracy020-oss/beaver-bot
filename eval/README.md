# Eval questions

`questions.csv` is the question set for retrieval and answer checks (`python -m assistant.eval_retrieval`).

| Column | Meaning |
|---|---|
| `question` | As a student would ask it |
| `category` | One of the 11 category ids in [docs/categories.md](../docs/categories.md): registration, dates, courses, paying, living, health, accessibility, support, rights, tech, ecampus |
| `expected_source_urls` | OSU pages that answer it, separated by ` \| `. Any one in the results counts as a hit. Leave empty when no page should be cited. |
| `expected_answer_notes` | What a correct answer says, with the facts to check |
| `should_refuse` | `yes` if the app must decline: the student's own records, an individual's contact details, live data, graded work, or no page answers it |
| `origin` | `synthetic` (written from the crawled pages, 2026-10-26) or `real` (from the student survey) |

**The 30 synthetic questions** were grounded by reading the stored pages directly, not through the retrieval
tool, so the eval doesn't grade the search with its own answers.

**Adding survey questions:**
- **Mark them:** set `origin` to `real`.
- **Remove personal details first:** names, emails, ID numbers, and anything a student wrote about their own situation.
- **Run them alone:** `python -m assistant.eval_retrieval --origin real` scores only those.

Real phrasing is the better test: the synthetic questions were written by someone who had read the pages.
