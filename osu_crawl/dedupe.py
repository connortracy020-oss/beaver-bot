"""Set aside duplicate content so search shows each text once. Offline and idempotent; part of the weekly rebuild.

- Pages with the same text under different URLs (Drupal "-0" copies, two paths to one page): one keeps its chunks;
  the others get `duplicate_of` and leave search. Their records stay, so the URLs remain known.
- PDFs with the same bytes under two URLs (a re-upload, a "%20" and a space spelling of one file): the same.
- Boilerplate chunks: a chunk text found on MIN_OWNERS or more pages/PDFs (transfer-table legends, catalog option
  boilerplate, "Loading...") is kept once, on the page other OSU sites link to most. Text shared by fewer owners
  stays everywhere: there the page around it usually matters (one major's requirements vs another's).
Nothing in data/raw is touched. A page or PDF that is re-extracted gets its chunks back and is checked again.

    python -m osu_crawl.dedupe          # count what would change
    python -m osu_crawl.dedupe apply    # apply it
"""
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from urllib.parse import urlsplit

from . import db

MIN_OWNERS = 5


def _rank(url: str, sites: int) -> tuple:
    """Lower is the better copy to keep: linked from more sites, not a "-0" clone, no query, shorter URL."""
    return (-sites, bool(re.search(r"-\d+/?$", urlsplit(url).path)), "?" in url, len(url), url)


def run(apply: bool, con: sqlite3.Connection | None = None) -> dict:
    con = con or db.connect()
    has_authority = con.execute("SELECT 1 FROM sqlite_master WHERE name='page_authority'").fetchone()
    sites = dict(con.execute("SELECT url, sites FROM page_authority").fetchall()) if has_authority else {}
    out = Counter()
    if apply:
        con.execute("UPDATE pages SET duplicate_of=NULL WHERE duplicate_of IS NOT NULL")
        con.execute("UPDATE documents SET duplicate_of=NULL WHERE duplicate_of IS NOT NULL")

    for table, key, kind in (("pages", "text_hash", "pages"), ("documents", "content_hash", "documents")):
        groups = defaultdict(list)
        extra = "AND length(main_text) > 0" if table == "pages" else "AND text IS NOT NULL"
        for rid, url, h in con.execute(f"SELECT id, url, {key} FROM {table} WHERE gone_at IS NULL AND {key} IS NOT NULL {extra}"):
            groups[h].append((rid, url))
        owner = "page_id" if table == "pages" else "document_id"
        for members in groups.values():
            if len(members) < 2:
                continue
            members.sort(key=lambda m: _rank(m[1], sites.get(m[1], 0)))
            for rid, _ in members[1:]:
                out[kind] += 1
                if apply:
                    con.execute(f"UPDATE {table} SET duplicate_of=? WHERE id=?", (members[0][1], rid))
                    out[f"{kind}_chunks"] += con.execute(f"DELETE FROM chunks WHERE {owner}=?", (rid,)).rowcount

    by_text = defaultdict(list)
    for cid, text, pid, did, url in con.execute("""SELECT c.id, c.text, c.page_id, c.document_id, COALESCE(p.url, d.url)
                                                   FROM chunks c LEFT JOIN pages p ON p.id = c.page_id
                                                   LEFT JOIN documents d ON d.id = c.document_id"""):
        by_text[text].append((cid, f"p{pid}" if pid else f"d{did}", url or ""))
    for text, copies in by_text.items():
        if len({o for _, o, _ in copies}) < MIN_OWNERS:
            continue
        out["boilerplate_texts"] += 1
        copies.sort(key=lambda c: (c[1].startswith("d"), *_rank(c[2], sites.get(c[2], 0)), c[0]))
        for cid, _, _ in copies[1:]:
            out["boilerplate_chunks"] += 1
            if apply:
                con.execute("DELETE FROM chunks WHERE id=?", (cid,))
    if apply:
        con.commit()
    return dict(out)


if __name__ == "__main__":
    print(run(apply=len(sys.argv) > 1 and sys.argv[1] == "apply"))
