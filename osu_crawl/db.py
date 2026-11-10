"""SQLite access: schema setup and the writes the crawler makes."""
import hashlib
import json
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit

from .config import DB_PATH

SCHEMA = Path(__file__).with_name("schema.sql")


# Columns added after the first database was created: (table, column, definition).
MIGRATIONS = [
    ("pages", "archived", "INTEGER NOT NULL DEFAULT 0"),
    ("dates", "authority", "TEXT NOT NULL DEFAULT 'mention'"),
    ("dates", "source_url", "TEXT"),
    ("pages", "gone_at", "TEXT"),        # set when a re-crawl gets 404/410; its chunks are removed from search
    ("documents", "gone_at", "TEXT"),
    ("pages", "duplicate_of", "TEXT"),      # set by dedupe.py: the same text is kept on this other URL
    ("documents", "duplicate_of", "TEXT"),
]

# Only the Registrar's academic calendar is a source of truth for dates. Everything else is a raw mention.
CALENDAR_URL = "https://registrar.oregonstate.edu/osu-academic-calendar"
VIEWS = """
CREATE VIEW IF NOT EXISTS deadlines AS
    SELECT d.*, p.title AS source_title FROM dates d JOIN pages p ON p.id = d.page_id
    WHERE d.authority = 'authoritative';
CREATE VIEW IF NOT EXISTS date_mentions AS
    SELECT d.*, COALESCE(p.title, doc.title) AS source_title FROM dates d
    LEFT JOIN pages p ON p.id = d.page_id LEFT JOIN documents doc ON doc.id = d.document_id
    WHERE d.authority = 'mention';
"""


def date_authority(url: str, archived: bool) -> str:
    """'authoritative' for the Registrar's current academic calendar, 'authoritative_archived' for its past-term
    archive, 'mention' for a date found anywhere else (never treated as a final deadline)."""
    if url.startswith(CALENDAR_URL):
        return "authoritative_archived" if archived or "/archive/" in url else "authoritative"
    return "mention"


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    for table, column, definition in MIGRATIONS:
        if column not in {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    con.executescript(VIEWS)
    return con


def sha256(text: str | bytes) -> str:
    return hashlib.sha256(text.encode("utf-8") if isinstance(text, str) else text).hexdigest()


def enqueue(con, url: str, domain: str, source: str, *, discovered_from=None, depth=0, priority=5,
            kind="page", sitemap_lastmod=None) -> bool:
    """Add a URL to the frontier if it's new. Returns True when added."""
    seq = con.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM frontier").fetchone()[0]
    cur = con.execute(
        "INSERT OR IGNORE INTO frontier(url, domain, source, discovered_from, depth, priority, seq, kind, sitemap_lastmod)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (url, domain, source, discovered_from, depth, priority, seq, kind, sitemap_lastmod))
    if cur.rowcount == 0 and priority is not None:
        # A URL found again by a better route moves up the queue.
        con.execute("UPDATE frontier SET priority = MIN(priority, ?) WHERE url = ? AND state = 'queued'", (priority, url))
    return cur.rowcount > 0


def set_state(con, url: str, state: str, run_id: int, skip_reason: str | None = None):
    con.execute("UPDATE frontier SET state=?, skip_reason=?, attempts=attempts+1, last_attempt_at=datetime('now'),"
                " run_id=? WHERE url=?", (state, skip_reason, run_id, url))


def log_skip(con, url: str, reason: str, detail: str, run_id: int):
    con.execute("INSERT OR IGNORE INTO skips(url, reason, detail, run_id, ts) VALUES (?,?,?,?,datetime('now'))",
                (url, reason, detail, run_id))


def log_fetch(con, run_id: int, res=None, *, url=None, error=None, elapsed=None):
    if res is None:
        con.execute("INSERT INTO fetch_log(run_id, url, error, fetched_at) VALUES (?,?,?,datetime('now'))",
                    (run_id, url, error))
        return
    con.execute(
        "INSERT INTO fetch_log(run_id, url, final_url, http_status, bytes, elapsed_s, etag, last_modified,"
        " content_hash, fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (run_id, res.url, res.final_url, res.status, len(res.content), elapsed, res.headers.get("etag"),
         res.headers.get("last-modified"), res.content_hash, res.retrieved_at))


def upsert_page(con, rec: dict) -> tuple[int, bool]:
    """Insert or update a page. Returns (page_id, text_changed)."""
    row = con.execute("SELECT id, text_hash, first_seen_at FROM pages WHERE url=?", (rec["url"],)).fetchone()
    if row is None:
        cols = list(rec) + ["first_seen_at", "changed_at"]
        vals = list(rec.values()) + [rec["retrieved_at"], rec["retrieved_at"]]
        cur = con.execute(f"INSERT INTO pages({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", vals)
        return cur.lastrowid, True
    changed = row["text_hash"] != rec["text_hash"]
    sets = dict(rec)
    if changed:
        sets["changed_at"] = rec["retrieved_at"]
    con.execute(f"UPDATE pages SET {','.join(f'{k}=?' for k in sets)} WHERE id=?", list(sets.values()) + [row["id"]])
    return row["id"], changed


def replace_children(con, *, page_id=None, document_id=None, chunks=(), dates=(), source_url=None,
                     date_authority_value="mention"):
    key, val = ("page_id", page_id) if page_id is not None else ("document_id", document_id)
    con.execute(f"DELETE FROM chunks WHERE {key}=?", (val,))
    con.execute(f"DELETE FROM dates WHERE {key}=?", (val,))
    con.executemany(
        f"INSERT INTO chunks({key}, seq, heading_path, anchor, text, token_estimate) VALUES (?,?,?,?,?,?)",
        [(val, c["seq"], c["heading_path"], c["anchor"], c["text"], c["token_estimate"]) for c in chunks])
    con.executemany(
        f"INSERT INTO dates({key}, context, date_text, date_iso, term, heading_path, cue, source, authority, source_url)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        [(val, d["context"], d["date_text"], d["date_iso"], d["term"], d["heading_path"], d["cue"], d["source"],
          date_authority_value, source_url) for d in dates])


def add_link_only(con, url: str, title: str | None, reason: str, office: str | None = None):
    """Resources the assistant links to but cannot read: scanned PDFs, the map app, bot-protected sites."""
    con.execute("INSERT INTO link_only(url, title, reason, owning_office, added_at) VALUES (?,?,?,?,datetime('now'))"
                " ON CONFLICT(url) DO UPDATE SET title=excluded.title, reason=excluded.reason,"
                " owning_office=COALESCE(excluded.owning_office, link_only.owning_office)", (url, title, reason, office))


REGION_ORDER = {"main": 0, "breadcrumb": 1, "sidebar": 2, "nav": 3, "footer": 4, "other": 5}


def replace_links(con, from_url: str, links: list[dict], host: str):
    """One row per (target, anchor text); when a link appears in several regions, the content region wins."""
    con.execute("DELETE FROM links WHERE from_url=?", (from_url,))
    links = sorted(links, key=lambda l: REGION_ORDER.get(l["region"], 9))
    con.executemany(
        "INSERT OR IGNORE INTO links(from_url, to_url, anchor_text, region, is_internal, nofollow) VALUES (?,?,?,?,?,?)",
        [(from_url, l["url"], l["text"], l["region"], int(urlsplit(l["url"]).hostname == host), int(l["nofollow"]))
         for l in links])


def upsert_document(con, rec: dict, authoritative: bool = False) -> int:
    """Insert a document, or update it.

    `authoritative` records come from fetching the document itself (PDF read, login wall hit): their values win,
    except an existing purpose, which only a linking page can supply. Records built from a link on some page only
    fill fields that are still empty, so a later link never downgrades kind (e.g. fillable_pdf back to pdf).
    """
    row = con.execute("SELECT id FROM documents WHERE url=?", (rec["url"],)).fetchone()
    if row is None:
        cols = list(rec)
        cur = con.execute(f"INSERT INTO documents({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                          list(rec.values()))
        return cur.lastrowid
    sets = {k: v for k, v in rec.items() if v is not None and k != "url"}
    if not sets:
        return row["id"]
    if authoritative:
        assigns = [f"{k}=COALESCE({k}, ?)" if k in ("purpose", "found_on_page_id") else f"{k}=?" for k in sets]
    else:
        assigns = [f"{k}=COALESCE({k}, ?)" for k in sets]
    con.execute(f"UPDATE documents SET {','.join(assigns)} WHERE id=?", list(sets.values()) + [row["id"]])
    return row["id"]


def to_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)
