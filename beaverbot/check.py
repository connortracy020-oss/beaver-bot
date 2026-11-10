"""Ask a batch of questions and report how the answers came out. For testing a provider before a demo.

    python -m beaverbot.check                       # the site's own suggested questions
    python -m beaverbot.check --eval                # plus eval/questions.csv, scored against its expected sources
    python -m beaverbot.check --spanish             # the Spanish versions of the site's questions
    python -m beaverbot.check "How do I drop a class?" "When is finals week?"
    python -m beaverbot.check --show                # print each answer in full

It uses the provider the site is configured for (beaverbot.local.toml or ASSISTANT_PROVIDER). With a paid
provider every question is one paid call, so the estimated cost is printed at the end. Full answers are saved
to data/logs/ (private, gitignored); nothing is sent anywhere except the provider's own API.
"""
import argparse
import csv
import datetime
import json
import os
import sys
import time

from . import answers, config, content


def norm(url: str) -> str:
    return url.strip().split("#")[0].split("?")[0].rstrip("/")


def run(questions: list[dict], show: bool = False, pinned: bool | None = None) -> list[dict]:
    rows = []
    for item in questions:
        steps = []
        started = time.time()
        try:
            res = answers.ask(item["question"], lang=item.get("lang", "en"), emit=lambda e, d: steps.append(d.get("step")),
                              use_pinned=pinned)
        except Exception as e:      # a provider error must not stop the whole batch
            res = {"kind": "error", "reason": f"{type(e).__name__}: {e}"[:200], "text": "", "pages": [], "contacts": [],
                   "mode": config.provider_name(), "lang": item.get("lang", "en")}
        seconds = time.time() - started
        urls = [norm(p["url"]) for p in res["pages"]]
        expected = [norm(u) for u in item.get("expected", [])]
        row = {"question": item["question"], "kind": res["kind"], "reason": res["reason"], "mode": res["mode"],
               "lang": res["lang"], "seconds": round(seconds, 2), "sources": urls, "text": res["text"],
               "expected": expected, "should_refuse": item.get("refuse"),
               "source_hit": (any(u in expected for u in urls) if expected else None)}
        if item.get("refuse") is not None:
            row["correct"] = (res["kind"] != "answer") if item["refuse"] else (res["kind"] == "answer")
        rows.append(row)
        mark = {"answer": "ANSWER ", "refusal": "REFUSAL", "crisis": "CRISIS ", "error": "ERROR  "}.get(res["kind"], res["kind"])
        hit = "" if row["source_hit"] is None else ("  source: yes" if row["source_hit"] else "  source: NO")
        print(f"{mark} {seconds:5.1f}s  {res['mode']:<9} {item['question'][:70]}{hit}"
              + (f"   [{res['reason']}]" if res["kind"] != "answer" else ""), flush=True)
        if show:
            print("    " + res["text"].replace("\n", "\n    "))
            for p in res["pages"]:
                print(f"    ({p['p']}) {p['title']}: {p['url']}")
            print()
    return rows


def run_talk(conversations: list[dict], show: bool = True) -> list[dict]:
    """Play whole conversations, keeping the history, the demo state and the class-finder step the way a browser would."""
    from . import talk
    from .demo import store
    rows = []
    for conv in conversations:
        print(f"\n=== {conv['name']}" + (f"   [demo: {conv['demo']}]" if conv.get("demo") else ""), flush=True)
        history, state, flow = [], {}, None
        for turn in conv["turns"]:
            demo = {"student": conv["demo"], "state": state, "flow": flow} if conv.get("demo") else None
            started = time.time()
            try:
                res = talk.converse(turn, history=history, demo=demo)
            except Exception as e:
                res = {"kind": "error", "reason": f"{type(e).__name__}: {e}"[:200], "text": "", "pages": [], "mode": "?", "followups": []}
            seconds = time.time() - started
            if res["kind"] == "demo":
                flow = res.get("flow")
                state = store.apply_change(state, res.get("apply"))
            elif res["kind"] in ("answer", "refusal"):
                flow = None
            label = res["kind"] + (f":{res['tool']}" if res.get("tool") else "") + (f" ({res['reason']})" if res["kind"] == "refusal" else "")
            print(f"  > {turn}\n    [{label} | {res['mode']} | {seconds:.1f}s" + (f" | {len(res['pages'])} source(s)" if res.get("pages") else "") + "]")
            if show:
                print("    " + res["text"].replace("\n", "\n    "))
                if res.get("followups") or res.get("chips"):
                    print("    next: " + " | ".join((res.get("chips") or []) + (res.get("followups") or [])))
            history = (history + [{"role": "user", "text": turn}, {"role": "bot", "text": (res.get("said") or res["text"])[:700]}])[-8:]
            rows.append({"conversation": conv["name"], "turn": turn, "kind": res["kind"], "tool": res.get("tool"), "mode": res["mode"],
                         "reason": res.get("reason"), "seconds": round(seconds, 2), "text": res["text"],
                         "sources": [p["url"] for p in res.get("pages", [])]})
    return rows


def load_eval() -> list[dict]:
    with open(config.ROOT / "eval" / "questions.csv", newline="", encoding="utf-8") as f:
        return [{"question": r["question"], "expected": [u for u in r["expected_source_urls"].split("|") if u.strip()],
                 "refuse": r["should_refuse"].strip().lower() == "yes"} for r in csv.DictReader(f)]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m beaverbot.check", description="Ask a batch of questions and summarize the answers.")
    ap.add_argument("questions", nargs="*")
    ap.add_argument("--eval", action="store_true", help="include eval/questions.csv")
    ap.add_argument("--spanish", action="store_true", help="ask the site's questions in Spanish")
    ap.add_argument("--show", action="store_true", help="print every answer in full")
    ap.add_argument("--talk", action="store_true", help="play the conversations in eval/conversations.json")
    ap.add_argument("--only", help="with --talk: only conversations whose name contains this text")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--pinned", choices=["on", "off"], help="override whether hand-checked answers are used first")
    args = ap.parse_args(argv)
    config.load_local()

    if args.talk:
        os.environ["BEAVERBOT_LIVE_SEARCH"] = "off"       # test runs use our own pages only
        convs = json.loads((config.ROOT / "eval" / "conversations.json").read_text(encoding="utf-8"))
        if args.only:
            convs = [c for c in convs if args.only.lower() in c["name"].lower()]
        if args.questions:
            convs = [{"name": "from the command line", "turns": args.questions}]
        print(f"Provider: {config.provider_name()}   conversations: {len(convs)}   turns: {sum(len(c['turns']) for c in convs)}", flush=True)
        rows = run_talk(convs)
        kinds = {}
        for r in rows:
            kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
        times = sorted(r["seconds"] for r in rows)
        print(f"\nTurns: {len(rows)}   by kind: {kinds}   median {times[len(times) // 2]:.1f}s, slowest {times[-1]:.1f}s")
        _usage_and_save({"provider": config.provider_name(), "turns": len(rows), "kinds": kinds}, rows, "talk")
        return

    items = [{"question": q} for q in args.questions]
    if not items:
        items = [{"question": q, "lang": "es" if args.spanish else "en"} for q in content.all_questions("es" if args.spanish else "en")]
        if args.eval:
            seen = {i["question"] for i in items}
            items += [i for i in load_eval() if i["question"] not in seen]
    if args.limit:
        items = items[:args.limit]

    print(f"Provider: {config.provider_name()}   questions: {len(items)}   hand-checked answers: "
          f"{args.pinned or config.pinned_mode()}\n", flush=True)
    rows = run(items, show=args.show, pinned=None if not args.pinned else args.pinned == "on")

    answered = [r for r in rows if r["kind"] == "answer"]
    scored = [r for r in rows if r.get("correct") is not None]
    with_expected = [r for r in answered if r["source_hit"] is not None]
    reasons = {}
    for r in rows:
        if r["kind"] != "answer":
            reasons[r["reason"]] = reasons.get(r["reason"], 0) + 1
    print(f"\nAnswered {len(answered)} of {len(rows)}. Not answered, by reason: {reasons or 'none'}")
    if scored:
        print(f"Answer-or-decline was right on {sum(r['correct'] for r in scored)} of {len(scored)} eval questions.")
    if with_expected:
        print(f"Cited an expected source on {sum(bool(r['source_hit']) for r in with_expected)} of {len(with_expected)} answered eval questions.")
    times = sorted(r["seconds"] for r in rows)
    if times:
        print(f"Time per question: median {times[len(times) // 2]:.1f}s, slowest {times[-1]:.1f}s")
    _usage_and_save({"provider": config.provider_name(), "count": len(rows), "answered": len(answered), "reasons": reasons}, rows, "check")


def _usage_and_save(summary: dict, rows: list[dict], prefix: str):
    try:
        from assistant.anthropic_provider import AnthropicProvider
        if AnthropicProvider.usage["calls"]:
            cost = AnthropicProvider.cost()
            summary["usage"] = dict(AnthropicProvider.usage, estimated_cost=cost)
            print(f"Model calls: {AnthropicProvider.usage['calls']}, input tokens {AnthropicProvider.usage['input_tokens']:,}, "
                  f"output tokens {AnthropicProvider.usage['output_tokens']:,}"
                  + (f", estimated cost ${cost:.4f}" if cost is not None else ""))
    except ImportError:
        pass
    out = config.DATA / "logs" / f"{prefix}-{datetime.datetime.now():%Y%m%dT%H%M%S}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"Full answers saved to {out.relative_to(config.ROOT)} (private).")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
