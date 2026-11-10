"""The guarded Tier 2b resume: nothing before the pause ends, only the three false stops cleared (their unpublished
pages skipped), and a new pause or block reported. Temporary state and a fake crawler: no network, no real logs."""
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from osu_crawl import crawl, db

PAUSE_END = datetime(2026, 10, 30, 13, 19, 56, tzinfo=timezone.utc)
BLOCKED = {
    "classes.oregonstate.edu": "robots.txt returned 202 (bot protection) on 2026-10-22",
    "commencement.oregonstate.edu": "HTTP 403 with a 19640-byte body on https://commencement.oregonstate.edu/2021-commencement",
    "familyresources.oregonstate.edu": "HTTP 403 with a 16276-byte body on https://familyresources.oregonstate.edu/about-us",
    "pharmacy.oregonstate.edu": "challenge page (HTTP 403) on https://pharmacy.oregonstate.edu/student-experience/our-campuses",
}


def _connect(path):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(db.SCHEMA.read_text(encoding="utf-8"))
    return con


class ResumeTier2b(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.logs = self.tmp / "logs"
        self.logs.mkdir()
        (self.logs / "blocked.json").write_text(json.dumps(BLOCKED))
        (self.logs / "cooldown.json").write_text(json.dumps({"oregonstate.edu": {
            "until": PAUSE_END.isoformat(), "reason": "pharmacy: challenge page", "set_at": "2026-10-29T13:19:56+00:00"}}))
        self.dbfile = self.tmp / "t.sqlite"
        con = _connect(self.dbfile)
        con.execute("INSERT INTO crawl_runs(phase, started_at, user_agent, hosts) VALUES ('tier2b', 'x', 'ua', '[]')")
        for url in crawl.TIER2B_FALSE_STOPS.values():
            con.execute("INSERT INTO frontier(url, domain, source, state) VALUES (?, ?, 'sitemap', 'blocked')",
                        (url, url.split("/")[2]))
        con.commit()
        self.patches = [mock.patch.object(crawl, "LOG_DIR", self.logs),
                        mock.patch.object(crawl.db, "connect", lambda *a, **k: _connect(self.dbfile)),
                        mock.patch.object(crawl, "_keep_awake", lambda on: None)]
        for p in self.patches:
            p.start()
        self.runs = []

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def fake_crawler(self, new_pause=False, new_block=False):
        test = self

        class FakeCrawler:
            def __init__(self, phase):
                test.runs.append(phase)

            def run(self):
                if new_pause:
                    (test.logs / "cooldown.json").write_text(json.dumps({"oregonstate.edu": {
                        "until": "2026-10-31T14:00:00+00:00", "reason": "HTTP 429", "set_at": "2026-10-30T14:00:00+00:00"}}))
                if new_block:
                    blocked = json.loads((test.logs / "blocked.json").read_text())
                    (test.logs / "blocked.json").write_text(json.dumps({**blocked, "mu.oregonstate.edu": "HTTP 403 ..."}))
        return FakeCrawler

    def test_refuses_before_the_pause_ends(self):
        with mock.patch.object(crawl, "Crawler", self.fake_crawler()):
            code = crawl.resume_tier2b(now=PAUSE_END - timedelta(minutes=10))
        self.assertEqual((code, self.runs), (3, []))
        self.assertEqual(json.loads((self.logs / "blocked.json").read_text()), BLOCKED)

    def test_clears_only_the_false_stops_and_skips_their_pages(self):
        with mock.patch.object(crawl, "Crawler", self.fake_crawler()):
            code = crawl.resume_tier2b(now=PAUSE_END + timedelta(minutes=2))
        self.assertEqual((code, self.runs), (0, ["tier2b"]))
        self.assertEqual(list(json.loads((self.logs / "blocked.json").read_text())), ["classes.oregonstate.edu"])
        states = dict(_connect(self.dbfile).execute("SELECT url, state || ':' || skip_reason FROM frontier").fetchall())
        self.assertEqual(set(states.values()), {"skipped:forbidden"})

    def test_a_different_block_on_the_same_site_is_not_cleared(self):
        other = {**BLOCKED, "pharmacy.oregonstate.edu": "HTTP 429 on https://pharmacy.oregonstate.edu/x"}
        (self.logs / "blocked.json").write_text(json.dumps(other))
        with mock.patch.object(crawl, "Crawler", self.fake_crawler()):
            crawl.resume_tier2b(now=PAUSE_END + timedelta(minutes=2))
        self.assertIn("pharmacy.oregonstate.edu", json.loads((self.logs / "blocked.json").read_text()))

    def test_a_new_pause_is_reported(self):
        with mock.patch.object(crawl, "Crawler", self.fake_crawler(new_pause=True)):
            self.assertEqual(crawl.resume_tier2b(now=PAUSE_END + timedelta(minutes=2)), 5)

    def test_a_new_block_is_reported(self):
        with mock.patch.object(crawl, "Crawler", self.fake_crawler(new_block=True)):
            self.assertEqual(crawl.resume_tier2b(now=PAUSE_END + timedelta(minutes=2)), 5)

    def test_refuses_a_faster_pace_or_a_running_crawl(self):
        fast = crawl.load_settings()
        fast.min_global_delay_s = 1.0
        with mock.patch.object(crawl, "load_settings", lambda: fast), \
                mock.patch.object(crawl, "Crawler", self.fake_crawler()):
            self.assertEqual(crawl.resume_tier2b(now=PAUSE_END + timedelta(minutes=2)), 4)
        (self.logs / "crawler.lock").write_text("1")
        with mock.patch.object(crawl, "Crawler", self.fake_crawler()):
            self.assertEqual(crawl.resume_tier2b(now=PAUSE_END + timedelta(minutes=2)), 6)
        self.assertEqual(self.runs, [])


if __name__ == "__main__":
    unittest.main()
