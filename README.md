# Beaver Bot (OSU campus assistant)

An independent student class project, **not affiliated with Oregon State University**. It collects OSU's *public* web
pages and answers student questions from them, always linking back to OSU's page. Nothing behind a login is
collected, no forms are submitted, and no OSU logos or styling are copied.

## Run the site

```
.venv\Scripts\python -m beaverbot
```

One command runs the whole site at http://localhost:8765. It builds the sample class database on the first run.
To rebuild that database: `.venv\Scripts\python -m beaverbot.demo.generate`. Everything about the site, including
how to switch between the free offline mode and a model, is in [docs/site.md](docs/site.md).

**Where things stand:** see [PROGRESS.md](PROGRESS.md). Key docs:
- [docs/site.md](docs/site.md): the website, how to run it, what it does, the rules it enforces
- [docs/demo-build-plan.md](docs/demo-build-plan.md): the demo layer (made-up students, sample classes, 11 popups)
- [docs/model-test.md](docs/model-test.md): how the answers tested with a real model
- [docs/crawl-policy.md](docs/crawl-policy.md): robots.txt, OSU terms, and the rules the crawler enforces
- [docs/structure-map.md](docs/structure-map.md): how OSU organizes student information
- [docs/phase2-report.md](docs/phase2-report.md): the Tier 1 crawl
- [docs/categories.md](docs/categories.md): the 12 task-based categories, their main sources and offices
- [docs/retrieval-eval.md](docs/retrieval-eval.md): how well search finds the right page
- [docs/answer-layer.md](docs/answer-layer.md): answers with verified quotes, refusals, model interface
- [docs/recrawl.md](docs/recrawl.md): the weekly re-crawl
- [docs/AI-USE.md](docs/AI-USE.md): which parts are AI-assisted

## ⚠️ Keep this repository private

The git history contains personal contact details:

- the maintainer's OSU email, in the crawler's User-Agent string quoted in the first commit's docs;
- the maintainer's personal email, as the git author on every commit.

Today the contact address lives only in the gitignored `crawler.toml`. The generated reports write `<contact_email>` instead.

Before making the repo public:
1. Start a fresh history from a clean tree (or rewrite this one).
2. Commit with a GitHub `noreply` address.
3. Change the contact if you no longer want it shared.

The crawled dataset (`data/`) must never be published in any case.

## Setup

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy crawler.example.toml crawler.toml
```

Then set `contact_email` in `crawler.toml`, or set the `OSU_CRAWLER_CONTACT` environment variable. The crawler refuses to run without a contact, because it is sent in the User-Agent so OSU's web admins can reach a person.

## Commands

| What | Command |
|---|---|
| Read robots.txt / count sitemaps / check URLs (Phase 0) | `python -m osu_crawl.discover robots|sitemaps|verify|links|text ...` |
| Crawl a phase (resumable; Ctrl+C is safe) | `python -m osu_crawl.crawl pilot` · `python -m osu_crawl.crawl tier1` |
| Weekly re-crawl: sitemaps, changed pages, rebuild (run by hand, never scheduled; [docs/recrawl.md](docs/recrawl.md)) | `python -m osu_crawl.weekly --dry-run` · `python -m osu_crawl.weekly` |
| Re-extract stored pages from saved copies (no requests) | `python -m osu_crawl.crawl reprocess <phase> <state> <url LIKE> [page|document]` |
| Drop stored PDFs that are records about named students (no requests; data/raw is kept) | `python -m osu_crawl.crawl prune-documents` |
| Set aside duplicate pages, PDFs and boilerplate chunks (no requests; also part of every rebuild) | `python -m osu_crawl.dedupe` · `python -m osu_crawl.dedupe apply` |
| Finish Tier 2b after the 2026-10-29 pause (owner-approved; refuses before the pause ends) | `python -m osu_crawl.crawl resume-tier2b` |
| Status of the queue | `python -m osu_crawl.crawl status` |
| Metrics report for a run | `python -m osu_crawl.report <phase>` |
| Structure map | `python -m osu_crawl.structure` |
| Personal-contact audit / scrub | `python -m osu_crawl.privacy audit` · `python -m osu_crawl.privacy scrub` |
| Categories, owners, docs/categories.md (offline) | `python -m assistant.categories` |
| Top 5 chunks for a question (offline) | `python -m assistant.retrieve "question"` |
| Retrieval eval on `eval/questions.csv` (offline) | `python -m assistant.eval_retrieval` |
| Answer with verified quotes, or refuse (offline by default) | `python -m assistant.answer "question"` · `--show-prompt` |
| Run the website | `python -m beaverbot` |
| Rebuild the sample class database (`data/demo.db`; invented sections, made-up students) | `python -m beaverbot.demo.generate` |
| Ask a batch of questions with the configured provider | `python -m beaverbot.check` · `--eval` · `--spanish` · `--show` |
| Measure search and answers on 176 everyday-wording questions | `python -m beaverbot.evalset --variant all` · `--answers --grade` ([docs/answer-quality.md](docs/answer-quality.md)) |
| Build the local meaning-based search index (optional) | `pip install -r requirements-search.txt` then `python -m assistant.semantic build` |
| Play whole conversations with the configured provider | `python -m beaverbot.check --talk` · `--only "part of a name"` |
| Tests | `python -m unittest discover -s tests -t .` |

Use `.venv\Scripts\python` for `python` on Windows.

## Data and privacy

- **What is stored where:** everything crawled goes to `data/`, which is gitignored:
  - `data/osu.sqlite`: pages, chunks with full-text search, documents and forms, dates, links, the crawl log
  - `data/raw/`: original pages, kept so they can be re-parsed without re-crawling
  - `data/logs/`: request logs and block lists
- **Removed before storage:** individuals' emails and direct phone numbers (`osu_crawl/privacy.py`). Office and role contacts stay.
- **Never fetched:** staff, people and directory pages.
- **Enforced by a test:** `tests/test_privacy.py` fails if a personal email or direct phone is found in stored text.
- **Raw copies:** the saved pages in `data/raw/` are as published (private, local only).
- **Sample data:** `data/demo.db` holds invented class sections and five made-up students for the demo. Course
  facts in it come from the public catalog; nothing comes from a real schedule or a real student's account.
- **What the site saves:** nothing, except a rating or a "report a wrong answer" the student chose to send
  (`data/feedback.sqlite`). See [docs/site.md](docs/site.md).
- **Model calls:** off by default: the default provider is offline. A paid model needs the owner's approval
  (`ASSISTANT_ALLOW_PAID_CALLS=yes`, or `allow_paid_calls` in the gitignored `beaverbot.local.toml`), and its key
  comes from an environment variable, never from this repo ([docs/answer-layer.md](docs/answer-layer.md)). The
  owner approved Claude Haiku 5.5 for testing on 2026-11-09. A model is sent only public page excerpts and the
  student's question with contact details and ID numbers removed.
