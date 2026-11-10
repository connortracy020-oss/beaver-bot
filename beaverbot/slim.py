"""Build the serving-only copy of the page database:  python -m beaverbot.slim

The full database (data/osu.sqlite) carries everything the crawler needs: every link, the fetch log, each page's
whole text, the crawl queue. The site needs far less: the excerpts and their search index, each page's address,
title and office, the categories, the link counts and the calendar dates. This writes just that to
data/serve/osu.sqlite, which is what goes to the host.

It opens data/osu.sqlite read-only and never changes it, and it never touches data/raw. The table layouts stay the
same as the full database, so the site's queries run unchanged; the columns the site never reads are left empty.
Like everything in data/, the result is private: it is never committed and never sent to a browser.
"""
import sqlite3
import sys
from pathlib import Path

from . import config

OUT = config.ROOT / "data" / "serve" / "osu.sqlite"
TABLES = ("pages", "documents", "chunks", "page_authority", "page_categories", "dates")
# Columns the site never reads. They are emptied, not dropped, so the layout matches the full database.
EMPTY = {"pages": {"main_text", "headings", "breadcrumb", "nav_path", "canonical_url", "etag", "content_hash", "text_hash",
                   "page_type_signals", "template", "contact_block", "extract_stats", "meta_robots", "raw_path"},
         "documents": {"text", "content_hash", "raw_path"}}
FTS_SHADOW = ("data", "idx", "docsize", "config")       # the search index's own tables, copied as they are


def build(src: Path | None = None, out: Path | None = None) -> dict:
    src, out = Path(src or config.ROOT / "data" / "osu.sqlite"), Path(out or OUT)
    if out.resolve() == src.resolve():
        raise SystemExit("The serving copy must not be written over the full database.")
    out.parent.mkdir(parents=True, exist_ok=True)
    for stale in (out, out.with_name(out.name + "-journal")):
        stale.unlink(missing_ok=True)
    con = sqlite3.connect(f"file:{out.as_posix()}", uri=True)       # uri=True so the full database can be attached read-only
    con.execute("ATTACH DATABASE ? AS full", (f"file:{src.as_posix()}?mode=ro",))
    master = {r[0]: r[1] for r in con.execute("SELECT name, sql FROM full.sqlite_master WHERE sql IS NOT NULL")}
    for table in TABLES:
        con.execute(master[table])
        cols = [(r[1], r[2].upper(), r[3]) for r in con.execute(f"PRAGMA full.table_info({table})")]
        picks = []
        for name, kind, notnull in cols:
            if name not in EMPTY.get(table, ()):
                picks.append(name)
            elif name == "text":                    # the site only counts which PDFs had text, never reads it
                picks.append("CASE WHEN text IS NULL THEN NULL ELSE '' END")
            else:
                picks.append(("0" if "INT" in kind else "''") if notnull else "NULL")
        con.execute(f"INSERT INTO main.{table} SELECT {', '.join(picks)} FROM full.{table}")
    con.execute(master["chunks_fts"])
    for part in FTS_SHADOW:
        con.execute(f"DELETE FROM main.chunks_fts_{part}")
        con.execute(f"INSERT INTO main.chunks_fts_{part} SELECT * FROM full.chunks_fts_{part}")
    for name, sql in master.items():
        if name in ("deadlines", "date_mentions", "pages_domain", "chunks_page", "page_authority_url"):
            con.execute(sql)
    con.commit()
    con.execute("DETACH DATABASE full")
    con.execute("VACUUM")
    con.close()
    return check(src, out)


def check(src: Path, out: Path) -> dict:
    """The copy must answer searches exactly as the full database does."""
    a = sqlite3.connect(f"file:{src.as_posix()}?mode=ro", uri=True)
    b = sqlite3.connect(f"file:{out.as_posix()}?mode=ro", uri=True)
    report = {"size_mb": round(out.stat().st_size / 1e6, 1), "full_size_mb": round(src.stat().st_size / 1e6, 1)}
    for table in TABLES:
        n = [c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for c in (a, b)]
        if n[0] != n[1]:
            raise SystemExit(f"{table}: {n[1]:,} rows copied, {n[0]:,} expected")
        report[table] = n[1]
    for words in ("tuition", "study rooms", "financial aid deadline", "parking permit", "advisor"):
        q = "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts), rowid LIMIT 50"
        if a.execute(q, (words,)).fetchall() != b.execute(q, (words,)).fetchall():
            raise SystemExit(f"search for {words!r} differs between the full database and the copy")
    for view in ("deadlines",):
        if a.execute(f"SELECT COUNT(*) FROM {view}").fetchone() != b.execute(f"SELECT COUNT(*) FROM {view}").fetchone():
            raise SystemExit(f"{view} differs")
    a.close(), b.close()
    return report


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    r = build()
    print(f"Wrote {OUT.relative_to(config.ROOT)}: {r['size_mb']} MB (the full database is {r['full_size_mb']} MB).")
    print("  " + ", ".join(f"{r[t]:,} {t}" for t in TABLES))
