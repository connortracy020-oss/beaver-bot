"""Changes a student asks for in the chat, turned into the same change a panel's button would ask for. SAMPLE DATA ONLY.

The chat can ask for anything a panel can: book a study room, send a maintenance request, join a parking waitlist,
save a job, join the payment plan, and so on. A request from the chat is only words ("book a study room tomorrow at
2"), so this module works out which room, which day, which job, and hands back (system, change). From there it goes
through exactly the path a button takes: the server writes out what would happen, the student reviews and confirms,
and it can be undone (systems.propose / confirm / undo). Nothing here changes anything, and the model never gets
further than asking.

`CHAT_ACTIONS` lists which chat tool reaches which panel action. A test checks it against every adapter's ACTIONS,
so a panel can't gain an action the chat doesn't have without someone deciding that on purpose.
"""
import copy
import re

from . import store
from .hub import Refused
from .systems import SYSTEMS, Ctx, read

# chat tool -> (system, the change types it can ask for, the site card shown with it)
CHAT_ACTIONS = {
    "library_book": ("library", ("book_room",), "library"), "library_cancel": ("library", ("cancel_room",), "library"),
    "housing_request": ("housing", ("maintenance",), "housing"), "housing_cancel": ("housing", ("cancel_request",), "housing"),
    "parking_waitlist": ("parking", ("join_waitlist",), "parking"), "parking_leave_waitlist": ("parking", ("leave_waitlist",), "parking"),
    "parking_add_vehicle": ("parking", ("add_vehicle",), "parking"), "parking_remove_vehicle": ("parking", ("remove_vehicle",), "parking"),
    "parking_buy": ("parking", ("buy_permit",), "parking"),
    "careers_save": ("careers", ("save_job",), "careers"), "careers_unsave": ("careers", ("unsave_job",), "careers"),
    "careers_apply": ("careers", ("apply_job",), "careers"), "careers_book": ("careers", ("book_career",), "careers"),
    "careers_cancel": ("careers", ("cancel_career",), "careers"),
    "billing_plan": ("billing", ("enroll_plan",), "billing"), "billing_pay": ("billing", ("paid",), "billing"),
    "card_add_money": ("card", ("add_money",), "id_card"),
    "reg_register": ("registration", ("register",), "schedule"), "reg_cart": ("registration", ("cart", "uncart"), "schedule"),
    "reg_withdraw": ("registration", ("withdraw",), "schedule"), "reg_grade": ("registration", ("grade_mode",), "schedule"),
}
# Reached by chat tools that existed before this module (beaverbot/server.py TOOL_CHANGES).
OLDER = {("registration", "add"), ("registration", "add_many"), ("registration", "remove"), ("advising", "book"), ("advising", "cancel")}
# Panel only, on purpose: fine adjustments to a class that need its section list on screen, and a demo control.
PANEL_ONLY = {("registration", "swap"), ("registration", "linked"), ("registration", "move"), ("registration", "credits"), ("advising", "attend")}

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def _time(text: str, times: list[str]) -> str | None:
    """ "at 2", "2pm", "14:00", "noon" -> the nearest bookable time."""
    low = text.lower()
    m = re.search(r"\b(\d{1,2})(?::(\d\d))?\s*(am|pm|a\.m\.|p\.m\.)?", low)
    if "noon" in low:
        hour = 12
    elif m and 1 <= int(m.group(1)) <= 23 and (m.group(3) or m.group(2) or re.search(r"\bat\s+" + m.group(1) + r"\b", low)):
        hour = int(m.group(1))
        if (m.group(3) or "").startswith("p") and hour < 12:
            hour += 12
        elif not m.group(3) and hour < 8:
            hour += 12                         # "at 2" means the afternoon
    else:
        return None
    def minutes(label):
        h, rest = label.split(":")
        return (int(h) % 12 + (12 if rest.endswith("PM") else 0)) * 60
    return min(times, key=lambda t: abs(minutes(t) - hour * 60))


def _day(text: str, days: list[dict]) -> dict | None:
    low = text.lower()
    for d in days:
        label = d["label"].lower()
        if label.split(",")[0] in low or any(w in low and w in label for w in WEEKDAYS):
            return d
    return None


def resolve(ctx: Ctx, tool: str, query: str = "", number=None) -> tuple[str, dict | None, str | None]:
    """(system, change, problem). `problem` is what to ask the student when the request can't be pinned down."""
    if tool not in CHAT_ACTIONS:
        raise Refused("unknown_change", 400)
    system = CHAT_ACTIONS[tool][0]
    query = " ".join(str(query or "").split())[:300]
    low = query.lower()
    pick = number if isinstance(number, int) and not isinstance(number, bool) and number >= 1 else None
    data = read(ctx, system) if system != "registration" else None

    if tool == "library_book":
        day = _day(query, data["days"]) or next((d for d in data["days"] if not any(b["date"] == d["date"] for b in data["bookings"])), data["days"][0])
        time = _time(query, data["times"]) or "2:00 PM"
        people = re.search(r"\b(\d+)\s*(people|of us|person|students|friends)", low)
        rooms = sorted(data["rooms"], key=lambda r: r["seats"])
        if people:
            rooms = [r for r in rooms if r["seats"] >= int(people.group(1))] or rooms[-1:]
        if "screen" in low or "monitor" in low:
            rooms = [r for r in rooms if r["monitor"]] or rooms
        for room in rooms:                       # the first room that is actually free then
            change = {"type": "book_room", "room": room["id"], "date": day["date"], "time": time}
            if not SYSTEMS["library"].plan(ctx, copy.deepcopy(change))["blocks"]:
                return system, change, None
        return system, {"type": "book_room", "room": rooms[0]["id"], "date": day["date"], "time": time}, None
    if tool == "library_cancel":
        if not data["bookings"]:
            return system, None, "You don't have a study room booked, so there's nothing to cancel."
        day = _day(query, [{"label": b["label"], "date": b["date"]} for b in data["bookings"]])
        hit = next((b for b in data["bookings"] if day and b["date"] == day["date"]), data["bookings"][-1])
        return system, {"type": "cancel_room", "id": hit["id"]}, None

    if tool == "housing_request":
        area = next((a for a in data["areas"] if a.lower().replace("my ", "") in low), "My room")
        if len(query) < 8:
            return system, None, "What's the problem, and where is it? One sentence is enough, like \"the heater in my room rattles all night\"."
        return system, {"type": "maintenance", "area": area, "description": query}, None
    if tool == "housing_cancel":
        hit = next((r for r in reversed(data["requests"]) if r["status"] == "Open"), None)
        if not hit:
            return system, None, "You don't have an open maintenance request to cancel."
        return system, {"type": "cancel_request", "id": hit["id"]}, None

    if system == "parking":
        named = re.search(r"\b([abcrm])[ -]?(?:zone|lot)\b|\b(?:zone|lot|permit) ([abcrm])\b|^([abcrm])$", low)      # "a permit" is not the A zone
        permit = "R" if "resident" in low else "M" if "motorcycle" in low else next(g for g in named.groups() if g).upper() if named else None
        offered = data["for_sale"]
        if tool == "parking_buy":
            choice = permit or next((p["id"] for p in offered if not p["sold_out"]), None) or (offered[0]["id"] if offered else None)
            if not choice:
                return system, None, data["eligibility"]
            return system, {"type": "buy_permit", "permit": choice}, None
        if tool == "parking_waitlist":
            choice = permit or next((p["id"] for p in offered if p["sold_out"] and not p["on_waitlist"]), None)
            if not choice:
                return system, None, (data["eligibility"] if not offered else "None of the permits you can get is sold out, so there's no waitlist to join.")
            return system, {"type": "join_waitlist", "permit": choice}, None
        if tool == "parking_leave_waitlist":
            choice = permit or next((p["id"] for p in offered if p["on_waitlist"]), None)
            if not choice:
                return system, None, "You're not on a parking waitlist."
            return system, {"type": "leave_waitlist", "permit": choice}, None
        # "abc 123", "ABC-123" and "ABC123" are the same plate
        plates = [re.sub(r"[^A-Z0-9]", "", w) for w in re.findall(r"\b[A-Z]{1,4}[ -]?\d{2,4}[A-Z]{0,3}\b|\b\d{2,4}[ -]?[A-Z]{2,4}\b|\b[A-Z0-9]{3,8}\b", query.upper())]
        plates = [w for w in plates if re.search(r"\d", w) and 3 <= len(w) <= 8]
        if tool == "parking_add_vehicle":
            if not plates:
                return system, None, "What's the licence plate? Type it like ABC123."
            return system, {"type": "add_vehicle", "plate": plates[0]}, None
        mine = [v["plate"] for v in data["vehicles"]]
        hit = next((p for p in plates if p in mine), mine[0] if len(mine) == 1 else None)
        if not hit:
            return system, None, ("You don't have a vehicle on file." if not mine else "Which plate should I remove? You have " + ", ".join(mine) + ".")
        return system, {"type": "remove_vehicle", "plate": hit}, None

    if system == "careers":
        if tool == "careers_cancel":
            return system, {"type": "cancel_career"}, None
        if tool == "careers_book":
            slot = data["slots"][pick - 1] if pick and pick <= len(data["slots"]) else (_slot_named(low, data["slots"]) or data["slots"][0])
            return system, {"type": "book_career", "slot": slot["id"]}, None
        words = [w for w in re.findall(r"[a-z]+", low) if len(w) > 3 and w not in ("that", "this", "the", "job", "save", "apply", "position", "internship", "role")]
        job = data["jobs"][pick - 1] if pick and pick <= len(data["jobs"]) else next(
            (j for j in data["jobs"] if any(w in (j["title"] + " " + j["employer"]).lower() for w in words)), None)
        if tool == "careers_unsave" and not job:
            job = next((j for j in data["jobs"] if j["saved"]), None)
        if not job:
            return system, None, "Which job? Tell me its name, like \"the peer tutor one\", or pick it on the card."
        return system, {"type": {"careers_save": "save_job", "careers_unsave": "unsave_job", "careers_apply": "apply_job"}[tool], "job": job["id"]}, None

    if tool == "billing_plan":
        return system, {"type": "enroll_plan"}, None
    if tool == "billing_pay":
        return system, {"type": "paid"}, None
    if tool == "card_add_money":
        amount = re.search(r"\$?\s*(\d{1,3}(?:\.\d\d)?)", query)
        if not amount:
            return system, None, "How much would you like to add? Between $5 and $500."
        return system, {"type": "add_money", "amount": float(amount.group(1)), "account": "Dining Dollars" if "dining" in low else "Orange Cash"}, None

    # registration: the class is named in words, so find it among the student's classes in the right term
    from . import intents
    if tool == "reg_register":
        return system, {"type": "register", "term": store.REG_TERM}, None
    term = store.NOW_TERM if tool in ("reg_withdraw", "reg_grade") else store.REG_TERM
    items = read(ctx, "registration", term=term)["items"]
    code = intents.course_in(ctx.con, query) if query else None
    hit = next((i for i in items if i["lecture"]["course"] == code), None) or next(
        (i for i in items if any(w in i["lecture"]["title"].lower() for w in re.findall(r"[a-z]{4,}", low))), None)
    if not hit and tool == "reg_grade" and not code:
        hit = None
    if not hit:
        mine = ", ".join(i["lecture"]["course"] for i in items) or "none"
        return system, None, f"Which class do you mean? In that term you have: {mine}."
    if tool == "reg_cart":
        return system, {"type": "uncart" if hit["status"] == "cart" and re.search(r"\b(out|remove|take)\b", low) else "cart", "term": term, "crn": hit["crn"]}, None
    if tool == "reg_withdraw":
        return system, {"type": "withdraw", "term": term, "crn": hit["crn"]}, None
    return system, {"type": "grade_mode", "term": term, "crn": hit["crn"], "mode": "S/U" if re.search(r"s/u|pass|satisf", low) else "Normal grading (A-F)"}, None


def _slot_named(low: str, slots: list[dict]) -> dict | None:
    return next((s for s in slots if any(w in low and w in s["label"].lower() for w in WEEKDAYS)), None)
