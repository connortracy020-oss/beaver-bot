"""Spanish for the sentences the demo's server writes (beaverbot/demo/es.py).

The check that matters: run the demo through its paces, collect every sentence it produced, and make sure none
is still English when the page is Spanish. Sample data only; skipped without data/demo.db.
"""
import json
import re
import unittest

from beaverbot import config
from beaverbot.demo import draft, es, finder, hub as H, store, systems as S
from tests.test_hub import ACCOUNTS, Clock, sign_in

HAVE_DEMO = config.DEMO_DB.exists()
# English words that only appear in a sentence nobody translated. Names of classes, people, buildings, forms and
# OSU systems stay in English on purpose, so the check looks for ordinary words, not for any English at all.
ENGLISH = re.compile(r"\b(the|your|you|is|are|isn't|can't|doesn't|won't|this|that|with|from|have|will|would|until|before|after|"
                     r"nothing|already|because|which|their|there|it's|you're|you'd)\b", re.I)
KEEP = re.compile(r"Petition for Late Change of Registration|Office of (Financial Aid|International Services)|Student (Accounts|Health Services)|Public Safety|"
                  r"Success Team|Calculus for|Introduction to|Principles of|Religion in the|in the United States|Writing in|for Engineering|and the|of the|"
                  r"The heater rattles all night")


class Sentences(unittest.TestCase):
    def test_single_sentences_values_and_nesting(self):
        self.assertEqual(es.say("Your other classes stay as they are."), "Tus otras clases quedan como están.")
        self.assertEqual(es.say("Cancel request"), "Cancelar solicitud", "an exact sentence wins over a looser pattern")
        self.assertEqual(es.say("Cancel Study room 2A"), "Cancelar Study room 2A")
        self.assertEqual(es.say("Add CS 261 to your Winter 2027 plan"), "Agregar CS 261 a tu plan de Winter 2027")
        self.assertEqual(es.say("Adds CS 261 Data Structures (Lecture 001, Tue Thu 8:30 AM to 9:50 AM; recitation Mon 11:00 AM to 11:50 AM) as Planned."),
                         "Agrega CS 261 Data Structures (Clase 001, mar jue 8:30 AM a 9:50 AM; recitación lun 11:00 AM a 11:50 AM) como Planeada.")
        self.assertEqual(es.say("MTH 254 can't be registered: MTH 254 needs MTH 252Z (or an equivalent) first, which isn't on your record."),
                         "MTH 254 no se puede inscribir: MTH 254 requiere antes MTH 252Z (o un equivalente), que no aparece en tu expediente.")
        self.assertEqual(es.say("Change CS 261's recitation"), "Cambiar recitación de CS 261")
        self.assertEqual(es.say("Booked: you're meeting Cedar Gnawsworth tomorrow at 2:30 PM (zoom)."),
                         "Reservado: te reúnes con Cedar Gnawsworth mañana a las 2:30 PM (zoom).")
        self.assertEqual(es.say("You're not registered yet. Registration opens Monday, Nov 16 at 7:00 AM."),
                         "Aún no tienes clases inscritas. La inscripción abre el lunes, Nov 16 a las 7:00 AM.")
        self.assertEqual(es.say("Data Structures"), "Data Structures", "a class title is left alone")
        self.assertEqual(es.say(""), "")
        self.assertIsNone(es.localize(None))

    def test_only_sentence_fields_are_touched(self):
        data = {"title": "Remove", "course": "Remove", "items": [{"reason": "That recitation or lab is full.", "id": 3}], "effects": ["Removes plate ABC123."], "token": "Remove"}
        out = es.localize(data)
        self.assertEqual(out, {"title": "Quitar", "course": "Remove", "items": [{"reason": "Esa recitación o laboratorio está llena.", "id": 3}],
                               "effects": ["Quita la placa ABC123."], "token": "Remove"})
        self.assertEqual(data["title"], "Remove", "the stored English is not changed")

    def test_no_banned_words_and_no_rule_is_duplicated(self):
        english = [en for en, _ in es.RULES]
        self.assertEqual(len(english), len(set(english)))
        for _, spanish in es.RULES:
            self.assertNotRegex(spanish.lower(), r"\bgarantizad|\boficial")


@unittest.skipUnless(HAVE_DEMO, "needs data/demo.db (python -m beaverbot.demo.generate)")
class EverythingTheDemoSays(unittest.TestCase):
    def setUp(self):
        self.hub = H.Hub(Clock())
        self.con = store.connect()
        self.seen: list[str] = []
        self.rows: list[str] = []

    def collect(self, data):
        """Every server-written sentence in a response, as the Spanish page would get it."""
        def walk(x):
            if isinstance(x, dict) and isinstance(x.get("times"), list):          # a class row: its notes are our sentences, its name is the class's
                self.seen.extend(x.get("notes") or [])
                self.seen.extend(x.get("misses") or [])
                self.seen.extend([x["note"]] if x.get("note") else [])
                self.rows.extend(x["times"])
                return
            if isinstance(x, list):
                for y in x:
                    walk(y)
            elif isinstance(x, dict):
                course_like = any(k in x for k in ("crn", "code", "course_code", "catalog_url", "label", "requirement", "apply_by", "goes_to"))
                for k, v in x.items():
                    if k in ("title", "text") and course_like:       # a class, requirement, job or form: its own name, not our sentence
                        continue
                    if k in es.KEYS and isinstance(v, str):
                        self.seen.append(v)
                    elif k in es.KEYS and isinstance(v, list) and all(isinstance(i, str) for i in v):
                        self.seen.extend(v)
                    else:
                        walk(v)
        walk(es.localize(data))

    def do(self, ctx, system, change, verify=False):
        p = S.propose(self.hub, ctx, system, change)
        self.collect(p)
        if p["blocks"]:
            return None
        if verify or p["verify"]:
            self.hub.verify(ctx.session)
        done = S.confirm(self.hub, ctx, p["id"], p["token"])
        self.collect(done)
        return done

    def test_nothing_the_demo_writes_is_left_in_english(self):
        for slug in sorted(ACCOUNTS):
            ctx = S.context(self.con, sign_in(self.hub, slug))
            for name in S.SYSTEMS:
                self.collect(S.read(ctx, name))
            for term in ("202701", "202702", "202703"):
                self.collect(S.read(ctx, "registration", term=term))
            for view in ("remaining", "plan", "checklist"):
                self.collect({"snapshot": S.read(ctx, "degree", view=view)["snapshot"]})
            # the schedule edited in the chat: its rows, its notes, and what can be swapped in or added
            items = draft.suggested(ctx)
            shown = draft.evaluate(ctx, "202702", items)
            self.collect(shown)
            self.collect(draft.evaluate(ctx, "202702", [{"crn": s["crn"]} for r in shown["rows"][:1] for s in finder.details(self.con, r["code"], "202702")["sections"]] + items))
            for r in shown["rows"]:
                self.collect(draft.options(ctx, "202702", items, replace=r["crn"]))
                self.collect(draft.sections(ctx, "202702", items, r["crn"]))
            self.collect(draft.options(ctx, "202702", items))
            self.collect(draft.options(ctx, "202702", items, query="calculus"))

        ctx = S.context(self.con, sign_in(self.hub, "juniper"))
        sections = finder.details(self.con, "CS 261", "202702")["sections"]
        a, b = sections[0]["crn"], next(s["crn"] for s in sections[1:] if s["seats_open"] > 0)
        reg = lambda **c: self.do(ctx, "registration", {"term": "202702", **c})       # noqa: E731
        reg(type="add", crn=a)
        reg(type="add", crn=a)                                  # duplicate: blocked
        reg(type="swap", crn=a, to_crn=b)
        linked = [k for k in next(s for s in sections if s["crn"] == b)["linked"] if k["seats_open"] > 0]
        if linked:
            reg(type="linked", crn=b, linked=linked[-1]["crn"])
        reg(type="grade_mode", crn=b, mode="S/U")
        reg(type="credits", crn=b, credits=9)
        reg(type="cart", crn=b)
        reg(type="uncart", crn=b)
        reg(type="register")                                    # hold: blocked
        self.do(ctx, "registration", {"type": "add", "term": "202702", "crn": finder.details(self.con, "MTH 254", "202702")["sections"][0]["crn"]})
        plan = S.read(ctx, "degree", view="plan")
        self.do(ctx, "registration", {"type": "add_many", "term": "202702", "items": [{"crn": p["option"]["lecture"]["crn"]} for p in plan["picks"]]})
        spring = finder.details(self.con, "CS 261", "202703")["sections"][0]["crn"]
        self.do(ctx, "registration", {"type": "move", "term": "202702", "crn": b, "to_term": "202703", "to_crn": spring})
        self.do(ctx, "registration", {"type": "remove", "term": "202703", "crn": spring})
        slots = S.read(ctx, "advising")["slots"]
        for change in ({"type": "cancel"}, {"type": "book", "slot": slots[0]["id"]}, {"type": "book", "slot": slots[1]["id"]}, {"type": "cancel"},
                       {"type": "book", "slot": slots[0]["id"]}, {"type": "attend"}):
            self.do(ctx, "advising", change)
        ctx.session.clock_days = 10
        ctx = S.context(self.con, ctx.session)
        self.collect(S.read(ctx, "registration", term="202702"))
        done = self.do(ctx, "registration", {"type": "register", "term": "202702"})
        registered = next((i for i in S.read(ctx, "registration", term="202702")["items"] if i["status"] == "registered"), None)
        if registered:
            self.do(ctx, "registration", {"type": "remove", "term": "202702", "crn": registered["crn"]})
        fall = S.read(ctx, "registration", term="202701")["items"]
        self.do(ctx, "registration", {"type": "add", "term": "202701", "crn": finder.details(self.con, "BA 354", "202701")["sections"][0]["crn"]})
        self.do(ctx, "registration", {"type": "remove", "term": "202701", "crn": fall[0]["crn"]})
        self.do(ctx, "registration", {"type": "grade_mode", "term": "202701", "crn": fall[1]["crn"], "mode": "S/U"})
        ctx.session.clock_days = 0
        ctx = S.context(self.con, ctx.session)
        self.do(ctx, "registration", {"type": "withdraw", "term": "202701", "crn": fall[0]["crn"]})
        self.do(ctx, "registration", {"type": "withdraw", "term": "202701", "crn": fall[1]["crn"]})
        ctx.session.clock_days = 40
        self.do(S.context(self.con, ctx.session), "registration", {"type": "withdraw", "term": "202701", "crn": fall[2]["crn"]})
        ctx.session.clock_days = 0
        ctx = S.context(self.con, ctx.session)

        for change in ({"type": "enroll_plan"}, {"type": "enroll_plan"}, {"type": "paid"}):
            self.do(ctx, "billing", change)
        self.do(ctx, "housing", {"type": "maintenance", "area": "My room", "description": "The heater rattles all night"})
        self.do(ctx, "housing", {"type": "maintenance", "area": "My room", "description": ""})
        self.do(ctx, "housing", {"type": "cancel_request", "id": 1})
        self.do(ctx, "housing", {"type": "cancel_request", "id": 1})
        for change in ({"type": "join_waitlist", "permit": "A"}, {"type": "join_waitlist", "permit": "A"}, {"type": "join_waitlist", "permit": "B"},
                       {"type": "leave_waitlist", "permit": "A"}, {"type": "add_vehicle", "plate": "ABC123"}, {"type": "add_vehicle", "plate": "x"},
                       {"type": "remove_vehicle", "plate": "ABC123"}):
            self.do(ctx, "parking", change)
        for change in ({"type": "save_job", "job": 0}, {"type": "unsave_job", "job": 0}, {"type": "cancel_career"}, {"type": "book_career", "slot": 0},
                       {"type": "book_career", "slot": 1}, {"type": "cancel_career"}):
            self.do(ctx, "careers", change)
        day = S.read(ctx, "library")["days"][1]["date"]
        for room in (1, 2, 3, 4):
            self.do(ctx, "library", {"type": "book_room", "room": room, "date": day, "time": "2:00 PM"})
        self.do(ctx, "library", {"type": "cancel_room", "id": 1})
        self.do(ctx, "library", {"type": "cancel_room", "id": 99})
        self.collect({"history": S.history(self.hub, ctx)})
        last = next((h for h in S.history(self.hub, ctx) if h["can_undo"]), None)
        if last:
            self.collect(S.undo(self.hub, ctx, last["id"]))

        self.assertGreater(len(set(self.seen)), 150, "the walk-through really exercised the demo")
        self.assertGreater(len(set(self.rows)), 40)
        english_times = sorted({t for t in self.rows if re.search(r"\b(Lecture|Recitation|Mon|Tue|Wed|Thu|Fri|to \d|Online)\b", t.split(" · ")[0] + " · " + (t.split(" · ") + [""])[1])})
        self.assertEqual(english_times, [], "a class row's section and meeting time are in Spanish")
        # A string made mostly of capitalized words is a name (a class, a form), which stays as its system shows it.
        named = lambda s: sum(w[:1].isupper() for w in s.split()) >= 0.6 * len(s.split()) and not s.endswith(".")      # noqa: E731
        left = sorted({s for s in self.seen if ENGLISH.search(KEEP.sub(" ", s)) and not named(s)})
        self.assertEqual(left, [], f"{len(left)} sentence(s) still English, for example: {json.dumps(left[:6], ensure_ascii=False)}")


if __name__ == "__main__":
    unittest.main()
