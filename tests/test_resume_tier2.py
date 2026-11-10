"""The guarded Tier 2 resume: nothing before the pause ends, only the rate-limited sites unblocked, and Tier 2 ends
for good if a 429 recurs. Runs on temporary state with a fake crawler: no network, no real logs or database."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from osu_crawl import crawl, db

PAUSE_END = datetime(2026, 10, 24, 4, 30, 53, tzinfo=timezone.utc)
BLOCKED = {
    "classes.oregonstate.edu": "robots.txt returned 202 (bot protection) on 2026-10-22",
    "food.oregonstate.edu": "challenge page on https://food.oregonstate.edu/west-side-grill",
    "career.oregonstate.edu": "challenge page on https://career.oregonstate.edu/x",
}


class ResumeTier2(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.logs = self.tmp / "logs"
        self.logs.mkdir()
        (self.logs / "blocked.json").write_text(json.dumps(BLOCKED))
        (self.logs / "cooldown.json").write_text(json.dumps({"oregonstate.edu": {
            "until": PAUSE_END.isoformat(), "reason": "test", "set_at": "2026-10-23T04:30:53+00:00"}}))
        dbfile = self.tmp / "t.sqlite"
        self.patches = [
            mock.patch.object(crawl, "LOG_DIR", self.logs),
            mock.patch.object(crawl, "TIER2_ENDED", self.logs / "tier2-ended.json"),
            mock.patch.object(crawl.db, "connect", lambda path=dbfile: db.__dict__["sqlite3"].connect(path)
                              if False else _connect(dbfile)),
        ]
        for p in self.patches:
            p.start()
        self.runs = []

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def fake_crawler(self, rate_limited_again: bool):
        test = self

        class FakeCrawler:
            def __init__(self, phase):
                test.runs.append(phase)

            def run(self):
                if rate_limited_again:  # what the fetcher writes when a 429 comes back
                    (test.logs / "cooldown.json").write_text(json.dumps({"oregonstate.edu": {
                        "until": "2026-10-25T05:00:00+00:00", "reason": "HTTP 429 again",
                        "set_at": "2026-10-24T05:00:00+00:00"}}))
        return FakeCrawler

    def test_refuses_before_the_pause_ends(self):
        with mock.patch.object(crawl, "Crawler", self.fake_crawler(False)):
            code = crawl.resume_tier2(now=PAUSE_END - timedelta(hours=1))
        self.assertEqual(code, 3)
        self.assertEqual(self.runs, [])  # no crawler was even created
        self.assertIn("food.oregonstate.edu", json.loads((self.logs / "blocked.json").read_text()))

    def test_unblocks_only_rate_limited_sites_then_crawls(self):
        with mock.patch.object(crawl, "Crawler", self.fake_crawler(False)):
            code = crawl.resume_tier2(now=PAUSE_END + timedelta(minutes=5))
        self.assertEqual(code, 0)
        self.assertEqual(self.runs, ["tier2"])
        still = json.loads((self.logs / "blocked.json").read_text())
        self.assertEqual(list(still), ["classes.oregonstate.edu"])  # bot-protected site stays blocked

    def test_a_recurring_429_ends_tier2_for_good(self):
        with mock.patch.object(crawl, "Crawler", self.fake_crawler(True)):
            code = crawl.resume_tier2(now=PAUSE_END + timedelta(minutes=5))
        self.assertEqual(code, 5)
        self.assertTrue((self.logs / "tier2-ended.json").exists())
        with mock.patch.object(crawl, "Crawler", self.fake_crawler(False)):
            again = crawl.resume_tier2(now=PAUSE_END + timedelta(days=3))
        self.assertEqual(again, 2)  # refuses to run again
        self.assertEqual(self.runs, ["tier2"])

    def test_refuses_a_faster_pace(self):
        fast = crawl.load_settings()
        fast.min_global_delay_s = 1.0
        with mock.patch.object(crawl, "load_settings", lambda: fast), \
                mock.patch.object(crawl, "Crawler", self.fake_crawler(False)):
            code = crawl.resume_tier2(now=PAUSE_END + timedelta(minutes=5))
        self.assertEqual(code, 4)
        self.assertEqual(self.runs, [])


def _connect(path):
    import sqlite3
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(db.SCHEMA.read_text(encoding="utf-8"))
    return con


if __name__ == "__main__":
    unittest.main()
