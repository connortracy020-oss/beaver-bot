"""The connected systems of the demo, each behind its own adapter. SAMPLE DATA ONLY.

An adapter is the one place that knows a system: what Beaver Bot may read from it, what it may change, and the
system's rules. Today each adapter returns invented data in the shape a real integration would return. To connect
a real system, OSU IT would replace the adapter's inside and keep its three methods:

    read(ctx, **options)   what to show, with `system`, `source` and `as_of` so a panel can say where it came from
    plan(ctx, change)      what a requested change would do: effects, what stays the same, warnings, and blocks
                           with the reason and the next step. Changes nothing.
    apply(ctx, change)     carry out a change that the student reviewed and confirmed (beaverbot/demo/hub.py).
                           Returns (summary, details, undoable).

Nothing in here is called by a model. A model can only ask for `plan`; the student's own confirmation, checked by
the hub, is what reaches `apply`.
"""
import copy
import datetime
import hashlib
import re
import secrets
from dataclasses import dataclass

from . import audit, finder, store
from .hub import Refused, Session

MAX_CREDITS, FULL_TIME = 19, 12
ACTIVE = ("planned", "cart", "registered", "waitlisted")
BADGES = {"planned": "Planned", "cart": "In cart", "registered": "Registered", "waitlisted": "Waitlisted", "withdrawn": "Withdrawn"}
AID_NOTE = ("Dropping below 12 credits can change financial aid, scholarships, housing eligibility and, for international students, "
            "visa status. Check with the Office of Financial Aid or the Office of International Services first.")


HANDOFF = "In the real version this opens {site} with this filled in, and you finish there. Beaver Bot has no card or bank form."


def lives_on_campus(row) -> bool:
    """The one place that decides this. Housing, the bill's room and dining lines, and parking all follow it."""
    return row["campus"] == "Corvallis" and row["standing"] in ("First-year", "Sophomore")


def studies_online(row) -> bool:
    return row["campus"] == "Ecampus"


ONLINE_NOTE = "You're an online student, so this is shown for reference: it's for students who come to the Corvallis campus."


@dataclass
class Ctx:
    con: object
    session: Session
    row: object                 # the sample student's row
    today: datetime.date

    @property
    def state(self) -> dict:
        return self.session.state()

    @property
    def slug(self) -> str:
        return self.session.slug


def context(con, session: Session) -> Ctx:
    row = store.student_row(con, session.slug)
    if row is None:
        raise Refused("unknown_account", 400)
    ctx = Ctx(con, session, row, session.today())
    seed(ctx)
    return ctx


def seed(ctx: Ctx) -> None:
    """A visitor's first look at a sample student: copy this term's registered classes into their own sandbox."""
    st = ctx.state
    if st.get("seeded"):
        st.setdefault("card", {"added": []})          # sandboxes started before the card could be topped up
        return
    current = [{"crn": r["crn"], "linked": r["linked_crn"], "status": "registered", "grade_mode": None, "credits": None}
               for r in ctx.con.execute("SELECT crn, linked_crn FROM student_courses WHERE student_id = ? AND term_code = ? "
                                        "AND status = 'in_progress' AND crn IS NOT NULL ORDER BY course_code", (ctx.row["id"], store.NOW_TERM))]
    st.update({"seeded": True, "terms": {store.NOW_TERM: current, store.REG_TERM: [], "202703": []}, "appointment": None,
               "cancelled": False, "met": False, "paid": False, "payment_plan": False, "parking": {"waitlist": [], "vehicles": []},
               "library": {"bookings": []}, "card": {"added": []},
               # made up fresh for each visitor, so it can't be worked out from anything else on the page
               "housing": {"requests": [], "combination": "-".join(str(secrets.randbelow(40)) for _ in range(3))}, "careers": {"saved": [], "appointment": None}})


def legacy(ctx: Ctx) -> dict:
    """This sandbox in the shape the older planning code reads (beaverbot/demo/store.py)."""
    st = ctx.state
    winter = [i for i in st["terms"].get(store.REG_TERM, []) if i["status"] in ACTIVE]
    draft = st.get("draft")
    return store.clean_state({"plan": [{"crn": i["crn"], "linked": i["linked"]} for i in winter], "appointment": st["appointment"],
                              "draft": draft["items"] if draft else None, "prefs": st.get("prefs"),
                              "cancelled": st["cancelled"], "met": st["met"], "paid": st["paid"],
                              "registered": bool(winter) and all(i["status"] == "registered" for i in winter)})


def current_holds(ctx: Ctx) -> list[dict]:
    """Holds as they stand now. A past-due hold is released by paying or by being current on a payment plan."""
    st = legacy(ctx)
    st["paid"] = st["paid"] or ctx.state["payment_plan"]
    return store.holds(ctx.con, ctx.row["id"], st, ctx.today)


def stamp(ctx: Ctx, system: str, source: str) -> dict:
    return {"system": system, "source": source, "sample": True, "as_of": datetime.datetime.now().strftime("%I:%M %p").lstrip("0"),
            "today": ctx.today.isoformat()}


def plan_of(title: str, effects=None, unchanged=None, warnings=None, blocks=None, verify=False, undoable=True, button="Confirm", classes=None) -> dict:
    """`classes` is the same change as `effects`, one class to a row, so a review can show a list instead of a paragraph."""
    return {"title": title, "effects": effects or [], "unchanged": unchanged or [], "warnings": warnings or [],
            "blocks": blocks or [], "verify": bool(verify), "undoable": bool(undoable), "button": button, "classes": classes or []}


def block(reason: str, next_step: str = "", action: dict | None = None) -> dict:
    """Why something can't be done, and what to do about it. `action` is a panel or change the student can open."""
    return {"reason": reason, "next": next_step, "action": action}


def _pick(seed_text: str, options: list, salt: str = ""):
    return options[int(hashlib.sha256(f"{seed_text}/{salt}".encode()).hexdigest(), 16) % len(options)]


def _time_line(sec: dict) -> str:
    """One meeting line for a class row: "Lecture 001 · Tue Thu 8:30 AM to 9:50 AM · Kelley 1001"."""
    m = next((m for m in sec["meetings"] if not m["tba"]), None)
    where = f" · {m['building']} {m['room'] or ''}".rstrip() if m and m["building"] else ""
    return f"{sec['type']} {sec['section']} · " + (f"{m['days_label']} {m['time_label']}{where}" if m else "Online, no set time")


def class_row(lec: dict, linked: dict | None = None, credits=None, action: str = "add", note: str | None = None) -> dict:
    """One class as a row: code, name, a line for each meeting, credits. `action` is what happens to it."""
    return {"action": action, "crn": lec["crn"], "code": lec["course"], "name": lec["title"],
            "times": [_time_line(lec)] + ([_time_line(linked)] if linked else []),
            "credits": credits if credits is not None else (lec["credits"] or 0), "note": note, "lecture": lec, "linked": linked}


def _when(sec: dict | None) -> str:
    m = next((m for m in (sec or {}).get("meetings", []) if not m["tba"]), None)
    return f"{m['days_label']} {m['time_label']}" if m else "online, no set time"


# ---- registration: plan, cart, register, drop, withdraw ------------------------------------------------------------
class Registration:
    ACTIONS = ("add", "add_many", "remove", "swap", "linked", "move", "grade_mode", "credits", "cart", "uncart", "withdraw", "register")
    id, label, source = "registration", "Register for Classes", "the registration system"

    def term_info(self, ctx: Ctx, code: str) -> dict:
        t = store.term(ctx.con, code)
        if not t or code not in ctx.state["terms"]:
            raise Refused("unknown_term", 400)
        start = datetime.date.fromisoformat(t["start_date"])
        info = {"code": code, "name": t["name"], "start": t["start_date"], "end": t["end_date"]}
        if code == store.NOW_TERM:
            deadline = start + datetime.timedelta(days=51)                 # the Friday that ends week 7
            info.update(mode="current", withdraw_by=deadline.isoformat(), withdraw_label=deadline.strftime("%A, %b ") + str(deadline.day),
                        can_withdraw=ctx.today <= deadline,
                        note="This term is under way. Adding and dropping closed after week 1. You can still withdraw from a class "
                             f"through {deadline.strftime('%b')} {deadline.day}, which leaves a W on your transcript.")
        elif code == store.REG_TERM:
            reg = store.registration(ctx.row, datetime.date.today())        # the real calendar day it opens
            opens = datetime.date.fromisoformat(reg["date"])
            info.update(mode="registration", opens=reg["date"], opens_label=f"{reg['date_label']} at {reg['time_label']}",
                        open=ctx.today >= opens,
                        note=("Registration is open for you." if ctx.today >= opens else
                              f"Registration opens for you {reg['date_label']} at {reg['time_label']}. Until then you can plan and fill your cart."))
        else:
            info.update(mode="planning", open=False,
                        note=f"Registration for {t['name']} hasn't been scheduled yet. You can plan it now, and your plan carries over.")
        return info

    def items(self, ctx: Ctx, code: str) -> list[dict]:
        out = []
        for i in ctx.state["terms"].get(code, []):
            lec = store.section(ctx.con, i["crn"])
            if not lec:
                continue
            info = store.course(ctx.con, lec["course"]) or {}
            options = store.linked(ctx.con, i["crn"])
            flexible = (info.get("credits_min") or 0) < (info.get("credits_max") or 0)
            out.append({"crn": i["crn"], "status": i["status"], "badge": BADGES[i["status"]], "lecture": lec,
                        "linked": store.section(ctx.con, i["linked"]) if i["linked"] else None, "has_linked": bool(options),
                        "credits": i["credits"] if i["credits"] is not None else (lec["credits"] or 0),
                        "grade_mode": i["grade_mode"] or lec["grade_mode"], "can_su": (lec["grade_mode"] or "").lower().startswith("normal"),
                        "credit_range": [info["credits_min"], info["credits_max"]] if flexible else None})
        return out

    def conflicts(self, items: list[dict]) -> list[dict]:
        live = [i for i in items if i["status"] in ACTIVE]
        meets = lambda i: i["lecture"]["meetings"] + (i["linked"]["meetings"] if i["linked"] else [])       # noqa: E731
        return [{"a": a["lecture"]["course"], "b": b["lecture"]["course"]} for n, a in enumerate(live) for b in live[n + 1:]
                if store.overlaps(meets(a), meets(b))]

    def read(self, ctx: Ctx, term: str | None = None, **_) -> dict:
        term = term if term in ctx.state["terms"] else store.REG_TERM
        info, items = self.term_info(ctx, term), self.items(ctx, term)
        live = [i for i in items if i["status"] in ACTIVE]
        credits = sum(i["credits"] for i in live)
        holds = current_holds(ctx)
        blocking = [h for h in holds if h["blocks"]]
        why = None
        if info["mode"] == "registration":
            if blocking:
                h = blocking[0]
                booked = next(iter(store.appointments(ctx.con, ctx.row, legacy(ctx), ctx.today)["upcoming"]), None) if h["type"] == "advising" else None
                if booked:              # the meeting is booked, so the next step is to go to it, not to book it again
                    why = block(f"Your advising hold is still on until you meet your advisor. You're booked for {booked['day_inline']} at {booked['time_label']}.",
                                "The hold comes off after that meeting, usually the same day. Then you can register.",
                                {"panel": "advising", "booked": True})
                else:
                    why = block(f"A hold is blocking registration: {h['title'].lower()}. {h['how_to_clear']}",
                                "Book your advisor and the hold comes off after you meet." if h["type"] == "advising" else "See where to pay.",
                                {"panel": "advising" if h["type"] == "advising" else "billing"})
            elif not info["open"]:
                why = block(f"Registration isn't open for you yet. It opens {info['opens_label']}.",
                            "You can plan and fill your cart now, then register in one step when it opens.")
        return {**stamp(ctx, self.label, self.source), "term": info,
                "terms": [{"code": c, "name": store.term(ctx.con, c)["name"], "count": sum(1 for i in ctx.state["terms"][c] if i["status"] in ACTIVE)}
                          for c in ctx.state["terms"]],
                "items": items, "conflicts": self.conflicts(items), "holds": holds, "cannot_register": why,
                "credits": {"total": credits, "registered": sum(i["credits"] for i in live if i["status"] == "registered"),
                            "min": FULL_TIME, "max": MAX_CREDITS, "full_time": credits >= FULL_TIME},
                "counts": {s: sum(1 for i in items if i["status"] == s) for s in BADGES}}

    # -- checks shared by add, swap and register --------------------------------------------------------------------
    def _others(self, ctx, term, skip_crn=None):
        return [i for i in self.items(ctx, term) if i["status"] in ACTIVE and i["crn"] != skip_crn]

    def _check(self, ctx: Ctx, term: str, lec: dict, linked: dict | None, skip_crn=None, strict=False, extra=()) -> tuple[list, list]:
        """(warnings, blocks) for holding this section in this term. `strict` is registering: warnings become blocks.
        `extra` is classes being added in the same request, so they are checked against each other too."""
        warnings, blocks = [], []
        hard = blocks if strict else warnings
        code = lec["course"]
        others = self._others(ctx, term, skip_crn) + list(extra)
        if any(o["lecture"]["course"] == code for o in others):
            blocks.append(block(f"{code} is already in this term.", "Swap its section instead of adding it twice.", {"swap": code}))
        mine = store.student_courses(ctx.con, ctx.row["id"])
        if code in store.taken_codes(mine, include_in_progress=False):
            warnings.append(f"Your record shows you already passed {code}. Retaking it replaces the grade in your GPA but earns no new credit.")
        taken = store.taken_codes(mine) | {o["lecture"]["course"]: None for t in ctx.state["terms"] if t < term
                                           for o in self.items(ctx, t) if o["status"] in ACTIVE}
        pre = finder.prerequisites(ctx.con, code, taken)
        if pre["status"] == "missing":
            hard.append(block(f"{code} needs {' and '.join(pre['missing'])} first, which isn't on your record.",
                              "Take the prerequisite first, or ask the department for an override if you've covered it elsewhere.")
                        if strict else f"{code} needs {' and '.join(pre['missing'])} first, which isn't on your record. You'd need it done, or an override, before registering.")
        coreq = (store.course(ctx.con, code) or {}).get("coreq_text") or ""
        need = [f"{s} {n}" for s, n in re.findall(r"\b([A-Z]{2,4})\s?(\d{3}[A-Z]?)\b", coreq)]
        if need and not any(c in taken or any(o["lecture"]["course"] == c for o in others) for c in need):
            text = f"{code} has a corequisite ({', '.join(need[:3])}) that has to be taken in the same term or earlier."
            hard.append(block(text, f"Add {need[0]} to this term too.") if strict else text)
        if lec["restrictions"]:
            closed = re.search(r"honors|into osu|cascades", lec["restrictions"], re.I)
            text = f"This section is restricted: {lec['restrictions']}."
            if closed:
                blocks.append(block(text, "Pick a different section of the same class.", {"swap": code}))
            else:
                warnings.append(text + " If that isn't you, registration will ask for an override.")
        meets = lec["meetings"] + (linked["meetings"] if linked else [])
        for o in others:
            if store.overlaps(meets, o["lecture"]["meetings"] + (o["linked"]["meetings"] if o["linked"] else [])):
                text = f"It meets at the same time as {o['lecture']['course']} ({_when(o['lecture'])})."
                hard.append(block(text, "Swap one of the two to another section.", {"swap": code}) if strict else text + " The calendar shows the overlap.")
        if store.linked(ctx.con, lec["crn"]) and not linked:
            blocks.append(block(f"{code} needs a recitation or lab picked along with the lecture.", "Choose one of its linked sections.", {"linked": lec["crn"]}))
        total = sum(o["credits"] for o in others) + (lec["credits"] or 0)
        if total > MAX_CREDITS:
            text = f"That makes {total:g} credits. The limit is {MAX_CREDITS} without your college's approval."
            hard.append(block(text, "Remove a class, or ask your advisor about an overload petition.") if strict else text)
        if lec["seats_open"] <= 0 and not strict:
            warnings.append("This section is full right now." + (" It has a waitlist you can join when you register." if lec["wait_cap"] > lec["wait_count"]
                                                               else " It has no waitlist, so pick another section or check back."))
        return warnings, blocks

    def _section(self, ctx, crn, term):
        lec = store.section(ctx.con, crn) if isinstance(crn, int) else None
        if not lec or lec["term"] != term or not lec["primary"]:
            raise Refused("unknown_section", 400)
        return lec

    def _linked(self, ctx, lec, linked_crn, term, others):
        """The chosen linked section, or the first open one that doesn't clash when none was chosen."""
        options = store.linked(ctx.con, lec["crn"])
        if not options:
            return None
        if isinstance(linked_crn, int):
            hit = next((o for o in options if o["crn"] == linked_crn), None)
            if not hit:
                raise Refused("unknown_section", 400)
            return hit
        busy = [o["lecture"]["meetings"] + (o["linked"]["meetings"] if o["linked"] else []) for o in others]
        free = [o for o in options if o["seats_open"] > 0 and not any(store.overlaps(o["meetings"], b) for b in busy)]
        return (free or [o for o in options if o["seats_open"] > 0] or options)[0]

    def _item(self, ctx, term, crn):
        hit = next((i for i in ctx.state["terms"].get(term, []) if i["crn"] == crn), None)
        if not hit:
            raise Refused("not_in_term", 409)
        return hit

    def _label(self, lec, linked=None):
        return f"{lec['course']} {lec['title']} ({lec['type']} {lec['section']}, {_when(lec)}" + (f"; {linked['type'].lower()} {_when(linked)}" if linked else "") + ")"

    def _status_note(self, info: dict) -> str:
        if info["mode"] == "registration":
            return ("You're not registered yet. " + ("Registration is open, so you can register from your cart." if info["open"]
                                                    else f"Registration opens {info['opens_label']}."))
        return "You're not registered: this term is for planning only so far."

    # -- plan ------------------------------------------------------------------------------------------------------------
    def plan(self, ctx: Ctx, change: dict) -> dict:
        kind, term = change.get("type"), change.get("term")
        info = self.term_info(ctx, term)
        name = info["name"]
        editable = info["mode"] in ("registration", "planning")
        closed = block(f"{name} is under way, and adding or swapping classes closed after week 1.",
                       "A late change needs a Petition for Late Change of Registration from the Registrar.")

        if kind == "add":
            lec = self._section(ctx, change.get("crn"), term)
            if not editable:
                return plan_of(f"Add {lec['course']} to {name}", blocks=[closed])
            linked = self._linked(ctx, lec, change.get("linked"), term, self._others(ctx, term))
            change["linked"] = linked["crn"] if linked else None
            warnings, blocks = self._check(ctx, term, lec, linked)
            return plan_of(f"Add {lec['course']} to your {name} plan", [f"Adds {self._label(lec, linked)} as Planned."],
                           [self._status_note(info), "Nothing is sent to the registration system."], warnings, blocks, button="Add to plan",
                           classes=[class_row(lec, linked)])

        if kind == "add_many":
            if not editable:
                return plan_of(f"Add classes to {name}", blocks=[closed])
            effects, warnings, keep, rows, batch = [], [], [], [], []
            for entry in (change.get("items") or [])[:8]:
                if not isinstance(entry, dict):
                    raise Refused("unknown_section", 400)
                lec = self._section(ctx, entry.get("crn"), term)
                linked = self._linked(ctx, lec, entry.get("linked"), term, self._others(ctx, term) + batch)
                w, b = self._check(ctx, term, lec, linked, extra=batch)
                if b:
                    warnings.append(f"{lec['course']} is left out: {b[0]['reason']}")
                    continue
                keep.append({"crn": lec["crn"], "linked": linked["crn"] if linked else None})
                batch.append({"crn": lec["crn"], "status": "planned", "lecture": lec, "linked": linked, "credits": lec["credits"] or 0})
                effects.append(f"Adds {self._label(lec, linked)} as Planned.")
                rows.append(class_row(lec, linked))
                warnings += [f"{lec['course']}: {x}" for x in w]          # with several classes, say which one
            change["items"] = keep
            return plan_of(f"Add {len(keep)} class{'es' if len(keep) != 1 else ''} to your {name} plan", effects,
                           [self._status_note(info)], warnings, [] if keep else [block("None of those classes can be added. " + " ".join(warnings[:3]), "Add them one at a time from Find a class to pick other sections.", {"panel": "finder"})],
                           button="Add to plan", classes=rows)

        item = self._item(ctx, term, change.get("crn")) if kind != "register" else None
        lec = store.section(ctx.con, item["crn"]) if item else None
        linked = store.section(ctx.con, item["linked"]) if item and item["linked"] else None

        if kind == "remove":
            if item["status"] == "registered" and info["mode"] == "current":
                return plan_of(f"Remove {lec['course']}", blocks=[block("You're registered in this class and the term is under way, so it can't just be removed.",
                                                                        "Withdraw from it instead. That leaves a W on your transcript.", {"withdraw": item["crn"]})])
            dropping = item["status"] in ("registered", "waitlisted")
            left = sum(o["credits"] for o in self._others(ctx, term, item["crn"]) if o["status"] == "registered")
            below = dropping and left < FULL_TIME <= left + (lec["credits"] or 0)
            return plan_of(("Drop " if dropping else "Remove ") + f"{lec['course']} from {name}",
                           [f"{'Drops' if dropping else 'Removes'} {self._label(lec, linked)}." + (" Your seat is released." if dropping else "")],
                           ["Your other classes stay as they are.", ("You lose your place on the waitlist." if item["status"] == "waitlisted" else "No W: the term hasn't started.") if dropping
                            else "Nothing was registered, so nothing is dropped."],
                           [AID_NOTE] if below else [], verify=below, button="Drop class" if dropping else "Remove",
                           classes=[class_row(lec, linked, action="drop" if dropping else "remove")])

        if kind == "swap":
            if not editable:
                return plan_of(f"Swap {lec['course']}", blocks=[closed])
            to = self._section(ctx, change.get("to_crn"), term)
            if to["course"] != lec["course"]:
                raise Refused("different_course", 400)
            new_linked = self._linked(ctx, to, change.get("linked"), term, self._others(ctx, term, item["crn"]))
            change["linked"] = new_linked["crn"] if new_linked else None
            warnings, blocks = self._check(ctx, term, to, new_linked, skip_crn=item["crn"], strict=item["status"] == "registered")
            if item["status"] == "registered" and to["seats_open"] <= 0:
                blocks.append(block("The section you want is full, and swapping would give up your seat in this one.", "Stay put, or join that section's waitlist first."))
            return plan_of(f"Swap {lec['course']} to another section", [f"From {self._label(lec, linked)}.", f"To {self._label(to, new_linked)}."],
                           [f"It stays {BADGES[item['status']].lower()}.", "Your other classes stay as they are."], warnings, blocks, button="Swap section",
                           classes=[class_row(lec, linked, action="from"), class_row(to, new_linked, action="to")])

        if kind == "linked":
            if not editable:
                return plan_of(f"Change {lec['course']}'s linked section", blocks=[closed])
            new_linked = self._linked(ctx, lec, change.get("linked"), term, self._others(ctx, term, item["crn"]))
            if not new_linked:
                raise Refused("no_linked", 400)
            warnings, blocks = self._check(ctx, term, lec, new_linked, skip_crn=item["crn"], strict=item["status"] == "registered")
            if new_linked["seats_open"] <= 0 and item["status"] == "registered":
                blocks.append(block("That recitation or lab is full.", "Pick another one."))
            return plan_of(f"Change {lec['course']}'s {new_linked['type'].lower()}",
                           [f"From {linked['type'].lower() + ' ' + _when(linked) if linked else 'none'} to {new_linked['type'].lower()} {new_linked['section']}, {_when(new_linked)}."],
                           ["The lecture stays the same."], warnings, blocks, button="Change it")

        if kind == "move":
            to_term = change.get("to_term")
            target = self.term_info(ctx, to_term)
            if item["status"] in ("registered", "waitlisted", "withdrawn") or target["mode"] == "current" or to_term == term:
                return plan_of(f"Move {lec['course']}", blocks=[block("Only a planned class can be moved, and only to a term that hasn't started.",
                                                                      "Drop or withdraw first if you're registered.")])
            to = self._section(ctx, change.get("to_crn"), to_term)
            if to["course"] != lec["course"]:
                raise Refused("different_course", 400)
            new_linked = self._linked(ctx, to, change.get("linked"), to_term, self._others(ctx, to_term))
            change["linked"] = new_linked["crn"] if new_linked else None
            warnings, blocks = self._check(ctx, to_term, to, new_linked)
            return plan_of(f"Move {lec['course']} to {target['name']}", [f"Removes it from {name}.", f"Adds {self._label(to, new_linked)} to {target['name']} as Planned."],
                           ["Your other classes stay as they are."], warnings, blocks, button="Move it",
                           classes=[class_row(lec, linked, action="from"), class_row(to, new_linked, action="to")])

        if kind == "grade_mode":
            mode = change.get("mode")
            row = self.items(ctx, term)
            me = next(i for i in row if i["crn"] == item["crn"])
            if mode not in ("Normal grading (A-F)", "S/U") or not me["can_su"]:
                return plan_of(f"Change how {lec['course']} is graded", blocks=[block("This class has only one grading option.", "")])
            if info["mode"] == "current" and not info["can_withdraw"]:
                return plan_of(f"Change how {lec['course']} is graded", blocks=[block(f"The deadline to change grading for {name} was {info['withdraw_label']}.",
                                                                                      "After that it takes a petition to the Registrar.")])
            warn = (["An S/U class usually can't count toward your major or minor, and S and U don't affect your GPA. Check with your advisor first."]
                    if mode == "S/U" else [])
            return plan_of(f"Grade {lec['course']} as {'S/U' if mode == 'S/U' else 'A-F'}", [f"Changes the grading basis from {me['grade_mode']} to {mode}."],
                           ["The section, time and credits stay the same."], warn, button="Change grading")

        if kind == "credits":
            me = next(i for i in self.items(ctx, term) if i["crn"] == item["crn"])
            value = change.get("credits")
            if not me["credit_range"] or not isinstance(value, (int, float)) or not me["credit_range"][0] <= value <= me["credit_range"][1]:
                reason = (f"Pick between {me['credit_range'][0]:g} and {me['credit_range'][1]:g} credits for this class." if me["credit_range"]
                          else "This class has a fixed number of credits.")
                return plan_of(f"Change {lec['course']}'s credits", blocks=[block(reason, "")])
            return plan_of(f"Take {lec['course']} for {value:g} credits", [f"Changes it from {me['credits']:g} to {value:g} credits."],
                           ["The section and time stay the same."], button="Change credits")

        if kind in ("cart", "uncart"):
            if info["mode"] != "registration" or item["status"] not in ("planned", "cart"):
                return plan_of("Move to cart", blocks=[block("Only a planned class in a term with registration can go in the cart.", "")])
            return plan_of(f"{'Put' if kind == 'cart' else 'Take'} {lec['course']} {'in' if kind == 'cart' else 'out of'} your cart",
                           [f"{lec['course']} becomes {'In cart' if kind == 'cart' else 'Planned'}."], [self._status_note(info)], button="OK")

        if kind == "withdraw":
            if info["mode"] != "current" or item["status"] != "registered":
                return plan_of(f"Withdraw from {lec['course']}", blocks=[block("Withdrawing is for a class you're registered in during a term that has started.",
                                                                               "Before a term starts, drop the class instead. That leaves no mark.")])
            if not info["can_withdraw"]:
                return plan_of(f"Withdraw from {lec['course']}", blocks=[block(f"The last day to withdraw from a {name} class was {info['withdraw_label']}.",
                                                                               "After that it takes a Petition for Late Change of Registration, or withdrawing from the whole term.")])
            left = sum(o["credits"] for o in self._others(ctx, term, item["crn"]) if o["status"] == "registered")
            warnings = ["A W goes on your transcript. It doesn't change your GPA.", "There's no tuition refund this late in the term.",
                        "A withdrawal can't be undone here. Getting back in takes a petition."]
            if left < FULL_TIME:
                warnings.append(f"You'd be at {left:g} credits. " + AID_NOTE)
            return plan_of(f"Withdraw from {lec['course']}", [f"{self._label(lec, linked)} becomes Withdrawn with a W."],
                           ["Your other classes stay as they are."], warnings, verify=True, undoable=False, button="Withdraw",
                           classes=[class_row(lec, linked, action="withdraw")])

        if kind == "register":
            state = self.read(ctx, term)
            if info["mode"] != "registration":
                return plan_of(f"Register for {name}", blocks=[block(info["note"], "")])
            if state["cannot_register"]:
                return plan_of(f"Register for {name}", blocks=[state["cannot_register"]])
            cart = [i for i in state["items"] if i["status"] == "cart"] or [i for i in state["items"] if i["status"] == "planned"]
            if not cart:
                return plan_of(f"Register for {name}", blocks=[block("There's nothing in your cart or plan to register.", "Find a class first.", {"panel": "finder"})])
            effects, warnings, rows = [], [], []
            for i in cart:
                result, reason = self._outcome(ctx, term, i)
                rows.append(class_row(i["lecture"], i["linked"], i["credits"], action=result,
                                      note={"registered": None, "waitlisted": f"Full: puts you on its waitlist (position {i['lecture']['wait_count'] + 1}).",
                                            "failed": f"Can't be registered: {reason}"}[result]))
                effects.append({"registered": f"Registers you in {self._label(i['lecture'], i['linked'])}.",
                                "waitlisted": f"{i['lecture']['course']} is full: puts you on its waitlist (position {i['lecture']['wait_count'] + 1}).",
                                "failed": f"{i['lecture']['course']} can't be registered: {reason}"}[result])
                if result == "failed":
                    warnings.append(f"{i['lecture']['course']} will stay in your cart so you can fix it.")
            total = sum(i["credits"] for i in state["items"] if i["status"] == "registered") + sum(i["credits"] for i in cart)
            if total < FULL_TIME:
                warnings.append(f"That's {total:g} credits, under the {FULL_TIME} that count as full-time. " + AID_NOTE)
            return plan_of(f"Register for {name}", effects, ["Classes that fail stay in your cart.", "You can drop a class without a W until the term starts."],
                           warnings, button="Register", classes=rows)
        raise Refused("unknown_change", 400)

    def _outcome(self, ctx, term, item) -> tuple[str, str]:
        _, blocks = self._check(ctx, term, item["lecture"], item["linked"], skip_crn=item["crn"], strict=True)
        if blocks:
            return "failed", blocks[0]["reason"]
        if item["lecture"]["seats_open"] <= 0 or (item["linked"] and item["linked"]["seats_open"] <= 0):
            lec = item["lecture"]
            return ("waitlisted", "") if lec["wait_cap"] > lec["wait_count"] else ("failed", "the section is full and has no waitlist.")
        return "registered", ""

    # -- apply -----------------------------------------------------------------------------------------------------------
    def apply(self, ctx: Ctx, change: dict) -> tuple[str, list[str], bool]:
        kind, term = change["type"], change["term"]
        info, rows = self.term_info(ctx, term), ctx.state["terms"][term]
        new = lambda crn, linked: {"crn": crn, "linked": linked, "status": "planned", "grade_mode": None, "credits": None}      # noqa: E731
        if kind == "add":
            lec = store.section(ctx.con, change["crn"])
            rows.append(new(change["crn"], change.get("linked")))
            return f"Added {lec['course']} to your {info['name']} plan.", [self._status_note(info)], True
        if kind == "add_many":
            for entry in change["items"]:
                rows.append(new(entry["crn"], entry.get("linked")))
            codes = [store.section(ctx.con, e["crn"])["course"] for e in change["items"]]
            return f"Added {len(codes)} classes to your {info['name']} plan: {', '.join(codes)}.", [self._status_note(info)], True
        if kind == "register":
            done, details = [], []
            cart = [i for i in self.items(ctx, term) if i["status"] == "cart"] or [i for i in self.items(ctx, term) if i["status"] == "planned"]
            for i in cart:                      # one at a time, so each sees the ones registered before it
                result, reason = self._outcome(ctx, term, i)
                code = i["lecture"]["course"]
                if result == "failed":
                    details.append(f"{code} was not registered: {reason}")
                    continue
                self._item(ctx, term, i["crn"])["status"] = result
                done.append(code)
                details.append(f"{code}: {'registered' if result == 'registered' else 'on the waitlist'}.")
            failed = len(cart) - len(done)
            summary = (f"Registered for {info['name']}: {', '.join(done)}." if done else f"Nothing was registered for {info['name']}.")
            if failed:
                summary += f" {failed} class{'es' if failed != 1 else ''} didn't go through and stayed in your cart."
            return summary, details, bool(done)
        item = self._item(ctx, term, change["crn"])
        code = store.section(ctx.con, item["crn"])["course"]
        if kind == "remove":
            was = item["status"]
            rows.remove(item)
            return (f"Dropped {code} from {info['name']}. No W, because the term hasn't started." if was in ("registered", "waitlisted")
                    else f"Removed {code} from your {info['name']} plan."), ["Your other classes didn't change."], True
        if kind == "swap":
            item.update(crn=change["to_crn"], linked=change.get("linked"))
            return f"Swapped {code} to section {store.section(ctx.con, change['to_crn'])['section']}.", [f"It is still {BADGES[item['status']].lower()}."], True
        if kind == "linked":
            item["linked"] = change["linked"]
            return f"Changed {code}'s linked section to {_when(store.section(ctx.con, change['linked']))}.", ["The lecture didn't change."], True
        if kind == "move":
            rows.remove(item)
            ctx.state["terms"][change["to_term"]].append(new(change["to_crn"], change.get("linked")))
            target = self.term_info(ctx, change["to_term"])
            return f"Moved {code} from {info['name']} to {target['name']}.", [self._status_note(target)], True
        if kind == "grade_mode":
            item["grade_mode"] = None if change["mode"].startswith("Normal") else "S/U"
            return f"{code} will be graded {'S/U' if item['grade_mode'] else 'A-F'}.", ["Nothing else about the class changed."], True
        if kind == "credits":
            item["credits"] = float(change["credits"])
            return f"{code} is now {change['credits']:g} credits.", [], True
        if kind in ("cart", "uncart"):
            item["status"] = "cart" if kind == "cart" else "planned"
            return f"{code} is {'in your cart' if kind == 'cart' else 'back in your plan'}.", [self._status_note(info)], True
        if kind == "withdraw":
            item["status"] = "withdrawn"
            return f"Withdrew from {code}. A W will show on your transcript.", ["Your other classes didn't change.", "This can't be undone here."], False
        raise Refused("unknown_change", 400)


# ---- advising: the advisor, open times, one appointment ------------------------------------------------------------
class Advising:
    ACTIONS = ("book", "cancel", "attend")
    id, label, source = "advising", "Advising appointments", "BeaverHub's Success Team"

    def read(self, ctx: Ctx, **_) -> dict:
        st = legacy(ctx)
        return {**stamp(ctx, self.label, self.source), "advisor": ctx.row["advisor_name"], "office": ctx.row["advisor_office"],
                "appointments": store.appointments(ctx.con, ctx.row, st, ctx.today), "slots": store.slots(ctx.con, ctx.row["id"], ctx.today),
                "holds": current_holds(ctx), "met": ctx.state["met"]}

    def _slot(self, ctx, sid):
        slot = next((s for s in store.slots(ctx.con, ctx.row["id"], ctx.today) if s["id"] == sid), None)
        if not slot:
            raise Refused("unknown_slot", 400)
        return slot

    def plan(self, ctx: Ctx, change: dict) -> dict:
        kind = change.get("type")
        upcoming = store.appointments(ctx.con, ctx.row, legacy(ctx), ctx.today)["upcoming"]
        who = ctx.row["advisor_name"]
        if kind == "book":
            slot = self._slot(ctx, change.get("slot"))
            when = f"{slot['day_inline']} at {slot['time_label']} ({slot['mode'].lower()}, {slot['minutes']} minutes)"
            if upcoming:
                old = upcoming[0]
                return plan_of(f"Move your meeting with {who}", [f"Cancels {old['day_inline']} at {old['time_label']}.", f"Books {when}."],
                               ["One step: you don't have to cancel first."], button="Move meeting")
            return plan_of(f"Book {who}", [f"Books {when}."], ["An advising hold comes off after you meet, not when you book."], button="Book it")
        if kind == "cancel":
            if not upcoming:
                return plan_of("Cancel your advisor meeting", blocks=[block("You don't have a meeting booked.", "Pick a time to book one.")])
            holds = [h for h in current_holds(ctx) if h["blocks"] and h["type"] == "advising"]
            return plan_of(f"Cancel your meeting with {who}", [f"Cancels {upcoming[0]['day_inline']} at {upcoming[0]['time_label']}."], [],
                           ["Your advising hold stays until you meet, so you'd need a new time before registration opens."] if holds else [], button="Cancel meeting")
        if kind == "attend":
            return plan_of("Demo only: pretend the meeting happened", ["Marks the advising meeting as attended.", "The advising hold comes off, as it would after a real meeting."],
                           ["This button exists only so the demo can show what happens next."], button="Pretend we met")
        raise Refused("unknown_change", 400)

    def apply(self, ctx: Ctx, change: dict) -> tuple[str, list[str], bool]:
        st, kind = ctx.state, change["type"]
        if kind == "book":
            slot = self._slot(ctx, change["slot"])
            st["appointment"], st["cancelled"] = {"slot": slot["id"]}, False
            return (f"Booked: you're meeting {ctx.row['advisor_name']} {slot['day_inline']} at {slot['time_label']} ({slot['mode'].lower()}).",
                    ["Any hold stays until after the meeting."], True)
        if kind == "cancel":
            st["appointment"], st["cancelled"] = None, True
            return "Cancelled your advisor meeting.", ["Pick a new time whenever you're ready."], True
        st["met"] = True
        return "Marked the advising meeting as attended (demo only). The advising hold is off.", [], True


# ---- billing: myBill ------------------------------------------------------------------------------------------------
class Billing:
    ACTIONS = ("enroll_plan", "paid")
    id, label, source = "billing", "Student billing", "myBill"
    PLAN_FEE, LATE_FEE = 15.0, 85.0

    def read(self, ctx: Ctx, **_) -> dict:
        bill = store.billing(ctx.con, ctx.row["id"], legacy(ctx), ctx.today)
        enrolled = bool(bill["plan_enrolled"]) or ctx.state["payment_plan"]
        statement = ctx.today.replace(day=5) if ctx.today.day >= 5 else (ctx.today.replace(day=1) - datetime.timedelta(days=1)).replace(day=5)
        return {**stamp(ctx, self.label, self.source), "billing": {**bill, "plan_enrolled": enrolled},
                "holds": [h for h in current_holds(ctx) if h["type"] == "financial"],
                "statements": [{"date": statement.isoformat(), "due": bill["due"], "amount": bill["balance"]}],
                "rules": [f"A ${self.LATE_FEE:.0f} late fee applies to an unpaid balance over $500 after the due date.",
                          "Paying by card adds a 3% fee ($3 minimum). An eCheck from a bank account has no fee.",
                          f"A payment plan costs ${self.PLAN_FEE:.0f} to join and spreads the term's balance over monthly payments."],
                "handoff": {"name": "myBill", "note": "Payments are made on myBill, OSU's billing site, run by a payment company. "
                                                      "Beaver Bot never sees or asks for a card or bank number."}}

    def plan(self, ctx: Ctx, change: dict) -> dict:
        kind = change.get("type")
        data = self.read(ctx)["billing"]
        if kind == "enroll_plan":
            if data["plan_enrolled"]:
                return plan_of("Join a payment plan", blocks=[block("You're already on a payment plan this term.", "")])
            if data["balance"] <= 0:
                return plan_of("Join a payment plan", blocks=[block("You don't owe anything this term, so there's nothing to spread out.", "")])
            return plan_of("Join this term's payment plan",
                           [f"Adds the ${self.PLAN_FEE:.0f} plan fee to your account.", f"Splits ${data['balance']:,.2f} into monthly payments."],
                           ["No payment is taken now. Payments themselves happen on myBill.", "While you stay current on the plan, the past-due hold comes off."],
                           ["Missing a plan payment brings the late fee and the hold back."], verify=True, button="Join the plan")
        if kind == "paid":
            if data["balance"] <= 0:
                return plan_of("Pay your balance", blocks=[block("You don't owe anything this term.", "")])
            return plan_of(f"Pay ${data['balance']:,.2f} on myBill", ["Sample data: marks the balance as paid, as if you had finished on myBill.", "A past-due hold comes off."],
                           [HANDOFF.format(site="myBill"), "No payment happens here."], button="Pretend it's paid")
        raise Refused("unknown_change", 400)

    def apply(self, ctx: Ctx, change: dict) -> tuple[str, list[str], bool]:
        if change["type"] == "enroll_plan":
            ctx.state["payment_plan"] = True      # on a plan and current: the hold is released, the balance is still owed
            return "You're on this term's payment plan (sample).", ["No payment was taken. The first payment would be made on myBill."], True
        ctx.state["paid"] = True
        return "Marked the balance as paid (sample). No payment happened.", ["In the real version you would have paid on myBill."], True


# ---- housing: MyUHDS -------------------------------------------------------------------------------------------------
class Housing:
    ACTIONS = ("maintenance", "cancel_request")
    id, label, source = "housing", "Housing", "MyUHDS"
    HALLS = ["Cedarbark Hall", "Riffle Hall", "Tanoak Hall", "Wapato Hall"]
    AREAS = ["My room", "Bathroom", "Hallway", "Lounge", "Laundry room"]

    def read(self, ctx: Ctx, reveal: bool = False, **_) -> dict:
        on_campus = lives_on_campus(ctx.row)
        hall = _pick(ctx.slug, self.HALLS, "hall")
        room = 100 + int(hashlib.sha256(ctx.slug.encode()).hexdigest(), 16) % 380
        box = 1000 + room * 3
        verified = bool(reveal) and ctx.session.public()["verified"]      # the combination needs a fresh "it's really me" check
        combo = ctx.state["housing"]["combination"]
        if verified:
            ctx.session.verified_until = 0.0        # one check shows it once; it doesn't also cover a withdrawal
        return {**stamp(ctx, self.label, self.source), "on_campus": on_campus,
                "room": {"hall": hall, "room": str(room), "type": "Double"} if on_campus else None,
                "mail": {"box": str(box), "combination": combo if verified else None, "hidden": not verified} if on_campus else None,
                "requests": list(ctx.state["housing"]["requests"]), "areas": self.AREAS,
                "urgent": "For flooding, no heat, a broken lock or anything unsafe, don't file a request: call the hall's front desk or Public Safety now."}

    def plan(self, ctx: Ctx, change: dict) -> dict:
        kind = change.get("type")
        data = self.read(ctx)
        if kind == "maintenance":
            if not data["on_campus"]:
                return plan_of("File a maintenance request", blocks=[block("You don't live in a residence hall, so there's no room to file for.", "")])
            area = change.get("area") if change.get("area") in self.AREAS else None
            text = " ".join(str(change.get("description") or "").split())[:300]
            if not area or len(text) < 8:
                return plan_of("File a maintenance request", blocks=[block("Pick where the problem is and describe it in a sentence.", "")])
            change["description"] = text
            return plan_of("File a maintenance request", [f"Sends a request for {data['room']['hall']} {data['room']['room']}, {area.lower()}: \"{text}\""],
                           ["Staff may enter your room to fix it.", "A confirmation goes to your OSU email."], [data["urgent"]], button="Send request")
        if kind == "cancel_request":
            hit = next((r for r in data["requests"] if r["id"] == change.get("id") and r["status"] == "Open"), None)
            if not hit:
                return plan_of("Cancel a request", blocks=[block("That request isn't open any more.", "")])
            return plan_of("Cancel this maintenance request", [f"Cancels \"{hit['description']}\"."], [], button="Cancel request")
        raise Refused("unknown_change", 400)

    def apply(self, ctx: Ctx, change: dict) -> tuple[str, list[str], bool]:
        reqs = ctx.state["housing"]["requests"]
        if change["type"] == "maintenance":
            reqs.append({"id": len(reqs) + 1, "area": change["area"], "description": change["description"], "status": "Open", "filed": ctx.today.isoformat()})
            return "Sent the maintenance request (sample).", ["Nothing was sent to a real housing office."], True
        next(r for r in reqs if r["id"] == change["id"])["status"] = "Cancelled"
        return "Cancelled the maintenance request.", [], True


# ---- the ID card: MyCard ---------------------------------------------------------------------------------------------
class Card:
    ACTIONS = ("add_money",)
    id, label, source = "card", "ID card and dining money", "MyCard"
    PLACES = ["Marketplace West", "Trader Bing's", "Cascadia Market", "JavaStop", "Bookstore cafe", "Vending, library"]
    LOW = 60.0

    def read(self, ctx: Ctx, **_) -> dict:
        bill = store.billing(ctx.con, ctx.row["id"], legacy(ctx), ctx.today) or {}
        dining, cash = float(bill.get("meal_plan") or 0), float(bill.get("orange_cash") or 0)
        added = ctx.state.setdefault("card", {"added": []})["added"]
        cash += sum(a["amount"] for a in added if a["account"] == "Orange Cash")
        dining += sum(a["amount"] for a in added if a["account"] == "Dining Dollars")
        # Purchases only come out of an account that had money in it, and someone who studies online isn't on campus buying coffee.
        funded = [name for name, had in (("Dining Dollars", bill.get("meal_plan")), ("Orange Cash", bill.get("orange_cash"))) if had]
        count = 0 if studies_online(ctx.row) or not funded else 8 if "Dining Dollars" in funded else 3
        tx = [{"date": ctx.today.isoformat(), "place": "Money added (sample)", "amount": a["amount"], "account": a["account"]} for a in reversed(added)]
        for n in range(count):
            day = ctx.today - datetime.timedelta(days=n * 2 + 1)
            amount = round(4 + (int(hashlib.sha256(f"{ctx.slug}{n}".encode()).hexdigest(), 16) % 900) / 100, 2)
            tx.append({"date": day.isoformat(), "place": _pick(ctx.slug, self.PLACES, str(n)), "amount": -amount,
                       "account": funded[1] if len(funded) > 1 and n % 3 == 0 else funded[0]})
        weeks = max(1, (datetime.date.fromisoformat(store.term(ctx.con, store.NOW_TERM)["end_date"]) - ctx.today).days // 7)
        return {**stamp(ctx, self.label, self.source), "card": "Active",
                "accounts": [{"name": "Dining Dollars", "balance": dining, "low": 0 < dining < self.LOW,
                              "note": (f"About ${dining / weeks:,.0f} a week until the term ends." if dining else "No dining plan this term.")},
                             {"name": "Orange Cash", "balance": cash, "low": False, "note": "Works on and off campus; never expires while you're a student."}],
                "transactions": tx, "note": ONLINE_NOTE if studies_online(ctx.row) else None,
                "handoff": {"name": "MyCard", "note": "Adding money happens on MyCard with its own payment page. Beaver Bot has no card form."}}

    def plan(self, ctx: Ctx, change: dict) -> dict:
        if change.get("type") != "add_money":
            raise Refused("unknown_change", 400)
        account = change.get("account") if change.get("account") in ("Orange Cash", "Dining Dollars") else "Orange Cash"
        amount = change.get("amount")
        if not isinstance(amount, (int, float)) or isinstance(amount, bool) or not 5 <= amount <= 500:
            return plan_of(f"Add money to {account}", blocks=[block("Pick an amount between $5 and $500.", "")])
        change.update(account=account, amount=round(float(amount), 2))
        return plan_of(f"Add ${amount:,.2f} to {account}", [f"Sample data: adds ${amount:,.2f} to your {account} balance, as if you had finished on MyCard."],
                       [HANDOFF.format(site="MyCard"), "No payment happens here."], button="Pretend it's added")

    def apply(self, ctx: Ctx, change: dict) -> tuple[str, list[str], bool]:
        ctx.state.setdefault("card", {"added": []})["added"].append({"account": change["account"], "amount": change["amount"]})
        return f"Added ${change['amount']:,.2f} to {change['account']} (sample). No payment happened.", ["In the real version you would have paid on MyCard."], True


# ---- parking ---------------------------------------------------------------------------------------------------------
class Parking:
    ACTIONS = ("join_waitlist", "leave_waitlist", "add_vehicle", "remove_vehicle", "buy_permit")
    id, label, source = "parking", "Parking", "the parking portal"
    PERMITS = [{"id": "A", "name": "A Zone (annual)", "price": 640, "sold_out": True, "zone": "Closest lots, central campus."},
               {"id": "B", "name": "B Zone (annual)", "price": 440, "sold_out": False, "zone": "Mid-campus lots and the parking structure."},
               {"id": "C", "name": "C Zone (annual)", "price": 130, "sold_out": False, "zone": "Edge lots with the campus shuttle."},
               {"id": "R", "name": "Residential (annual)", "price": 410, "sold_out": True, "zone": "For students living in a residence hall."},
               {"id": "M", "name": "Motorcycle (annual)", "price": 95, "sold_out": False, "zone": "Marked motorcycle spaces in any zone."}]

    def eligible(self, ctx: Ctx) -> tuple[list[str], str]:
        """Which permits this student can get, and why. It follows where they live, the same fact Housing shows."""
        if studies_online(ctx.row):
            return [], "You're an online student, so no annual permit is offered. For a visit to campus, the parking portal sells day permits."
        if lives_on_campus(ctx.row):
            return ["R"], "You live in a residence hall, so the Residential permit is the only one you can get."
        return ["A", "B", "C", "M"], "You live off campus, so you can get a commuter permit (A, B or C) or a motorcycle permit."

    def read(self, ctx: Ctx, **_) -> dict:
        st = ctx.state["parking"]
        ids, why = self.eligible(ctx)
        owned = st.setdefault("permits", [])
        return {**stamp(ctx, self.label, self.source), "permits": [{"id": p, "name": self._name(p)} for p in owned], "vehicles": st["vehicles"], "tickets": [],
                "for_sale": [{**p, "on_waitlist": p["id"] in st["waitlist"], "owned": p["id"] in owned} for p in self.PERMITS if p["id"] in ids],
                "eligibility": why,
                "handoff": {"name": "the parking portal", "note": "Buying a permit and paying a citation happen on the parking portal's own payment page."}}

    def plan(self, ctx: Ctx, change: dict) -> dict:
        kind, st = change.get("type"), ctx.state["parking"]
        if kind in ("join_waitlist", "leave_waitlist"):
            p = next((p for p in self.PERMITS if p["id"] == change.get("permit")), None)
            if not p:
                raise Refused("unknown_permit", 400)
            on = p["id"] in st["waitlist"]
            if kind == "join_waitlist" and p["id"] not in self.eligible(ctx)[0]:
                return plan_of(f"Join the {p['name']} waitlist", blocks=[block(f"You can't get the {p['name']} permit. {self.eligible(ctx)[1]}", "")])
            if kind == "join_waitlist" and not p["sold_out"]:
                return plan_of(f"Join the {p['name']} waitlist", blocks=[block("That permit isn't sold out, so there's no waitlist.", "Buy it on the parking portal.")])
            if (kind == "join_waitlist") == on:
                return plan_of("Parking waitlist", blocks=[block("You're already on that waitlist." if on else "You're not on that waitlist.", "")])
            if kind == "join_waitlist":
                return plan_of(f"Join the {p['name']} waitlist", ["Adds you to the waitlist. You're emailed if a permit opens up."],
                               ["Nothing is charged. You'd still buy the permit yourself if one is offered.", "You can still buy a different zone meanwhile."], button="Join waitlist")
            return plan_of(f"Leave the {p['name']} waitlist", ["Takes you off the waitlist."], [], button="Leave waitlist")
        if kind == "buy_permit":
            p = next((p for p in self.PERMITS if p["id"] == change.get("permit")), None)
            if not p:
                raise Refused("unknown_permit", 400)
            ids, why = self.eligible(ctx)
            if p["id"] not in ids:
                return plan_of(f"Buy the {p['name']} permit", blocks=[block(f"You can't get the {p['name']} permit. {why}", "")])
            if p["id"] in st.setdefault("permits", []):
                return plan_of(f"Buy the {p['name']} permit", blocks=[block("You already have that permit.", "")])
            if p["sold_out"]:
                return plan_of(f"Buy the {p['name']} permit", blocks=[block(f"The {p['name']} permit is sold out.", "Join its waitlist and you're emailed if one opens up.")])
            if not st["vehicles"]:
                return plan_of(f"Buy the {p['name']} permit", blocks=[block("Add a vehicle first. Your plate is your permit.", "Add your licence plate, then buy the permit.")])
            return plan_of(f"Buy the {p['name']} permit for ${p['price']:,.2f}", [f"Sample data: shows the {p['name']} permit under your permits, as if you had finished on the parking portal."],
                           [HANDOFF.format(site="the parking portal"), "No payment happens here."], button="Pretend it's bought")
        if kind == "add_vehicle":
            plate = re.sub(r"[^A-Z0-9]", "", str(change.get("plate") or "").upper())[:8]
            if len(plate) < 3 or any(v["plate"] == plate for v in st["vehicles"]):
                return plan_of("Add a vehicle", blocks=[block("Enter a plate with at least 3 letters or numbers that isn't already listed.", "")])
            change["plate"] = plate
            return plan_of(f"Add vehicle {plate}", [f"Adds plate {plate} to your parking account."], ["Your plate is your permit: there's no sticker."], button="Add vehicle")
        if kind == "remove_vehicle":
            if not any(v["plate"] == change.get("plate") for v in st["vehicles"]):
                raise Refused("unknown_vehicle", 400)
            return plan_of(f"Remove vehicle {change['plate']}", [f"Removes plate {change['plate']}."], [], button="Remove")
        raise Refused("unknown_change", 400)

    def _name(self, pid: str) -> str:
        return next(p["name"] for p in self.PERMITS if p["id"] == pid)

    def apply(self, ctx: Ctx, change: dict) -> tuple[str, list[str], bool]:
        st, kind = ctx.state["parking"], change["type"]
        if kind == "buy_permit":
            st.setdefault("permits", []).append(change["permit"])
            return f"The {self._name(change['permit'])} permit shows as bought (sample). No payment happened.", ["In the real version you would have paid on the parking portal."], True
        if kind == "join_waitlist":
            st["waitlist"].append(change["permit"])
            return f"You're on the waitlist for {self._name(change['permit'])} (sample).", ["Nothing was charged."], True
        if kind == "leave_waitlist":
            st["waitlist"].remove(change["permit"])
            return f"You're off the waitlist for {self._name(change['permit'])}.", [], True
        if kind == "add_vehicle":
            st["vehicles"].append({"plate": change["plate"]})
            return f"Added vehicle {change['plate']}.", [], True
        st["vehicles"] = [v for v in st["vehicles"] if v["plate"] != change["plate"]]
        return f"Removed vehicle {change['plate']}.", [], True


# ---- careers: Handshake ------------------------------------------------------------------------------------------------
class Careers:
    ACTIONS = ("save_job", "unsave_job", "book_career", "cancel_career", "apply_job")
    id, label, source = "careers", "Jobs and career help", "Handshake"
    JOBS = [("Peer tutor", "Learning commons (on campus)", "$16.50 an hour", "Part-time, on campus"),
            ("Front desk assistant", "Recreation center (on campus)", "$15.75 an hour", "Part-time, on campus"),
            ("Summer field technician", "Willamette Valley Watershed Group", "$21 an hour", "Internship, Corvallis"),
            ("Software engineering intern", "Tidewater Robotics", "$32 an hour", "Internship, Portland"),
            ("Marketing intern", "Three Rivers Credit Union", "$19 an hour", "Internship, hybrid"),
            ("Lab assistant", "Soil science lab (on campus)", "$16 an hour", "Part-time, on campus")]

    def read(self, ctx: Ctx, **_) -> dict:
        st = ctx.state["careers"]
        jobs = [{"id": n, "title": t, "employer": e, "pay": p, "type": k, "apply_by": (ctx.today + datetime.timedelta(days=9 + n * 4)).isoformat(),
                 "saved": n in st["saved"], "applied": n in st.setdefault("applied", [])} for n, (t, e, p, k) in enumerate(self.JOBS)]
        slots = [{"id": n, "label": f"{store.business_day(ctx.today, 2 + n).strftime('%A, %b')} {store.business_day(ctx.today, 2 + n).day} at {t}"}
                 for n, t in enumerate(["10:00 AM", "1:30 PM", "3:00 PM"])]
        return {**stamp(ctx, self.label, self.source), "jobs": jobs, "appointment": st["appointment"], "slots": slots,
                "checklist": [{"title": "Upload a resume", "done": False}, {"title": "Fill in your profile", "done": True}, {"title": "Set job preferences", "done": False}],
                "handoff": {"name": "Handshake", "note": "Applying to a job happens on Handshake, where your resume lives."}}

    def plan(self, ctx: Ctx, change: dict) -> dict:
        kind, data = change.get("type"), self.read(ctx)
        if kind in ("save_job", "unsave_job"):
            job = next((j for j in data["jobs"] if j["id"] == change.get("job")), None)
            if not job:
                raise Refused("unknown_job", 400)
            return plan_of(f"{'Save' if kind == 'save_job' else 'Unsave'} \"{job['title']}\"", [f"{'Saves' if kind == 'save_job' else 'Removes'} it {'to' if kind == 'save_job' else 'from'} your saved jobs."],
                           ["Saving isn't applying. The employer isn't told."], button="Save" if kind == "save_job" else "Unsave")
        if kind == "apply_job":
            job = next((j for j in data["jobs"] if j["id"] == change.get("job")), None)
            if not job:
                raise Refused("unknown_job", 400)
            if job["applied"]:
                return plan_of(f"Apply to \"{job['title']}\"", blocks=[block("You've already applied to that one.", "")])
            return plan_of(f"Apply to \"{job['title']}\"", [f"Sample data: marks \"{job['title']}\" at {job['employer']} as Applied, as if you had finished on Handshake."],
                           [HANDOFF.format(site="Handshake"), "Nothing is sent to an employer."], ["Your profile checklist still has \"Upload a resume\" open."], button="Pretend I applied")
        if kind == "book_career":
            slot = next((s for s in data["slots"] if s["id"] == change.get("slot")), None)
            if not slot:
                raise Refused("unknown_slot", 400)
            return plan_of("Book a career advising appointment", [f"Books {slot['label']} with a career advisor."] + (["Replaces the one you have."] if data["appointment"] else []),
                           [], button="Book it")
        if kind == "cancel_career":
            if not data["appointment"]:
                return plan_of("Cancel career appointment", blocks=[block("You don't have one booked.", "")])
            return plan_of("Cancel your career advising appointment", [f"Cancels {data['appointment']['label']}."], [], button="Cancel it")
        raise Refused("unknown_change", 400)

    def apply(self, ctx: Ctx, change: dict) -> tuple[str, list[str], bool]:
        st, kind = ctx.state["careers"], change["type"]
        if kind == "save_job":
            st["saved"] = sorted(set(st["saved"]) | {change["job"]})
            return "Saved the job (sample).", ["You haven't applied."], True
        if kind == "apply_job":
            st["applied"] = sorted(set(st.setdefault("applied", [])) | {change["job"]})
            return "Marked the job as applied (sample). Nothing was sent to an employer.", ["In the real version you would have applied on Handshake."], True
        if kind == "unsave_job":
            st["saved"] = [j for j in st["saved"] if j != change["job"]]
            return "Removed the saved job.", [], True
        if kind == "book_career":
            st["appointment"] = next(s for s in self.read(ctx)["slots"] if s["id"] == change["slot"])
            return f"Booked career advising for {st['appointment']['label']} (sample).", [], True
        st["appointment"] = None
        return "Cancelled the career advising appointment.", [], True


# ---- library -----------------------------------------------------------------------------------------------------------
class Library:
    ACTIONS = ("book_room", "cancel_room")
    id, label, source = "library", "Library", "the library's account and room booking"
    ROOMS = [{"id": 1, "name": "Study room 2A", "floor": 2, "seats": 4, "monitor": True}, {"id": 2, "name": "Study room 3C", "floor": 3, "seats": 6, "monitor": True},
             {"id": 3, "name": "Study room 4B", "floor": 4, "seats": 8, "monitor": False}, {"id": 4, "name": "Quiet room 5A", "floor": 5, "seats": 2, "monitor": False}]
    TIMES = ["10:00 AM", "12:00 PM", "2:00 PM", "4:00 PM", "6:00 PM"]

    def read(self, ctx: Ctx, **_) -> dict:
        days = [store.business_day(ctx.today, n) for n in range(0, 4)]
        return {**stamp(ctx, self.label, self.source), "loans": [], "requests": [], "fines": 0.0, "bookings": ctx.state["library"]["bookings"],
                "rooms": self.ROOMS, "times": self.TIMES, "days": [{"date": d.isoformat(), "label": store.day_label(d, ctx.today)} for d in days],
                "limit": "One booking a day, two hours each.", "note": ONLINE_NOTE if studies_online(ctx.row) else None}

    def plan(self, ctx: Ctx, change: dict) -> dict:
        kind, data = change.get("type"), self.read(ctx)
        if kind == "book_room":
            room = next((r for r in self.ROOMS if r["id"] == change.get("room")), None)
            day = next((d for d in data["days"] if d["date"] == change.get("date")), None)
            if not room or not day or change.get("time") not in self.TIMES:
                raise Refused("unknown_room", 400)
            if any(b["date"] == day["date"] for b in data["bookings"]):
                return plan_of("Book a study room", blocks=[block(f"You already have a room booked {store.day_inline(day['label'])}. The limit is one a day.",
                                                                  "Cancel that one first, or pick another day.")])
            taken = int(hashlib.sha256(f"{room['id']}{day['date']}{change['time']}".encode()).hexdigest(), 16) % 4 == 0
            if taken:
                return plan_of("Book a study room", blocks=[block(f"{room['name']} is already taken at {change['time']} {store.day_inline(day['label'])}.",
                                                                  "Pick another time or another room.")])
            return plan_of(f"Book {room['name']}", [f"Books {room['name']} (floor {room['floor']}, up to {room['seats']} people) {store.day_inline(day['label'])} at {change['time']} for 2 hours."],
                           ["The room is released if nobody shows up in the first 15 minutes."], button="Book room")
        if kind == "cancel_room":
            hit = next((b for b in data["bookings"] if b["id"] == change.get("id")), None)
            if not hit:
                return plan_of("Cancel a room", blocks=[block("That booking isn't there any more.", "")])
            return plan_of(f"Cancel {hit['room']}", [f"Cancels {hit['room']} on {hit['label']} at {hit['time']}."], [], button="Cancel booking")
        raise Refused("unknown_change", 400)

    def apply(self, ctx: Ctx, change: dict) -> tuple[str, list[str], bool]:
        rows = ctx.state["library"]["bookings"]
        if change["type"] == "book_room":
            room = next(r for r in self.ROOMS if r["id"] == change["room"])
            label = store.day_label(datetime.date.fromisoformat(change["date"]), ctx.today)
            rows.append({"id": max([b["id"] for b in rows], default=0) + 1, "room": room["name"], "date": change["date"], "label": label, "time": change["time"]})
            return f"Booked {room['name']} {store.day_inline(label)} at {change['time']} (sample).", [], True
        ctx.state["library"]["bookings"] = [b for b in rows if b["id"] != change["id"]]
        return "Cancelled the study room.", [], True


# ---- read-only systems ---------------------------------------------------------------------------------------------------
class ReadOnly:
    def plan(self, ctx, change):
        raise Refused("read_only", 400)

    apply = plan


class Canvas(ReadOnly):
    id, label, source = "canvas", "Coursework", "Canvas"
    KINDS = ["Homework", "Quiz", "Discussion post", "Lab report", "Reading response", "Problem set"]

    def read(self, ctx: Ctx, **_) -> dict:
        courses = []
        for n, i in enumerate(x for x in SYSTEMS["registration"].items(ctx, store.NOW_TERM) if x["status"] == "registered"):
            due = [{"title": f"{_pick(ctx.slug, self.KINDS, f'{n}{k}')} {3 + k + n}", "due": (ctx.today + datetime.timedelta(days=1 + (n + k * 3) % 9)).isoformat()}
                   for k in range(1 + (n % 2))]
            courses.append({"course": i["lecture"]["course"], "title": i["lecture"]["title"], "due": due})
        todo = sorted(({"course": c["course"], **d} for c in courses for d in c["due"]), key=lambda d: d["due"])
        return {**stamp(ctx, self.label, self.source), "courses": courses, "todo": todo,
                "note": "Beaver Bot reads what's due. It can't see or change grades, and it never submits work."}


class Degree(ReadOnly):
    id, label, source = "degree", "Degree progress", "MyDegrees"

    def read(self, ctx: Ctx, view: str = "audit", program: int | None = None, **_) -> dict:
        st = legacy(ctx)
        if view == "whatif" and isinstance(program, int):
            body = audit.what_if(ctx.con, ctx.slug, program)
        elif view == "remaining":
            body = audit.remaining(ctx.con, ctx.slug, st)
        elif view == "plan":
            body = audit.winter_plan(ctx.con, ctx.slug, st)
        elif view == "checklist":
            body = audit.checklist(ctx.con, ctx.slug, st, ctx.today)
        else:
            body = audit.audit(ctx.con, ctx.slug, st)
        if body is None:
            raise Refused("not_found", 404)
        return {**stamp(ctx, self.label, self.source), "view": view, **body,
                "snapshot": "A degree audit is a snapshot. A grade posted or a class added since it last refreshed won't show yet."}


class Wellness(ReadOnly):
    """Student Health, Counseling and Disability Access Services: the light-touch rule. Beaver Bot may show that an
    appointment exists or that letters are ready, and where to go. It never shows a reason, a diagnosis, a
    provider's notes or which accommodations someone has."""
    id, label, source = "wellness", "Health and access", "each office's own portal"

    def read(self, ctx: Ctx, **_) -> dict:
        n = int(hashlib.sha256(ctx.slug.encode()).hexdigest(), 16)
        day = store.business_day(ctx.today, 3 + n % 4)
        items = [{"office": "Student Health Services", "line": f"You have an appointment on {day.strftime('%A, %b')} {day.day}." if n % 2 else "No upcoming appointments.",
                  "portal": "the patient portal"},
                 {"office": "Counseling & Psychological Services", "line": "No upcoming appointments.", "portal": "the counseling portal"},
                 {"office": "Disability Access Services", "line": "Your accommodation letters for this term are ready to send." if n % 3 == 0 else "Nothing waiting for you.",
                  "portal": "the DAS portal"}]
        return {**stamp(ctx, self.label, self.source), "items": items,
                "rule": "Beaver Bot only shows that something exists and where to see it. The details stay in each office's own portal."}


class Home(ReadOnly):
    """The signed-in overview: one line per system, each drawn from that system's adapter."""
    id, label, source = "home", "Your overview", "all connected systems"

    def read(self, ctx: Ctx, **_) -> dict:
        st = legacy(ctx)
        dash = audit.dashboard(ctx.con, ctx.slug, st, ctx.today)
        reg = SYSTEMS["registration"].read(ctx, store.REG_TERM)
        return {**stamp(ctx, self.label, self.source), "student": dash["student"], "registration": reg["term"], "cannot_register": reg["cannot_register"],
                "holds": current_holds(ctx), "appointments": dash["appointments"], "billing": SYSTEMS["billing"].read(ctx)["billing"],
                "tasks": dash["tasks"], "checklist": dash["checklist"], "credits": reg["credits"], "counts": reg["counts"],
                "this_term": [i["lecture"]["course"] for i in SYSTEMS["registration"].items(ctx, store.NOW_TERM) if i["status"] == "registered"]}


SYSTEMS = {s.id: s for s in (Home(), Registration(), Advising(), Billing(), Housing(), Card(), Parking(), Careers(), Library(), Canvas(), Degree(), Wellness())}
UNDO_KEYS = {"registration": ["terms"], "advising": ["appointment", "cancelled", "met"], "billing": ["payment_plan", "paid"], "housing": ["housing"], "card": ["card"],
             "parking": ["parking"], "careers": ["careers"], "library": ["library"]}


def read(ctx: Ctx, system: str, **options) -> dict:
    if system not in SYSTEMS:
        raise Refused("unknown_system", 404)
    return SYSTEMS[system].read(ctx, **options)


def propose(hub, ctx: Ctx, system: str, change: dict, by: str = "student") -> dict:
    """Work out what a change would do and file it as a proposal. Changes nothing."""
    if system not in SYSTEMS or not isinstance(change, dict):
        raise Refused("unknown_system", 404)
    change = copy.deepcopy(change)
    plan = SYSTEMS[system].plan(ctx, change)
    return hub.propose(ctx.session, system, change, plan, by)


def confirm(hub, ctx: Ctx, pid, token) -> dict:
    """Carry out a proposal the student confirmed. One change at a time per session, and the checks are run
    again first, because things may have changed since the review was written (another tab, a seat taken, the
    registration window). If what would happen is no longer what the student read, it is not carried out."""
    with ctx.session.lock:
        p = hub.take(ctx.session, pid, token)
        adapter = SYSTEMS[p.system]
        fresh = adapter.plan(ctx, copy.deepcopy(p.change))
        if fresh["blocks"]:
            raise Refused("blocked", 409, fresh["blocks"][0]["reason"])
        if (fresh["effects"], fresh["warnings"], fresh["verify"]) != (p.plan["effects"], p.plan["warnings"], p.plan["verify"]):
            raise Refused("proposal_changed", 409)
        if fresh["verify"] and not ctx.session.public()["verified"]:
            p.used = False                              # the same review can be confirmed once the fresh check is done
            raise Refused("verify_first", 403)
        before = {k: copy.deepcopy(ctx.state[k]) for k in UNDO_KEYS[p.system]}
        summary, details, undoable = adapter.apply(ctx, p.change)
        entry = hub.record(ctx.session, p.system, summary, {"restore": before} if undoable else None, details)
        if fresh["verify"]:
            ctx.session.verified_until = 0.0            # a fresh check covers one high-impact change, not a spree
        return {"ok": True, "summary": summary, "details": details, "history_id": entry["id"], "can_undo": undoable, "system": p.system}


def _registered(state: dict, con) -> dict:
    """Registered credits in each term, for telling whether an undo would drop someone below full-time."""
    out = {}
    for term, rows in state.get("terms", {}).items():
        out[term] = sum((i["credits"] if i["credits"] is not None else (store.section(con, i["crn"]) or {}).get("credits") or 0)
                        for i in rows if i["status"] == "registered")
    return out


def undo(hub, ctx: Ctx, history_id) -> dict:
    """Reverse the most recent change in a system, where the real system would allow it. An undo that would take
    the student below full-time is a high-impact change like any other, so it needs the fresh check too."""
    with ctx.session.lock:
        entry = next((e for e in ctx.session.history if e["id"] == history_id and e["student"] == ctx.slug), None)
        if not entry or entry["undone"] or not entry["undo"]:
            raise Refused("cannot_undo", 409)
        later = [e for e in ctx.session.history if e["id"] > entry["id"] and e["system"] == entry["system"] and e["student"] == ctx.slug
                 and not e["undone"] and not e.get("is_undo")]
        if later:
            raise Refused("undo_latest_first", 409)
        restore = entry["undo"]["restore"]
        if "terms" in restore:
            now, then = _registered(ctx.state, ctx.con), _registered(restore, ctx.con)
            if any(then[t] < FULL_TIME <= now[t] for t in now) and not ctx.session.public()["verified"]:
                raise Refused("verify_first", 403)
            ctx.session.verified_until = 0.0 if any(then[t] < FULL_TIME <= now[t] for t in now) else ctx.session.verified_until
        ctx.state.update(copy.deepcopy(restore))
        entry["undone"] = True
        done = hub.record(ctx.session, entry["system"], f"Undid: {entry['summary']}", None)
        done["is_undo"] = True
        return {"ok": True, "summary": done["summary"], "system": entry["system"]}


def history(hub, ctx: Ctx) -> list[dict]:
    """What was done this session for this student, newest first. Undo is offered only for the latest change in
    each system, and only where the real system would allow it."""
    rows = hub.history(ctx.session)
    seen = set()
    for row in rows:                                # newest first
        if row.get("is_undo") or row["undone"]:
            row["can_undo"] = False
            continue
        row["can_undo"] = row["can_undo"] and row["system"] not in seen
        seen.add(row["system"])
    return rows


def reset(ctx: Ctx, everyone: bool = False) -> None:
    """Put this visitor's sample data back the way it started."""
    s = ctx.session
    if everyone:
        s.sandboxes.clear()
        s.history.clear()
        s.clock_days = 0
    else:
        s.sandboxes.pop(s.slug, None)
        s.history[:] = [e for e in s.history if e["student"] != s.slug]
    s.proposals.clear()
    seed(ctx)
