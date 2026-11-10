"""Keyword retrieval over the stored chunks: SQLite FTS5 with BM25 ranking. Reads the local database only.

    python -m assistant.retrieve "How do I change a class to S/U grading?"
    python -m assistant.retrieve -k 3 --json "When does winter term start?"

Each hit carries what an answer needs to cite its source: page title, heading path, URL (with the section
anchor when there is one), the date we retrieved the page, and a short excerpt.
"""
import argparse
import json
import math
import re
import sqlite3
import sys
from dataclasses import asdict, dataclass

from osu_crawl import db

from . import owners, semantic
from .categories import NO_PURPOSE

STOPWORDS = set("""
a about after again all am an and any are as at be been before being both but by can could did do does doing
during each few for from get got had has have having how i if in into is it its just me more most my myself no
nor not now of off on once only or other our out over own same she should so some such than that the their them
then there these they this those through to too under until up very was we were what when where which while who
whom why will with would you your yours yourself much many way ways need want know tell please also set
""".split())  # "set" (2026-10-29): "set up" is filler like "get"; it matched a staff FAQ's "appointment has been set up"
COURSE_RE = re.compile(r"\b([A-Za-z]{2,4})\s?(\d{3}[A-Za-z]?)\b")
PAST_RE = re.compile(r"\b(past|previous|archived?|last year|(19|20)[01]\d)\b", re.IGNORECASE)
CANDIDATES = 150    # FTS rows re-ranked before filtering and de-duplication
PER_PAGE = 2        # at most this many chunks from one page in the results
SEMANTIC_CANDIDATES, RRF = 80, 60


@dataclass
class Hit:
    chunk_id: int
    score: float          # BM25, higher is better
    coverage: float       # share of the question's search terms that appear in this chunk
    title: str
    heading_path: str
    url: str              # page URL, with #anchor for the section when known
    page_url: str         # page URL alone, for comparing sources
    retrieved_at: str
    office: str | None
    excerpt: str
    text: str


def terms(question: str) -> list[str]:
    words = re.findall(r"[a-z0-9][a-z0-9'/-]*", question.lower())
    out = []
    for w in words:
        w = w.strip("'/-").removesuffix("'s")
        if w and w not in STOPWORDS and (len(w) > 1 or w.isdigit()) and w not in out:
            out.append(w)
    return out


def fts_query(question: str) -> str:
    """OR of the question's words, each quoted (so FTS syntax in user text is inert), plus course codes as phrases."""
    parts = [f'"{dept.lower()} {num.lower()}"' for dept, num in COURSE_RE.findall(question)]
    for t in terms(question):
        for piece in re.split(r"[/-]", t):  # "S/U" -> "s" OR "u" would be noise; keep pieces of 2+ chars
            if len(piece) > 1 or piece.isdigit():
                parts.append(f'"{piece}"')
    return " OR ".join(dict.fromkeys(parts))


def _coverage(question: str, text: str) -> float:
    ts = [t for t in terms(question) if len(t) > 2 or t.isdigit()]
    if not ts:
        return 0.0
    low = text.lower()
    # Prefix match is a cheap stand-in for stemming: "registering" counts for "register".
    return sum(1 for t in ts if t[: max(4, len(t) - 3)] in low) / len(ts)


def _no_purpose(url: str) -> bool:
    m = re.match(r"https?://([^/]+)(/[^?#]*)?", url)
    host, path = (m.group(1), (m.group(2) or "/").lower()) if m else ("", "/")
    return any(host == h and re.search(rx, path) for h, rx in NO_PURPOSE)


@dataclass
class Config:
    # Chosen on eval/questions.csv (docs/retrieval-eval.md). Prefix "stemming" and exact word-pair boosts were
    # also tried there; both lowered the hit rate, so they're gone.
    authority: float = 0.15       # boost pages many OSU sites link to: score * (1 + a * ln(1 + linking sites))
    document_weight: float = 0.8  # PDFs are often reports and slide decks; prefer web pages on equal terms
    # Chosen on eval/student-questions.csv (docs/answer-quality.md):
    expand: bool = True           # add OSU's own words for the question's topic ("meal plan" -> "dining plan")
    owner_boost: float = 2.0      # multiply the score of pages on the site of the office that owns the topic
    semantic: float = 3.0         # weight of meaning-based search when its index exists (assistant/semantic.py)


DEFAULT = Config()


def build_authority(con: sqlite3.Connection) -> int:
    """How many distinct OSU sites link to each page from their content. Rebuilt after every crawl."""
    con.execute("DROP TABLE IF EXISTS page_authority")
    con.execute("""CREATE TABLE page_authority AS
        SELECT to_url AS url, COUNT(DISTINCT substr(from_url, 9, instr(substr(from_url, 9), '/') - 1)) AS sites
        FROM links WHERE region = 'main' AND from_url <> to_url GROUP BY to_url""")
    con.execute("CREATE UNIQUE INDEX page_authority_url ON page_authority(url)")
    con.commit()
    return con.execute("SELECT COUNT(*) FROM page_authority").fetchone()[0]


def search(con: sqlite3.Connection, question: str, k: int = 5, include_archived: bool | None = None,
           cfg: Config | None = None) -> list[Hit]:
    cfg = cfg or DEFAULT
    topics = owners.topics_for(question) if (cfg.expand or cfg.owner_boost != 1.0) else []
    query = fts_query(f"{question} {' '.join(t.words for t in topics)}" if cfg.expand and topics else question)
    if not query:
        return []
    if include_archived is None:
        include_archived = bool(PAST_RE.search(question))
    has_authority = con.execute("SELECT 1 FROM sqlite_master WHERE name='page_authority'").fetchone()
    rows = con.execute(f"""
        SELECT c.id, bm25(chunks_fts, 1.0, 3.0) AS rank,
               snippet(chunks_fts, 0, '[', ']', '...', 32) AS excerpt,
               c.heading_path, c.anchor, c.text, c.document_id IS NOT NULL AS is_doc,
               COALESCE(p.url, d.url) AS url, COALESCE(p.title, d.title) AS title,
               COALESCE(p.retrieved_at, d.retrieved_at) AS retrieved_at,
               COALESCE(p.owning_office, d.owning_office) AS office, COALESCE(p.archived, 0) AS archived,
               {"COALESCE((SELECT sites FROM page_authority a WHERE a.url = COALESCE(p.url, d.url)), 0)"
                if has_authority else "0"} AS sites
        FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid
        LEFT JOIN pages p ON p.id = c.page_id LEFT JOIN documents d ON d.id = c.document_id
        WHERE chunks_fts MATCH ? ORDER BY rank LIMIT ?""", (query, CANDIDATES * (2 if topics else 1))).fetchall()

    def weight(r) -> float:
        w = 1 + cfg.authority * math.log1p(r["sites"])
        if topics and cfg.owner_boost != 1.0 and owners.owns(topics, r["url"]):
            w *= cfg.owner_boost
        return w * (cfg.document_weight if r["is_doc"] else 1.0)

    near = semantic.nearest(question, SEMANTIC_CANDIDATES) if cfg.semantic > 0 else []
    if near:
        # Two rankings, one by words and one by meaning, merged by position (reciprocal rank fusion) so neither
        # scale has to be comparable with the other. Authority, the owning office and the PDF weight still apply.
        by_id = {r["id"]: r for r in rows}
        missing = [cid for cid, _ in near if cid not in by_id]
        if missing:
            marks = ",".join("?" * len(missing))
            for r in con.execute(f"""
                SELECT c.id, 0.0 AS rank, substr(c.text, 1, 220) AS excerpt, c.heading_path, c.anchor, c.text,
                       c.document_id IS NOT NULL AS is_doc, COALESCE(p.url, d.url) AS url, COALESCE(p.title, d.title) AS title,
                       COALESCE(p.retrieved_at, d.retrieved_at) AS retrieved_at,
                       COALESCE(p.owning_office, d.owning_office) AS office, COALESCE(p.archived, 0) AS archived,
                       {"COALESCE((SELECT sites FROM page_authority a WHERE a.url = COALESCE(p.url, d.url)), 0)"
                        if has_authority else "0"} AS sites
                FROM chunks c LEFT JOIN pages p ON p.id = c.page_id LEFT JOIN documents d ON d.id = c.document_id
                WHERE c.id IN ({marks}) AND COALESCE(p.gone_at, d.gone_at) IS NULL""", missing):
                by_id[r["id"]] = r
        word_rank = {r["id"]: i for i, r in enumerate(sorted(rows, key=lambda r: r["rank"]), 1)}
        mean_rank = {cid: i for i, (cid, _) in enumerate(near, 1)}
        fused = {cid: (1 / (RRF + word_rank[cid]) if cid in word_rank else 0.0)
                      + (cfg.semantic / (RRF + mean_rank[cid]) if cid in mean_rank else 0.0) for cid in by_id}
        rows = list(by_id.values())
        score = lambda r: 100 * fused[r["id"]] * weight(r)       # noqa: E731
    else:
        score = lambda r: -r["rank"] * weight(r)                 # noqa: E731

    hits, per_page = [], {}
    for r in sorted(rows, key=score, reverse=True):
        if (r["archived"] and not include_archived) or _no_purpose(r["url"]):
            continue
        if per_page.get(r["url"], 0) >= PER_PAGE:
            continue
        per_page[r["url"]] = per_page.get(r["url"], 0) + 1
        hits.append(Hit(
            chunk_id=r["id"], score=round(score(r), 3),
            coverage=round(_coverage(question, r["heading_path"] + " " + r["text"]), 2),
            title=r["title"] or "", heading_path=r["heading_path"] or "",
            url=r["url"] + (f"#{r['anchor']}" if r["anchor"] else ""), page_url=r["url"],
            retrieved_at=(r["retrieved_at"] or "")[:10], office=r["office"],
            excerpt=" ".join(r["excerpt"].split()), text=r["text"]))
        if len(hits) == k:
            break
    return hits


def connect() -> sqlite3.Connection:
    con = db.connect()
    con.row_factory = sqlite3.Row
    return con


def main(argv=None):
    ap = argparse.ArgumentParser(description="Top chunks for a question, from the local OSU page database.")
    ap.add_argument("question")
    ap.add_argument("-k", type=int, default=5)
    ap.add_argument("--json", action="store_true", help="print JSON instead of text")
    ap.add_argument("--archived", action="store_true", help="include archived calendars")
    args = ap.parse_args(argv)
    hits = search(connect(), args.question, args.k, include_archived=args.archived or None)
    if args.json:
        print(json.dumps([{k: v for k, v in asdict(h).items() if k != "text"} for h in hits], indent=2))
        return
    if not hits:
        print("No matching pages.")
    for i, h in enumerate(hits, 1):
        print(f"{i}. {h.title}  ({h.office or 'unknown office'})")
        print(f"   {h.heading_path}")
        print(f"   {h.url}   retrieved {h.retrieved_at}   score {h.score}, terms matched {h.coverage:.0%}")
        print(f"   {h.excerpt}\n")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
