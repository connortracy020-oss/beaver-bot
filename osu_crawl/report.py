"""Metrics for a crawl run, written to docs/<phase>-metrics.md. The human-written report links to it.

    python -m osu_crawl.report pilot
"""
import json
import re
import statistics
import sys
from collections import Counter

from . import db
from .config import ROOT

EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")
PHONE_RE = re.compile(r"\(?\b\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}\b")


def pct(n, d):
    return f"{(100 * n / d):.0f}%" if d else "n/a"


def table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def redact(s: str) -> str:
    return PHONE_RE.sub("[phone]", EMAIL_RE.sub("[email]", s or ""))


def short(s, n=160):
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def build(phase: str) -> str:
    con = db.connect()
    run = con.execute("SELECT * FROM crawl_runs WHERE phase=? ORDER BY id DESC", (phase,)).fetchone()
    if run is None:
        sys.exit(f"no {phase} run")
    rid, hosts = run["id"], json.loads(run["hosts"])
    marks = ",".join("?" * len(hosts))
    q = lambda sql, *a: con.execute(sql, a).fetchall()
    md = [f"# {phase.title()} metrics (generated)", "",
          f"Run {rid}: started {run['started_at']}, finished {run['finished_at'] or 'not finished'}.  ",
          # The contact address stays out of anything committed (it lives in the gitignored crawler.toml).
          f"User-Agent: `{re.sub(r'contact: [^;)]+', 'contact: <contact_email>', run['user_agent'])}`", ""]

    # requests
    fl = q("SELECT url, final_url, http_status, error, elapsed_s FROM fetch_log WHERE run_id=?", rid)
    status = Counter(r["http_status"] if r["http_status"] else "error" for r in fl)
    md += ["## Requests", "", f"{len(fl)} page/PDF requests (plus robots.txt).",
           table(["status", "count"], sorted(status.items(), key=lambda x: str(x[0]))), ""]
    elapsed = [r["elapsed_s"] for r in fl if r["elapsed_s"]]
    if elapsed:
        md += [f"Response time: median {statistics.median(elapsed):.2f} s, max {max(elapsed):.2f} s.", ""]

    # frontier
    rows = q(f"SELECT domain, kind, state, COALESCE(skip_reason,'') r, COUNT(*) n FROM frontier WHERE domain IN ({marks})"
             " GROUP BY 1,2,3,4 ORDER BY 1,2,3", *hosts)
    md += ["## Frontier by host", "", table(["host", "kind", "state", "reason", "n"],
                                            [(r["domain"], r["kind"], r["state"], r["r"], r["n"]) for r in rows]), ""]

    # skips
    sk = q("SELECT reason, COUNT(*) n FROM skips GROUP BY reason ORDER BY n DESC")
    md += ["## Skips (all reasons, including sitemap entries never requested)", "",
           table(["reason", "count"], [(r["reason"], r["n"]) for r in sk]), ""]
    for reason in ("robots", "login", "noindex", "duplicate", "unsupported_type", "too_large"):
        items = q("SELECT url, detail FROM skips WHERE reason=? LIMIT 15", reason)
        if items:
            md += [f"**{reason}** (first 15):", ""] + [f"- {r['url']} — {short(r['detail'], 90)}" for r in items] + [""]
    blocked = q("SELECT * FROM blocked_hosts")
    md += ["**Blocked hosts:** " + (", ".join(f"{b['host']} ({b['reason']})" for b in blocked) or "none"), ""]

    # pages
    pages = q(f"SELECT * FROM pages WHERE domain IN ({marks})", *hosts)
    n = len(pages)
    stats = [json.loads(p["extract_stats"] or "{}") for p in pages]
    md += ["## Pages", "", f"{n} pages stored.", "",
           table(["host", "pages"], Counter(p["domain"] for p in pages).most_common()), "",
           table(["page_type", "pages"], Counter(p["page_type"] for p in pages).most_common()), "",
           table(["template", "pages"], Counter(p["template"] for p in pages).most_common()), ""]

    main_chars = [s.get("main_chars", 0) for s in stats]
    ratios = [s["main_chars"] / s["trafilatura_chars"] for s in stats if s.get("trafilatura_chars")]
    has = lambda f: sum(1 for p in pages if f(p))
    md += ["## Extraction quality", "",
           table(["check", "result"], [
               ("main region found by selector", pct(sum(1 for s in stats if s.get("main_found")), n)),
               ("has breadcrumb", pct(has(lambda p: json.loads(p["breadcrumb"] or "[]")), n)),
               ("declares <link rel=canonical>", pct(sum(1 for s in stats if s.get("canonical_tag")), n)),
               ("has headings below the title", pct(sum(1 for s in stats if s.get("headings", 0) > 1), n)),
               ("has office contact block", pct(has(lambda p: p["contact_block"]), n)),
               ("has Last-Modified", pct(has(lambda p: p["last_modified"]), n)),
               ("has ETag", pct(has(lambda p: p["etag"]), n)),
               ("main text chars (min / median / p90)",
                f"{min(main_chars, default=0)} / {int(statistics.median(main_chars)) if main_chars else 0} / "
                f"{sorted(main_chars)[int(0.9 * (len(main_chars) - 1))] if main_chars else 0}"),
               ("our text vs trafilatura (median ratio)", f"{statistics.median(ratios):.2f}" if ratios else "n/a"),
           ]), ""]
    thin = [(p["url"], s.get("main_chars")) for p, s in zip(pages, stats) if s.get("main_chars", 0) < 300]
    if thin:
        md += ["Pages with under 300 characters of main text:", ""] + [f"- {u} ({c})" for u, c in thin[:25]] + [""]
    traf_more = [(p["url"], s["main_chars"], s["trafilatura_chars"]) for p, s in zip(pages, stats)
                 if s.get("trafilatura_chars", 0) > 1.2 * max(1, s.get("main_chars", 0))]
    if traf_more:
        md += ["Pages where trafilatura found 20%+ more text than our extractor (possible misses):", ""]
        md += [f"- {u} (ours {a}, trafilatura {b})" for u, a, b in traf_more[:25]] + [""]
    dup = q(f"SELECT text_hash, GROUP_CONCAT(url, ' , ') urls, COUNT(*) n FROM pages WHERE domain IN ({marks})"
            " GROUP BY text_hash HAVING n > 1", *hosts)
    if dup:
        md += ["Identical main text at several URLs:", ""] + [f"- {short(d['urls'], 300)}" for d in dup] + [""]

    # chunks
    ch = q(f"SELECT c.* FROM chunks c JOIN pages p ON p.id=c.page_id WHERE p.domain IN ({marks})", *hosts)
    toks = [c["token_estimate"] for c in ch]
    md += ["## Chunks", "",
           f"{len(ch)} page chunks; tokens median {int(statistics.median(toks)) if toks else 0}, max {max(toks, default=0)}; "
           f"{pct(sum(1 for c in ch if (c['heading_path'] or '').count('>') >= 1), len(ch))} have a heading path below the "
           f"page title; {pct(sum(1 for c in ch if c['anchor']), len(ch))} have an #anchor for deep links.", ""]

    # documents
    docs = q("SELECT * FROM documents")
    md += ["## Documents and forms", "", table(["kind", "count"], Counter(d["kind"] for d in docs).most_common()), ""]
    fetched = [d for d in docs if d["text"] is not None]
    if fetched:
        ocr = sum(d["needed_ocr"] for d in fetched)
        pii = [(d["url"], len(EMAIL_RE.findall(d["text"] or "")), len(PHONE_RE.findall(d["text"] or ""))) for d in fetched]
        pii = [p for p in pii if p[1] + p[2] >= 5]
        md += [f"{len(fetched)} PDFs read; {ocr} would need OCR; "
               f"{sum(1 for d in fetched if d['kind'] == 'fillable_pdf')} fillable.", ""]
        if pii:
            md += ["PDFs with 5+ emails/phone numbers (check for personal details):", ""]
            md += [f"- {u} ({e} emails, {p} phones)" for u, e, p in pii] + [""]
    md += ["Sample documents:", "", table(["kind", "office", "purpose", "url"], [
        (d["kind"], short(d["owning_office"], 30), short(d["purpose"] or d["title"], 60), d["url"]) for d in docs[:20]]), ""]

    # dates
    dt = q("SELECT d.*, p.url page_url FROM dates d LEFT JOIN pages p ON p.id=d.page_id")
    md += ["## Dates", "", table(["source", "rows", "with ISO date"], [
        (s, sum(1 for d in dt if d["source"] == s), sum(1 for d in dt if d["source"] == s and d["date_iso"]))
        for s in ("table", "text")]), "", "Samples:", "",
           table(["date_text", "date_iso", "term", "cue", "context"],
                 [(d["date_text"], d["date_iso"], d["term"], short(d["cue"], 40), short(d["context"], 70))
                  for d in dt[:8] + dt[-8:]]), ""]

    # menus
    menus = q("SELECT host, menu FROM nav_menus")
    md += ["## Navigation menus captured", ""]
    for m in menus:
        tree = json.loads(m["menu"])
        md += [f"- **{m['host']}**: {len(tree)} top-level items, {sum(len(t['children']) for t in tree)} second-level: "
               + ", ".join(short(t["text"], 30) for t in tree[:10])]
    md += [""]

    # samples
    md += ["## Sample records", ""]
    for host in hosts:
        for p in q("SELECT * FROM pages WHERE domain=? ORDER BY LENGTH(main_text) DESC LIMIT 2", host):
            # These docs go into git: show chunks without anyone's contact details, and redact any that remain.
            chunks = [c for c in q("SELECT heading_path, anchor, text FROM chunks WHERE page_id=? ORDER BY seq", p["id"])
                      if not EMAIL_RE.search(c["text"]) and not PHONE_RE.search(c["text"])][:2]
            md += [f"### {p['title']}", "", "```json", json.dumps({
                "url": p["url"], "canonical_url": p["canonical_url"], "title": p["title"],
                "breadcrumb": json.loads(p["breadcrumb"] or "[]"), "page_type": p["page_type"],
                "page_type_signals": json.loads(p["page_type_signals"] or "{}"), "template": p["template"],
                "owning_office": p["owning_office"], "language": p["language"], "last_modified": p["last_modified"],
                "retrieved_at": p["retrieved_at"], "content_hash": p["content_hash"][:16] + "…",
                "contact_block": redact(short(p["contact_block"], 120)),
                "chunks": [{"heading_path": c["heading_path"], "anchor": c["anchor"], "text": redact(short(c["text"], 220))}
                           for c in chunks],
            }, indent=2, ensure_ascii=False), "```", ""]
    return "\n".join(md)


if __name__ == "__main__":
    phase = sys.argv[1] if len(sys.argv) > 1 else "pilot"
    out = ROOT / "docs" / f"{phase}-metrics.md"
    out.write_text(build(phase), encoding="utf-8")
    print(f"wrote {out}")
