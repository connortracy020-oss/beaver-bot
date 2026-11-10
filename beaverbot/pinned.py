"""Hand-checked answers for the questions students ask most (pinned.json).

Each one was written from the stored OSU page it cites, and carries the exact sentences it relies on. Nothing is
trusted because it is in this file: at request time every quote is looked up in the stored page again and the
answer goes through the same verifier as a model's. If OSU changes the page and a quote is gone, the entry is
skipped and the normal search answers instead.

They are used first when the provider is offline (BEAVERBOT_PINNED, beaverbot/config.py), so the demo reads well
without a model. With a model connected they are off by default, so the team tests the model itself.
"""
import json
import re
import sqlite3
from pathlib import Path

from assistant.retrieve import Hit
from assistant.verify import quote_in

PATH = Path(__file__).with_name("pinned.json")
_entries: list[dict] | None = None


def entries() -> list[dict]:
    global _entries
    if _entries is None:
        _entries = json.loads(PATH.read_text(encoding="utf-8")) if PATH.exists() else []
    return _entries


def find(question: str) -> dict | None:
    for e in entries():
        if re.search(e["match"], question, re.I) and not (e.get("unless") and re.search(e["unless"], question, re.I)):
            return e
    return None


def _chunks(con: sqlite3.Connection, url: str) -> list[sqlite3.Row]:
    return con.execute("""SELECT c.id, c.heading_path, c.anchor, c.text, p.url, p.title, p.retrieved_at, p.owning_office
                          FROM chunks c JOIN pages p ON p.id = c.page_id
                          WHERE p.url = ? AND p.gone_at IS NULL ORDER BY c.seq""", (url,)).fetchall()


def prepare(con: sqlite3.Connection, entry: dict, lang: str = "en") -> tuple[list[Hit], str] | None:
    """The entry as (hits, model-format JSON), or None when a quote is no longer on the stored page."""
    hits: dict[int, Hit] = {}
    cites = []
    for c in entry["citations"]:
        row = next((r for r in _chunks(con, c["url"]) if quote_in(c["quote"], r["text"])), None)
        if row is None:
            return None
        url = row["url"] + (f"#{row['anchor']}" if row["anchor"] else "")
        hits.setdefault(row["id"], Hit(
            chunk_id=row["id"], score=99.0, coverage=1.0, title=row["title"] or "", heading_path=row["heading_path"] or "",
            url=url, page_url=row["url"], retrieved_at=(row["retrieved_at"] or "")[:10], office=row["owning_office"],
            excerpt="", text=row["text"]))
        cites.append({"chunk_id": row["id"], "quote": c["quote"]})
    text = entry["answer"].get(lang) or entry["answer"]["en"]
    return list(hits.values()), json.dumps({"status": "answered", "answer": text, "citations": cites})
