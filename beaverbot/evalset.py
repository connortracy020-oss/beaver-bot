"""Measure search and answers on eval/student-questions.csv: everyday student wording, with the page a careful
person would send them to.

    python -m beaverbot.evalset                  # search only: is an expected page in the top 1, 3, 5? Free, offline.
    python -m beaverbot.evalset --variant all    # compare the search settings side by side
    python -m beaverbot.evalset --answers        # the whole site with the configured provider (paid with a model)
    python -m beaverbot.evalset --misses         # list the questions a variant gets wrong

Search-only runs never call a model and never leave this machine. --answers uses the configured provider and our
own database only: the live web backup is switched off for test runs unless --live is given.
"""
import argparse
import csv
import datetime
import json
import os
import sys
import time

from assistant.retrieve import Config, search

from . import answers, config

PATH = config.ROOT / "eval" / "student-questions.csv"
VARIANTS = {
    "keyword": Config(expand=False, owner_boost=1.0, semantic=0.0),          # what the site did before
    "words": Config(expand=True, owner_boost=1.0, semantic=0.0),             # + OSU's wording for the topic
    "owner": Config(expand=True, owner_boost=2.0, semantic=0.0),                              # + the owning office's site first
    "full": Config(),                                                        # the current defaults
}


def norm(url: str) -> str:
    return url.strip().split("#")[0].split("?")[0].rstrip("/").replace("://www.", "://")


def load(path=PATH) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        rows = []
        for r in csv.DictReader(f):
            rows.append({"question": r["question"], "category": r["category"], "priority": r.get("priority", "normal"),
                         "in_data": r["in_data"].strip().lower() == "yes", "notes": r.get("notes", ""),
                         "expected": [norm(u) for u in r["expected_source_urls"].split("|") if u.strip()]})
        return rows


def rank_of(expected: list[str], urls: list[str]) -> int | None:
    """1-based position of the first expected page among the distinct pages returned, or None."""
    pages = list(dict.fromkeys(norm(u) for u in urls))
    return next((i for i, u in enumerate(pages, 1) if u in expected), None)


def rates(ranks: list[int | None]) -> dict:
    n = len(ranks) or 1
    return {f"top{k}": round(100 * sum(1 for r in ranks if r and r <= k) / n, 1) for k in (1, 3, 5, 10)} | {"n": len(ranks)}


def run_search(rows: list[dict], cfg: Config, k: int = 20) -> list[int | None]:
    con = answers.connect()
    return [rank_of(r["expected"], [h.page_url for h in search(con, answers.expand(r["question"]), k, cfg=cfg)]) for r in rows]


def run_answers(rows: list[dict], show: bool = False) -> list[dict]:
    """Each question through the whole site, as one new conversation."""
    from . import talk
    out = []
    for r in rows:
        started = time.time()
        try:
            res = talk.converse(r["question"])
        except Exception as e:
            res = {"kind": "error", "reason": f"{type(e).__name__}: {e}"[:200], "text": "", "pages": [], "mode": "?"}
        cited = [norm(p["url"]) for p in res.get("pages", [])]
        row = {"question": r["question"], "in_data": r["in_data"], "priority": r["priority"], "kind": res["kind"],
               "reason": res.get("reason"), "mode": res.get("mode"), "live": bool(res.get("live")), "seconds": round(time.time() - started, 1),
               "cited": cited, "expected": r["expected"], "hit": any(u in r["expected"] for u in cited), "text": res.get("text", ""),
               "notes": r["notes"]}
        out.append(row)
        mark = "OK  " if row["hit"] else ("ans " if res["kind"] == "answer" else res["kind"][:4].ljust(4))
        print(f"{mark} {row['seconds']:5.1f}s  {r['question'][:78]}", flush=True)
        if show:
            print("      " + row["text"].replace("\n", "\n      ")[:700] + "\n      " + " ".join(cited))
    return out


GRADER = """You grade a campus assistant's reply to a student's question about Oregon State University. You get the question, the grader's notes on what a correct answer contains (written from OSU's page), and the reply. Choose one verdict:
"correct": the reply gives the key fact or steps in the notes, or correctly sends the student to the place the notes name.
"partial": the reply is on topic and not wrong, but misses the key fact in the notes, or answers for a narrower group than was asked.
"wrong": the reply contradicts the notes, answers a different question, or states the key fact incorrectly.
If the notes say the answer is not in the data, "correct" means the reply gave accurate, relevant help without inventing specifics, and "wrong" means it stated specifics it could not know.
Reply with one JSON object: {"verdict": "...", "why": "a few words"}."""
GRADE_SCHEMA = {"type": "object", "properties": {"verdict": {"type": "string", "enum": ["correct", "partial", "wrong"]}, "why": {"type": "string"}},
                "required": ["verdict", "why"], "additionalProperties": False}


def grade(results: list[dict]) -> None:
    """Add a grade to each result. Replies that said "I don't know" are 'declined' with no model call."""
    from assistant.providers import get_provider
    provider = get_provider(config.provider_name())
    for r in results:
        if r["kind"] != "answer":
            r["grade"] = "declined"
            continue
        user = f"<question>\n{r['question']}\n</question>\n<notes>\n{r['notes']}\n</notes>\n<reply>\n{r['text']}\n</reply>"
        try:
            data = json.loads(provider.complete(GRADER, user, 300, schema=GRADE_SCHEMA))
            r["grade"], r["why"] = data["verdict"], data.get("why", "")
        except Exception as e:
            r["grade"], r["why"] = "ungraded", f"{type(e).__name__}"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m beaverbot.evalset")
    ap.add_argument("--variant", default="full", help="keyword, words, owner, full, or all")
    ap.add_argument("--answers", action="store_true", help="run the whole site with the configured provider")
    ap.add_argument("--misses", action="store_true", help="list questions with no expected page in the top 5")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--only", help="top = only the priority questions; or text a question must contain")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--grade", action="store_true", help="with --answers: have the model grade each answer against the notes")
    ap.add_argument("--live", action="store_true", help="with --answers: allow the live web backup (uses Brave quota)")
    args = ap.parse_args(argv)
    config.load_local()
    rows = load()
    if args.only:
        rows = [r for r in rows if (r["priority"] == "top" if args.only == "top" else args.only.lower() in r["question"].lower())]
    if args.limit:
        rows = rows[:args.limit]
    inside = [r for r in rows if r["in_data"]]

    if args.answers:
        if not args.live:
            os.environ["BEAVERBOT_LIVE_SEARCH"] = "off"
        print(f"Provider: {config.provider_name()}   questions: {len(rows)}   live web backup: {'on' if args.live else 'off'}\n", flush=True)
        results = run_answers(rows, args.show)
        if args.grade:
            grade(results)
            ins = [r for r in results if r["in_data"]]
            count = lambda rs, v: sum(1 for r in rs if r.get("grade") == v)      # noqa: E731
            print(f"\nGraded against the notes, in our data ({len(ins)}): correct {count(ins, 'correct')}, partly {count(ins, 'partial')}, "
                  f"wrong {count(ins, 'wrong')}, said it didn't know {count(ins, 'declined')}")
            top = [r for r in ins if r["priority"] == "top"]
            print(f"Priority ({len(top)}): correct {count(top, 'correct')}, partly {count(top, 'partial')}, wrong {count(top, 'wrong')}, "
                  f"didn't know {count(top, 'declined')}")
            outs = [r for r in results if not r["in_data"]]
            print(f"Not in our data ({len(outs)}): declined {count(outs, 'declined')}, answered and judged fine {count(outs, 'correct') + count(outs, 'partial')}, "
                  f"answered wrongly {count(outs, 'wrong')}")
        ins, outs = [r for r in results if r["in_data"]], [r for r in results if not r["in_data"]]
        answered = [r for r in ins if r["kind"] == "answer"]
        print(f"\nIn our data ({len(ins)}): answered {len(answered)}, of those citing an expected page {sum(r['hit'] for r in answered)}; "
              f"\"I don't know\" {sum(r['kind'] == 'refusal' for r in ins)}; other {sum(r['kind'] not in ('answer', 'refusal') for r in ins)}")
        print(f"Not in our data ({len(outs)}): declined {sum(r['kind'] != 'answer' for r in outs)}, answered anyway {sum(r['kind'] == 'answer' for r in outs)}")
        top = [r for r in ins if r["priority"] == "top"]
        if top:
            print(f"Priority questions ({len(top)}): answered citing an expected page {sum(r['hit'] for r in top)}")
        times = sorted(r["seconds"] for r in results)
        print(f"Time per question: median {times[len(times) // 2]:.1f}s, slowest {times[-1]:.1f}s")
        from .check import _usage_and_save
        _usage_and_save({"provider": config.provider_name(), "count": len(results)}, results, "evalset")
        return

    names = list(VARIANTS) if args.variant == "all" else [args.variant]
    print(f"{len(inside)} questions whose answer is in our data ({sum(r['priority'] == 'top' for r in inside)} priority), "
          f"{len(rows) - len(inside)} that are not.\n")
    print(f"{'variant':<10}{'top 1':>8}{'top 3':>8}{'top 5':>8}{'top 10':>8}   priority: top 1 / 3 / 5")
    summary = {}
    for name in names:
        ranks = run_search(inside, VARIANTS[name])
        r, t = rates(ranks), rates([x for x, row in zip(ranks, inside) if row["priority"] == "top"])
        summary[name] = {"all": r, "priority": t}
        print(f"{name:<10}{r['top1']:>7}%{r['top3']:>7}%{r['top5']:>7}%{r['top10']:>7}%   {t['top1']}% / {t['top3']}% / {t['top5']}%")
        if args.misses:
            for x, row in zip(ranks, inside):
                if not x or x > 5:
                    print(f"    [{x or '-'}] {row['question']}  ->  {row['expected'][0] if row['expected'] else ''}")
    out = config.DATA / "logs" / f"evalset-search-{datetime.datetime.now():%Y%m%dT%H%M%S}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=1), encoding="utf-8")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
