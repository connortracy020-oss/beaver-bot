"""The connected sites must agree with each other about each sample student, and the chat must be able to ask for
whatever a panel can.

One fact, one source: where a student lives decides their housing, the room and dining lines on their bill, and
which parking permit they can get. The credits they are taking decide the tuition line. Money on the ID card
decides whether there are purchases. Sample data only; skipped without data/demo.db.
"""
import re
import unittest
from pathlib import Path

from beaverbot import config
from beaverbot.demo import actions, draft, hub as H, intents, store, systems as S
from tests.test_hub import ACCOUNTS, Clock, sign_in

HAVE_DEMO = config.DEMO_DB.exists()


@unittest.skipUnless(HAVE_DEMO, "needs data/demo.db (python -m beaverbot.demo.generate)")
class TheSitesAgree(unittest.TestCase):
    def setUp(self):
        self.hub = H.Hub(Clock())
        self.con = store.connect()

    def each(self):
        for slug in sorted(ACCOUNTS):
            ctx = S.context(self.con, sign_in(self.hub, slug))
            yield slug, ctx, {name: S.read(ctx, name) for name in ("housing", "billing", "parking", "card", "library", "registration")}

    def test_living_on_campus_means_room_and_dining_charges_and_residential_parking(self):
        seen = set()
        for slug, ctx, d in self.each():
            on_campus = d["housing"]["on_campus"]
            seen.add(on_campus)
            self.assertEqual(on_campus, S.lives_on_campus(ctx.row), slug)
            lines = [t["description"] for t in d["billing"]["billing"]["transactions"]]
            self.assertEqual("Residence hall room" in lines, on_campus, f"{slug}: housing and the bill disagree about a room")
            self.assertEqual("Dining plan" in lines, on_campus, f"{slug}: housing and the bill disagree about a dining plan")
            self.assertEqual(bool(d["card"]["accounts"][0]["balance"]), on_campus, f"{slug}: Dining Dollars without a dining plan, or the reverse")
            offered = [p["id"] for p in d["parking"]["for_sale"]]
            if on_campus:
                self.assertEqual(offered, ["R"], f"{slug} lives on campus, so only the Residential permit is offered")
                self.assertTrue(d["housing"]["room"] and d["housing"]["mail"])
            else:
                self.assertNotIn("R", offered, slug)
                self.assertIsNone(d["housing"]["room"])
            self.assertTrue(d["parking"]["eligibility"], slug)
        self.assertEqual(seen, {True, False}, "the sample students cover both cases")

    def test_the_chat_and_the_panel_say_the_same_thing_about_parking(self):
        for slug, ctx, d in self.each():
            said = draft.site_facts(ctx, "parking")
            card = draft.chat_card(ctx, intents.run_tool(self.con, slug, S.legacy(ctx), None, "parking", {}))
            self.assertEqual([p["id"] for p in card["data"]["for_sale"]], [p["id"] for p in d["parking"]["for_sale"]], slug)
            self.assertIn(d["parking"]["eligibility"], said, f"{slug}: the reply and the panel give different rules")
            for p in S.Parking.PERMITS:                        # nobody can be offered, waitlisted for, or sold a permit they can't have
                if p["id"] not in [x["id"] for x in d["parking"]["for_sale"]]:
                    for kind in ("buy_permit", "join_waitlist"):
                        self.assertTrue(S.propose(self.hub, ctx, "parking", {"type": kind, "permit": p["id"]})["blocks"], (slug, kind, p["id"]))

    def test_the_tuition_line_matches_the_credits_being_taken(self):
        for slug, ctx, d in self.each():
            taking = sum(i["credits"] for i in S.read(ctx, "registration", term=store.NOW_TERM)["items"] if i["status"] == "registered")
            tuition = [t["description"] for t in d["billing"]["billing"]["transactions"] if "uition" in t["description"]]
            self.assertEqual(len(tuition), 1, f"{slug}: tuition is one line, not {tuition}")
            self.assertEqual(float(re.search(r"([\d.]+) credits", tuition[0]).group(1)), taking, f"{slug}: {tuition[0]} but taking {taking:g}")
            online = S.studies_online(ctx.row)
            self.assertEqual(tuition[0].startswith("Ecampus"), online, slug)

    def test_the_bill_adds_up(self):
        for slug, ctx, d in self.each():
            b = d["billing"]["billing"]
            self.assertAlmostEqual(sum(t["amount"] for t in b["transactions"]), b["balance"], 2, f"{slug}: the lines don't add up to the balance")
            self.assertEqual(len({(t["date"], t["description"], t["amount"]) for t in b["transactions"] if t["amount"] > 0}),
                             len([t for t in b["transactions"] if t["amount"] > 0]), f"{slug}: the same charge is listed twice")

    def test_card_purchases_only_come_from_an_account_with_money(self):
        for slug, ctx, d in self.each():
            bill = d["billing"]["billing"]
            funded = {name for name, had in (("Dining Dollars", bill["meal_plan"]), ("Orange Cash", bill["orange_cash"])) if had}
            spent = {t["account"] for t in d["card"]["transactions"] if t["amount"] < 0}
            self.assertLessEqual(spent, funded, f"{slug}: purchases from an account that never had money")
            if S.studies_online(ctx.row):
                self.assertEqual(d["card"]["transactions"], [], f"{slug} studies online and has campus purchases")
                for name in ("card", "library"):
                    self.assertIn("online student", d[name]["note"], f"{slug}: {name} should say it's for students on campus")
                self.assertEqual(d["parking"]["for_sale"], [])
            else:
                self.assertIsNone(d["card"]["note"])

    def test_the_pretend_steps_update_the_sample_data_and_can_be_undone(self):
        ctx = S.context(self.con, sign_in(self.hub, "mateo"))

        def do(system, change):
            p = S.propose(self.hub, ctx, system, change)
            self.assertEqual(p["blocks"], [], (system, change))
            self.assertTrue(any("In the real version this opens" in u for u in p["unchanged"]), f"{system}: the hand-off line is missing")
            self.assertTrue(any(e.startswith("Sample data:") for e in p["effects"]), system)
            self.assertNotRegex(" ".join(p["effects"] + p["unchanged"]).lower(), r"card number|cvv|routing|account number")
            done = S.confirm(self.hub, ctx, p["id"], p["token"])
            self.assertTrue(done["can_undo"])
            return done

        before = S.read(ctx, "card")["accounts"][1]["balance"]
        added = do("card", {"type": "add_money", "amount": 25, "account": "Orange Cash"})
        self.assertEqual(S.read(ctx, "card")["accounts"][1]["balance"], before + 25)
        S.undo(self.hub, ctx, added["history_id"])
        self.assertEqual(S.read(ctx, "card")["accounts"][1]["balance"], before)

        self.assertIn("vehicle", S.propose(self.hub, ctx, "parking", {"type": "buy_permit", "permit": "C"})["blocks"][0]["reason"])
        p = S.propose(self.hub, ctx, "parking", {"type": "add_vehicle", "plate": "ABC123"})
        S.confirm(self.hub, ctx, p["id"], p["token"])
        bought = do("parking", {"type": "buy_permit", "permit": "C"})
        self.assertEqual([x["id"] for x in S.read(ctx, "parking")["permits"]], ["C"])
        self.assertTrue(S.propose(self.hub, ctx, "parking", {"type": "buy_permit", "permit": "C"})["blocks"], "not twice")
        self.assertTrue(S.propose(self.hub, ctx, "parking", {"type": "buy_permit", "permit": "A"})["blocks"], "sold out")
        S.undo(self.hub, ctx, bought["history_id"])
        self.assertEqual(S.read(ctx, "parking")["permits"], [])

        do("careers", {"type": "apply_job", "job": 1})
        self.assertTrue(S.read(ctx, "careers")["jobs"][1]["applied"])
        do("billing", {"type": "paid"})
        self.assertEqual(S.read(ctx, "billing")["billing"]["balance"], 0)


@unittest.skipUnless(HAVE_DEMO, "needs data/demo.db (python -m beaverbot.demo.generate)")
class TheChatCanDoWhatThePanelsCan(unittest.TestCase):
    def setUp(self):
        self.hub = H.Hub(Clock())
        self.con = store.connect()

    def test_every_panel_action_has_a_chat_tool(self):
        panel = {(name, kind) for name, adapter in S.SYSTEMS.items() for kind in getattr(adapter, "ACTIONS", ())}
        self.assertGreater(len(panel), 25)
        chat = {(system, kind) for system, kinds, _ in actions.CHAT_ACTIONS.values() for kind in kinds} | actions.OLDER
        self.assertEqual(panel - chat - actions.PANEL_ONLY, set(), "a panel can do this and the chat has no tool for it")
        self.assertEqual(chat - panel, set(), "a chat tool asks for a change no panel has")
        self.assertEqual(set(actions.CHAT_ACTIONS), set(intents.ACTION_SITE))
        for tool in actions.CHAT_ACTIONS:
            self.assertIn(tool, intents.TOOLS, "the model can't call it")
            self.assertIn(intents.ACTION_SITE[tool], intents.REPLY_TOOLS, "and its reply has a card")

    def test_every_action_an_adapter_lists_is_one_it_accepts(self):
        ctx = S.context(self.con, sign_in(self.hub, "mateo"))
        for name, adapter in S.SYSTEMS.items():
            for kind in getattr(adapter, "ACTIONS", ()):
                try:
                    S.propose(self.hub, ctx, name, {"type": kind, "term": store.REG_TERM})
                except H.Refused as e:
                    self.assertNotEqual(e.code, "unknown_change", f"{name} lists {kind} but refuses it")
            with self.assertRaises(H.Refused):
                S.propose(self.hub, ctx, name, {"type": "no_such_change", "term": store.REG_TERM})

    def test_a_request_in_words_becomes_the_same_change_a_button_makes(self):
        ctx = S.context(self.con, sign_in(self.hub, "juniper"))
        go = lambda tool, q="", n=None: actions.resolve(ctx, tool, q, n)       # noqa: E731
        system, change, problem = go("library_book", "tomorrow at 2 for 5 people")
        self.assertEqual((system, change["type"], change["time"], problem), ("library", "book_room", "2:00 PM", None))
        self.assertGreaterEqual(next(r for r in S.Library.ROOMS if r["id"] == change["room"])["seats"], 5)
        self.assertEqual(S.propose(self.hub, ctx, system, change)["blocks"], [], "it picked a room that is free")
        self.assertEqual(go("housing_request", "the heater in my room rattles all night")[1], {"type": "maintenance", "area": "My room", "description": "the heater in my room rattles all night"})
        self.assertIsNone(go("housing_request", "help")[1])
        self.assertEqual(go("parking_waitlist")[1], {"type": "join_waitlist", "permit": "R"}, "an on-campus student is offered the Residential waitlist")
        self.assertEqual(go("parking_buy", "a permit")[1], {"type": "buy_permit", "permit": "R"})
        self.assertEqual(go("parking_add_vehicle", "my plate is abc 123")[1], {"type": "add_vehicle", "plate": "ABC123"})
        self.assertIsNone(go("parking_add_vehicle", "my car")[1])
        self.assertEqual(go("careers_save", "the peer tutor one")[1], {"type": "save_job", "job": 0})
        self.assertEqual(go("careers_apply", "", 2)[1], {"type": "apply_job", "job": 1})
        self.assertEqual(go("card_add_money", "add 25 dollars")[1], {"type": "add_money", "amount": 25.0, "account": "Orange Cash"})
        self.assertIsNone(go("card_add_money", "some money")[1])
        self.assertEqual(go("billing_plan")[1], {"type": "enroll_plan"})
        self.assertEqual(go("reg_withdraw", "public speaking")[1]["type"], "withdraw")
        priya = S.context(self.con, sign_in(self.hub, "priya"))
        system, change, problem = actions.resolve(priya, "parking_buy", "")
        self.assertIsNone(change)
        self.assertIn("online student", problem)
        with self.assertRaises(H.Refused):
            go("delete_everything")

    def test_a_chat_request_is_only_ever_a_proposal(self):
        ctx = S.context(self.con, sign_in(self.hub, "juniper"))
        for tool in actions.CHAT_ACTIONS:
            reply = intents.run_tool(self.con, "juniper", S.legacy(ctx), None, tool, {"query": "tomorrow at 2, plate ABC123, $25, peer tutor, public speaking"})
            self.assertEqual(reply["apply"]["type"], "site_action", tool)
            self.assertNotRegex(reply["text"].lower(), r"\b(booked|added|sent|bought|applied|paid|done)\b", f"{tool}: it must not claim the change happened")
        self.assertEqual(S.history(self.hub, ctx), [])

    def test_the_panels_use_one_hand_off_pattern(self):
        panels = (Path(__file__).resolve().parents[1] / "beaverbot" / "static" / "js" / "hub" / "panels.js").read_text(encoding="utf-8")
        self.assertNotIn("This demo stops here", panels)
        self.assertNotIn("Buy on the portal", panels, "plain text that looked like a button")
        for change in ("add_money", "buy_permit", "apply_job", '"paid"'):
            self.assertIn(change, panels, f"the panel has no pretend step for {change}")
        self.assertNotRegex(panels.lower(), r'type: "(password|tel)"|card number|cvv|routing number')


if __name__ == "__main__":
    unittest.main()
