"""The conversation layer (beaverbot/talk.py): which action a turn takes, and the checks on what a model wrote.

No network and no paid calls: the model is a scripted stand-in that returns the JSON a real one would. Searches
are replaced with fixed excerpts, so these tests don't need the crawled pages. Tests that use the sample student
database (data/demo.db) are skipped when it is absent.
"""
import datetime
import json
import sqlite3
import unittest
from unittest import mock

from assistant.guide import GuideProvider
from assistant.providers import ScriptedProvider
from assistant.retrieve import Hit
from beaverbot import config, spanish, talk
from beaverbot.demo import finder, intents, store

HAVE_PAGES = config.OSU_DB.exists()
HAVE_DEMO = config.DEMO_DB.exists()
TODAY = datetime.date(2026, 11, 9)

TUTORING = Hit(chunk_id=7, score=9.0, coverage=1.0, title="Tutoring", heading_path="Tutoring",
               url="https://success.oregonstate.edu/tutoring", page_url="https://success.oregonstate.edu/tutoring",
               retrieved_at="2026-11-01", office="Academic Success Center", excerpt="",
               text="Drop-in tutoring is free for all OSU students. Tutors are in the Valley Library, room 125. "
                    "No appointment is needed.")
HOURS = Hit(chunk_id=8, score=8.0, coverage=1.0, title="Tutoring hours", heading_path="Hours",
            url="https://success.oregonstate.edu/tutoring-hours", page_url="https://success.oregonstate.edu/tutoring-hours",
            retrieved_at="2026-11-01", office="Academic Success Center", excerpt="",
            text="Tutoring is open Sunday through Thursday from 10 a.m. to 8 p.m. during the term.")


def reply(action, text="", **fields):
    """One model turn, in the JSON format talk.SCHEMA asks for."""
    base = {"action": action, "reply": text, "citations": [], "search_query": "", "tool": "", "course": "", "times": [],
            "avoid": [], "where": "any", "after": "", "before": "", "show_options": False, "number": 0, "program": "",
            "query": "", "suggestions": []}
    base.update(fields)
    return json.dumps(base)


def empty_db():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript("CREATE TABLE pages (id INTEGER PRIMARY KEY, url TEXT, title TEXT, retrieved_at TEXT, owning_office TEXT, gone_at TEXT);"
                      "CREATE TABLE chunks (id INTEGER PRIMARY KEY, page_id INTEGER, seq INTEGER, heading_path TEXT, anchor TEXT, text TEXT);")
    return con


class Turn(unittest.TestCase):
    """One message in, one payload out, with a scripted model."""

    def setUp(self):
        self.searches = []
        self.results = {}                      # search words -> hits; anything else gets self.default
        self.default = [TUTORING]

        def find(con, search_question, today, emit):
            self.searches.append(search_question)
            return list(self.results.get(search_question, self.default))

        for patch in (mock.patch.object(talk, "_find", find), mock.patch.object(config, "pinned_mode", lambda: "off")):
            patch.start()
            self.addCleanup(patch.stop)

    def say(self, question, outputs, **kw):
        self.model = ScriptedProvider(outputs)
        return talk.converse(question, con=empty_db(), provider=self.model, today=TODAY, **kw)

    # -- chat ---------------------------------------------------------------------------------------
    def test_a_greeting_is_just_a_reply(self):
        res = self.say("hi", [reply("chat", "Hey! What's on your mind?", suggestions=["When is the add/drop deadline?", "Where do I get tutoring?"])])
        self.assertEqual((res["kind"], res["text"], res["mode"]), ("chat", "Hey! What's on your mind?", "scripted"))
        self.assertEqual(res["followups"], ["When is the add/drop deadline?", "Where do I get tutoring?"])
        self.assertEqual((res["pages"], res["contacts"]), ([], []), "small talk shows no sources and no office")

    def test_the_model_sees_the_conversation_so_far(self):
        history = [{"role": "user", "text": "where do i get tutoring"}, {"role": "bot", "text": "In the Valley Library."}]
        self.say("is it free?", [reply("chat", "Yes.")], history=history)
        prompt = self.model.calls[0][1]
        self.assertIn("Student: where do i get tutoring", prompt)
        self.assertIn("Beaver Bot: In the Valley Library.", prompt)
        self.assertEqual(self.searches, ["where do i get tutoring is it free?"], "a short follow-up is searched with the message before it")

    def test_history_is_trimmed_and_redacted(self):
        history = [{"role": "user", "text": f"message {i}"} for i in range(12)]
        history += [{"role": "user", "text": "my email is someone@example.com " + "x" * 2000}, {"role": "nobody", "text": "skip me"}, "junk"]
        clean = talk.clean_history(history)
        self.assertEqual(len(clean), talk.MAX_HISTORY)
        self.assertIn("[email removed]", clean[-1]["text"])
        self.assertLessEqual(len(clean[-1]["text"]), talk.MAX_TURN_CHARS)
        self.assertEqual(talk.clean_history("not a list"), [])

    def test_a_chat_reply_with_an_unsourced_fact_goes_back_once_and_can_become_a_real_answer(self):
        good = reply("answer", "Yes, drop-in tutoring is free. [1]", citations=[{"chunk_id": 7, "quote": "Drop-in tutoring is free for all OSU students."}])
        res = self.say("is tutoring free?", [reply("chat", "Yes, the Academic Success Center tutoring is free."), good])
        self.assertEqual(res["kind"], "answer")
        self.assertEqual(res["pages"][0]["url"], TUTORING.url)
        self.assertEqual(len(self.model.calls), 2)
        self.assertIn("<problems>", self.model.calls[1][1])
        self.assertIn("Academic", self.model.calls[1][1], "the second try is told which name had no source")

    def test_unchecked_text_is_never_shown_when_the_second_try_fails_too(self):
        bad = reply("chat", "It closes at 9 pm, call 541-737-0000.")
        res = self.say("when does tutoring close?", [bad, bad])
        self.assertEqual(res["kind"], "refusal")
        self.assertNotIn("541", res["text"])
        self.assertTrue(res["contacts"], "a real question that can't be answered names an office")
        vague = self.say("lol", [bad, bad])
        self.assertEqual((vague["kind"], vague["text"]), ("chat", talk.VAGUE[0]), "not a question: ask what they meant")

    def test_what_a_chat_reply_may_and_may_not_say(self):
        known, allowed = talk._words("whats my gpa"), talk._numbers("i have 3 classes")
        ok = lambda text, q="": talk._chat_problems(text, allowed, known, question=q)      # noqa: E731
        self.assertEqual(ok("I can't see your GPA, since this site never sees real records. You said 3 classes."), [])
        self.assertEqual(ok('Try asking "When is the deadline?" or "How do I drop a class?"'), [], "a quoted example isn't a name")
        self.assertEqual(ok("Hola. ¿Qué necesitas? Puedo ayudarte con OSU."), [])
        self.assertTrue(ok("Your GPA is in MyDegrees."))
        self.assertTrue(ok("Ask the Registrar about that."))
        self.assertTrue(ok("CAPS can help."))
        self.assertTrue(ok("It costs 15 dollars."))
        self.assertTrue(ok("See oregonstate.edu for more."))
        self.assertTrue(ok("OSU has poetry classes and lit journals."))
        self.assertTrue(ok("That is the official rule."))
        self.assertTrue(ok("Want me to look that up?", "is tutoring free?"), "a question gets a search, not an offer to search")
        self.assertEqual(ok("Tell me the class and I'll look it up.", "tutoring"), [], "asking back is fine when the message was vague")
        self.assertTrue(ok(""))

    # -- answers ------------------------------------------------------------------------------------
    def test_an_answer_is_shown_only_with_quotes_that_are_on_the_page(self):
        good = reply("answer", "Good question. Tutoring is free. [1]\n\n[2]\n+ Go to the Valley Library, room 125.",
                     citations=[{"chunk_id": 7, "quote": "Drop-in tutoring is free for all OSU students."},
                                {"chunk_id": 7, "quote": "Tutors are in the Valley Library, room 125."}],
                     suggestions=["What are the hours?", "Do I need an appointment?"])
        res = self.say("where do i get tutoring?", [good])
        self.assertEqual(res["kind"], "answer")
        self.assertEqual(res["text"], "Tutoring is free. [1] [2]\n+ Go to the Valley Library, room 125.", "filler opener, blank line and stray marker are tidied")
        self.assertEqual(res["followups"], ["What are the hours?", "Do I need an appointment?"])
        self.assertEqual(res["pages"][0]["quotes"], ["Drop-in tutoring is free for all OSU students.", "Tutors are in the Valley Library, room 125."])

    def test_a_made_up_quote_is_retried_then_replaced_never_shown(self):
        fake = reply("answer", "Tutoring costs $40 an hour. [1]", citations=[{"chunk_id": 7, "quote": "Tutoring costs $40 an hour."}])
        res = self.say("how much is tutoring?", [fake, fake])
        self.assertEqual(len(self.model.calls), 2)
        self.assertNotIn("$40", res["text"])
        self.assertIn(res["kind"], ("answer", "refusal"))
        if res["kind"] == "answer":
            self.assertEqual(res["mode"], "guide", "the fallback is exact quotes from the page")

    def test_the_word_excerpt_never_reaches_the_student(self):
        self.assertEqual(talk._tidy("The excerpts I found cover one case. Excerpt two says more."), "The pages I found cover one case. Page two says more.")
        self.assertEqual(talk._tidy("Great question! Here you go.", one_line=True), "Here you go.")

    # -- search -------------------------------------------------------------------------------------
    def test_the_model_can_search_again_and_keeps_what_it_already_found(self):
        self.results["tutoring hours"] = [HOURS]
        good = reply("answer", "It's open Sunday through Thursday. [1] It's free too. [2]",
                     citations=[{"chunk_id": 8, "quote": "Tutoring is open Sunday through Thursday from 10 a.m. to 8 p.m. during the term."},
                                {"chunk_id": 7, "quote": "Drop-in tutoring is free for all OSU students."}])
        res = self.say("when can i go?", [reply("search", search_query="tutoring hours"), good])
        self.assertEqual(self.searches, ["when can i go?", "tutoring hours"])
        self.assertEqual(res["kind"], "answer")
        self.assertEqual({p["url"] for p in res["pages"]}, {HOURS.url, TUTORING.url})
        self.assertIn("<searches_tried>\ntutoring hours", self.model.calls[1][1])

    def test_an_answer_that_admits_a_gap_must_search_first(self):
        """ "Math study rooms aren't listed..." without having looked under other words is sent back to search."""
        self.results["math tutoring learning center"] = [HOURS]
        gap = reply("answer", "Math-specific study rooms aren't listed on OSU's pages, but drop-in tutoring is free. [1]",
                    citations=[{"chunk_id": 7, "quote": "Drop-in tutoring is free for all OSU students."}])
        good = reply("answer", "Tutoring is in the Valley Library, room 125. [1] It runs Sunday through Thursday. [2]",
                     citations=[{"chunk_id": 7, "quote": "Tutors are in the Valley Library, room 125."},
                                {"chunk_id": 8, "quote": "Tutoring is open Sunday through Thursday from 10 a.m. to 8 p.m. during the term."}])
        res = self.say("where are the study rooms for math", [gap, reply("search", search_query="math tutoring learning center"), good])
        self.assertEqual(self.searches, ["where are the study rooms for math", "math tutoring learning center"])
        self.assertIn("haven't used your search tool", self.model.calls[1][1])
        self.assertEqual(res["kind"], "answer")
        self.assertFalse(talk.source_talk(res["text"]), res["text"])
        self.assertTrue(res["text"].startswith("Tutoring is in the Valley Library"))

    def test_an_answer_never_talks_about_its_sources(self):
        for bad in ("Math study rooms aren't listed on OSU's pages, but the library has rooms.", "According to OSU's page, tutoring is free.",
                    "I couldn't find that in the database.", "My search didn't turn up a math room.", "The stored pages don't say.",
                    "Las salas no aparecen en las páginas de OSU."):
            self.assertTrue(talk.source_talk(bad), bad)
        for fine in ("The MSLC is in 108 Kidder Hall. [1] I didn't find a room just for math, but the library has rooms you can reserve. [2]",
                     "Drop-in tutoring is free for all OSU students. [1]", "The Valley Library lists its study rooms by floor. [1]"):
            self.assertFalse(talk.source_talk(fine), fine)
        # after a search has been done, source talk still gets one rewrite before the reply is shown
        talky = reply("answer", "OSU's pages say drop-in tutoring is free. [1]", citations=[{"chunk_id": 7, "quote": "Drop-in tutoring is free for all OSU students."}])
        clean = reply("answer", "Drop-in tutoring is free. [1]", citations=[{"chunk_id": 7, "quote": "Drop-in tutoring is free for all OSU students."}])
        res = self.say("is tutoring free", [talky, clean])
        self.assertEqual(res["text"], "Drop-in tutoring is free. [1]")
        self.assertIn("talks about the sources", self.model.calls[1][1])
        self.assertNotIn('say "OSU' + "'s page" + '"', talk.BASE)
        self.assertIn("Lead with the best answer", talk.BASE)

    def test_a_subject_pulls_in_its_own_help_center(self):
        from assistant import owners
        ids = lambda q: [t.id for t in owners.topics_for(q)]       # noqa: E731
        self.assertIn("math-help", ids("where are the study rooms for math at osu"))
        self.assertIn("math-help", ids("i need help with MTH 252"))
        self.assertIn("chem-help", ids("where can I get help with chem"))
        self.assertIn("physics-help", ids("quiet place to study for physics"))
        self.assertIn("cs-help", ids("is there tutoring for CS 161"))
        self.assertIn("writing", ids("where can I get help writing a paper"))
        self.assertNotIn("math-help", ids("how do I take the math placement test"), "naming a subject alone is not asking for help with it")
        self.assertNotIn("math-help", ids("where can I reserve a study room"))
        self.assertIn("Learning Center", owners.expansion("where are the study rooms for math at osu"))
        self.assertTrue(owners.owns(owners.topics_for("math study group"), "https://math.oregonstate.edu/undergraduate/mathematics-statistics-learning-center"))

    def test_searching_stops_after_two_tries(self):
        again = [reply("search", search_query=f"try {i}") for i in range(5)]
        res = self.say("what is the meaning of the fifth floor?", again)
        self.assertEqual(len(self.searches), 1 + talk.MAX_SEARCHES)
        self.assertEqual(len(self.model.calls), talk.MAX_SEARCHES + 1)
        self.assertIn("No searches are left", self.model.calls[-1][1])
        self.assertEqual((res["kind"], res["reason"]), ("refusal", "model found no answer"))

    # -- I don't know -------------------------------------------------------------------------------
    def test_giving_up_without_searching_is_sent_back_once(self):
        self.say("can i bring my pet snake to class?", [reply("not_found", "No idea."), reply("not_found", "I couldn't find anything about snakes.")])
        self.assertEqual(len(self.model.calls), 2)
        self.assertIn("without using your search tool", self.model.calls[1][1])

    def test_not_found_uses_the_models_sentence_when_it_states_nothing(self):
        res = self.say("can i bring my pet snake to class?", [reply("not_found", "I couldn't find anything on OSU's pages about bringing a snake to class.")] * 2)
        self.assertEqual(res["kind"], "refusal")
        self.assertEqual(res["text"], "I couldn't find anything on OSU's pages about bringing a snake to class. This office can help:")
        self.assertTrue(res["contacts"])
        named = self.say("can i bring my pet snake to class?", [reply("not_found", "Ask the Registrar, they decide that.")] * 2)
        self.assertTrue(named["text"].startswith("I couldn't find that on OSU's public pages"), "a sentence that names an office is dropped")

    # -- crisis and the fixed rules -----------------------------------------------------------------
    def test_crisis_words_never_reach_a_model(self):
        res = self.say("i want to kill myself", [reply("chat", "nope")])
        self.assertEqual(res["kind"], "crisis")
        self.assertEqual(self.model.calls, [])
        self.assertEqual(self.searches, [])

    def test_the_model_can_also_raise_a_crisis_from_indirect_words(self):
        res = self.say("i dont see the point in anything anymore", [reply("crisis")])
        self.assertEqual(res["kind"], "crisis")
        self.assertIn("911", res["text"])

    def test_contact_details_and_live_seats_get_the_fixed_reply_without_a_model(self):
        for q, why in (("what's professor smith's email", "individual_contact"), ("how many seats are left in CS 161", "live_data")):
            res = self.say(q, [reply("chat", "nope")])
            self.assertEqual((res["kind"], res["reason"]), ("refusal", why), q)
            self.assertEqual(self.model.calls, [], q)

    def test_my_records_goes_to_the_model_which_cannot_use_a_tool_when_signed_out(self):
        res = self.say("whats my gpa", [reply("tool", "Sure.", tool="audit"),
                                       reply("chat", "I can't see your GPA, since this site never sees real records.")])
        self.assertEqual(res["kind"], "chat")
        self.assertTrue(res["offer_demo"], "the sample-data demo is offered")
        self.assertIn("isn't signed in", self.model.calls[1][1])

    def test_graded_work_is_flagged_to_the_model_and_a_long_reply_is_replaced(self):
        res = self.say("can you write my essay for me", [reply("chat", "I can't write it for you, but I can help you find writing support.")])
        self.assertEqual(res["kind"], "chat")
        self.assertIn("graded work", self.model.calls[0][1])
        essay = self.say("can you write my essay for me", [reply("chat", "Sure. " + "The beaver is a noble animal. " * 20)])
        self.assertEqual((essay["kind"], essay["reason"]), ("refusal", "academic_integrity"))

    # -- when the model is unavailable --------------------------------------------------------------
    def test_a_failing_model_falls_back_to_the_rules(self):
        def boom(system, user):
            raise ConnectionError("offline")
        with mock.patch("traceback.print_exc"):
            res = self.say("hi", boom)
        self.assertEqual((res["kind"], res["mode"]), ("chat", "rules"))

    def test_small_talk_without_a_model(self):
        for text, lang in (("hi", "en"), ("thanks!", "en"), ("what can you do?", "en"), ("who are you", "en"), ("hola", "es"), ("gracias", "es")):
            res = talk.converse(text, con=empty_db(), provider=GuideProvider(today=TODAY), today=TODAY)
            self.assertEqual((res["kind"], res["lang"]), ("chat", lang), text)
        self.assertIsNone(talk.small_talk("how do i drop a class", "en"))
        self.assertIn("Mateo", talk.small_talk("hey", "en", "Mateo")["text"])

    # -- language -----------------------------------------------------------------------------------
    def test_spanish_is_noticed_from_one_word_and_sticks_for_short_replies(self):
        self.assertTrue(spanish.is_spanish("hola"))
        self.assertTrue(spanish.is_spanish("ok", "¿cómo dejo una clase?"))
        self.assertFalse(spanish.is_spanish("ok thanks", "¿cómo dejo una clase?"))
        self.assertFalse(spanish.is_spanish("parking"))
        res = self.say("gracias", [reply("chat", "¡De nada!")])
        self.assertEqual(res["lang"], "es")
        self.assertIn("Spanish", self.model.calls[0][0])


@unittest.skipUnless(HAVE_DEMO, "needs data/demo.db (python -m beaverbot.demo.generate)")
class SignedIn(unittest.TestCase):
    """The same turn when signed in to the demo: tools run on sample data and change only the browser's state."""

    def setUp(self):
        for patch in (mock.patch.object(talk, "_find", lambda con, q, today, emit: [TUTORING]),
                      mock.patch.object(config, "pinned_mode", lambda: "off")):
            patch.start()
            self.addCleanup(patch.stop)
        self.con = store.connect()
        self.state, self.flow = {}, None

    def say(self, question, outputs, slug="mateo"):
        self.model = ScriptedProvider(outputs)
        res = talk.converse(question, con=empty_db(), provider=self.model, today=TODAY,
                            demo={"student": slug, "state": self.state, "flow": self.flow})
        if res["kind"] == "demo":
            self.flow = res.get("flow")
            self.state = store.apply_change(self.state, res.get("apply"))
        return res

    def test_the_reported_conversation(self):
        res = self.say("i need to take vector calc", [reply("tool", "Vector calc, got it.", tool="find_class", course="vector calc")])
        self.assertEqual((res["kind"], res["tool"]), ("demo", "finder_prefs"))
        self.assertTrue(res["text"].startswith("Vector calc, got it. MTH 254 is Vector Calculus I."))
        res = self.say("mornings, no fridays", [reply("tool", "Okay.", tool="find_class", times=["morning"], avoid=["F"], show_options=True)])
        self.assertEqual(res["tool"], "finder_options")
        self.assertIn("Class finder: working on MTH 254; options shown: 1)", talk.sample_context(self.con, "mateo", self.state, self.flow, TODAY))
        res = self.say("add it to my calendar", [reply("tool", "Sure.", tool="add_to_plan", number=1)])
        self.assertEqual(res["apply"]["type"], "plan_add")
        self.assertEqual([p["lecture"]["course"] for p in store.plan_sections(self.con, self.state)], ["MTH 254"])
        res = self.say("actually drop it", [reply("tool", "No problem.", tool="drop_from_plan")])
        self.assertEqual(res["apply"]["type"], "plan_drop")
        self.assertEqual(store.clean_state(self.state)["plan"], [])
        self.assertTrue(res["sample"])

    def test_the_model_words_a_tool_result_and_made_up_details_fall_back_to_the_fixed_sentence(self):
        ask = reply("tool", "Sure.", tool="remaining")
        res = self.say("i think i need vector calc", [ask, json.dumps({"reply": "Vector calc isn't on your list, Juniper. Want me to find sections anyway?"})], slug="juniper")
        self.assertEqual(res["text"], "Vector calc isn't on your list, Juniper. Want me to find sections anyway?")
        self.assertIn("Requirements left: WR 227Z Technical Writing", res["said"], "the card's contents go into the conversation memory")
        self.assertIn("<tool_result", self.model.calls[1][1])
        bad = self.say("what do i still need", [ask, json.dumps({"reply": "You need PH 211 and 47 more credits."})], slug="juniper")
        self.assertTrue(bad["text"].startswith("Sure. You have 3 requirements left"))

    def test_advisor_times_are_matched_from_plain_words(self):
        slots = store.slots(self.con, store.student_row(self.con, "juniper")["id"], TODAY)
        pick = lambda text: (lambda s: s and f"{s['date']} {s['time_label']}")(intents.match_slot(slots, text))     # noqa: E731
        self.assertEqual(pick("thursday afternoon"), "2026-11-12 1:00 PM")
        self.assertEqual(pick("friday morning"), "2026-11-13 10:00 AM")
        self.assertEqual(pick("earliest"), "2026-11-10 9:00 AM")
        self.assertEqual(pick("tomorrow at 2:30"), "2026-11-10 2:30 PM")
        self.assertIsNone(pick("wednesday afternoon"))
        res = self.say("move it to friday morning", [reply("tool", "Okay.", tool="book_appointment", query="friday morning")], slug="juniper")
        self.assertIn("Friday, Nov 13 at 10:00 AM", res["text"])
        none = self.say("wednesday afternoon?", [reply("tool", "Okay.", tool="book_appointment", query="wednesday afternoon")], slug="juniper")
        self.assertIn("Nothing is open wednesday afternoon", none["text"])
        self.assertIsNone(none["apply"])

    def test_a_lead_in_is_a_few_words_with_no_new_numbers(self):
        tool = lambda lead: self.say("how much do i owe", [reply("tool", lead, tool="billing")])["text"]      # noqa: E731
        self.assertTrue(tool("Let me check.").startswith("Let me check. "))
        self.assertFalse(tool("You owe $999.99 right now.").startswith("You owe $999"))
        self.assertFalse(tool("Sure, I will go ahead and pull up every single detail of your bill right now.").startswith("Sure"))
        self.assertTrue(tool("Sure. I'll pull up every detail of your bill and your whole account.").startswith("Sure. You"), "only the first sentence is kept")

    def test_the_record_is_in_the_prompt_and_can_be_quoted_in_a_chat_reply(self):
        context = talk.sample_context(self.con, "tessa", {}, {}, TODAY)
        for needle in ("Tessa Fern", "Mechanical Engineering", "GPA: 2.75 overall", "Advisor: Sage Timbertooth", "Minimum grade not met",
                       "ME 316 with a D+", "Open advisor times: 1)", "This term's classes: ENGR 390 Engineering Economy"):
            self.assertIn(needle, context)
        self.assertNotIn("@", context, "no email addresses, even made-up ones")
        res = self.say("who's my advisor?", [reply("chat", "Your advisor is Sage Timbertooth, in College of Engineering advising.")], slug="tessa")
        self.assertEqual(res["kind"], "chat")
        self.assertIn("<sample_student>", self.model.calls[0][1])
        made_up = self.say("who's my advisor?", [reply("chat", "Your advisor is Dr. Pat Quincy.")] * 2, slug="tessa")
        self.assertNotIn("Quincy", made_up["text"], "a name that isn't in the record is not shown")

    def test_booking_moving_and_cancelling_an_advisor_meeting(self):
        res = self.say("book the second time", [reply("tool", "Sure.", tool="book_appointment", number=2)], slug="juniper")
        self.assertEqual((res["tool"], res["apply"]["type"]), ("appointment", "book"))
        self.assertIn("Booked.", res["text"])
        res = self.say("move it to the first one", [reply("tool", "Okay.", tool="book_appointment", number=1)], slug="juniper")
        self.assertIn("Moved.", res["text"])
        res = self.say("cancel it", [reply("tool", "Done.", tool="cancel_appointment")], slug="juniper")
        self.assertEqual(res["apply"]["type"], "cancel_appointment")
        self.assertTrue(store.clean_state(self.state)["cancelled"])

    def test_a_whole_suggested_plan_can_be_added(self):
        res = self.say("add all of those", [reply("tool", "On it.", tool="add_plan_all")], slug="juniper")
        self.assertEqual(res["apply"]["type"], "plan_add_many")
        self.assertGreaterEqual(len(store.clean_state(self.state)["plan"]), 3)
        self.assertEqual(intents.run_tool(self.con, "juniper", {}, {}, "no_such_tool", {}, TODAY), None)

    def test_work_hours_become_time_bounds(self):
        self.assertEqual(finder.clean_prefs({"after": "15:00", "before": "25:99"})["after"], 900)
        self.assertIsNone(finder.clean_prefs({"before": "25:99"})["before"])
        found = finder.find(self.con, "juniper", "CS 261", {"after": "15:00"}, {})
        for option in found["options"]:
            for m in option["lecture"]["meetings"]:
                self.assertTrue(m["tba"] or m["start"] >= 900)
        self.assertIn("starting 3:00 PM or later", found["prefs_label"])

    def test_asking_about_the_advisor_is_not_blocked_as_a_contact_request(self):
        res = self.say("what's my advisor's email?", [reply("tool", "No email here.", tool="appointment")], slug="juniper")
        self.assertEqual((res["kind"], res["tool"]), ("demo", "appointment"))

    def test_osu_questions_still_get_sourced_answers_when_signed_in(self):
        good = reply("answer", "Drop-in tutoring is free. [1]", citations=[{"chunk_id": 7, "quote": "Drop-in tutoring is free for all OSU students."}])
        res = self.say("is tutoring free?", [good])
        self.assertEqual(res["kind"], "answer")
        self.assertEqual(res["pages"][0]["url"], TUTORING.url)


@unittest.skipUnless(HAVE_PAGES, "needs the crawled pages (data/osu.sqlite)")
class WithPages(unittest.TestCase):
    def test_neighbouring_excerpts_and_the_hand_checked_answer_are_given_to_the_model(self):
        from beaverbot import answers
        con = answers.connect()
        hits = talk._find(con, "how many credits to graduate", TODAY, lambda e, d: None)
        top = next(h for h in hits if not h.url.startswith(answers.CALENDAR_URL))
        around = {h.chunk_id for h in answers.neighbors(con, top)}
        self.assertTrue(around and around <= {h.chunk_id for h in hits}, "the paragraphs around the best match come along")
        model = ScriptedProvider([reply("not_found")] * 2)
        with mock.patch.object(config, "pinned_mode", lambda: "fallback"):
            talk.converse("how many credits to graduate", con=con, provider=model, today=TODAY)
        self.assertIn("<checked_answer>", model.calls[0][1])
        self.assertIn("180 earned credits", model.calls[0][1])

    def test_without_a_model_a_vague_message_gets_a_question_back_not_an_office(self):
        res = talk.converse("asdfgh", provider=GuideProvider(today=TODAY), today=TODAY)
        self.assertEqual((res["kind"], res["text"]), ("chat", talk.VAGUE[0]))
        self.assertTrue(res["followups"])


if __name__ == "__main__":
    unittest.main()
