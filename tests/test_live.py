"""The live web backup (beaverbot/live.py) and topic ownership (assistant/owners.py).

No network: Brave's API and OSU's sites are replaced with stand-ins. These tests check the rules the owner set:
off unless switched on, OSU's public sites only, a monthly cap with a stop at 90%, a cache, and a key that never
reaches a file.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from assistant import owners
from assistant.retrieve import Config
from beaverbot import live

KEY = "test-key-not-real-0123456789"


class FakeResponse:
    status_code = 200

    def __init__(self, urls):
        self.urls = urls

    def json(self):
        return {"web": {"results": [{"title": f"Page {i}", "url": u, "description": "<strong>Dining</strong> plans"} for i, u in enumerate(self.urls)]}}


class Backup(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        root = Path(self.dir.name)
        env = {"BRAVE_SEARCH_API_KEY": KEY, "BEAVERBOT_LIVE_SEARCH": "on", "BEAVERBOT_BRAVE_MONTHLY_LIMIT": "10"}
        for patch in (mock.patch.dict(os.environ, env), mock.patch.object(live, "USAGE_PATH", root / "usage.json"),
                      mock.patch.object(live, "CACHE_PATH", root / "cache.json")):
            patch.start()
            self.addCleanup(patch.stop)
        self.calls = []

    def get(self, urls):
        def fake(url, params=None, headers=None, timeout=None):
            self.calls.append({"url": url, "params": params, "headers": headers})
            return FakeResponse(urls)
        return mock.patch("httpx.get", fake)

    def test_it_is_off_unless_the_owner_switches_it_on_and_a_key_exists(self):
        self.assertTrue(live.enabled())
        with mock.patch.dict(os.environ, {"BEAVERBOT_LIVE_SEARCH": "off"}):
            self.assertFalse(live.enabled())
        with mock.patch.dict(os.environ):
            del os.environ["BEAVERBOT_LIVE_SEARCH"]
            self.assertFalse(live.enabled(), "off by default")
        with mock.patch.dict(os.environ, {"BRAVE_SEARCH_API_KEY": ""}):
            self.assertFalse(live.enabled())

    def test_only_public_osu_pages_survive_the_filter(self):
        good = ["https://uhds.oregonstate.edu/dining/dining-plans", "https://studenthealth.oregonstate.edu/locations"]
        bad = ["http://uhds.oregonstate.edu/dining", "https://example.com/oregonstate.edu", "https://oregonstate.edu.evil.com/",
               "https://canvas.oregonstate.edu/courses/1", "https://beaverhub.oregonstate.edu/", "https://prodapps.isadm.oregonstate.edu/x",
               "https://mysupport.oregonstate.edu/", "https://directory.oregonstate.edu/people/1", "https://classes.oregonstate.edu/",
               "https://guides.library.oregonstate.edu/x", "https://engineering.oregonstate.edu/people/someone",
               "https://asosu.oregonstate.edu/minutes/2025", "https://science.oregonstate.edu/directory/x",
               "https://liberalarts.oregonstate.edu/users/someone", "https://uhds.oregonstate.edu/sites/default/files/roster.xlsx"]
        for url in good:
            self.assertTrue(live.allowed(url), url)
        for url in bad:
            self.assertFalse(live.allowed(url), url)

    def test_a_search_sends_only_the_redacted_question_limited_to_osu(self):
        with self.get(["https://uhds.oregonstate.edu/dining/dining-plans", "https://canvas.oregonstate.edu/x"]):
            results = live.brave("meal plan prices? my email is someone@example.com and my id is 931234567")
        self.assertEqual([r["url"] for r in results], ["https://uhds.oregonstate.edu/dining/dining-plans"])
        self.assertEqual(results[0]["description"], "Dining plans", "markup is stripped")
        sent = self.calls[0]
        self.assertTrue(sent["params"]["q"].endswith(" site:oregonstate.edu"))
        self.assertNotIn("someone@example.com", sent["params"]["q"])
        self.assertNotIn("931234567", sent["params"]["q"])
        self.assertEqual(sent["headers"]["X-Subscription-Token"], KEY)
        self.assertEqual(set(sent["params"]), {"q", "count", "country", "search_lang", "safesearch"}, "nothing else about the student")

    def test_results_are_cached_and_counted_and_the_key_is_never_written(self):
        with self.get(["https://uhds.oregonstate.edu/dining/dining-plans"]):
            live.brave("meal plan prices")
            live.brave("Meal plan   prices")
        self.assertEqual(len(self.calls), 1, "the second ask came from the cache")
        self.assertEqual(live.used(), 1)
        for path in Path(self.dir.name).iterdir():
            self.assertNotIn(KEY, path.read_text(encoding="utf-8"), path.name)

    def test_it_stops_at_ninety_percent_of_the_monthly_limit(self):
        with self.get(["https://uhds.oregonstate.edu/dining/dining-plans"]):
            for i in range(12):
                live.brave(f"question number {i}")
        self.assertEqual(len(self.calls), 9)
        self.assertEqual(live.used(), 9)
        self.assertFalse(live.enabled())
        self.assertEqual(live.status()["stop_at"], 9)

    def test_a_failed_search_still_counts_and_returns_nothing(self):
        class Down(FakeResponse):
            status_code = 429
        with mock.patch("httpx.get", lambda *a, **k: Down([])), mock.patch("builtins.print") as printed:
            self.assertEqual(live.brave("anything at all"), [])
        self.assertEqual(live.used(), 1)
        self.assertNotIn(KEY, json.dumps([str(c) for c in printed.call_args_list]))

    def test_a_page_outside_the_rules_is_never_opened(self):
        with mock.patch("osu_crawl.fetcher.PoliteFetcher") as fetcher:
            self.assertEqual(live.fetch("https://canvas.oregonstate.edu/courses/1", "anything"), [])
            self.assertEqual(live.fetch("https://engineering.oregonstate.edu/people/someone", "anything"), [])
            fetcher.assert_not_called()


class Owners(unittest.TestCase):
    def test_student_words_map_to_the_office_that_owns_the_topic(self):
        cases = {"what are the tiers to the meal plans at OSU?": "uhds.oregonstate.edu", "where can I get tutoring": "success.oregonstate.edu",
                 "how do I change my major": "advising.oregonstate.edu", "i need a therapist": "counseling.oregonstate.edu",
                 "can i set up a payment plan": "finance.oregonstate.edu", "wifi isnt working": "technology.oregonstate.edu",
                 "is there a dorm for transfer students": "uhds.oregonstate.edu"}
        for question, host in cases.items():
            hosts = {h for t in owners.topics_for(question) for h, _ in t.hosts}
            self.assertIn(host, hosts, question)
        self.assertEqual(owners.topics_for("what is the meaning of life"), [])
        self.assertIn("dining plan", owners.expansion("meal plan tiers"))

    def test_only_the_owning_section_counts(self):
        dining = owners.topics_for("meal plan prices")
        self.assertTrue(owners.owns(dining, "https://uhds.oregonstate.edu/dining/dining-plans"))
        self.assertFalse(owners.owns(dining, "https://health.oregonstate.edu/faq/42026"))
        self.assertFalse(owners.owns(dining, "https://uhds.oregonstate.edu.example.com/dining"))

    def test_the_office_card_is_the_topics_own_office(self):
        names = [n for n, _ in owners.contacts_for("what are the tiers to the meal plans?")]
        self.assertEqual(names, ["University Housing & Dining Services"])
        self.assertNotIn("Recreational Sports", names)
        self.assertEqual(owners.contacts_for("asdf"), [])
        for topic in owners.TOPICS:
            for _, url in topic.contacts:
                self.assertTrue(url.startswith("https://") and ".oregonstate.edu" in url, topic.id)

    def test_search_settings_can_be_switched_off_for_comparison(self):
        base = Config(expand=False, owner_boost=1.0)
        self.assertFalse(base.expand)
        self.assertEqual(base.owner_boost, 1.0)


if __name__ == "__main__":
    unittest.main()
