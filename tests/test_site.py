"""The Beaver Bot site: the offline guide provider, hand-checked answers, the site pipeline, feedback storage,
the demo layer and the web server.

No network. Tests that need the crawled pages (data/osu.sqlite) or the sample database (data/demo.db) are skipped
when those files are absent, so the suite still runs on a fresh clone.
"""
import datetime
import json
import os
import re
import sqlite3
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from assistant import providers as P
from assistant.anthropic_provider import AnthropicProvider
from assistant.guide import GuideProvider, calendar_query
from assistant.verify import verify
from beaverbot import answers, config, content, feedback, pinned, spanish
from beaverbot.demo import finder, store

ROOT = Path(__file__).resolve().parent.parent
HAVE_PAGES = config.OSU_DB.exists()
HAVE_DEMO = config.DEMO_DB.exists()
TODAY = datetime.date(2026, 11, 9)
BANNED = re.compile(r"\bofficial\b|\bguaranteed\b|you should definitely", re.I)

CALENDAR = {"id": 1, "title": "Academic Calendar", "section": "Academic calendar filters", "url": "https://registrar.oregonstate.edu/osu-academic-calendar",
            "text": "January 2027:\nMonth/Day | Day of Week | Name\n"
                    "Jan 4, 2027 | Monday, 2027 | Winter Term Classes Begin\n"
                    "Jan 8, 2027 | Friday, 2027 | Last Day to Drop a Winter Term 5A - 1st 5 Weeks Course (100% Tuition Refund)\n"
                    "Jan 10, 2027 | Sunday, 2027 | Last Day to Drop a Winter Course (100% Tuition Refund)\n"
                    "Jan 10, 2027 | Sunday, 2027 | Last Day to Add a Winter Course Online without Dept. Approval\n"
                    "Oct 4, 2026 | Sunday, 2026 | Last Day to Drop a Fall Course (100% Tuition Refund)"}
DROP = {"id": 2, "title": "Dropping a Class", "section": "Dropping a Class", "url": "https://registrar.oregonstate.edu/drop-class",
        "text": "How to drop a class:\nTo drop a course, login to Beaver Hub as follows:\nStep 1: Log into Beaver Hub.\n"
                "Step 2: Select the Academics tab.\nStep 3: Select Register for Classes.\nStep 4: Select the Submit button.\n"
                "A confirmation message will display in the upper right."}
PARKING = {"id": 3, "title": "Parking", "section": "Parking", "url": "https://transportation.oregonstate.edu/parking",
           "text": "You will need a parking permit valid in the A, B, or C Zones on weekdays. Permit Type | Zone | Notes\n"
                   "Students living on campus are only eligible for Residential R parking permits."}


def checked(result: dict, chunks: list[dict]):
    return verify(json.dumps(result), {c["id"]: c["text"] for c in chunks})


class Guide(unittest.TestCase):
    def setUp(self):
        self.guide = GuideProvider(today=TODAY)

    def test_dates_come_from_calendar_rows_and_skip_short_sessions_and_past_dates(self):
        out = self.guide.compose("When is the add/drop deadline?", [CALENDAR])
        self.assertEqual(out["status"], "answered")
        self.assertIn("Jan 10, 2027", out["answer"])
        self.assertNotIn("5A", out["answer"])           # a 5-week session wasn't asked about
        self.assertNotIn("Oct 4, 2026", out["answer"])  # already passed on the test date
        self.assertTrue(checked(out, [CALENDAR]).ok)

    def test_a_named_term_is_respected(self):
        out = self.guide.compose("When is the last day to drop a fall class?", [CALENDAR])
        self.assertIn("Oct 4, 2026", out["answer"])
        self.assertNotIn("Jan 10", out["answer"])

    def test_how_to_becomes_steps_in_page_order(self):
        out = self.guide.compose("How do I drop a class?", [PARKING, DROP])
        steps = [l for l in out["answer"].splitlines() if l.startswith("+ ")]
        self.assertEqual(len(steps), 4)
        self.assertTrue(steps[0].startswith("+ Log into Beaver Hub."))
        self.assertTrue(checked(out, [PARKING, DROP]).ok)

    def test_plain_questions_get_exact_quotes(self):
        out = self.guide.compose("Do I need a parking permit?", [PARKING])
        self.assertEqual(out["status"], "answered")
        self.assertTrue(all(l.startswith("> ") for l in out["answer"].splitlines()[1:]))
        self.assertTrue(checked(out, [PARKING]).ok)

    def test_nothing_relevant_is_not_found(self):
        self.assertEqual(self.guide.compose("What's the best pizza place in Portland?", [DROP])["status"], "not_found")

    def test_spanish_wording_keeps_english_quotes(self):
        out = self.guide.compose("How do I drop a class?", [DROP], lang="es")
        self.assertIn("Así se hace", out["answer"])
        self.assertIn("Log into Beaver Hub.", out["answer"])
        self.assertTrue(checked(out, [DROP]).ok)

    def test_complete_reads_the_same_prompt_a_model_gets(self):
        from assistant.answer import SYSTEM, build_prompt
        from assistant.retrieve import Hit
        hit = Hit(chunk_id=2, score=1, coverage=1, title=DROP["title"], heading_path=DROP["section"], url=DROP["url"],
                  page_url=DROP["url"], retrieved_at="2026-10-22", office=None, excerpt="", text=DROP["text"])
        raw = self.guide.complete(SYSTEM, build_prompt("How do I drop a class?", [hit]))
        self.assertTrue(verify(raw, {2: DROP["text"]}).ok)

    def test_only_date_questions_use_the_calendar(self):
        self.assertIsNone(calendar_query("How do I drop a class?"))
        self.assertEqual(calendar_query("When is the last day to withdraw in winter?")["season"], "winter")


class PinnedAnswers(unittest.TestCase):
    def test_file_is_well_formed_and_uses_the_sites_own_wording_rules(self):
        entries = pinned.entries()
        self.assertGreaterEqual(len(entries), 5)
        known = set(content.all_questions("en")) | set(content.all_questions("es"))
        for e in entries:
            re.compile(e["match"])
            for lang in ("en", "es"):
                self.assertFalse(BANNED.search(e["answer"][lang]), e["id"])
                markers = {int(m) for m in re.findall(r"\[(\d+)\]", e["answer"][lang])}
                self.assertEqual(markers, set(range(1, len(e["citations"]) + 1)), f"{e['id']} {lang}: every citation is used")
            for c in e["citations"]:
                self.assertTrue(c["url"].startswith("https://") and "oregonstate.edu" in c["url"])
                self.assertLessEqual(len(c["quote"]), 320, "quotes stay short")
            for q in e["followups"]["en"]:
                self.assertTrue(q in known or q.startswith("When is the last day"), q)

    def test_the_right_entry_is_found(self):
        self.assertEqual(pinned.find("How do I set up a payment plan?")["id"], "payment-plan")
        self.assertEqual(pinned.find("What happens if I miss a payment?")["id"], "late-bill")
        self.assertEqual(pinned.find("Where do I get tutoring?")["id"], "tutoring")
        self.assertIsNone(pinned.find("Is tutoring available for online students?"))
        self.assertIsNone(pinned.find("When is the last day to change the grading basis?"))

    @unittest.skipUnless(HAVE_PAGES, "needs data/osu.sqlite")
    def test_every_entry_still_verifies_against_the_stored_pages(self):
        con = answers.connect()
        for e in pinned.entries():
            for lang in ("en", "es"):
                prepared = pinned.prepare(con, e, lang)
                self.assertIsNotNone(prepared, f"{e['id']}: a quote is no longer on the stored page")
                hits, raw = prepared
                verdict = verify(raw, {h.chunk_id: h.text for h in hits})
                self.assertTrue(verdict.ok, f"{e['id']} {lang}: {verdict.problems}")

    def test_a_missing_quote_drops_the_entry(self):
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.executescript("""CREATE TABLE pages(id INTEGER PRIMARY KEY, url, title, retrieved_at, owning_office, gone_at);
                             CREATE TABLE chunks(id INTEGER PRIMARY KEY, page_id, seq, heading_path, anchor, text);
                             INSERT INTO pages VALUES (1, 'https://x.oregonstate.edu/a', 'A', '2026-10-22', 'Office', NULL);
                             INSERT INTO chunks VALUES (10, 1, 0, 'A', NULL, 'Permits are sold online each fall.');""")
        entry = {"answer": {"en": "Buy it online. [1]"}, "citations": [{"url": "https://x.oregonstate.edu/a", "quote": "Permits are sold online"}]}
        hits, raw = pinned.prepare(con, entry)
        self.assertEqual(hits[0].chunk_id, 10)
        self.assertTrue(verify(raw, {10: hits[0].text}).ok)
        entry["citations"][0]["quote"] = "Permits are free"
        self.assertIsNone(pinned.prepare(con, entry))


class SitePipeline(unittest.TestCase):
    def test_streaming_pieces_rebuild_the_text_and_never_split_a_marker(self):
        text = "Here's how:\n+ Step one. [1]\n+ Step two with **bold** words. [12]\n\n> A quote."
        parts = answers.pieces(text)
        self.assertEqual("".join(parts), text)
        self.assertFalse(any(re.search(r"\[\d*$", p) for p in parts))

    def test_follow_ups_are_recognized(self):
        self.assertTrue(answers.is_followup("What about spring?"))
        self.assertTrue(answers.is_followup("and for winter"))
        self.assertFalse(answers.is_followup("How do I get a parking permit for my car?"))

    def test_own_words_check_ignores_quotes_but_not_a_models_sentences(self):
        text = 'Order it online.\n> Order Official Transcript in Beaver Hub.\n+ Use the official form.'
        self.assertFalse(answers.BANNED_RE.search(answers._own_words(text, quoted_lists=True)))
        self.assertTrue(answers.BANNED_RE.search(answers._own_words(text, quoted_lists=False)))

    def test_official_is_taken_out_of_a_models_own_sentences_only(self):
        text = 'Order an official transcript online.\n> Order Official Transcript in Beaver Hub.\n+ Select "an official copy" and then Order Official Transcript.'
        soft = answers._soften(text)
        self.assertIn("Order a transcript online.", soft)
        self.assertIn("> Order Official Transcript in Beaver Hub.", soft)      # a quote line is untouched
        self.assertIn('"an official copy"', soft)                              # so is text inside quotation marks
        self.assertFalse(answers.BANNED_RE.search(answers._own_words(soft, quoted_lists=False)))
        self.assertTrue(answers.BANNED_RE.search(answers._own_words("This is guaranteed to work.", quoted_lists=False)))

    def test_search_is_widened_for_known_vocabulary_gaps(self):
        self.assertIn("counseling", answers.expand("How do I see a counselor?"))
        self.assertEqual(answers.expand("How do I drop a class?"), "How do I drop a class?")

    def test_a_model_gets_one_retry_with_the_verifiers_reasons(self):
        from assistant.answer import SYSTEM, build_prompt
        from assistant.retrieve import Hit
        hit = Hit(chunk_id=2, score=1, coverage=1, title=DROP["title"], heading_path=DROP["section"], url=DROP["url"],
                  page_url=DROP["url"], retrieved_at="2026-10-22", office=None, excerpt="", text=DROP["text"])
        bad = json.dumps({"status": "answered", "answer": "Log in and drop it [1].", "citations": [{"chunk_id": 2, "quote": "Log in to Beaver Hub today"}]})
        good = json.dumps({"status": "answered", "answer": "Log in and drop it [1].", "citations": [{"chunk_id": 2, "quote": "Log into Beaver Hub."}]})
        model = P.ScriptedProvider([bad, good])
        site = answers.SiteProvider(model, "en", "How do I drop a class?", "How do I drop a class?", lambda e, d: None, TODAY)
        out = site.complete(SYSTEM, build_prompt("How do I drop a class?", [hit]))
        self.assertEqual(out, good)
        self.assertEqual(len(model.calls), 2)
        self.assertIn("quote is not in chunk", model.calls[1][1])              # the retry was told what failed
        self.assertIn("Today is Monday, November 9, 2026", model.calls[0][0])  # and the model knows the date
        calm = P.ScriptedProvider([good])
        answers.SiteProvider(calm, "en", "q", "q", lambda e, d: None, TODAY).complete(SYSTEM, build_prompt("q", [hit]))
        self.assertEqual(len(calm.calls), 1, "a good first answer is not asked for twice")

    def test_hand_checked_answers_come_first_offline_and_as_a_fallback_with_a_model(self):
        with mock.patch.dict(os.environ, {"BEAVERBOT_PINNED": "", "ASSISTANT_PROVIDER": "guide"}):
            self.assertEqual(config.pinned_mode(), "first")
        with mock.patch.dict(os.environ, {"BEAVERBOT_PINNED": "", "ASSISTANT_PROVIDER": "anthropic"}):
            self.assertEqual(config.pinned_mode(), "fallback")
        with mock.patch.dict(os.environ, {"BEAVERBOT_PINNED": "off", "ASSISTANT_PROVIDER": "anthropic"}):
            self.assertEqual(config.pinned_mode(), "off")

    def test_spanish_is_detected_and_turned_into_search_words(self):
        self.assertTrue(spanish.looks_spanish("¿Cómo configuro un plan de pago?"))
        self.assertFalse(spanish.looks_spanish("How do I get a visa letter?"))
        self.assertIn("payment plan", spanish.to_english("¿Cómo configuro un plan de pago?"))
        self.assertIn("tutoring", spanish.to_english("¿Dónde consigo tutoría?"))

    def test_site_questions_have_spanish_twins_and_sensible_follow_ups(self):
        self.assertEqual(content.english_for("¿Cómo dejo una clase?"), "How do I drop a class?")
        nxt = content.followups("paying", "How do I set up a payment plan?", "en")
        self.assertEqual(len(nxt), 3)
        self.assertNotIn("How do I set up a payment plan?", nxt)
        self.assertEqual(len(content.POPULAR), 6)
        self.assertEqual([q for q, _ in content.POPULAR[:3]],
                         ["When is the add/drop deadline?", "How do I set up a payment plan?", "Where do I get tutoring?"])

    def test_site_wording_avoids_the_banned_words(self):
        files = ["beaverbot/static/js/i18n.js", "beaverbot/content.py", "beaverbot/demo/intents.py", "beaverbot/demo/audit.py",
                 "beaverbot/static/js/chat.js", "beaverbot/static/js/pages.js", "beaverbot/static/js/hub/core.js",
                 "beaverbot/static/js/hub/panels.js", "beaverbot/static/js/hub/main.js", "beaverbot/static/js/signin.js", "beaverbot/static/index.html"]
        for name in files:
            for n, line in enumerate((ROOT / name).read_text(encoding="utf-8").splitlines(), 1):
                if "never" in line.lower() or line.lstrip().startswith(("/*", "#", "//")):
                    continue        # the rule itself is written down in comments
                self.assertFalse(BANNED.search(line), f"{name}:{n}: {line.strip()[:80]}")

    def test_the_site_never_calls_out_to_the_network(self):
        for path in (ROOT / "beaverbot").rglob("*.py"):
            if path.name == "live.py":      # the one module allowed to: the labeled live-search backup (tests/test_live.py)
                continue
            source = path.read_text(encoding="utf-8")
            for needle in ("import httpx", "urllib.request", "import requests", "osu_crawl.fetcher", "osu_crawl.crawl"):
                self.assertNotIn(needle, source, f"{path.name} must not make requests")
        for path in (ROOT / "beaverbot" / "static").rglob("*"):
            if path.suffix in (".html", ".css", ".js"):
                self.assertNotRegex(path.read_text(encoding="utf-8"), r"(src|href)=\"https?://(?!\S*oregonstate\.edu)", path.name)

    @unittest.skipUnless(HAVE_PAGES, "needs data/osu.sqlite")
    def test_the_demo_path_end_to_end(self):
        events = []
        ask = lambda q, **kw: answers.ask(q, emit=lambda e, d: events.append(d.get("step")), today=TODAY,
                                          provider=GuideProvider(today=TODAY), **kw)
        dates = ask("When is the add/drop deadline?")
        self.assertEqual(dates["kind"], "answer")
        self.assertIn("Jan 10, 2027", dates["text"])
        self.assertTrue(dates["pages"][0]["url"].startswith("https://registrar.oregonstate.edu/osu-academic-calendar"))
        plan = ask("How do I set up a payment plan?", use_pinned=True)
        self.assertEqual((plan["kind"], plan["mode"]), ("answer", "pinned"))
        self.assertTrue(plan["checked"] and plan["pages"] and plan["followups"])
        self.assertEqual(ask("Where do I get tutoring?", use_pinned=True)["kind"], "answer")
        steps = ask("How do I drop a class?", use_pinned=False)
        self.assertIn("+ ", steps["text"])
        self.assertEqual(ask("How do I see a counselor?", use_pinned=True)["kind"], "answer")
        unknown = ask("What's the best pizza place in Portland?")
        self.assertEqual(unknown["kind"], "refusal")
        self.assertTrue(unknown["contacts"])
        self.assertNotIn("official", unknown["text"].lower())
        self.assertIn("searching", events)

    @unittest.skipUnless(HAVE_PAGES, "needs data/osu.sqlite")
    def test_crisis_guard_and_spanish(self):
        crisis = answers.ask("I want to hurt myself", today=TODAY)
        self.assertEqual(crisis["kind"], "crisis")
        self.assertIn("911", crisis["text"])
        self.assertEqual(crisis["followups"], [])
        self.assertEqual(answers.ask("quiero morir", today=TODAY)["kind"], "crisis")
        own = answers.ask("What's my current balance?", today=TODAY)
        self.assertEqual((own["kind"], own["reason"], own["offer_demo"]), ("refusal", "own_records", True))
        es = answers.ask("¿Cómo configuro un plan de pago?", today=TODAY, use_pinned=True, provider=GuideProvider(today=TODAY))
        self.assertEqual((es["kind"], es["lang"]), ("answer", "es"))
        self.assertIn("myBill", es["text"])


class Feedback(unittest.TestCase):
    def test_a_rating_keeps_no_question_and_a_report_is_redacted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "feedback.sqlite"
            self.assertTrue(feedback.rate({"rating": "up", "kind": "answer", "category": "paying", "lang": "en", "mode": "guide",
                                           "sources": ["https://finance.oregonstate.edu/student-accounts/payment-plans", "javascript:alert(1)"],
                                           "question": "this must not be stored"}, path))
            self.assertFalse(feedback.rate({"rating": "sideways"}, path))
            self.assertTrue(feedback.report({"question": "Why is 931234567 on my bill? mail me at sam@example.com", "answer": "An answer.",
                                             "note": "call 541-555-0100", "sources": []}, path))
            self.assertFalse(feedback.report({"question": "", "answer": "x"}, path))
            con = sqlite3.connect(path)
            columns = [r[1] for r in con.execute("PRAGMA table_info(ratings)")]
            self.assertNotIn("question", columns)
            day, sources = con.execute("SELECT day, sources FROM ratings").fetchone()
            self.assertRegex(day, r"^\d{4}-\d{2}-\d{2}$")
            self.assertEqual(json.loads(sources), ["https://finance.oregonstate.edu/student-accounts/payment-plans"])
            question, note = con.execute("SELECT question, note FROM reports").fetchone()
            self.assertNotIn("931234567", question)
            self.assertNotIn("sam@example.com", question)
            self.assertNotIn("541-555-0100", note)
            con.close()
            self.assertEqual(feedback.summary(path), {"up": 1, "down": 0, "reports": 1})


class ModelAdapter(unittest.TestCase):
    class FakeClient:
        def __init__(self, stop_reason="end_turn", text='{"status": "not_found", "answer": "", "citations": []}'):
            self.requests, self.stop_reason, self.text = [], stop_reason, text
            self.messages = self

        def create(self, **request):
            self.requests.append(request)
            block = type("Block", (), {"type": "text", "text": self.text})
            thinking = type("Block", (), {"type": "thinking", "thinking": ""})
            return type("Message", (), {"stop_reason": self.stop_reason, "content": [thinking, block]})

    def test_paid_provider_is_locked_until_the_owner_approves(self):
        with mock.patch.dict(os.environ, {"ASSISTANT_ALLOW_PAID_CALLS": ""}):
            with self.assertRaises(P.PaidCallNotApproved):
                P.get_provider("anthropic")
        with mock.patch.dict(os.environ, {"ASSISTANT_ALLOW_PAID_CALLS": "yes"}):
            self.assertTrue(P.get_provider("anthropic").paid)       # building it sends nothing

    def test_it_sends_only_the_two_prompt_strings_and_reads_the_text_block(self):
        client = self.FakeClient(text='{"status": "answered"}')
        with mock.patch.dict(os.environ, {"ASSISTANT_MODEL": "", "ASSISTANT_EFFORT": ""}):
            out = AnthropicProvider(client=client).complete("SYSTEM", "USER")
        self.assertEqual(out, '{"status": "answered"}')
        sent = client.requests[0]
        self.assertEqual((sent["system"], sent["messages"]), ("SYSTEM", [{"role": "user", "content": "USER"}]))
        self.assertEqual(sent["model"], "claude-haiku-5-5")
        self.assertNotIn("temperature", sent)
        self.assertEqual(sent["output_config"]["format"]["type"], "json_schema")

    def test_a_sentence_around_the_json_is_dropped(self):
        from assistant.anthropic_provider import json_only
        answer = '{"status": "answered", "answer": "Dec 7 [1].", "citations": [{"chunk_id": 1, "quote": "Fall Finals Week Begins"}]}'
        self.assertEqual(json_only("Finals week begins Dec 7.\n\n" + answer), answer)
        self.assertEqual(json_only(answer), answer)
        self.assertEqual(json_only("no json here"), "no json here")

    def test_a_model_refusal_becomes_not_found(self):
        out = AnthropicProvider(client=self.FakeClient(stop_reason="refusal", text="")).complete("s", "u")
        self.assertEqual(json.loads(out)["status"], "not_found")

    def test_offline_providers_are_registered(self):
        self.assertFalse(P.get_provider("guide").paid)
        self.assertEqual(config.provider_name() if not os.environ.get("ASSISTANT_PROVIDER") else "guide", "guide")


class DemoHelpers(unittest.TestCase):
    def test_preferences_from_plain_words(self):
        prefs = finder.parse_prefs("mornings, no Fridays, on campus")
        self.assertEqual((prefs["times"], prefs["avoid"], prefs["mode"]), (["morning"], ["F"], "campus"))
        self.assertEqual(finder.parse_prefs("online is fine")["mode"], "online")
        self.assertEqual(finder.parse_prefs("only Tuesdays and Thursdays in the evening")["avoid"], ["M", "W", "F"])
        self.assertFalse(finder.parse_prefs("MTH 254")["understood"])
        self.assertTrue(finder.parse_prefs("any time works")["understood"])

    def test_dates_are_relative_to_today(self):
        friday = datetime.date(2026, 11, 13)
        self.assertEqual(store.business_day(friday, 1), datetime.date(2026, 11, 16))        # skips the weekend
        self.assertEqual(store.business_day(friday, -1), datetime.date(2026, 11, 12))
        self.assertEqual(store.next_weekday(datetime.date(2026, 11, 16), 0), datetime.date(2026, 11, 23))   # never today
        self.assertEqual((store.clock(8 * 60 + 30), store.clock(13 * 60), store.clock(0)), ("8:30 AM", "1:00 PM", "12:00 AM"))
        self.assertEqual(store.day_inline("Tomorrow"), "tomorrow")

    def test_demo_state_from_a_browser_is_reduced_to_known_shapes(self):
        state = store.clean_state({"plan": [{"crn": 12345, "linked": "x"}, {"crn": "DROP TABLE"}, "junk"], "met": 1,
                                   "appointment": {"slot": "7"}, "extra": {"anything": True}})
        self.assertEqual(state["plan"], [{"crn": 12345, "linked": None}])
        self.assertEqual((state["met"], state["appointment"]), (True, None))
        self.assertNotIn("extra", state)


@unittest.skipUnless(HAVE_DEMO, "needs data/demo.db (python -m beaverbot.demo.generate)")
class DemoLayer(unittest.TestCase):
    def setUp(self):
        from beaverbot.demo import audit, intents
        self.audit, self.intents, self.con = audit, intents, store.connect()

    def route(self, text, flow=None, state=None, slug="juniper"):
        return self.intents.route(self.con, text, slug, state or {}, flow, TODAY)

    def test_questions_about_osu_still_go_to_the_real_answers(self):
        for q in ["How do I drop a class?", "When is the add/drop deadline?", "What are the prerequisites for CS 261?",
                  "How do I set up a payment plan?", "What happens if I pay my bill late?", "Where do I get tutoring?"]:
            self.assertIsNone(self.route(q), q)

    def test_each_popup_can_be_reached_from_the_chat(self):
        cases = {"When can I register?": "registration", "book my advisor": "appointment", "am I ready to register?": "checklist",
                 "What do I still need?": "remaining", "What if I switched to psychology?": "whatif", "Build my winter plan": "plan",
                 "find me a class": "finder_course", "show my schedule": "schedule", "I need the form to change my grading basis": "forms",
                 "what's my balance": "billing", "explain my degree audit": "audit",
                 "where do I find my class schedule in beaverhub": "resources"}
        for text, tool in cases.items():
            reply = self.route(text)
            self.assertIsNotNone(reply, text)
            if tool == "plan":           # the first time, it asks a few preference questions; saying it again builds the plan
                self.assertEqual(reply["tool"], "plan_prefs", text)
                reply = self.route(text, flow=reply["flow"])
            self.assertEqual(reply["tool"], tool, text)
            self.assertTrue(reply["sample"], "every demo reply is marked as sample data")

    def test_the_class_finder_conversation(self):
        first = self.route("find me a class")
        named = self.route("MTH 254", flow=first["flow"])
        self.assertEqual((named["tool"], named["flow"]["course"]), ("finder_prefs", "MTH 254"))
        options = self.route("mornings, no Fridays, on campus", flow=named["flow"])
        self.assertEqual(options["tool"], "finder_options")
        found = options["data"]
        self.assertTrue(found["options"], "the guaranteed demo course has a morning section")
        for o in found["options"]:
            lecture, linked = o["lecture"], o["linked"]
            self.assertGreater(lecture["seats_open"], 0)
            for m in lecture["meetings"] + (linked["meetings"] if linked else []):
                self.assertNotIn("F", m["days"])
            self.assertLess(lecture["meetings"][0]["start"], 12 * 60)
            if linked:
                self.assertFalse(store.overlaps(lecture["meetings"], linked["meetings"]))
        self.assertEqual(self.route("calculus", flow=first["flow"])["flow"]["course"], "MTH 251Z")
        self.assertIsNone(self.route("How do I drop a class?", flow=first["flow"]), "a real question leaves the finder")

    def test_a_class_in_the_plan_blocks_overlapping_sections(self):
        first = finder.find(self.con, "juniper", "MTH 254", {"times": ["morning"], "avoid": [], "mode": "campus"}, {})["options"][0]
        state = {"plan": [{"crn": first["lecture"]["crn"], "linked": first["linked"]["crn"] if first["linked"] else None}]}
        busy = first["lecture"]["meetings"]
        for code in ("CS 261", "MTH 256"):
            for o in finder.find(self.con, "juniper", code, {"times": [], "avoid": [], "mode": "campus"}, state)["options"]:
                self.assertFalse(store.overlaps(o["lecture"]["meetings"], busy), f"{code} option clashes with the plan")

    def test_juniper_story(self):
        dash = self.audit.dashboard(self.con, "juniper", {}, TODAY)
        self.assertTrue(dash["blocked"])
        self.assertEqual(dash["registration"]["day_label"], "Monday")
        self.assertEqual(self.audit.remaining(self.con, "juniper", {})["count"], 3)
        slot = dash["slots"][0]["id"]
        booked = self.audit.dashboard(self.con, "juniper", {"appointment": {"slot": slot}}, TODAY)
        self.assertEqual(len(booked["appointments"]["upcoming"]), 1)
        self.assertTrue(booked["blocked"], "booking alone doesn't clear the hold")
        self.assertFalse(self.audit.dashboard(self.con, "juniper", {"met": True}, TODAY)["blocked"])

    def test_winter_plan_has_no_clashes_and_respects_prerequisites(self):
        for slug in ("juniper", "mateo", "priya", "devon", "tessa"):
            plan = self.audit.winter_plan(self.con, slug, {})
            self.assertTrue(plan["picks"], slug)
            meetings = [p["option"]["lecture"]["meetings"] + (p["option"]["linked"]["meetings"] if p["option"]["linked"] else [])
                        for p in plan["picks"]]
            for i in range(len(meetings)):
                for j in range(i + 1, len(meetings)):
                    self.assertFalse(store.overlaps(meetings[i], meetings[j]), f"{slug}: two picks overlap")
            self.assertLessEqual(plan["credits"], 19)

    def test_tessa_has_the_confusing_line_explained(self):
        report = self.audit.audit(self.con, "tessa", {})
        lines = [r for b in report["blocks"] for r in b["requirements"] if r["status"] == "not_met"]
        self.assertEqual(len(lines), 1)
        self.assertIn("C or better", report["notes"]["not_met"]["text"])

    def test_what_if_and_billing(self):
        program = self.audit.find_program(self.con, "computer science")
        result = self.audit.what_if(self.con, "mateo", program["id"])
        self.assertGreater(len(result["counted"]), 0)
        self.assertEqual(result["total"], len(result["counted"]) + len(result["in_progress"]) + len(result["needed"]))
        priya = self.audit.dashboard(self.con, "priya", {}, TODAY)
        self.assertGreater(priya["billing"]["past_due"], 0)
        self.assertTrue(priya["blocked"])
        self.assertFalse(self.audit.dashboard(self.con, "priya", {"paid": True}, TODAY)["blocked"])

    def test_no_real_looking_identities(self):
        for s in self.con.execute("SELECT email, sample_id FROM students"):
            self.assertTrue(s["email"].endswith("@example.com"))
            self.assertRegex(s["sample_id"], r"^SAMPLE-\d{4}$")


class Server(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from beaverbot.server import make_server
        cls.server = make_server("127.0.0.1", 0, quiet=True)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def get(self, path):
        try:
            with urllib.request.urlopen(self.base + path, timeout=20) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def post(self, path, body, raw: bytes | None = None):
        req = urllib.request.Request(self.base + path, data=raw if raw is not None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def events(self, body):
        status, headers, raw = self.post("/api/ask", body)
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("text/event-stream"))
        out = []
        for block in raw.decode("utf-8").split("\n\n"):
            if block.strip():
                event, data = block.split("\n", 1)
                out.append((event.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
        return out

    def test_pages_static_files_and_security_headers(self):
        for path in ("/", "/topics", "/deadlines", "/offices", "/saved", "/about"):
            status, headers, body = self.get(path)
            self.assertEqual(status, 200, path)
            self.assertIn(b"Beaver Bot", body)
            self.assertIn("default-src 'self'", headers["Content-Security-Policy"])
            self.assertEqual(headers["Referrer-Policy"], "no-referrer")
        self.assertEqual(self.get("/static/css/base.css")[0], 200)
        self.assertTrue(self.get("/static/js/app.js")[1]["Content-Type"].startswith("text/javascript"))
        self.assertEqual(self.get("/nope")[0], 404)

    def test_the_databases_are_never_served(self):
        for path in ("/data/osu.sqlite", "/static/../../data/osu.sqlite", "/static/..%2f..%2fdata/demo.db",
                     "/static/../config.py", "/osu.sqlite"):
            status, headers, body = self.get(path)
            self.assertEqual(status, 404, path)
            self.assertFalse(body.startswith(b"SQLite format"), path)

    def test_config_and_offices(self):
        cfg = json.loads(self.get("/api/config")[2])
        self.assertEqual(cfg["name"], "Beaver Bot")
        self.assertEqual(len(cfg["popular"]["en"]), 6)
        self.assertEqual(len(cfg["popular"]["es"]), 6)
        offices = json.loads(self.get("/api/offices")[2])["offices"]
        self.assertTrue(any(o["phone"] for o in offices))
        self.assertTrue(all(o["url"].startswith("https://") for o in offices))

    def test_bad_requests_are_refused(self):
        self.assertEqual(self.post("/api/ask", {"question": ""})[0], 400)
        self.assertEqual(self.post("/api/ask", None, raw=b"not json")[0], 400)
        self.assertEqual(self.post("/api/ask", None, raw=b"x" * 40_000)[0], 400)
        self.assertEqual(self.post("/api/nothing", {"a": 1})[0], 404)
        self.assertEqual(json.loads(self.post("/api/feedback", {"rating": "maybe"})[2]), {"ok": False})

    @unittest.skipUnless(HAVE_PAGES, "needs data/osu.sqlite")
    def test_a_question_streams_status_then_the_answer(self):
        with mock.patch.dict(os.environ, {"ASSISTANT_PROVIDER": "guide", "BEAVERBOT_STREAM_MS": "0"}):
            events = self.events({"question": "How do I drop a class?", "lang": "en"})
        kinds = [e for e, _ in events]
        self.assertEqual(kinds[0], "status")
        self.assertLess(kinds.index("meta"), kinds.index("delta"))
        self.assertEqual(kinds[-1], "done")
        meta = dict(events)["meta"]
        self.assertEqual(meta["kind"], "answer")
        self.assertTrue(meta["pages"][0]["url"].startswith("https://registrar.oregonstate.edu/"))
        self.assertEqual("".join(d["t"] for e, d in events if e == "delta"), dict(events)["done"]["text"])

    @unittest.skipUnless(HAVE_PAGES and HAVE_DEMO, "needs both databases")
    def test_demo_questions_use_sample_data_only_when_signed_in(self):
        with mock.patch.dict(os.environ, {"ASSISTANT_PROVIDER": "guide", "BEAVERBOT_STREAM_MS": "0"}):
            signed_out = dict(self.events({"question": "What's my balance?"}))["meta"]
            claimed = dict(self.events({"question": "What's my balance?", "demo": {"student": "juniper", "state": {}}}))["meta"]
            crisis = dict(self.events({"question": "I want to hurt myself", "demo": {"student": "juniper", "state": {}}}))["meta"]
        self.assertEqual((signed_out["kind"], signed_out["reason"]), ("refusal", "own_records"))
        self.assertEqual((claimed["kind"], claimed["reason"]), ("refusal", "own_records"),
                         "naming a student in the request signs nobody in: identity comes only from the session (tests/test_hub.py)")
        self.assertEqual(crisis["kind"], "crisis", "the crisis step comes before everything, signed in or not")

    @unittest.skipUnless(HAVE_DEMO, "needs data/demo.db")
    def test_demo_api(self):
        students = json.loads(self.get("/api/demo/students")[2])["students"]
        self.assertEqual({s["slug"] for s in students}, {"juniper", "mateo", "priya", "devon", "tessa"})
        self.assertEqual(self.post("/api/demo/student", {"student": "juniper", "state": {}})[0], 404, "student data needs a session now")
        self.assertTrue(json.loads(self.get("/api/demo/courses?q=calculus")[2])["courses"])
        self.assertTrue(json.loads(self.get("/api/demo/forms?q=grading")[2])["forms"])
        self.assertGreater(len(json.loads(self.get("/api/demo/resources?q=bill")[2])["resources"]), 2)


if __name__ == "__main__":
    unittest.main()
