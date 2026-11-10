"""The schedule a student edits in the chat before adding it (beaverbot/demo/draft.py), the class rows in a review,
and the rule that a chat reply only points at a card when one is really shown.

No network beyond a test server on 127.0.0.1, no model, sample data only. Skipped when data/demo.db is absent.
"""
import copy
import json
import re
import unittest
from pathlib import Path
from unittest import mock

from beaverbot import config, talk
from beaverbot.demo import draft, es, finder, hub as H, store, systems as S
from tests import test_hub
from tests.test_hub import ACCOUNTS, Clock, sign_in

HAVE_DEMO = config.DEMO_DB.exists()
TERM = "202702"


@unittest.skipUnless(HAVE_DEMO, "needs data/demo.db (python -m beaverbot.demo.generate)")
class EditingADraft(unittest.TestCase):
    def setUp(self):
        self.hub = H.Hub(Clock())
        self.con = store.connect()

    def ctx(self, slug="juniper"):
        return S.context(self.con, sign_in(self.hub, slug))

    def sections(self, code):
        return finder.details(self.con, code, TERM)["sections"]

    def test_every_student_gets_rows_with_a_line_per_meeting_and_nothing_changes(self):
        for slug in sorted(ACCOUNTS):
            ctx = self.ctx(slug)
            before = copy.deepcopy(ctx.state)
            d = draft.evaluate(ctx, TERM, draft.suggested(ctx))
            self.assertTrue(d["rows"], slug)
            for r in d["rows"]:
                self.assertTrue(r["code"] and r["name"] and r["times"] and r["credits"] > 0, (slug, r["code"]))
                self.assertRegex(r["times"][0], r"^\w+ \w+ · ", "the section, then when it meets")
                self.assertEqual(len(r["times"]), 2 if r["linked"] else 1)
            self.assertEqual(d["credits"]["adding"], sum(r["credits"] for r in d["rows"]))
            self.assertEqual(d["conflicts"], [], f"{slug}: the suggested plan has no clashes")
            self.assertTrue(d["sample"])
            self.assertEqual(ctx.state, before, "looking at a draft changes nothing")
            self.assertEqual(ctx.session.proposals, {}, "and files no proposal")

    def test_a_draft_holds_only_real_sections_of_this_term_one_per_course(self):
        ctx = self.ctx()
        a, b = self.sections("CS 261")[0]["crn"], self.sections("CS 261")[1]["crn"]
        fall = finder.details(self.con, "CS 261", "202701")["sections"][0]["crn"]
        d = draft.evaluate(ctx, TERM, [{"crn": a}, {"crn": b}, {"crn": 1}, {"crn": "x"}, "junk", {"crn": fall}, None])
        self.assertEqual([r["crn"] for r in d["rows"]], [a])
        self.assertEqual(draft.evaluate(ctx, TERM, "nonsense")["rows"], [])
        many = [{"crn": finder.details(self.con, c["code"], TERM)["sections"][0]["crn"]} for c in store.search_courses(self.con, "MTH", 30)
                if finder.details(self.con, c["code"], TERM)["sections"]]
        self.assertLessEqual(len(draft.evaluate(ctx, TERM, many)["rows"]), draft.MAX_ROWS)
        with self.assertRaises(H.Refused):
            draft.evaluate(ctx, "202701", [])                # the term under way can't be re-planned
        with self.assertRaises(H.Refused):
            draft.evaluate(ctx, "209901", [])

    def test_removing_and_swapping_update_credits_and_clashes(self):
        ctx = self.ctx()
        items = draft.suggested(ctx)
        full = draft.evaluate(ctx, TERM, items)
        less = draft.evaluate(ctx, TERM, items[1:])
        self.assertEqual(less["credits"]["adding"], full["credits"]["adding"] - full["rows"][0]["credits"])
        # move the first class onto a section that meets when another class in the list does
        first = full["rows"][0]
        found = draft.sections(ctx, TERM, items, first["crn"])
        self.assertTrue(next(s for s in found["sections"] if s["current"])["crn"] == first["crn"])
        self.assertEqual(found["code"], first["code"])
        others = [r for r in full["rows"][1:] if not all(m["tba"] for m in r["lecture"]["meetings"])]
        clash = None
        for other in others:                      # find any pair of sections in the two courses that overlap
            for s in self.sections(first["code"]):
                for o in self.sections(other["code"]):
                    if store.overlaps(s["meetings"], o["meetings"]):
                        clash = (s["crn"], o["crn"], other["code"])
        self.assertTrue(clash, "the sample data has two sections that meet at the same time")
        rest = [i for i in items if i["crn"] not in (first["crn"], next(r["crn"] for r in full["rows"] if r["code"] == clash[2]))]
        d = draft.evaluate(ctx, TERM, [{"crn": clash[0]}, {"crn": clash[1]}] + rest)
        self.assertIn({"a": first["code"], "b": clash[2]}, d["conflicts"])
        row = d["rows"][0]
        self.assertIn(clash[2], row["clash"])
        self.assertTrue(any(clash[2] in n and "same time" in n for n in row["notes"]), row["notes"])
        marked = draft.sections(ctx, TERM, [{"crn": first["crn"]}, {"crn": clash[1]}], first["crn"])
        self.assertTrue(next(s for s in marked["sections"] if s["crn"] == clash[0])["clash"], "the section list marks the one that would clash")

    def test_a_linked_section_is_kept_when_chosen_and_picked_when_not(self):
        ctx = self.ctx()
        lec = next(s for s in self.sections("CS 261") if len(s["linked"]) > 1)
        chosen = lec["linked"][-1]["crn"]
        self.assertEqual(draft.evaluate(ctx, TERM, [{"crn": lec["crn"], "linked": chosen}])["items"], [{"crn": lec["crn"], "linked": chosen}])
        auto = draft.evaluate(ctx, TERM, [{"crn": lec["crn"], "linked": 123}])["items"][0]["linked"]
        self.assertIn(auto, [k["crn"] for k in lec["linked"]], "a recitation that doesn't belong to the lecture is replaced by one that does")

    def test_replacements_meet_the_same_requirement_and_search_finds_any_class(self):
        for slug in sorted(ACCOUNTS):
            ctx = self.ctx(slug)
            items = draft.suggested(ctx)
            d = draft.evaluate(ctx, TERM, items)
            have = {r["code"] for r in d["rows"]}
            reqs = draft._requirements(ctx)
            for r in d["rows"]:
                found = draft.options(ctx, TERM, items, replace=r["crn"])
                if not r["requirement"]:
                    self.assertEqual(found["courses"], [])
                    continue
                self.assertEqual(found["requirement"], r["requirement"])
                allowed = next(q for q in reqs if q["label"] == r["requirement"] and r["code"] in q["codes"])["codes"]
                for c in found["courses"]:
                    self.assertIn(c["code"], allowed, f"{slug}: {c['code']} doesn't meet {r['requirement']}")
                    self.assertNotIn(c["code"], have)
                    self.assertEqual(c["item"]["crn"], c["crn"])
                    swapped = draft.evaluate(ctx, TERM, [c["item"] if i["crn"] == r["crn"] else i for i in items])
                    self.assertIn(c["code"], [x["code"] for x in swapped["rows"]])
        ctx = self.ctx("juniper")
        found = draft.options(ctx, TERM, draft.suggested(ctx), query="statistics")
        self.assertTrue(found["courses"] and all("ST" in c["code"] or "tatistic" in c["name"] for c in found["courses"]))
        self.assertEqual(draft.options(ctx, TERM, [], query="zzzz qqqq")["courses"], [])
        suggested = draft.options(ctx, TERM, [])["courses"]
        self.assertTrue(suggested and all(c["requirement"] for c in suggested), "with nothing typed, it offers classes the open requirements call for")

    def test_a_class_already_in_the_term_is_flagged_and_left_out_at_review(self):
        ctx = self.ctx()
        items = draft.suggested(ctx)
        p = S.propose(self.hub, ctx, "registration", {"type": "add", "term": TERM, **items[0]})
        S.confirm(self.hub, ctx, p["id"], p["token"])
        d = draft.evaluate(ctx, TERM, items)
        self.assertTrue(d["rows"][0]["blocked"])
        self.assertEqual(d["credits"]["existing"], d["rows"][0]["credits"])
        self.assertEqual(d["credits"]["adding"], sum(r["credits"] for r in d["rows"][1:]))
        self.assertEqual([r["code"] for r in d["existing"]], [d["rows"][0]["code"]])


@unittest.skipUnless(HAVE_DEMO, "needs data/demo.db (python -m beaverbot.demo.generate)")
class ReviewsListClassesAsRows(unittest.TestCase):
    def setUp(self):
        self.hub = H.Hub(Clock())
        self.con = store.connect()
        self.ctx = S.context(self.con, sign_in(self.hub, "juniper"))

    def test_adding_several_classes_gives_one_row_each_and_still_confirms(self):
        items = draft.suggested(self.ctx)
        p = S.propose(self.hub, self.ctx, "registration", {"type": "add_many", "term": TERM, "items": items})
        self.assertEqual(len(p["classes"]), len(p["effects"]), "the rows and the sentences describe the same change")
        for row, item in zip(p["classes"], items):
            self.assertEqual((row["action"], row["crn"]), ("add", item["crn"]))
            self.assertTrue(row["code"] and row["name"] and row["times"] and row["credits"])
        done = S.confirm(self.hub, self.ctx, p["id"], p["token"])
        self.assertTrue(done["can_undo"])
        self.assertEqual(len(S.read(self.ctx, "registration", term=TERM)["items"]), len(items))

    def test_classes_in_one_request_are_checked_against_each_other(self):
        a = finder.details(self.con, "CS 261", TERM)["sections"]
        pair = None
        for code in ("WR 227Z", "CH 221Z", "MTH 254", "ST 314"):
            for s in a:
                for o in finder.details(self.con, code, TERM)["sections"]:
                    if store.overlaps(s["meetings"], o["meetings"]) and not pair:
                        pair = (s["crn"], o["crn"], code)
        self.assertTrue(pair)
        p = S.propose(self.hub, self.ctx, "registration", {"type": "add_many", "term": TERM, "items": [{"crn": pair[0]}, {"crn": pair[1]}]})
        self.assertTrue(any(w.startswith(f"{pair[2]}: ") and "CS 261" in w for w in p["warnings"]), p["warnings"])
        twice = S.propose(self.hub, self.ctx, "registration", {"type": "add_many", "term": TERM, "items": [{"crn": a[0]["crn"]}, {"crn": a[1]["crn"]}]})
        self.assertEqual(len(twice["classes"]), 1, "the same course isn't added twice in one go")
        with self.assertRaises(H.Refused):
            S.propose(self.hub, self.ctx, "registration", {"type": "add_many", "term": TERM, "items": ["junk"]})

    def test_other_class_changes_carry_rows_too(self):
        do = lambda change: S.propose(self.hub, self.ctx, "registration", {"term": TERM, **change})      # noqa: E731
        secs = finder.details(self.con, "CS 261", TERM)["sections"]
        p = do({"type": "add", "crn": secs[0]["crn"]})
        self.assertEqual([c["action"] for c in p["classes"]], ["add"])
        S.confirm(self.hub, self.ctx, p["id"], p["token"])
        self.assertEqual([c["action"] for c in do({"type": "swap", "crn": secs[0]["crn"], "to_crn": secs[1]["crn"]})["classes"]], ["from", "to"])
        self.assertEqual([c["action"] for c in do({"type": "remove", "crn": secs[0]["crn"]})["classes"]], ["remove"])

    def test_rows_and_notes_come_out_in_spanish(self):
        items = draft.suggested(self.ctx)
        d = es.localize(draft.evaluate(self.ctx, TERM, items))
        self.assertRegex(d["rows"][0]["times"][0], r"^Clase \d+ · (lun|mar|mié|jue|vie)")
        self.assertEqual(es.localize({"times": ["Lecture 001 · Mon 9:00 AM to 9:50 AM · Driftwood Laboratory 424"]})["times"],
                         ["Clase 001 · lun 9:00 AM a 9:50 AM · Driftwood Laboratory 424"], "a building's name is left alone")
        self.assertEqual(es.say("CS 261: It meets at the same time as CH 221Z (Tue Thu 8:30 AM to 9:50 AM). The calendar shows the overlap."),
                         "CS 261: Se cruza con CH 221Z (mar jue 8:30 AM a 9:50 AM). El calendario muestra el cruce.")
        self.assertEqual(es.say("CS 261 is already in your Winter 2027 classes, so it won't be added again."),
                         "CS 261 ya está en tus clases de Winter 2027, así que no se agregará otra vez.")
        self.assertEqual(es.localize({"misses": ["starts at 8:00 AM", "its recitation overlaps your plan"]})["misses"], ["empieza a las 8:00 AM", "su recitación se cruza con tu plan"])
        self.assertEqual(es.say("Booked: you're meeting Cedar Gnawsworth tomorrow at 2:30 PM (zoom)."), "Reservado: te reúnes con Cedar Gnawsworth mañana a las 2:30 PM (zoom).")


class Scripted:
    name = "scripted"

    def __init__(self, text):
        self.text, self.systems = text, []

    def complete(self, system, user, *a, **k):
        self.systems.append(system)
        return json.dumps({"reply": self.text})


class ARepliesCard(unittest.TestCase):
    """A reply may say "the card below" only when a card is really shown under it."""

    def voice(self, tool, text, apply=None):
        model = Scripted(text)
        out = talk._voice(model, "what classes do i need", [], "Name: Sample", {"tool": tool, "apply": apply}, "You have 3 requirements left.", "en", {"3"}, set())
        return out, model.systems[0]

    def test_a_reply_with_nothing_under_it_is_never_described_as_a_card(self):
        out, system = self.voice("mystery", "Take a look at the card below for the three you have left.")
        self.assertIsNone(out, "the fixed sentence is used instead")
        self.assertIn("There is no card", system)
        self.assertNotIn("@@UNDER@@", system)
        self.assertEqual(self.voice("mystery", "You have 3 left. The button opens the full list.")[0], "You have 3 left. The button opens the full list.")
        self.assertIsNone(self.voice("mystery", "Mira la tarjeta de abajo.")[0])
        self.assertEqual(talk.without_card_talk("You owe $5. The card below has the details. Pay on myBill."), "You owe $5. Pay on myBill.")
        self.assertEqual(talk.without_card_talk("See the card below."), "Here's what I found.")

    def test_tools_that_do_show_a_card_may_point_at_it(self):
        for tool in sorted(talk.CARD_TOOLS):
            out, system = self.voice(tool, "It's all in the card below.")
            self.assertEqual(out, "It's all in the card below.")
            self.assertIn("A card with the details is shown", system)
        self.assertEqual(self.voice("appointment", "See the card below.", apply={"type": "book", "slot": 1})[0], "See the card below.", "a requested change gets a review card")


@unittest.skipUnless(HAVE_DEMO, "needs data/demo.db (python -m beaverbot.demo.generate)")
class EveryToolReplyHasACard(unittest.TestCase):
    """The rule behind "again no card": whenever a reply may mention a card, a card is sent and the page can draw it.
    Covers every chat tool, every sample student and every connected system."""

    ARGS = [{}, {"course": "MTH 254"}, {"course": "MTH 254", "show_options": True}, {"course": "zzzz"}, {"query": "change major"}, {"query": "print"},
            {"program": "psychology"}, {"slot": 1}, {"query": "friday morning"}, {"option": 1, "course": "WR 227Z"}, {"avoid": ["F"]}]

    def setUp(self):
        self.hub = H.Hub(Clock())
        self.con = store.connect()

    def replies(self, slug):
        from beaverbot.demo import intents
        ctx = S.context(self.con, sign_in(self.hub, slug))
        # before any preferences are saved, the class finder asks for them; afterwards it never does
        yield ctx, "find_class", intents.run_tool(self.con, slug, S.legacy(ctx), None, "find_class", {"course": "MTH 254"})
        for tool in intents.TOOLS:
            for args in self.ARGS:
                reply = intents.run_tool(self.con, slug, S.legacy(ctx), None, tool, dict(args))
                if reply:
                    yield ctx, tool, reply

    def test_every_reply_from_every_tool_gets_a_card_or_a_review(self):
        from beaverbot.demo import intents
        seen = set()
        for slug in sorted(ACCOUNTS):
            for ctx, tool, reply in self.replies(slug):
                seen.add(reply["tool"])
                self.assertIn(reply["tool"], intents.REPLY_TOOLS, f"{tool} replied as {reply['tool']}, which isn't listed")
                if reply.get("apply"):
                    continue                            # a requested change: the server sends a review card instead
                card = draft.chat_card(ctx, reply)
                self.assertTrue(card, f"{slug}: {tool} ({reply['tool']}) has text but no card: {reply['text'][:60]}")
                self.assertIn(card["kind"], ("draft", "prefs", "classes", "options", "site"))
                if card["kind"] == "site":
                    self.assertTrue(card["data"]["sample"] and card["data"]["system"] and card["data"]["source"] and card["panel"][0])
                self.assertEqual(es.localize(card)["kind"], card["kind"])
        self.assertEqual(seen, set(intents.REPLY_TOOLS), "every listed reply tool was exercised")
        self.assertEqual(talk.CARD_TOOLS, set(intents.REPLY_TOOLS), "the model is told there's a card exactly when there is one")

    def test_what_a_site_reply_says_matches_what_its_card_shows(self):
        from beaverbot.demo import intents
        for slug in sorted(ACCOUNTS):
            ctx = S.context(self.con, sign_in(self.hub, slug))
            for tool in intents.SITES:
                said = draft.site_facts(ctx, tool)
                self.assertTrue(said and said.endswith("."), (slug, tool))
                self.assertNotRegex(said, r"(?i)guaranteed|official|you should definitely")
            bill = S.read(ctx, "card")
            self.assertIn(f"${bill['accounts'][0]['balance']:,.2f}", draft.site_facts(ctx, "id_card"))
        self.assertIsNone(draft.site_facts(ctx, "mystery"))

    def test_every_connected_system_can_be_shown_in_the_chat(self):
        shown = {system for system, _, _ in draft.SITE_OF.values()} | {"registration"}
        self.assertEqual(set(S.SYSTEMS) - {"home"} - shown, set(), "a connected system with no chat card")
        for tool, (system, options, panel) in draft.SITE_OF.items():
            self.assertIn(system, S.SYSTEMS, tool)

    def test_the_page_can_draw_every_card_the_server_sends(self):
        hub_js = Path(__file__).resolve().parents[1] / "beaverbot" / "static" / "js" / "hub"
        briefs = (hub_js / "briefs.js").read_text(encoding="utf-8")
        body = briefs[briefs.index("export const BRIEF = {"):briefs.index("\n};", briefs.index("export const BRIEF = {"))]
        drawn = set(re.findall(r"^  (\w+): ", body, re.M))
        needed = {system for system, _, _ in draft.SITE_OF.values()} | set(draft.OWN_DATA)
        self.assertEqual(needed - drawn, set(), "the server sends a card for these, and briefs.js has nothing to draw it with")
        main = (hub_js / "main.js").read_text(encoding="utf-8")
        for kind, fn in (("draft", "showDraft("), ("prefs", "prefsCard("), ("classes", "classesCard("), ("options", "optionsCard("), ("site", "siteCard(")):
            self.assertIn(fn, main, kind)
        panels = (hub_js / "panels.js").read_text(encoding="utf-8")
        for tool, target in {**{t: v[2] for t, v in draft.SITE_OF.items()}, **draft.OWN_DATA}.items():
            self.assertIn(f'register("{target[0]}"', panels, f"{tool}: its Open link goes to a panel that doesn't exist")


@unittest.skipUnless(HAVE_DEMO, "needs data/demo.db (python -m beaverbot.demo.generate)")
class ThePlanIsAWorkingDraft(unittest.TestCase):
    """A suggested plan is kept in the visitor's sandbox on the server. The card's buttons and follow-ups in the chat
    edit that one draft, and each edit gives the whole plan back."""

    def setUp(self):
        from beaverbot.demo import intents
        self.intents = intents
        self.hub = H.Hub(Clock())
        self.con = store.connect()
        self.ctx = S.context(self.con, sign_in(self.hub, "juniper"))

    def tool(self, name, flow=None, **args):
        return self.intents.run_tool(self.con, "juniper", S.legacy(self.ctx), flow, name, args)

    def start(self):
        asked = self.tool("plan")
        self.assertEqual(asked["tool"], "plan_prefs", "the first time, it asks before building")
        self.assertEqual(draft.chat_card(self.ctx, asked)["kind"], "prefs")
        built = self.tool("plan", flow=asked["flow"])            # "just build it"
        self.assertEqual(built["tool"], "plan")
        return draft.chat_card(self.ctx, built)

    def test_the_first_plan_asks_once_then_the_draft_is_kept(self):
        card = self.start()
        self.assertEqual((card["kind"], card["version"], card["can_undo"]), ("draft", 1, False))
        self.assertEqual(S.read(self.ctx, "registration", term=TERM)["items"], [], "a draft is not the student's classes")
        again = self.tool("plan")
        self.assertEqual(again["tool"], "plan", "never asked twice")
        self.assertIn("as you left it", again["text"])
        self.assertEqual(draft.chat_card(self.ctx, again)["items"], card["items"])

    def test_swapping_from_the_chat_changes_one_row_and_gives_the_whole_plan_back(self):
        card = self.start()
        chem = next(r for r in card["rows"] if r["code"].startswith("CH "))
        shown = self.tool("find_class", course="chem", before="17:00")
        self.assertEqual(shown["tool"], "finder_options")
        self.assertEqual(shown["data"]["course"]["code"], chem["code"], '"chem" means the chemistry class in the plan')
        self.assertEqual(shown["data"]["swap"], chem["crn"])
        starts = [self.intents._start(o) for o in shown["data"]["options"]]
        self.assertEqual(starts, sorted(starts), "earliest first, so the card matches the words")
        self.assertRegex(shown["chips"][0], r"^Use the \d+:\d\d [AP]M one$")
        self.assertNotIn("Add the first one", shown["chips"])
        self.assertEqual(es.chip(shown["chips"][0])[:14], "Usa la de las ")
        self.assertEqual(self.tool("find_class", course="química")["data"]["course"]["code"], chem["code"], "the same in Spanish")
        self.assertEqual(self.tool("find_class", course="MTH 254")["data"]["course"]["code"], "MTH 254", "a course code always wins")
        options = draft.chat_card(self.ctx, shown)
        self.assertEqual((options["kind"], options["swap"], options["drafting"]), ("options", chem["crn"], True))
        picked = self.tool("add_to_plan", flow=shown["flow"], option=1)
        self.assertEqual(picked["apply"]["type"], "draft_put")
        self.assertIn("Swapped", picked["text"])
        after = draft.edit(self.ctx, {"op": "put", "crn": picked["apply"]["crn"], "linked": picked["apply"]["linked"]})
        self.assertEqual([r["code"] for r in after["rows"]], [r["code"] for r in card["rows"]], "every class is still there, in the same order")
        self.assertEqual([r["code"] for r in after["rows"]].count(chem["code"]), 1, "never two of the same course")
        self.assertEqual((after["changed"], after["version"], after["can_undo"]), (picked["apply"]["crn"], 2, True))
        self.assertNotEqual(next(r for r in after["rows"] if r["code"] == chem["code"])["crn"], chem["crn"])
        back = draft.edit(self.ctx, {"op": "undo"})
        self.assertEqual(back["items"], card["items"])
        self.assertFalse(back["can_undo"])
        with self.assertRaises(H.Refused):
            draft.edit(self.ctx, {"op": "undo"})

    def test_dropping_and_adding_from_the_chat_edit_the_draft(self):
        card = self.start()
        gone = self.tool("drop_from_plan", course=card["rows"][2]["code"])
        self.assertEqual(gone["apply"], {"type": "draft_drop", "crn": card["rows"][2]["crn"]})
        less = draft.edit(self.ctx, {"op": "drop", "crn": card["rows"][2]["crn"]})
        self.assertEqual(len(less["rows"]), len(card["rows"]) - 1)
        new = self.tool("add_to_plan", course="ST 314", option=1)
        self.assertEqual(new["apply"]["type"], "draft_put")
        more = draft.edit(self.ctx, {"op": "put", "crn": new["apply"]["crn"], "linked": new["apply"]["linked"]})
        self.assertIn("ST 314", [r["code"] for r in more["rows"]])
        with self.assertRaises(H.Refused):
            draft.edit(self.ctx, {"op": "put", "crn": 1})
        with self.assertRaises(H.Refused):
            draft.edit(self.ctx, {"op": "nonsense"})
        self.assertEqual(draft.edit(self.ctx, {"op": "clear"}), {"ok": True})
        self.assertIsNone(draft.saved(self.ctx))

    def test_answers_shape_the_plan_and_a_bend_names_the_class(self):
        card = draft.edit(self.ctx, {"op": "build", "prefs": {"times": ["morning", "midday", "junk"], "no8": True, "days": "four", "credits": "16+", "mode": "campus",
                                                              "busy": ["evenings"], "gap": "long", "note": "work  Tue 2 to 6 " + "x" * 300, "evil": "<script>"}})
        prefs = card["prefs"]
        self.assertEqual((prefs["times"], prefs["days"], prefs["credits"], prefs["busy"], prefs["no8"]), (["morning", "midday"], "four", "16+", ["evenings"], True))
        self.assertNotIn("evil", prefs)
        self.assertLessEqual(len(prefs["note"]), 120)
        self.assertGreaterEqual(card["credits"]["adding"], 15)
        for r in card["rows"]:
            for sec in (r["lecture"], r["linked"]):
                for m in (sec or {}).get("meetings", []):
                    if not m["tba"]:
                        self.assertNotIn("F", m["days"], f"{r['code']} meets on a Friday")
        self.assertTrue(card["bends"], "this sample student can't have everything in the morning")
        codes = {r["code"] for r in card["rows"]}
        self.assertTrue(all(b.split(":")[0] in codes or " and " in b for b in card["bends"]), card["bends"])
        self.assertEqual(draft.clean_answers("junk"), draft.clean_answers({}))
        plain = draft.edit(self.ctx, {"op": "build", "prefs": {}})
        self.assertEqual(plain["bends"], [])

    def test_the_class_finder_reuses_the_answers_and_never_asks_again(self):
        self.assertEqual(self.tool("find_class", course="MTH 254")["tool"], "finder_prefs", "with nothing answered yet, it asks")
        draft.edit(self.ctx, {"op": "build", "prefs": {"days": "tr"}})
        found = self.tool("find_class", course="MTH 254")
        self.assertEqual(found["tool"], "finder_options")
        self.assertEqual(found["data"]["prefs"]["avoid"], ["F", "M", "W"])


@unittest.skipUnless(HAVE_DEMO, "needs data/demo.db (python -m beaverbot.demo.generate)")
class OverHttpToo(test_hub.OverHttp):
    """Only what this file adds; the parent's own tests are not run again here."""

    def ask(self, sid, reply, body=None, lang="en", raw=False):
        give_raw = raw
        from beaverbot import server as server_module
        with mock.patch.object(server_module, "library_ready", lambda: True), mock.patch.object(server_module.talk, "converse", lambda *a, **k: copy.deepcopy(reply)):
            status, _, raw = self.call("/api/ask", {"question": "what should i take", "stream": False, "lang": lang, **(body or {})}, cookie=sid)
        self.assertEqual(status, 200)
        meta = next(json.loads(b.split("data: ", 1)[1]) for b in raw.decode().split("\n\n") if b.startswith("event: meta"))
        return (meta, raw.decode()) if give_raw else meta

    def base_reply(self, tool, data, **more):
        return {"kind": "demo", "tool": tool, "text": "Here you go.", "data": data, "chips": ["Show my checklist"], "pages": [], "cites": {}, "contacts": [],
                "followups": [], "category": None, "checked": None, "mode": "sample data", "lang": "en", **more}

    def start(self, slug="juniper"):
        set_cookie, data = self.sign_in(slug)
        return set_cookie.split(";")[0].split("=", 1)[1], data["csrf"]

    def test_draft_routes_need_the_session_and_its_csrf_token_and_change_nothing(self):
        sid, csrf = self.start()
        for path in ("/api/hub/draft", "/api/hub/draft/options", "/api/hub/draft/sections"):
            self.assertEqual(self.call(path, {"term": TERM, "items": []})[0], 401, path)
            self.assertEqual(self.call(path, {"term": TERM, "items": []}, cookie=sid)[0], 403, path)
        crn = finder.details(store.connect(), "CS 261", TERM)["sections"][0]["crn"]
        status, _, raw = self.call("/api/hub/draft", {"term": TERM, "items": [{"crn": crn}]}, cookie=sid, csrf=csrf)
        self.assertEqual((status, [r["code"] for r in json.loads(raw)["rows"]]), (200, ["CS 261"]))
        status, _, raw = self.call("/api/hub/draft/sections", {"term": TERM, "items": [{"crn": crn}], "crn": crn}, cookie=sid, csrf=csrf)
        self.assertEqual(status, 200)
        self.assertGreater(len(json.loads(raw)["sections"]), 1)
        self.assertEqual(self.call("/api/hub/draft/sections", {"term": TERM, "items": [], "crn": crn}, cookie=sid, csrf=csrf)[0], 404)
        status, _, raw = self.call("/api/hub/draft/options", {"term": TERM, "items": [{"crn": crn}], "query": "writing"}, cookie=sid, csrf=csrf)
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(raw)["courses"])
        self.assertEqual(json.loads(self.call(f"/api/hub/registration?term={TERM}", cookie=sid)[2])["items"], [])

    def test_a_suggested_plan_arrives_as_an_editable_card_in_the_students_language(self):
        from beaverbot.demo import audit
        sid, _ = self.start()
        plan = audit.winter_plan(store.connect(), "juniper", {})
        meta = self.ask(sid, self.base_reply("plan", plan))
        self.assertEqual(meta["card"]["kind"], "draft")
        self.assertEqual([r["code"] for r in meta["card"]["rows"]], [p["course"]["code"] for p in plan["picks"]])
        self.assertNotIn("proposal", meta)
        spanish = self.ask(sid, self.base_reply("plan", plan), lang="es")
        self.assertTrue(spanish["card"]["rows"][0]["times"][0].startswith("Clase "))
        self.assertEqual(spanish["chips"], ["Muestra mi lista de pendientes"])
        self.assertEqual(self.ask(sid, self.base_reply("schedule", {}))["card"]["kind"], "classes")
        self.assertEqual(self.ask(sid, self.base_reply("billing", {}))["card"]["system"], "billing")

    def test_a_reply_never_mentions_a_card_unless_one_is_sent_with_it(self):
        from beaverbot.demo import intents
        sid, _ = self.start()
        said = "You owe $1,243.50, due Sunday, Nov 22. The card below has the details."
        for tool in intents.REPLY_TOOLS:
            if tool in ("plan", "plan_prefs", "finder_options", "whatif", "forms", "resources", "finder_course", "finder_prefs"):
                continue                                  # these need the tool's own data; the card for each is checked without the server above
            meta = self.ask(sid, self.base_reply(tool, {}, text=said))
            self.assertTrue(meta.get("card"), f"{tool}: the reply mentions a card and none was sent")
        bare, raw = self.ask(sid, self.base_reply("mystery", {}, text=said), raw=True)
        self.assertNotIn("card", bare)
        self.assertNotRegex(raw, r"(?i)card below", "with nothing to draw, the sentence about a card is taken out")
        self.assertIn("You owe $1,243.50", raw)

    def test_a_chat_follow_up_edits_the_draft_and_sends_the_whole_plan_back(self):
        sid, csrf = self.start()
        con = store.connect()
        built = json.loads(self.call("/api/hub/draft", {"op": "build", "prefs": {}}, cookie=sid, csrf=csrf)[2])
        chem = next(r for r in built["rows"] if r["code"].startswith("CH "))
        other = next(s["crn"] for s in finder.details(con, chem["code"], TERM)["sections"] if s["crn"] != chem["crn"])
        reply = self.base_reply("plan", {"picks": []}, text="Swapped. Here's the whole plan again.", apply={"type": "draft_put", "crn": other, "linked": None})
        meta = self.ask(sid, reply)
        self.assertNotIn("proposal", meta)
        self.assertEqual((meta["card"]["kind"], meta["card"]["changed"], meta["card"]["can_undo"]), ("draft", other, True))
        self.assertEqual([r["code"] for r in meta["card"]["rows"]], [r["code"] for r in built["rows"]])
        self.assertEqual(json.loads(self.call(f"/api/hub/registration?term={TERM}", cookie=sid)[2])["items"], [], "only the draft changed")
        self.assertEqual(self.call("/api/hub/draft", {"op": "undo"}, cookie=sid)[0], 403, "editing the draft needs the CSRF token too")

    def test_add_them_all_means_the_list_as_the_student_edited_it(self):
        sid, _ = self.start()
        con = store.connect()
        a, b = (finder.details(con, c, TERM)["sections"][0]["crn"] for c in ("CS 261", "WR 227Z"))
        reply = self.base_reply("schedule", {}, apply={"type": "plan_add_many", "items": [{"crn": a, "linked": None}]})
        self.assertEqual([c["code"] for c in self.ask(sid, reply)["proposal"]["classes"]], ["CS 261"])
        edited = self.ask(sid, reply, {"demo": {"draft": [{"crn": b, "linked": None}]}})
        self.assertEqual([c["code"] for c in edited["proposal"]["classes"]], ["WR 227Z"])
        self.assertEqual(json.loads(self.call(f"/api/hub/registration?term={TERM}", cookie=sid)[2])["items"], [], "still only a proposal")
        junk = self.ask(sid, reply, {"demo": {"draft": [{"crn": "x"}, 7]}})
        self.assertNotIn("proposal", junk, "a draft that isn't real sections proposes nothing")


# The parent class's own tests would be collected a second time through the subclass; drop them.
for _name in [n for n in dir(test_hub.OverHttp) if n.startswith("test_")]:
    setattr(OverHttpToo, _name, None)

if __name__ == "__main__":
    unittest.main()
