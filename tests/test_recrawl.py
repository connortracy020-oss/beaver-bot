"""Re-crawl behavior on a temporary database with a fake fetcher: no network, no real logs.

- a page the sitemap says is unchanged gets no request, but only within SITEMAP_TRUST_DAYS of our copy;
- everything else (PDFs included) gets a conditional request with the stored ETag / Last-Modified;
- a 404 removes the page's chunks from search and records when it went away;
- the weekly command refuses to start while OSU is paused, below the 3 s pace, or while another crawl runs.
"""
import json
import tempfile
import unittest
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from osu_crawl import crawl, db, weekly
from osu_crawl.fetcher import FetchResult

URL = "https://registrar.oregonstate.edu/transcripts"
PDF = "https://registrar.oregonstate.edu/sites/registrar.oregonstate.edu/files/form.pdf"


def ago(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


class FakeFetcher:
    def __init__(self, status=304):
        self.status, self.calls = status, []

    def fetch(self, url, extra_headers=None, max_bytes=None, hop_check=None):
        self.calls.append((url, dict(extra_headers or {})))
        return FetchResult(url, url, self.status, {"content-type": "text/html"}, b"", ago(0), "", None)


class Recrawl(unittest.TestCase):
    def setUp(self):
        self.con = db.connect(Path(tempfile.mkdtemp()) / "t.sqlite")
        self.con.execute("INSERT INTO crawl_runs(id, phase, started_at, user_agent, hosts) VALUES (1, 'recrawl', ?, 'ua', '[]')",
                         (ago(0),))
        self.c = crawl.Crawler.__new__(crawl.Crawler)
        self.c.con, self.c.run_id, self.c.counts = self.con, 1, defaultdict(int)
        self.c.settings = crawl.load_settings()
        self.c.fetcher = FakeFetcher()

    def store(self, retrieved_days_ago: float, sitemap_lastmod_days_ago: float | None):
        retrieved = ago(retrieved_days_ago)
        db.enqueue(self.con, URL, "registrar.oregonstate.edu", "sitemap",
                   sitemap_lastmod=ago(sitemap_lastmod_days_ago) if sitemap_lastmod_days_ago is not None else None)
        self.con.execute("INSERT INTO pages(url, domain, title, retrieved_at, first_seen_at, changed_at, content_hash,"
                         " text_hash, http_status) VALUES (?,?,?,?,?,?,?,?,200)",
                         (URL, "registrar.oregonstate.edu", "Transcripts", retrieved, retrieved, retrieved, "h", "t"))
        pid = self.con.execute("SELECT id FROM pages WHERE url=?", (URL,)).fetchone()["id"]
        self.con.execute("INSERT INTO chunks(page_id, seq, heading_path, text) VALUES (?,0,'Transcripts',"
                         "'Paper transcript, mailed: $12 fee.')", (pid,))
        self.con.execute("INSERT INTO fetch_log(run_id, url, http_status, etag, last_modified, fetched_at)"
                         " VALUES (1, ?, 200, '\"abc\"', 'Wed, 21 Oct 2026 10:00:00 GMT', ?)", (URL, retrieved))
        self.con.commit()

    def row(self, url=URL):
        return self.con.execute("SELECT * FROM frontier WHERE url=?", (url,)).fetchone()

    def test_unchanged_by_sitemap_sends_nothing(self):
        self.store(retrieved_days_ago=3, sitemap_lastmod_days_ago=10)
        self.c.handle(self.row())
        self.assertEqual(self.c.fetcher.calls, [])
        self.assertEqual(self.row()["state"], "not_modified")

    def test_sitemap_dates_are_not_trusted_forever(self):
        self.store(retrieved_days_ago=crawl.SITEMAP_TRUST_DAYS + 5, sitemap_lastmod_days_ago=60)
        self.c.handle(self.row())
        self.assertEqual(len(self.c.fetcher.calls), 1)
        _, headers = self.c.fetcher.calls[0]
        self.assertEqual(headers["If-None-Match"], '"abc"')  # conditional: a 304 costs OSU almost nothing
        self.assertEqual(self.row()["state"], "not_modified")

    def test_changed_sitemap_date_triggers_a_conditional_request(self):
        self.store(retrieved_days_ago=10, sitemap_lastmod_days_ago=2)
        self.c.handle(self.row())
        self.assertEqual(len(self.c.fetcher.calls), 1)

    def test_pdfs_get_conditional_requests_too(self):
        db.enqueue(self.con, PDF, "registrar.oregonstate.edu", "link", kind="document")
        self.con.execute("INSERT INTO fetch_log(run_id, url, http_status, etag, fetched_at) VALUES (1, ?, 200, '\"pdf1\"', ?)",
                         (PDF, ago(7)))
        self.c.handle(self.row(PDF))
        self.assertEqual(self.c.fetcher.calls[0][1].get("If-None-Match"), '"pdf1"')

    def test_a_404_removes_the_page_from_search(self):
        self.store(retrieved_days_ago=10, sitemap_lastmod_days_ago=2)
        self.c.fetcher = FakeFetcher(status=404)
        self.c.handle(self.row())
        page = self.con.execute("SELECT gone_at, http_status FROM pages WHERE url=?", (URL,)).fetchone()
        self.assertIsNotNone(page["gone_at"])
        self.assertEqual(page["http_status"], 404)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0], 0)
        hits = self.con.execute("SELECT COUNT(*) FROM chunks_fts WHERE chunks_fts MATCH 'transcript'").fetchone()[0]
        self.assertEqual(hits, 0)
        self.assertEqual(self.c.counts["gone"], 1)


class WeeklyPreflight(unittest.TestCase):
    def setUp(self):
        self.logs = Path(tempfile.mkdtemp())
        self.patch = mock.patch.object(weekly, "LOG_DIR", self.logs)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def test_ok_when_nothing_is_wrong(self):
        self.assertEqual(weekly.preflight(), 0)

    def test_refuses_while_osu_is_paused(self):
        (self.logs / "cooldown.json").write_text(json.dumps({"oregonstate.edu": {"until": ago(-5)}}))
        self.assertEqual(weekly.preflight(), 3)

    def test_an_expired_pause_does_not_block(self):
        (self.logs / "cooldown.json").write_text(json.dumps({"oregonstate.edu": {"until": ago(1)}}))
        self.assertEqual(weekly.preflight(), 0)

    def test_refuses_a_faster_pace(self):
        fast = crawl.load_settings()
        fast.min_global_delay_s = 1.0
        with mock.patch.object(weekly, "load_settings", lambda: fast):
            self.assertEqual(weekly.preflight(), 4)

    def test_refuses_while_another_crawl_runs(self):
        (self.logs / "crawler.lock").write_text("pid 1")
        self.assertEqual(weekly.preflight(), 6)

    def test_blocked_sites_are_left_out(self):
        (self.logs / "blocked.json").write_text(json.dumps({"food.oregonstate.edu": "HTTP 429"}))
        usable, blocked = weekly.hosts()
        self.assertNotIn("food.oregonstate.edu", usable)
        self.assertIn("food.oregonstate.edu", blocked)
        self.assertNotIn("map.oregonstate.edu", usable)  # link-only


if __name__ == "__main__":
    unittest.main()
