"""The only two things the site ever saves, both in data/feedback.sqlite (gitignored, server side).

- **Ratings:** thumbs up or down, the day, the topic, and which OSU pages the answer cited. Not the question, and
  nothing about who clicked: no account, cookie, session id or address.
- **Reports:** when a student presses "Report a wrong answer": the question (with contact details and ID numbers
  removed), the answer that was shown, its sources and an optional note. This is the one place a question is kept,
  and the button says so.
"""
import datetime
import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from assistant.answer import redact

from . import config

_lock = threading.Lock()
SCHEMA = """
CREATE TABLE IF NOT EXISTS ratings (
    id       INTEGER PRIMARY KEY,
    day      TEXT NOT NULL,          -- date only, never a time
    rating   TEXT NOT NULL,          -- up | down
    kind     TEXT,                   -- answer | refusal | ...
    category TEXT,
    lang     TEXT,
    mode     TEXT,                   -- which provider wrote the answer
    sources  TEXT NOT NULL           -- JSON list of OSU page URLs the answer cited
);
CREATE TABLE IF NOT EXISTS reports (
    id       INTEGER PRIMARY KEY,
    day      TEXT NOT NULL,
    question TEXT NOT NULL,          -- redacted
    answer   TEXT NOT NULL,
    sources  TEXT NOT NULL,
    note     TEXT,                   -- redacted
    category TEXT,
    lang     TEXT,
    mode     TEXT
);
"""


@contextmanager
def _connect(path: Path | None = None):
    """Open, write and close: the file is never left locked between requests."""
    path = path or config.FEEDBACK_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    try:
        con.executescript(SCHEMA)
        yield con
        con.commit()
    finally:
        con.close()


def _urls(sources) -> str:
    urls = [s for s in (sources or []) if isinstance(s, str) and s.startswith("https://") and len(s) < 400][:12]
    return json.dumps(urls)


def _short(value, limit: int) -> str | None:
    return " ".join(str(value).split())[:limit] if isinstance(value, str) and value.strip() else None


def rate(data: dict, path: Path | None = None) -> bool:
    rating = data.get("rating")
    if rating not in ("up", "down"):
        return False
    with _lock, _connect(path) as con:
        con.execute("INSERT INTO ratings(day, rating, kind, category, lang, mode, sources) VALUES (?,?,?,?,?,?,?)",
                    (datetime.date.today().isoformat(), rating, _short(data.get("kind"), 20),
                     _short(data.get("category"), 30), _short(data.get("lang"), 5), _short(data.get("mode"), 30),
                     _urls(data.get("sources"))))
    return True


def report(data: dict, path: Path | None = None) -> bool:
    question, answer = _short(data.get("question"), 400), _short(data.get("answer"), 4000)
    if not question or not answer:
        return False
    note = _short(data.get("note"), 600)
    with _lock, _connect(path) as con:
        con.execute("INSERT INTO reports(day, question, answer, sources, note, category, lang, mode) VALUES (?,?,?,?,?,?,?,?)",
                    (datetime.date.today().isoformat(), redact(question), answer, _urls(data.get("sources")),
                     redact(note) if note else None, _short(data.get("category"), 30), _short(data.get("lang"), 5),
                     _short(data.get("mode"), 30)))
    return True


def summary(path: Path | None = None) -> dict:
    """Counts for the team: how answers are rated, and how many reports are waiting."""
    with _lock, _connect(path) as con:
        ups, downs = (con.execute("SELECT COUNT(*) FROM ratings WHERE rating = ?", (r,)).fetchone()[0] for r in ("up", "down"))
        return {"up": ups, "down": downs, "reports": con.execute("SELECT COUNT(*) FROM reports").fetchone()[0]}
