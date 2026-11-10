"""The weekly re-crawl, as one command. It is never scheduled automatically: a person runs it (owner's decision).

    python -m osu_crawl.weekly --dry-run      # the plan and an estimate; sends nothing
    python -m osu_crawl.weekly                # refresh sitemaps, re-crawl what changed, rebuild everything derived
    python -m osu_crawl.weekly --rebuild-only # only the offline rebuild (step 4), e.g. after editing categories

Steps (docs/recrawl.md):
1. **Preflight (offline):** stop if OSU is paused (data/logs/cooldown.json), another crawl holds the lock, or the global
   pace is under 3 s. Blocked sites stay blocked; only the owner unblocks them.
2. **Sitemaps:** re-read each site's sitemap through the same polite fetcher, so the crawl knows what changed.
3. **Re-crawl** (`crawl recrawl`): pages the sitemap says are unchanged since our copy get no request (up to 28 days);
   the rest get a conditional request (304 = unchanged); new pages from sitemaps and links are fetched; 404/410 pages
   are removed from search. All the usual rules apply: robots.txt, 3 s between requests, pause on any 429.
4. **Rebuild (offline):** privacy audit, categories, link authority, metrics, structure map, retrieval eval.
5. **Report:** docs/recrawl-report.md (counts) and data/logs/recrawl-<time>.json.

Exit codes: 0 done; 3 OSU paused (nothing sent, or the run stopped when a pause began); 4 pace under 3 s;
6 another crawl is running.
"""
import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone

from . import db
from .config import DISCOVERY_DIR, LOG_DIR, ROOT, load_settings
from .crawl import PHASES, SITEMAP_TRUST_DAYS, Crawler, iso_date, now_iso
from .fetcher import CrawlerLocked, PoliteFetcher
from .scope import SCOPE

PHASE = "recrawl"
MIN_GLOBAL_S = 3.0


def _json(path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def paused_until(now: datetime | None = None) -> str | None:
    pause = _json(LOG_DIR / "cooldown.json").get("oregonstate.edu")
    if pause and (now or datetime.now(timezone.utc)) < datetime.fromisoformat(pause["until"]):
        return pause["until"]
    return None


def hosts() -> tuple[list[str], dict[str, str]]:
    """Sites to re-crawl, and the blocked ones left out (with why)."""
    blocked = _json(LOG_DIR / "blocked.json")
    usable = [h for h in PHASES[PHASE] if h not in blocked and not SCOPE.get(h, {}).get("link_only")]
    return usable, {h: why for h, why in blocked.items() if h in PHASES[PHASE]}


def preflight() -> int:
    until = paused_until()
    if until:
        print(f"OSU is paused until {until} after a rate limit. Nothing was sent; run this again after that.")
        return 3
    pace = load_settings().min_global_delay_s
    if pace < MIN_GLOBAL_S:
        print(f"min_global_delay_s is {pace}; it must be at least {MIN_GLOBAL_S} s. Nothing was sent.")
        return 4
    if (LOG_DIR / "crawler.lock").exists():
        print(f"{LOG_DIR / 'crawler.lock'} exists: another crawl is running (or was killed; then delete the file).")
        return 6
    return 0


def plan() -> dict:
    """What a run would request, from what's stored now. Sitemaps can move pages between the two page counts."""
    usable, blocked = hosts()
    con = db.connect()
    marks = ",".join("?" * len(usable))
    trust_from = iso_date((datetime.now(timezone.utc) - timedelta(days=SITEMAP_TRUST_DAYS)).isoformat())
    pages_skip = pages_ask = docs = 0
    for r in con.execute(f"""SELECT f.kind, f.sitemap_lastmod, p.retrieved_at FROM frontier f
                             LEFT JOIN pages p ON p.url = f.url
                             WHERE f.domain IN ({marks}) AND f.state IN ('fetched','not_modified','error','queued')""",
                         usable):
        if r["kind"] == "document":
            docs += 1
        elif (r["retrieved_at"] and r["sitemap_lastmod"] and iso_date(r["retrieved_at"]) >= trust_from
              and iso_date(r["sitemap_lastmod"]) <= iso_date(r["retrieved_at"])):
            pages_skip += 1
        else:
            pages_ask += 1
    sitemap_files = sum(len(v.get("sitemap_files_fetched", [])) or 1
                        for h, v in _json(DISCOVERY_DIR / "sitemaps.json").items() if h in usable)
    requests = len(usable) + sitemap_files + pages_ask + docs   # robots.txt + sitemaps + conditional fetches
    return {"sites": len(usable), "blocked_sites": blocked, "sitemap_requests": sitemap_files + len(usable),
            "pages_skipped_by_sitemap": pages_skip, "pages_to_ask": pages_ask, "pdfs_to_ask": docs,
            "max_requests": requests, "max_hours_at_3s": round(requests * MIN_GLOBAL_S / 3600, 1)}


def refresh_sitemaps(usable: list[str]) -> dict:
    from .discover import cmd_sitemaps
    fetcher = PoliteFetcher(load_settings(), allowed_hosts=set(usable), log_name="weekly-sitemaps.jsonl")
    try:
        cmd_sitemaps(fetcher, usable)
    finally:
        fetcher.close()
    summary = _json(DISCOVERY_DIR / "sitemaps.json")
    failed = [h for h in usable if summary.get(h, {}).get("blocked")
              or (summary.get(h, {}).get("errors") and not summary.get(h, {}).get("urls_listed"))]
    if failed and not paused_until():
        # No fresh sitemap for these: forget their old sitemap dates so every page gets a conditional request.
        con = db.connect()
        con.execute(f"UPDATE frontier SET sitemap_lastmod=NULL WHERE domain IN ({','.join('?' * len(failed))})", failed)
        con.commit()
    return {"failed": failed, "blocked": dict(fetcher.blocked)}


def rebuild() -> dict:
    """Everything derived from the stored pages. Offline: no requests."""
    from assistant import categories, eval_retrieval
    from assistant.retrieve import build_authority

    from . import dedupe, privacy, report, structure
    out = {}
    audit = privacy.run(apply=False)
    out["privacy_findings"] = sum(v["emails"] + v["phones"] for v in audit["fields"].values())
    con = db.connect()
    out["owners_normalized"] = categories.normalize_owners(con)
    out["categories"] = dict(categories.assign(con))
    (ROOT / "docs" / "categories.md").write_text(categories.build_doc(con), encoding="utf-8")
    out["authority_rows"] = build_authority(con)
    out["deduped"] = dedupe.run(apply=True, con=con)  # after authority: the most-linked copy is the one kept
    if con.execute("SELECT 1 FROM crawl_runs WHERE phase=?", (PHASE,)).fetchone():
        (ROOT / "docs" / f"{PHASE}-metrics.md").write_text(report.build(PHASE), encoding="utf-8")
    m = structure.build()
    (ROOT / "docs" / "structure-map.json").write_text(json.dumps(m, indent=1, ensure_ascii=False), encoding="utf-8")
    (ROOT / "docs" / "structure-map.generated.md").write_text(structure.to_markdown(m), encoding="utf-8")
    rows = eval_retrieval.load()
    res = eval_retrieval.run(rows)
    (ROOT / "docs" / "retrieval-eval.md").write_text(eval_retrieval.report(res, "all questions"), encoding="utf-8")
    scored = res["scored"]
    out["retrieval_top3"] = f"{sum(1 for r in scored if r['rank'] and r['rank'] <= 3)}/{len(scored)}"
    out["retrieval_top5"] = f"{sum(1 for r in scored if r['rank'])}/{len(scored)}"
    return out


def summarize(run_id: int, started: str, sitemaps: dict, rebuilt: dict, exit_code: int) -> dict:
    con = db.connect()
    q = lambda sql, *a: con.execute(sql, a).fetchone()[0]  # noqa: E731
    statuses = Counter({(r[0] if r[0] is not None else "network error"): r[1] for r in con.execute(
        "SELECT http_status, COUNT(*) FROM fetch_log WHERE run_id=? GROUP BY 1", (run_id,))})
    s = {
        "run_id": run_id, "started": started, "finished": now_iso(), "exit_code": exit_code,
        "requests": sum(statuses.values()), "responses": {str(k): v for k, v in sorted(statuses.items(), key=str)},
        "unchanged_by_sitemap": q("SELECT COUNT(*) FROM frontier WHERE run_id=? AND skip_reason='sitemap_lastmod'", run_id),
        "pages_new": q("SELECT COUNT(*) FROM pages WHERE first_seen_at >= ?", started),
        "pages_changed": q("SELECT COUNT(*) FROM pages WHERE changed_at >= ? AND first_seen_at < ?", started, started),
        "pages_gone": q("SELECT COUNT(*) FROM pages WHERE gone_at >= ?", started),
        "pdfs_gone": q("SELECT COUNT(*) FROM documents WHERE gone_at >= ?", started),
        "still_queued": q("SELECT COUNT(*) FROM frontier WHERE state='queued'"),
        "sitemaps_failed": sitemaps.get("failed", []),
        "blocked_sites": _json(LOG_DIR / "blocked.json"),
        "osu_paused_until": paused_until(),
        **rebuilt,
    }
    s["changed_examples"] = [dict(r) for r in con.execute(
        "SELECT title, url FROM pages WHERE changed_at >= ? ORDER BY changed_at DESC LIMIT 20", (started,))]
    return s


def write_report(s: dict) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    (LOG_DIR / f"recrawl-{stamp}.json").write_text(json.dumps(s, indent=1), encoding="utf-8")
    lines = ["# Re-crawl report (generated)", "",
             f"Run {s['run_id']}, {s['started']} to {s['finished']}. Exit code {s['exit_code']}. "
             "Written by `python -m osu_crawl.weekly`.", "",
             "| | Count |", "|---|---:|",
             f"| Requests sent | {s['requests']} |",
             *[f"| HTTP {k} | {v} |" for k, v in s["responses"].items()],
             f"| Pages skipped (sitemap says unchanged) | {s['unchanged_by_sitemap']} |",
             f"| New pages | {s['pages_new']} |",
             f"| Changed pages | {s['pages_changed']} |",
             f"| Pages removed from search (404/410) | {s['pages_gone']} |",
             f"| PDFs removed from search (404/410) | {s['pdfs_gone']} |",
             f"| URLs still queued | {s['still_queued']} |", "",
             f"- **Sitemaps that failed:** {', '.join(s['sitemaps_failed']) or 'none'}",
             f"- **Blocked sites (not contacted):** {', '.join(s['blocked_sites']) or 'none'}",
             f"- **OSU paused until:** {s['osu_paused_until'] or 'not paused'}",
             f"- **Privacy audit:** {s.get('privacy_findings', 'not run')} personal emails or phones found in "
             "stored text (should be 0)",
             f"- **Retrieval eval:** top 3 {s.get('retrieval_top3', '-')}, top 5 {s.get('retrieval_top5', '-')}", ""]
    if s["changed_examples"]:
        lines += ["## Changed or new pages (latest 20)", ""] + [f"- [{r['title']}]({r['url']})" for r in s["changed_examples"]]
    (ROOT / "docs" / "recrawl-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Weekly re-crawl of OSU's public pages (run by hand).")
    ap.add_argument("--dry-run", action="store_true", help="show the plan; send nothing")
    ap.add_argument("--rebuild-only", action="store_true", help="skip the crawl; rebuild derived data offline")
    args = ap.parse_args(argv)

    if args.rebuild_only:
        print(json.dumps(rebuild(), indent=1))
        return 0
    code = preflight()
    p = plan()
    print("Plan:", json.dumps(p, indent=1))
    if args.dry_run or code:
        return code

    started = now_iso()
    t0 = time.time()
    usable, _ = hosts()
    print(f"\n[1/3] Refreshing sitemaps for {len(usable)} sites")
    try:
        sitemaps = refresh_sitemaps(usable)
    except CrawlerLocked as e:
        print(e)
        return 6
    if paused_until():
        print(f"OSU paused itself during the sitemap refresh (until {paused_until()}); stopping before the crawl.")
        code = 3
    else:
        print(f"\n[2/3] Re-crawling (pace: one request every {MIN_GLOBAL_S:.0f}+ s across all of OSU)")
        crawler = Crawler(PHASE)
        crawler.run()
        if paused_until():
            code = 3
    run_id = db.connect().execute("SELECT id FROM crawl_runs WHERE phase=? ORDER BY id DESC", (PHASE,)).fetchone()
    print("\n[3/3] Rebuilding derived data (offline)")
    rebuilt = rebuild()
    s = summarize(run_id["id"] if run_id else 0, started, sitemaps, rebuilt, code)
    write_report(s)
    print(f"\nDone in {(time.time() - t0) / 60:.0f} min. Report: docs/recrawl-report.md")
    if s["blocked_sites"] or s["osu_paused_until"]:
        print("ATTENTION: blocked sites or an OSU pause; see the report. Nothing is retried automatically.")
    return code


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
