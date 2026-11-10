"""The signed-in demo's rules: sign-in, sessions, who can see what, how changes are confirmed, and the
registration rules (beaverbot/demo/hub.py, systems.py and the server's /api/hub, /api/session, /api/idp routes).

No network beyond a test server on 127.0.0.1, no model, sample data only. Skipped when data/demo.db is absent.
"""
import base64
import hashlib
import json
import os
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock

from beaverbot import config
from beaverbot.demo import finder, hub as H, store, systems as S

HAVE_DEMO = config.DEMO_DB.exists()
ACCOUNTS = {"juniper", "mateo", "priya", "devon", "tessa"}
VERIFIER = "v" * 64
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


def sign_in(hub, slug="juniper", old=None):
    rid = hub.start_sign_in(CHALLENGE, "state-1234")
    out = hub.approve_sign_in(rid, slug, ACCOUNTS)
    return hub.finish_sign_in(out["code"], VERIFIER, old)


class SignInAndSessions(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.hub = H.Hub(self.clock)

    def refused(self, code, fn, *args):
        with self.assertRaises(H.Refused) as raised:
            fn(*args)
        self.assertEqual(raised.exception.code, code)

    def test_a_code_needs_the_matching_verifier_and_works_once(self):
        rid = self.hub.start_sign_in(CHALLENGE, "state-1234")
        out = self.hub.approve_sign_in(rid, "juniper", ACCOUNTS)
        self.assertEqual(out["state"], "state-1234", "the app's own state value comes back unchanged")
        self.refused("bad_code", self.hub.finish_sign_in, out["code"], "w" * 64)
        self.refused("bad_code", self.hub.finish_sign_in, out["code"], VERIFIER)       # the wrong try used the code up
        self.refused("sign_in_expired", self.hub.approve_sign_in, rid, "juniper", ACCOUNTS)

    def test_requests_and_codes_expire_and_only_known_accounts_work(self):
        rid = self.hub.start_sign_in(CHALLENGE, "state-1234")
        self.refused("unknown_account", self.hub.approve_sign_in, rid, "somebody-real", ACCOUNTS)
        rid = self.hub.start_sign_in(CHALLENGE, "state-1234")
        self.clock.now += H.AUTH_TTL + 1
        self.refused("sign_in_expired", self.hub.approve_sign_in, rid, "juniper", ACCOUNTS)
        rid = self.hub.start_sign_in(CHALLENGE, "state-1234")
        out = self.hub.approve_sign_in(rid, "juniper", ACCOUNTS)
        self.clock.now += 61
        self.refused("bad_code", self.hub.finish_sign_in, out["code"], VERIFIER)
        self.refused("bad_request", self.hub.start_sign_in, "short", "state-1234")

    def test_the_session_id_changes_at_sign_in_and_the_old_one_dies(self):
        first = sign_in(self.hub)
        second = sign_in(self.hub, "mateo", old=first.sid)
        self.assertNotEqual(first.sid, second.sid)
        self.assertIsNone(self.hub.get(first.sid))
        self.assertEqual(self.hub.get(second.sid).slug, "mateo")
        self.assertGreaterEqual(len(second.sid), 40)
        self.assertNotEqual(second.sid, second.csrf)

    def test_idle_and_hard_limits_and_sign_out(self):
        s = sign_in(self.hub)
        self.clock.now += H.IDLE - 5
        self.assertIsNotNone(self.hub.get(s.sid, touch=False), "peeking is allowed")
        self.clock.now += 10
        self.assertIsNone(self.hub.get(s.sid), "peeking didn't keep it alive: idle for 20 minutes ends it")
        s = sign_in(self.hub)
        for _ in range(30):                              # active the whole time, but never past the hard limit
            self.clock.now += H.IDLE - 60
            self.hub.get(s.sid)
        self.assertIsNone(self.hub.get(s.sid), "8 hours in all, however active")
        s = sign_in(self.hub)
        self.hub.sign_out(s.sid)
        self.assertIsNone(self.hub.get(s.sid), "signing out ends the session on the server")
        self.assertIsNone(self.hub.get(None))
        self.assertIsNone(self.hub.get("made-up-session-id"))

    def test_the_cookie_is_httponly_secure_and_samesite(self):
        header = H.cookie_header("abc")
        for flag in ("HttpOnly", "Secure", "SameSite=Strict", "Path=/"):
            self.assertIn(flag, header)
        self.assertEqual(H.read_cookie("other=1; bb_session=abc; x=2"), "abc")
        self.assertIsNone(H.read_cookie("other=1"))
        self.assertIn("Max-Age=0", H.cookie_header("", clear=True))

    def test_csrf_and_rate_limits(self):
        s = sign_in(self.hub)
        self.hub.check_csrf(s, s.csrf)
        for bad in (None, "", "nope", s.sid):
            self.refused("csrf", self.hub.check_csrf, s, bad)
        self.assertTrue(all(self.hub.allow("k", 3, 60) for _ in range(3)))
        self.assertFalse(self.hub.allow("k", 3, 60))
        self.clock.now += 61
        self.assertTrue(self.hub.allow("k", 3, 60))


@unittest.skipUnless(HAVE_DEMO, "needs data/demo.db (python -m beaverbot.demo.generate)")
class Changes(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.hub = H.Hub(self.clock)
        self.con = store.connect()

    def ctx(self, slug="mateo", session=None):
        self.session = session or sign_in(self.hub, slug)
        return S.context(self.con, self.session)

    def do(self, ctx, system, change, verify=False):
        p = S.propose(self.hub, ctx, system, change)
        if p["blocks"]:
            return p
        if verify:
            self.hub.verify(ctx.session)
        return S.confirm(self.hub, ctx, p["id"], p["token"])

    def refused(self, code, fn, *args):
        with self.assertRaises(H.Refused) as raised:
            fn(*args)
        self.assertEqual(raised.exception.code, code)

    def option(self, ctx, code, term="202702"):
        found = finder.find(self.con, ctx.slug, code, {}, S.legacy(ctx), term)
        return (found["options"] or found["closest"])[0]["lecture"]["crn"]

    def items(self, ctx, term="202702"):
        return {i["lecture"]["course"]: i for i in S.read(ctx, "registration", term=term)["items"]}

    # -- the confirmation step -----------------------------------------------------------------------
    def test_nothing_changes_until_the_proposal_is_confirmed_with_its_token(self):
        ctx = self.ctx()
        p = S.propose(self.hub, ctx, "registration", {"type": "add", "term": "202702", "crn": self.option(ctx, "BA 354")}, by="assistant")
        self.assertEqual(self.items(ctx), {}, "a proposal, including one from the assistant, changes nothing")
        self.assertEqual(p["by"], "assistant")
        self.refused("bad_token", S.confirm, self.hub, ctx, p["id"], "guessed-token")
        self.refused("proposal_gone", S.confirm, self.hub, ctx, "no-such-proposal", p["token"])
        self.assertEqual(self.items(ctx), {})
        done = S.confirm(self.hub, ctx, p["id"], p["token"])
        self.assertTrue(done["ok"] and done["can_undo"])
        self.assertEqual(self.items(ctx)["BA 354"]["badge"], "Planned")
        self.refused("proposal_gone", S.confirm, self.hub, ctx, p["id"], p["token"])
        self.assertEqual(len(self.items(ctx)), 1, "a confirmation works exactly once")

    def test_a_proposal_expires_and_belongs_to_one_session(self):
        ctx = self.ctx()
        p = S.propose(self.hub, ctx, "registration", {"type": "add", "term": "202702", "crn": self.option(ctx, "BA 354")})
        other = S.context(self.con, sign_in(self.hub, "mateo"))
        self.refused("proposal_gone", S.confirm, self.hub, other, p["id"], p["token"])
        self.clock.now += H.PROPOSAL_TTL + 1
        self.refused("proposal_expired", S.confirm, self.hub, ctx, p["id"], p["token"])
        self.assertEqual(self.items(ctx), {})

    def test_a_blocked_proposal_cannot_be_confirmed_and_says_why(self):
        ctx = self.ctx("juniper")
        self.do(ctx, "registration", {"type": "add", "term": "202702", "crn": self.option(ctx, "CS 261")})
        p = S.propose(self.hub, ctx, "registration", {"type": "register", "term": "202702"})
        self.assertIn("advising hold", p["blocks"][0]["reason"])
        self.assertEqual(p["blocks"][0]["action"], {"panel": "advising"}, "the way forward is offered, not just the refusal")
        self.refused("blocked", S.confirm, self.hub, ctx, p["id"], p["token"])

    def test_high_impact_changes_need_a_fresh_check_each_time(self):
        ctx = self.ctx()
        crn = S.read(ctx, "registration", term="202701")["items"][0]["crn"]
        p = S.propose(self.hub, ctx, "registration", {"type": "withdraw", "term": "202701", "crn": crn})
        self.assertTrue(p["verify"] and not p["undoable"])
        self.refused("verify_first", S.confirm, self.hub, ctx, p["id"], p["token"])
        p = S.propose(self.hub, ctx, "registration", {"type": "withdraw", "term": "202701", "crn": crn})
        self.hub.verify(ctx.session)
        done = S.confirm(self.hub, ctx, p["id"], p["token"])
        self.assertFalse(done["can_undo"], "a withdrawal can't be undone")
        self.assertFalse(ctx.session.public()["verified"], "one check covers one high-impact change")
        self.assertEqual(S.read(ctx, "registration", term="202701")["counts"]["withdrawn"], 1)
        self.assertTrue(S.propose(self.hub, self.ctx("priya"), "billing", {"type": "enroll_plan"})["verify"], "anything involving money")

    # -- who sees what -------------------------------------------------------------------------------
    def test_each_visitor_has_their_own_sandbox(self):
        mine = self.ctx("juniper")
        self.do(mine, "parking", {"type": "join_waitlist", "permit": "R"})      # she lives on campus, so Residential is the one she can get
        self.do(mine, "registration", {"type": "add", "term": "202702", "crn": self.option(mine, "CS 261")})
        theirs = S.context(self.con, sign_in(self.hub, "juniper"))
        self.assertFalse(S.read(theirs, "parking")["for_sale"][0]["on_waitlist"])
        self.assertEqual(self.items(theirs), {})
        self.assertEqual(S.history(self.hub, theirs), [])
        self.assertEqual(len(S.history(self.hub, mine)), 2)

    def test_reading_is_always_about_the_sessions_own_student(self):
        ctx = self.ctx("tessa")
        home = S.read(ctx, "home")
        self.assertEqual(home["student"]["first_name"], "Tessa")
        for name in S.SYSTEMS:
            data = S.read(ctx, name)
            self.assertTrue(data["sample"] and data["source"] and data["as_of"], f"{name} says where it came from")
        self.refused("unknown_system", S.read, ctx, "payroll")

    # -- registration rules ------------------------------------------------------------------------------
    def test_planning_registering_and_undoing(self):
        ctx = self.ctx("mateo")
        self.do(ctx, "registration", {"type": "add", "term": "202702", "crn": self.option(ctx, "BA 354")})
        dup = S.propose(self.hub, ctx, "registration", {"type": "add", "term": "202702", "crn": self.option(ctx, "BA 354")})
        self.assertIn("already in this term", dup["blocks"][0]["reason"])
        closed = S.propose(self.hub, ctx, "registration", {"type": "register", "term": "202702"})
        self.assertIn("isn't open for you yet", closed["blocks"][0]["reason"])
        ctx.session.clock_days = 10                      # the demo control: registration week
        ctx = S.context(self.con, ctx.session)
        done = self.do(ctx, "registration", {"type": "register", "term": "202702"})
        self.assertIn("BA 354", done["summary"])
        self.assertEqual(self.items(ctx)["BA 354"]["badge"], "Registered")
        reg_id = done["history_id"]
        dropped = S.propose(self.hub, ctx, "registration", {"type": "remove", "term": "202702", "crn": self.items(ctx)["BA 354"]["crn"]})
        self.assertIn("Drop", dropped["title"])
        self.assertIn("No W", " ".join(dropped["unchanged"]))
        S.undo(self.hub, ctx, reg_id)
        self.assertEqual(self.items(ctx)["BA 354"]["badge"], "Planned")
        self.refused("cannot_undo", S.undo, self.hub, ctx, reg_id)

    def test_a_class_that_fails_stays_in_the_cart_and_the_rest_go_through(self):
        ctx = self.ctx("mateo")
        self.do(ctx, "registration", {"type": "add", "term": "202702", "crn": self.option(ctx, "BA 354")})
        self.do(ctx, "registration", {"type": "add", "term": "202702", "crn": self.option(ctx, "MTH 254")})     # prerequisite not met
        ctx.session.clock_days = 10
        ctx = S.context(self.con, ctx.session)
        p = S.propose(self.hub, ctx, "registration", {"type": "register", "term": "202702"})
        self.assertTrue(any("MTH 254 can't be registered" in e for e in p["effects"]), "the review says which class will fail, before confirming")
        done = S.confirm(self.hub, ctx, p["id"], p["token"])
        self.assertIn("didn't go through", done["summary"])
        items = self.items(ctx)
        self.assertEqual((items["BA 354"]["badge"], items["MTH 254"]["badge"]), ("Registered", "Planned"))

    def test_every_planned_class_is_editable(self):
        ctx = self.ctx("juniper")
        crn = self.option(ctx, "CS 261")
        self.do(ctx, "registration", {"type": "add", "term": "202702", "crn": crn})
        item = self.items(ctx)["CS 261"]
        self.assertTrue(item["linked"], "a lecture with recitations gets one picked along with it")
        sections = finder.details(self.con, "CS 261", "202702")["sections"]
        other = next(s for s in sections if s["crn"] != crn and s["seats_open"] > 0)
        self.do(ctx, "registration", {"type": "swap", "term": "202702", "crn": crn, "to_crn": other["crn"]})
        self.assertEqual(self.items(ctx)["CS 261"]["crn"], other["crn"])
        choices = [k for k in other["linked"] if k["seats_open"] > 0]
        if len(choices) > 1:
            pick = next(k for k in choices if k["crn"] != self.items(ctx)["CS 261"]["linked"]["crn"])
            self.do(ctx, "registration", {"type": "linked", "term": "202702", "crn": other["crn"], "linked": pick["crn"]})
            self.assertEqual(self.items(ctx)["CS 261"]["linked"]["crn"], pick["crn"])
        self.do(ctx, "registration", {"type": "grade_mode", "term": "202702", "crn": other["crn"], "mode": "S/U"})
        self.assertEqual(self.items(ctx)["CS 261"]["grade_mode"], "S/U")
        self.do(ctx, "registration", {"type": "cart", "term": "202702", "crn": other["crn"]})
        self.assertEqual(self.items(ctx)["CS 261"]["badge"], "In cart")
        spring = finder.details(self.con, "CS 261", "202703")["sections"][0]["crn"]
        self.do(ctx, "registration", {"type": "move", "term": "202702", "crn": other["crn"], "to_term": "202703", "to_crn": spring})
        self.assertEqual(self.items(ctx), {})
        self.assertEqual(self.items(ctx, "202703")["CS 261"]["badge"], "Planned")
        self.do(ctx, "registration", {"type": "remove", "term": "202703", "crn": spring})
        self.assertEqual(self.items(ctx, "202703"), {})
        wrong = next(s for s in finder.details(self.con, "CS 162", "202702")["sections"])
        self.do(ctx, "registration", {"type": "add", "term": "202702", "crn": crn})
        self.refused("different_course", S.propose, self.hub, ctx, "registration", {"type": "swap", "term": "202702", "crn": crn, "to_crn": wrong["crn"]})

    def test_time_conflicts_credit_limits_and_full_sections_are_explained(self):
        ctx = self.ctx("juniper")
        reg = S.SYSTEMS["registration"]
        first = finder.details(self.con, "CS 261", "202702")["sections"][0]
        self.do(ctx, "registration", {"type": "add", "term": "202702", "crn": first["crn"]})
        mine = self.items(ctx)["CS 261"]
        clash = self.con.execute("""SELECT s.crn FROM sections s JOIN meetings m ON m.crn = s.crn WHERE s.term_code = '202702' AND s.is_primary = 1
                                    AND s.course_code <> 'CS 261' AND m.days = ? AND m.start_min = ? LIMIT 1""",
                                 (mine["lecture"]["meetings"][0]["days"], mine["lecture"]["meetings"][0]["start"])).fetchone()
        if clash:
            lec = store.section(self.con, clash[0])
            warnings, _ = reg._check(ctx, "202702", lec, None)
            self.assertTrue(any("same time as CS 261" in w for w in warnings), "planning warns about a clash")
            _, blocks = reg._check(ctx, "202702", lec, None, strict=True)
            self.assertTrue(any("same time as CS 261" in b["reason"] for b in blocks), "registering refuses it, with the reason")
        full = self.con.execute("""SELECT crn FROM sections WHERE term_code = '202702' AND is_primary = 1 AND seats_taken >= seats_total
                                   AND wait_cap > wait_count LIMIT 1""").fetchone()
        if full:
            lec = store.section(self.con, full[0])
            item = {"crn": lec["crn"], "lecture": lec, "linked": None, "credits": lec["credits"] or 0, "status": "cart"}
            with mock.patch.object(reg, "_check", lambda *a, **k: ([], [])):
                self.assertEqual(reg._outcome(ctx, "202702", item)[0], "waitlisted")
        ctx.state["terms"]["202702"] = [{"crn": r[0], "linked": None, "status": "planned", "grade_mode": None, "credits": None}
                                        for r in self.con.execute("SELECT crn FROM sections WHERE term_code = '202702' AND is_primary = 1 AND credits = 4 LIMIT 5")]
        over = store.section(self.con, self.con.execute("SELECT crn FROM sections WHERE term_code = '202702' AND is_primary = 1 AND credits = 4 LIMIT 1 OFFSET 7").fetchone()[0])
        warnings, _ = reg._check(ctx, "202702", over, None)
        self.assertTrue(any("The limit is 19" in w for w in warnings))

    def test_the_current_term_allows_only_withdrawing_until_the_deadline(self):
        ctx = self.ctx("mateo")
        crn = S.read(ctx, "registration", term="202701")["items"][0]["crn"]
        add = S.propose(self.hub, ctx, "registration", {"type": "add", "term": "202701", "crn": finder.details(self.con, "BA 354", "202701")["sections"][0]["crn"]})
        self.assertIn("closed after week 1", add["blocks"][0]["reason"])
        gone = S.propose(self.hub, ctx, "registration", {"type": "remove", "term": "202701", "crn": crn})
        self.assertEqual(gone["blocks"][0]["action"], {"withdraw": crn})
        ok = S.propose(self.hub, ctx, "registration", {"type": "withdraw", "term": "202701", "crn": crn})
        self.assertEqual(ok["blocks"], [])
        self.assertTrue(any("W goes on your transcript" in w for w in ok["warnings"]))
        ctx.session.clock_days = 30
        late = S.propose(self.hub, S.context(self.con, ctx.session), "registration", {"type": "withdraw", "term": "202701", "crn": crn})
        self.assertIn("last day to withdraw", late["blocks"][0]["reason"])
        self.assertIn("Petition", late["blocks"][0]["next"])

    def test_dropping_below_full_time_warns_and_needs_the_extra_check(self):
        ctx = self.ctx("mateo")                          # 16 credits this term
        items = S.read(ctx, "registration", term="202701")["items"]
        big = next(i for i in items if i["credits"] == 4)
        self.do(ctx, "registration", {"type": "withdraw", "term": "202701", "crn": big["crn"]}, verify=True)       # 12 left
        again = next(i for i in S.read(ctx, "registration", term="202701")["items"] if i["status"] == "registered")
        p = S.propose(self.hub, ctx, "registration", {"type": "withdraw", "term": "202701", "crn": again["crn"]})
        self.assertTrue(any("financial aid" in w for w in p["warnings"]), "the review says what dropping below 12 can affect")
        self.assertTrue(p["verify"])
        self.assertTrue(S.read(ctx, "registration", term="202701")["credits"]["full_time"], "still at 12 until it is confirmed")

    # -- the other systems -----------------------------------------------------------------------------
    def test_advising_billing_library_parking_housing(self):
        ctx = self.ctx("juniper")
        slots = S.read(ctx, "advising")["slots"]
        self.assertIn("Booked", self.do(ctx, "advising", {"type": "book", "slot": slots[0]["id"]})["summary"])
        move = S.propose(self.hub, ctx, "advising", {"type": "book", "slot": slots[1]["id"]})
        self.assertIn("Move", move["title"])
        self.assertTrue(S.read(ctx, "registration")["cannot_register"], "booking doesn't lift the hold; meeting does")
        self.do(ctx, "advising", {"type": "attend"})
        self.assertFalse(any(h["blocks"] for h in S.read(ctx, "advising")["holds"]))

        priya = self.ctx("priya")
        self.assertTrue(any(h["blocks"] for h in S.read(priya, "billing")["holds"]))
        before = S.read(priya, "billing")["billing"]["balance"]
        self.do(priya, "billing", {"type": "enroll_plan"}, verify=True)
        after = S.read(priya, "billing")
        self.assertEqual(after["billing"]["balance"], before, "joining a plan doesn't pretend the balance was paid")
        self.assertFalse(any(h["blocks"] for h in after["holds"]))
        self.assertNotIn("card_number", json.dumps(after))

        day = S.read(ctx, "library")["days"][1]["date"]
        room = next(r for r in (1, 2, 3, 4) if not S.propose(self.hub, ctx, "library", {"type": "book_room", "room": r, "date": day, "time": "2:00 PM"})["blocks"])
        self.do(ctx, "library", {"type": "book_room", "room": room, "date": day, "time": "2:00 PM"})
        second = S.propose(self.hub, ctx, "library", {"type": "book_room", "room": room, "date": day, "time": "4:00 PM"})
        self.assertIn("one a day", second["blocks"][0]["reason"])

        commuter = S.context(self.con, sign_in(self.hub, "mateo"))
        self.assertIn("isn't sold out", S.propose(self.hub, commuter, "parking", {"type": "join_waitlist", "permit": "B"})["blocks"][0]["reason"])
        self.assertIn("only one you can get", S.propose(self.hub, S.context(self.con, sign_in(self.hub, "devon")), "parking", {"type": "join_waitlist", "permit": "B"})["blocks"][0]["reason"])
        self.do(ctx, "parking", {"type": "add_vehicle", "plate": "abc-123"})
        self.assertEqual(S.read(ctx, "parking")["vehicles"], [{"plate": "ABC123"}])

        hidden = S.read(ctx, "housing")
        self.assertTrue(hidden["mail"]["hidden"] and hidden["mail"]["combination"] is None)
        self.assertIsNone(S.read(ctx, "housing", reveal=True)["mail"]["combination"], "asking isn't enough: it needs the fresh check")
        self.hub.verify(ctx.session)
        self.assertTrue(S.read(ctx, "housing", reveal=True)["mail"]["combination"])
        # Adding money is a hand-off with a pretend step: it asks for an amount, never for a card or bank number.
        self.assertIn("amount", S.propose(self.hub, ctx, "card", {"type": "add_money"})["blocks"][0]["reason"])
        ready = S.propose(self.hub, ctx, "card", {"type": "add_money", "amount": 25, "card_number": "4111111111111111"})
        self.assertIn("MyCard", " ".join(ready["unchanged"]))
        self.assertNotIn("4111", json.dumps(ready))
        self.refused("unknown_change", S.propose, self.hub, ctx, "card", {"type": "pay_by_card"})

    def test_health_counseling_and_disability_show_only_that_something_exists(self):
        for slug in sorted(ACCOUNTS):
            text = json.dumps(S.read(self.ctx(slug), "wellness")).lower()
            for word in ("diagnos", "medication", "reason for visit", "adhd", "depress", "anxiety", "provider notes", "accommodation for"):
                self.assertNotIn(word, text, slug)

    def test_history_offers_undo_only_for_the_latest_change_in_a_system(self):
        ctx = self.ctx("juniper")
        a = self.do(ctx, "registration", {"type": "add", "term": "202702", "crn": self.option(ctx, "CS 261")})
        b = self.do(ctx, "registration", {"type": "add", "term": "202702", "crn": self.option(ctx, "WR 227Z")})
        rows = S.history(self.hub, ctx)
        self.assertEqual([r["can_undo"] for r in rows], [True, False])
        self.refused("undo_latest_first", S.undo, self.hub, ctx, a["history_id"])
        S.undo(self.hub, ctx, b["history_id"])
        self.assertEqual(list(self.items(ctx)), ["CS 261"])
        S.reset(ctx)
        self.assertEqual(self.items(ctx), {})
        self.assertEqual(S.history(self.hub, ctx), [])


@unittest.skipUnless(HAVE_DEMO, "needs data/demo.db (python -m beaverbot.demo.generate)")
class AfterTheSecurityReview(Changes):
    """One test per finding of the 2026-11-10 security review, so none of them can quietly come back."""

    def setUp(self):
        super().setUp()

    def register_four(self, ctx):
        """Sixteen registered winter credits for a sample student, by the demo's own steps."""
        rows = self.con.execute("""SELECT s.crn, s.course_code FROM sections s WHERE s.term_code = '202702' AND s.is_primary = 1 AND s.credits = 4
                                   AND s.seats_taken < s.seats_total AND s.restrictions IS NULL
                                   AND s.crn NOT IN (SELECT lecture_crn FROM linked_sections) AND s.campus = 'Ecampus'
                                   AND s.course_code NOT IN (SELECT course_code FROM prerequisites) GROUP BY s.course_code LIMIT 4""").fetchall()
        self.assertEqual(len(rows), 4, "the sample data has four open online classes with no prerequisites")
        ctx.state["terms"]["202702"] = [{"crn": r[0], "linked": None, "status": "registered", "grade_mode": None, "credits": None} for r in rows]
        return [r[0] for r in rows]

    def test_a_review_written_before_things_changed_is_not_carried_out(self):
        ctx = self.ctx("mateo")
        a, b = self.register_four(ctx)[:2]
        first = S.propose(self.hub, ctx, "registration", {"type": "remove", "term": "202702", "crn": a})
        second = S.propose(self.hub, ctx, "registration", {"type": "remove", "term": "202702", "crn": b})
        self.assertFalse(first["verify"] or second["verify"], "each drop alone leaves 12 credits")
        S.confirm(self.hub, ctx, first["id"], first["token"])
        self.refused("proposal_changed", S.confirm, self.hub, ctx, second["id"], second["token"])
        self.assertEqual(S.read(ctx, "registration", term="202702")["credits"]["registered"], 12, "the second drop did not slip through")
        again = S.propose(self.hub, ctx, "registration", {"type": "remove", "term": "202702", "crn": b})
        self.assertTrue(again["verify"] and any("financial aid" in w for w in again["warnings"]))
        self.refused("verify_first", S.confirm, self.hub, ctx, again["id"], again["token"])
        self.hub.verify(ctx.session)
        self.assertTrue(S.confirm(self.hub, ctx, again["id"], again["token"])["ok"], "the same review works once the fresh check is done")

    def test_an_undo_that_drops_below_full_time_needs_the_fresh_check(self):
        ctx = self.ctx("mateo")
        ctx.state["terms"]["202702"] = []
        ctx.session.clock_days = 10
        ctx = S.context(self.con, ctx.session)
        crns = self.register_four(ctx)
        for i in ctx.state["terms"]["202702"]:
            i["status"] = "cart"
        done = self.do(ctx, "registration", {"type": "register", "term": "202702"})
        self.assertEqual(S.read(ctx, "registration", term="202702")["credits"]["registered"], 16, crns)
        self.refused("verify_first", S.undo, self.hub, ctx, done["history_id"])
        self.hub.verify(ctx.session)
        S.undo(self.hub, ctx, done["history_id"])
        self.assertEqual(S.read(ctx, "registration", term="202702")["credits"]["registered"], 0)
        self.assertFalse(ctx.session.public()["verified"])

    def test_the_mailbox_combination_is_random_and_one_check_shows_it_once(self):
        a, b = self.ctx("devon"), None
        b = S.context(self.con, sign_in(self.hub, "devon"))
        self.assertNotEqual(a.state["housing"]["combination"], b.state["housing"]["combination"], "not worked out from the account name")
        self.assertNotIn(a.state["housing"]["combination"], json.dumps(S.read(a, "card")) + json.dumps(S.read(a, "housing")))
        self.hub.verify(a.session)
        self.assertTrue(S.read(a, "housing", reveal=True)["mail"]["combination"])
        self.assertFalse(a.session.public()["verified"], "showing it used the check up")
        crn = S.read(a, "registration", term="202701")["items"][0]["crn"]
        p = S.propose(self.hub, a, "registration", {"type": "withdraw", "term": "202701", "crn": crn})
        self.refused("verify_first", S.confirm, self.hub, a, p["id"], p["token"])

    def test_sign_in_values_must_be_plain_tokens(self):
        for bad in ("x" * 42 + "é", "a b" * 20, "<script>" * 8):
            self.refused("bad_request", self.hub.start_sign_in, bad, "state-1234")
        self.refused("bad_request", self.hub.start_sign_in, CHALLENGE, "state&code=evil")
        rid = self.hub.start_sign_in(CHALLENGE, "state-1234")
        out = self.hub.approve_sign_in(rid, "juniper", ACCOUNTS)
        self.refused("bad_code", self.hub.finish_sign_in, out["code"], "é" * 64)

    def test_two_confirmations_at_once_cannot_both_use_one_check(self):
        ctx = self.ctx("mateo")
        crns = [i["crn"] for i in S.read(ctx, "registration", term="202701")["items"]][:2]
        proposals = [S.propose(self.hub, ctx, "registration", {"type": "withdraw", "term": "202701", "crn": c}) for c in crns]
        self.hub.verify(ctx.session)
        results = []

        def go(p):
            try:
                S.confirm(self.hub, S.context(self.con.__class__ is None or store.connect(), ctx.session), p["id"], p["token"])
                results.append("ok")
            except H.Refused as e:
                results.append(e.code)
        threads = [threading.Thread(target=go, args=(p,)) for p in proposals]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(sorted(results)[0], "ok")
        self.assertIn(sorted(results)[1], ("verify_first", "proposal_changed"))
        self.assertEqual(S.read(ctx, "registration", term="202701")["counts"]["withdrawn"], 1)


@unittest.skipUnless(HAVE_DEMO, "needs data/demo.db (python -m beaverbot.demo.generate)")
class OverHttp(unittest.TestCase):
    """The same rules through the real server: cookies, headers and status codes."""

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

    def setUp(self):
        self.server.hub.hits.clear()

    def call(self, path, body=None, cookie=None, csrf=None, headers=None):
        h = {"Content-Type": "application/json", **(headers or {})}
        if cookie:
            h["Cookie"] = f"{H.COOKIE}={cookie}"
        if csrf:
            h["X-CSRF-Token"] = csrf

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        opener = urllib.request.build_opener(NoRedirect)
        req = urllib.request.Request(self.base + path, data=None if body is None else json.dumps(body).encode(), headers=h, method="GET" if body is None else "POST")
        try:
            with opener.open(req, timeout=30) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def sign_in(self, slug="juniper", cookie=None):
        status, headers, _ = self.call(f"/auth/start?challenge={CHALLENGE}&state=state-1234")
        self.assertEqual(status, 302)
        rid = headers["Location"].split("request=")[1]
        redirect = json.loads(self.call("/api/idp/approve", {"request": rid, "account": slug})[2])["redirect"]
        code = redirect.split("code=")[1].split("&")[0]
        status, headers, body = self.call("/api/session/token", {"code": code, "verifier": VERIFIER}, cookie=cookie)
        self.assertEqual(status, 200)
        return headers["Set-Cookie"], json.loads(body)

    def test_sign_in_sets_a_locked_down_cookie_and_never_returns_the_session_id(self):
        set_cookie, data = self.sign_in()
        for flag in ("HttpOnly", "Secure", "SameSite=Strict", "Path=/"):
            self.assertIn(flag, set_cookie)
        self.assertTrue(H.cookie_header("abc", https=True).startswith("__Host-"), "over https the prefix makes a browser insist on Secure and host-only")
        self.assertTrue(set_cookie.startswith("bb_session="), "plain http on this computer can't use the prefix")
        self.assertNotIn("Domain", set_cookie)
        sid = set_cookie.split(";")[0].split("=", 1)[1]
        self.assertNotIn(sid, json.dumps(data), "the browser's scripts never see the session id")
        self.assertEqual(data["profile"]["first_name"], "Juniper")
        self.assertNotIn("password", json.dumps(data).lower())
        again, _ = self.sign_in("mateo", cookie=sid)
        self.assertNotEqual(again.split(";")[0], set_cookie.split(";")[0], "a new id at every sign-in")
        self.assertEqual(self.call("/api/hub/home", cookie=sid)[0], 401, "the old session is gone")

    def test_every_hub_route_needs_a_session(self):
        for path in ("/api/hub/home", "/api/hub/registration", "/api/hub/billing", "/api/hub/history", "/api/hub/sections?code=CS%20261"):
            self.assertEqual(self.call(path)[0], 401, path)
        for path in ("/api/hub/propose", "/api/hub/confirm", "/api/hub/undo", "/api/hub/reset", "/api/hub/clock", "/api/session/verify", "/api/session/signout"):
            self.assertEqual(self.call(path, {"system": "registration"})[0], 401, path)
        self.assertEqual(json.loads(self.call("/api/session")[2]), {"signed_in": False})
        self.assertEqual(self.call("/api/demo/student", {"student": "juniper", "state": {}})[0], 404, "the old route that trusted the browser is gone")

    def test_a_student_id_from_the_browser_is_ignored(self):
        set_cookie, data = self.sign_in("juniper")
        sid = set_cookie.split(";")[0].split("=", 1)[1]
        status, _, body = self.call("/api/hub/home?student=tessa&slug=tessa", cookie=sid)
        self.assertEqual((status, json.loads(body)["student"]["first_name"]), (200, "Juniper"))
        status, _, body = self.call("/api/hub/propose", {"student": "tessa", "slug": "tessa", "system": "advising", "change": {"type": "cancel", "student": "tessa"}},
                                    cookie=sid, csrf=data["csrf"])
        self.assertEqual(status, 200)
        tessa_cookie, _ = self.sign_in("tessa")
        tessa_sid = tessa_cookie.split(";")[0].split("=", 1)[1]
        mine = json.loads(self.call("/api/hub/history", cookie=sid)[2])["history"]
        theirs = json.loads(self.call("/api/hub/history", cookie=tessa_sid)[2])["history"]
        self.assertEqual((mine, theirs), ([], []))

    def test_changes_need_the_csrf_token_and_the_same_origin(self):
        set_cookie, data = self.sign_in()
        sid = set_cookie.split(";")[0].split("=", 1)[1]
        change = {"system": "parking", "change": {"type": "join_waitlist", "permit": "R"}}
        self.assertEqual(self.call("/api/hub/propose", change, cookie=sid)[0], 403, "no CSRF token")
        self.assertEqual(self.call("/api/hub/propose", change, cookie=sid, csrf="wrong")[0], 403)
        self.assertEqual(self.call("/api/hub/propose", change, cookie=sid, csrf=data["csrf"], headers={"Origin": "https://evil.example"})[0], 403)
        status, _, body = self.call("/api/hub/propose", change, cookie=sid, csrf=data["csrf"])
        p = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(self.call("/api/hub/confirm", {"id": p["id"], "token": p["token"]}, cookie=sid)[0], 403, "confirming needs it too")
        self.assertEqual(self.call("/api/hub/confirm", {"id": p["id"], "token": "guess"}, cookie=sid, csrf=data["csrf"])[0], 403)
        done = json.loads(self.call("/api/hub/confirm", {"id": p["id"], "token": p["token"]}, cookie=sid, csrf=data["csrf"])[2])
        self.assertTrue(done["ok"])
        self.assertEqual(self.call("/api/hub/confirm", {"id": p["id"], "token": p["token"]}, cookie=sid, csrf=data["csrf"])[0], 409, "single use")
        self.assertEqual(self.call("/api/session/signout", {}, cookie=sid, csrf=data["csrf"])[0], 200)
        self.assertEqual(self.call("/api/hub/home", cookie=sid)[0], 401, "signing out ends it on the server")

    def test_the_assistant_can_only_propose(self):
        """A model tool result that wants a change reaches the browser as a proposal. The sample data is untouched,
        and what the conversation step was given holds no token, session id or CSRF value."""
        from beaverbot import server as server_module
        set_cookie, data = self.sign_in("juniper")
        sid = set_cookie.split(";")[0].split("=", 1)[1]
        crn = finder.details(store.connect(), "CS 261", "202702")["sections"][0]["crn"]
        seen = {}

        def fake(question, lang="en", history=None, demo=None, emit=None):
            seen["demo"] = demo
            return {"kind": "demo", "tool": "schedule", "text": "Done. CS 261 is in your plan.", "apply": {"type": "plan_add", "crn": crn, "linked": None},
                    "pages": [], "cites": {}, "contacts": [], "followups": [], "category": None, "checked": None, "mode": "sample data", "lang": "en"}
        with mock.patch.object(server_module, "library_ready", lambda: True), mock.patch.object(server_module.talk, "converse", fake):
            status, _, raw = self.call("/api/ask", {"question": "add CS 261", "stream": False, "demo": {"student": "tessa", "state": {"plan": [{"crn": 1}]}}}, cookie=sid)
        self.assertEqual(status, 200)
        meta = next(json.loads(b.split("data: ", 1)[1]) for b in raw.decode().split("\n\n") if b.startswith("event: meta"))
        self.assertEqual(seen["demo"]["student"], "juniper", "who is asking comes from the session, not the request")
        flat = json.dumps(seen["demo"])
        for secret in (sid, data["csrf"]):
            self.assertNotIn(secret, flat)
        self.assertNotIn("apply", meta)
        self.assertEqual((meta["proposal"]["by"], meta["proposal"]["system"]), ("assistant", "registration"))
        self.assertNotIn("Done.", raw.decode(), "it doesn't claim a change that hasn't happened")
        items = json.loads(self.call("/api/hub/registration?term=202702", cookie=sid)[2])["items"]
        self.assertEqual(items, [], "nothing changed: the student hasn't confirmed")

    def test_one_students_changes_never_show_for_another(self):
        mine, data = self.sign_in("juniper")
        sid = mine.split(";")[0].split("=", 1)[1]
        p = json.loads(self.call("/api/hub/propose", {"system": "parking", "change": {"type": "join_waitlist", "permit": "R"}}, cookie=sid, csrf=data["csrf"])[2])
        self.call("/api/hub/confirm", {"id": p["id"], "token": p["token"]}, cookie=sid, csrf=data["csrf"])
        theirs, other = self.sign_in("juniper")
        other_sid = theirs.split(";")[0].split("=", 1)[1]
        self.assertEqual(len(json.loads(self.call("/api/hub/history", cookie=sid)[2])["history"]), 1)
        self.assertEqual(json.loads(self.call("/api/hub/history", cookie=other_sid)[2])["history"], [], "another visitor, even as the same sample student")
        self.assertFalse(json.loads(self.call("/api/hub/parking", cookie=other_sid)[2])["for_sale"][0]["on_waitlist"])
        self.assertEqual(self.call("/api/hub/confirm", {"id": p["id"], "token": p["token"]}, cookie=other_sid, csrf=other["csrf"])[0], 409)
        self.assertEqual(self.call("/api/hub/undo", {"id": 1}, cookie=other_sid, csrf=other["csrf"])[0], 409, "and can't undo it either")

    def test_every_route_that_changes_something_needs_the_csrf_token(self):
        set_cookie, data = self.sign_in()
        sid = set_cookie.split(";")[0].split("=", 1)[1]
        for path, body in (("/api/hub/undo", {"id": 1}), ("/api/hub/reset", {"everyone": True}), ("/api/hub/clock", {"days": 9}), ("/api/session/verify", {}),
                           ("/api/hub/reveal", {"system": "housing"}), ("/api/hub/find", {"course": "CS 261"}), ("/api/session/keepalive", {})):
            self.assertEqual(self.call(path, body, cookie=sid)[0], 403, path)
        self.assertFalse(json.loads(self.call("/api/session", cookie=sid)[2])["verified"], "the refused requests did nothing")
        self.assertEqual(json.loads(self.call("/api/session", cookie=sid)[2])["clock_days"], 0)

    def test_requests_under_another_sites_name_are_refused(self):
        self.assertEqual(self.call("/", headers={"Host": "evil.example"})[0], 403)
        self.assertEqual(self.call("/api/config", headers={"Host": "evil.example:8765"})[0], 403)
        self.assertEqual(self.call("/api/idp/approve", {"request": "x", "account": "juniper"}, headers={"Host": "evil.example"})[0], 403)
        with mock.patch.dict(os.environ, {"BEAVERBOT_HOSTS": "beaverbot.example"}):
            self.assertEqual(self.call("/", headers={"Host": "beaverbot.example"})[0], 200)
        status, headers, _ = self.call("/static/css/base.css")
        etag = headers["ETag"]
        status, headers, _ = self.call("/static/css/base.css", headers={"If-None-Match": etag})
        self.assertEqual(status, 304)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"], "an unchanged file still carries the security headers")

    def test_sign_in_is_rate_limited_and_pages_cannot_be_framed(self):
        codes = [self.call(f"/auth/start?challenge={CHALLENGE}&state=state-1234")[0] for _ in range(23)]
        self.assertEqual(codes.count(302), 20)
        self.assertEqual(codes[-1], 429)
        self.server.hub.hits.clear()
        for path in ("/", "/signin", "/auth/callback"):
            status, headers, body = self.call(path)
            self.assertEqual(status, 200, path)
            self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
            self.assertIn("script-src 'self'", headers["Content-Security-Policy"])
        page = self.call("/signin")[2].decode().lower()
        self.assertNotIn('type="password"', page)
        self.assertNotIn("duo", page)
        js = (config.STATIC / "js" / "signin.js").read_text(encoding="utf-8").lower()
        self.assertNotIn("password\"", js.replace('"password"', ""))
        for name in ("signin.js", "hub/core.js", "hub/panels.js", "hub/main.js"):
            source = (config.STATIC / "js" / name).read_text(encoding="utf-8")
            self.assertNotIn("innerHTML", source, f"{name} never builds HTML from text")
            self.assertNotIn("document.cookie", source)


if __name__ == "__main__":
    unittest.main()
