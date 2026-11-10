"""The sample-data tools a signed-in demo visitor can use from the conversation.

`run_tool` runs one tool by name and returns the reply the browser renders. It is what the model calls when it is
running the conversation (beaverbot/talk.py). `route` is the offline stand-in: it picks a tool from the wording of
a message with plain patterns, and returns None for anything that is a question about OSU itself, so that still
goes to the real answer pipeline and its sources.

Every reply built here is marked as sample data. Tools that change something (a class added to the plan, an
appointment booked) return an `apply` instruction; the change itself lives in the visitor's browser tab only.
"""
import datetime
import re

from assistant.retrieve import COURSE_RE

from . import audit, finder, store

INFO_START = re.compile(r"^\s*(how|when|what happens|what is|what are|what's the|where|who|why|can i|do i need|does|is there|are there)\b", re.I)
FILLER = set("""find me a an the i need to take for looking search some another new good open winter next term
class classes course courses section sections please want would like get into sign up fit fits that my schedule
with and in on at of help can you could is are there any this spring fall time times have trying enroll""".split())

RX = {
    "whatif": re.compile(r"what if i (switch|chang|transfer|mov)\w*|\bswitch(ing|ed)?\b.{0,20}\bto\b|chang\w+ (my )?major|"
                         r"if i (majored|were|was) in|\bwhat-?if\b", re.I),
    "plan": re.compile(r"\b(build|make|create|draft|plan|put together)\b.{0,25}\b(winter|next term|my)\b.{0,20}\b(plan|schedule|term)\b|"
                       r"\bwinter plan\b|\bplan (my|for) winter\b", re.I),
    "remaining": re.compile(r"what (classes |courses |else )?(do|should) i (still )?(need|have left|take)|"
                            r"requirements? (do i have )?(left|remaining)|what('s| is) left|\bstill need\b|what do i need next", re.I),
    "checklist": re.compile(r"checklist|am i ready|ready to register|before i register|pre-?registration|ready for registration", re.I),
    "appointment": re.compile(r"\b(book|schedule|make|set up|reschedule|cancel|move|change)\b.{0,30}\b(appointment|meeting|advis[oe]r)|"
                              r"\b(meet|see|talk to)\b.{0,12}\bmy advis[oe]r|advis[oe]r appointment|who is my advis[oe]r", re.I),
    "registration": re.compile(r"\b(my )?holds?\b|when (can|do|does) (i|my) regist|why can'?t i register|"
                               r"registration (open|time|date|day)|my registration|when (is|does) registration|"
                               r"\b(help me|i want to|i need to|let me|time to|ready to)\b.{0,12}\bregister\b|^register( for (my )?classes)?[.!]?$", re.I),
    "billing": re.compile(r"\b(my|a) balance\b|how much do i (still )?owe|what do i owe|what('s| is) my (bill|balance)|"
                          r"(show|see|view|check|pay) (me )?my (bill|balance)|where do i pay|\bamount due\b|my bill$", re.I),
    "audit": re.compile(r"degree audit|my audit|mydegrees|still needed|not met|explain (my|this|the) (audit|degree|gpa|line)|"
                        r"what does .{0,50} mean|my (gpa|degree progress|progress|degree checklist)|am i on track", re.I),
    "forms": re.compile(r"\b(forms?|petitions?)\b", re.I),
    "schedule": re.compile(r"\bmy (schedule|classes|plan|winter)\b|\b(drop|swap|remove)\b.{0,30}\b(plan|schedule|[A-Za-z]{2,4} ?\d{3})|"
                           r"simulate registration|show (me )?my (classes|week)", re.I),
    "finder": re.compile(r"\b(find|need|looking for|search for|sign up for|get into|fits?|open)\b.{0,40}\b(class|classes|course|section|recitation|lab|lecture)\b|"
                         r"class finder|\b(class|section)s? (that|which) fit|which sections|"
                         r"\b(need|want|have|trying|like|going) to (take|enroll in|sign up for|get into)\b|\b(add|put)\b.{0,30}\b(to|in|on) my (plan|schedule|calendar)\b", re.I),
    "resources": re.compile(r"\b(beaver ?hub|which (tool|link|site)|where (do|can) i find)\b", re.I),
}
TIME_WORDS = re.compile(r"\b(morning|afternoon|evening|night|online|ecampus|on[- ]campus|in[- ]person|mwf|no (mon|tue|wed|thu|fri)|"
                        r"avoid|fridays?|mondays?)\b", re.I)
TOOLS = ("registration", "appointment", "book_appointment", "cancel_appointment", "checklist", "remaining", "whatif", "plan",
         "add_plan_all", "find_class", "add_to_plan", "drop_from_plan", "schedule", "forms", "billing", "audit", "resources",
         "housing", "id_card", "parking", "careers", "library", "coursework", "wellness",
         # changes on the connected sites; each becomes a review the student confirms (beaverbot/demo/actions.py)
         "library_book", "library_cancel", "housing_request", "housing_cancel", "parking_waitlist", "parking_leave_waitlist", "parking_add_vehicle",
         "parking_remove_vehicle", "parking_buy", "careers_save", "careers_unsave", "careers_apply", "careers_book", "careers_cancel", "billing_plan",
         "billing_pay", "card_add_money", "reg_register", "reg_cart", "reg_withdraw", "reg_grade")
# chat tool -> the site whose card goes with it. The same table, with the change each one asks for, is actions.CHAT_ACTIONS.
ACTION_SITE = {"library_book": "library", "library_cancel": "library", "housing_request": "housing", "housing_cancel": "housing", "parking_waitlist": "parking",
               "parking_leave_waitlist": "parking", "parking_add_vehicle": "parking", "parking_remove_vehicle": "parking", "parking_buy": "parking",
               "careers_save": "careers", "careers_unsave": "careers", "careers_apply": "careers", "careers_book": "careers", "careers_cancel": "careers",
               "billing_plan": "billing", "billing_pay": "billing", "card_add_money": "id_card", "reg_register": "schedule", "reg_cart": "schedule",
               "reg_withdraw": "schedule", "reg_grade": "schedule"}
# Read-only looks at the other connected sites. The words are fixed and say nothing specific: the card under the
# reply is written by the server from the visitor's own sandbox (beaverbot/demo/draft.py), so it is the one place
# the details come from.
SITES = {"housing": "Here's what your housing account shows: your room, your mailbox and any maintenance requests.",
         "id_card": "Here's your ID card: your dining and Orange Cash balances and your latest purchases.",
         "parking": "Here's your parking: permits, vehicles, citations and what's for sale.",
         "careers": "Here's your jobs and career page: openings, your career appointment and your to-do list.",
         "library": "Here's your library account: loans, fines and study room bookings.",
         "coursework": "Here's what's due in your classes.",
         "wellness": "Here's what I can show for health, counseling and disability access. I only see that something exists and where to open it, never the details."}
# Every name a reply can carry in "tool". Each one gets a card under the reply (draft.chat_card); a test checks it.
REPLY_TOOLS = ("registration", "appointment", "checklist", "remaining", "whatif", "whatif_ask", "plan", "plan_prefs", "schedule", "finder_options", "finder_prefs",
               "finder_course", "forms", "billing", "audit", "resources", *SITES)


def _reply(tool: str, text: str, data: dict | None = None, flow: dict | None = None, chips: list[str] | None = None,
           apply: dict | None = None) -> dict:
    return {"kind": "demo", "tool": tool, "text": text, "data": data or {}, "flow": flow, "chips": chips or [],
            "apply": apply, "sample": True, "reason": "demo", "pages": [], "cites": {}, "contacts": [], "followups": [],
            "category": None, "checked": None, "mode": "sample data", "lang": "en"}


def course_in(con, text: str) -> str | None:
    """A real course this text names: by code first, then by a word or two of its title ("vector calc")."""
    for subject, number in COURSE_RE.findall(text):
        for code in (f"{subject.upper()} {number.upper()}", f"{subject.upper()} {number.upper()}Z"):
            if store.course(con, code):
                return code
    words = [w for w in re.findall(r"[a-z]+", text.lower()) if w not in FILLER and len(w) > 2
             and not TIME_WORDS.fullmatch(w)]
    words = [w for w in words if w not in ("morning", "mornings", "afternoon", "afternoons", "evening", "evenings",
                                           "online", "campus", "person", "avoid", "friday", "fridays", "monday",
                                           "mondays", "only", "not", "what", "still", "requirement", "requirements",
                                           "add", "put", "plan", "calendar")]
    if 1 <= len(words) <= 4:
        found = store.search_courses(con, " ".join(words), limit=1)
        if not found and len(words) > 1:
            found = store.search_courses(con, " ".join(w[:4] if len(w) > 5 else w for w in words), limit=1)   # "calc" finds "calculus"
        if found:
            return found[0]["code"]
    return None


def _when(section: dict) -> str:
    m = next((m for m in section["meetings"] if not m["tba"]), None)
    return f"{m['days_label']} {m['time_label'].split(' to ')[0]}" if m else "online"


def _start(option: dict) -> int:
    return min((m["start"] for m in option["lecture"]["meetings"] if not m["tba"]), default=24 * 60)


def _find_sorted(con, slug: str, code: str, prefs: dict, state: dict) -> dict:
    """The class finder's results, earliest first, so "the first one" and "the 9:00 AM one" mean what the card shows."""
    found = finder.find(con, slug, code, prefs, state)
    found["options"].sort(key=_start)
    found["closest"].sort(key=_start)
    return found


def _drafted(con, state: dict, code: str) -> dict | None:
    """The class in the plan being worked out in the chat, if this course is in it."""
    return next((p for p in store.plan_sections(con, {"plan": state.get("draft") or []}) if p["lecture"]["course"] == code), None)


# How a Spanish speaker names a subject, as the start of the English word in a class title.
SUBJECTS_ES = (("quim", "chem"), ("escrit", "writ"), ("redacc", "writ"), ("matem", "math"), ("calcul", "calc"), ("estadist", "statist"), ("fisic", "physic"),
               ("biolog", "biolog"), ("datos", "data"), ("negocio", "business"), ("psicolog", "psycholog"), ("econom", "econom"), ("histor", "histor"),
               ("comunic", "communic"), ("etica", "ethic"), ("finanz", "financ"), ("ingenier", "engineer"))


def _named(con, state: dict, text: str) -> str | None:
    """The course a few words name. A class in the plan being worked on wins ("chem" means the chemistry class that is
    in it), unless they gave a course code."""
    if text and not COURSE_RE.search(text):
        plain = text.lower().translate(str.maketrans("áéíóúüñ", "aeiouun"))
        words = [w for w in re.findall(r"[a-z]+", plain) if len(w) >= 3 and w not in FILLER and not TIME_WORDS.fullmatch(w)]
        words += [en for w in words for es_, en in SUBJECTS_ES if w.startswith(es_)]         # "química" is the chemistry class
        hits = [p["lecture"]["course"] for p in store.plan_sections(con, {"plan": state.get("draft") or []})
                if any(t.startswith(w) for w in words for t in re.findall(r"[a-z]+", p["lecture"]["title"].lower()))]
        if len(hits) == 1:
            return hits[0]
    return course_in(con, text) if text else None


def plan_prefs(state: dict, args: dict) -> tuple[dict | None, bool]:
    """(preferences for the class finder, whether this message changed them). Saved answers, then what was just said."""
    saved = state.get("prefs") if isinstance(state.get("prefs"), dict) else None
    said = {k: v for k, v in {"times": args.get("times") or [], "avoid": args.get("avoid") or [], "after": args.get("after"), "before": args.get("before"),
                              "mode": args.get("where") if args.get("where") in ("campus", "online") else None}.items() if v}
    if not said:
        return saved, False
    return {**(saved or {}), **said}, True


def _finder_options(con, slug: str, code: str, prefs: dict, state: dict) -> dict:
    found = _find_sorted(con, slug, code, prefs, state)
    swap = _drafted(con, state, code)
    found["swap"] = swap["lecture"]["crn"] if swap else None
    found["drafting"] = state.get("draft") is not None
    title = f"{found['course']['code']} ({found['course']['title']})"
    lines = []
    if found["taken"]:
        lines.append(f"Heads up: your record shows you've already passed {code}.")
    elif found["in_progress"]:
        lines.append(f"You're taking {code} this term, so this would be a repeat.")
    if found["prereqs"]["status"] == "missing":
        lines.append(f"One thing first: {code} needs " + " and ".join(found["prereqs"]["missing"]) + ", which I don't see on your record.")
    if found["options"]:
        n = len(found["options"])
        lines.append(f"Here {'is' if n == 1 else 'are'} {n} {title} option{'s' if n != 1 else ''} for {found['term']} that fit{'s' if n == 1 else ''} "
                     f"{found['prefs_label']}. {'It has' if n == 1 else 'Each has'} open seats and doesn't clash with your plan."
                     + (f" Pick one and it replaces the {code} section in the plan you're working on." if swap else ""))
    elif found["closest"]:
        lines.append(f"Nothing for {title} fits all of that ({found['prefs_label']}). These are the closest:")
    elif found["counts"]["sections"]:
        lines.append(f"I couldn't find an open {title} section for {found['term']} that works. Every match is full or clashes with your plan.")
    else:
        lines.append(f"{title} isn't in the sample schedule for {found['term']}.")
    return _reply("finder_options", " ".join(lines), found,
                  flow={"name": "finder", "step": "options", "course": code, "prefs": found["prefs"]},
                  chips=[f"Use the {_when(o['lecture']).split(' ')[-2]} {_when(o['lecture']).split(' ')[-1]} one" if _start(o) < 24 * 60 else "Use the online one"
                         for o in found["options"][:2]] + ["Try other times", "Show my plan"] if found["options"] else
                        ["Try other times", "Find a different class"])


def _ask_prefs(con, code: str) -> dict:
    info = store.course(con, code)
    return _reply("finder_prefs", f"{code} is {info['title']}. When works for you? Pick what you like, or just tell me "
                  "(for example: mornings, no Fridays, on campus).",
                  {"course": {"code": code, "title": info["title"], "credits": info["credits_text"]}},
                  flow={"name": "finder", "step": "prefs", "course": code}, chips=["Any time works"])


def _ask_course(con, slug: str, state: dict, missed: str | None = None) -> dict:
    left = audit.remaining(con, slug, state) or {"items": []}
    suggestions = [{"code": i["code"], "title": i["title"]} for i in left["items"] if i.get("code")][:5]
    lead = (f"I couldn't match \"{missed}\" to a class in the catalog. Try a course code like MTH 254, or a word from the title."
            if missed else "Which class or requirement? Give me a course code, a name like \"calculus\", or ask what you still need.")
    return _reply("finder_course", lead, {"suggestions": suggestions},
                  flow={"name": "finder", "step": "course"}, chips=["What do I still need?"])


def _what_if(con, slug: str, program: dict) -> dict:
    result = audit.what_if(con, slug, program["id"])
    n, total = len(result["counted"]), result["total"]
    return _reply("whatif", f"If you switched to {program['name']}: {n} of its {total} requirements are already covered "
                  f"by classes you've finished, and {len(result['needed'])} would be new.", result,
                  chips=["What do I still need?", "Book my advisor"])


def _schedule(con, slug: str, state: dict, today, text: str | None = None, apply: dict | None = None) -> dict:
    dash = audit.dashboard(con, slug, state, today)
    n = len(dash["plan"])
    k = len(dash["schedule"])
    default = f"You're in {k} class{'es' if k != 1 else ''} this term. " + (
        (f"Your winter plan has {n} class{'es' if n != 1 else ''}. You can add or drop here, and "
         "it only changes this sample schedule.") if n else
        "Your winter plan is empty so far. Tell me a class you need and I'll find sections that fit.")
    return _reply("schedule", text or default,
                  {"plan": dash["plan"], "schedule": dash["schedule"], "registration": dash["registration"],
                   "blocked": dash["blocked"], "holds": dash["holds"]},
                  chips=["Find a class", "Build my winter plan"], apply=apply)


def match_slot(slots: list[dict], text: str) -> dict | None:
    """The first open advisor time that fits words like "friday morning", "tomorrow at 2:30" or "earliest"."""
    low = text.lower()
    days = [i for i, rx in enumerate((r"mon", r"tue", r"wed", r"thu", r"fri")) if re.search(rf"\b{rx}", low)]
    clock = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", low)
    for s in slots:
        date = datetime.date.fromisoformat(s["date"])
        hour = datetime.datetime.strptime(s["time_label"], "%I:%M %p")
        if days and date.weekday() not in days:
            continue
        if "tomorrow" in low and s["day_label"] != "Tomorrow" or "today" in low and s["day_label"] != "Today":
            continue
        if "morning" in low and hour.hour >= 12 or "afternoon" in low and not 12 <= hour.hour < 17:
            continue
        if clock and (clock.group(2) or clock.group(3)):
            h = int(clock.group(1)) % 12 + (12 if (clock.group(3) or hour.strftime("%p").lower()) == "pm" else 0)
            if (h, int(clock.group(2) or 0)) != (hour.hour, hour.minute):
                continue
        return s
    return None


def _appointment(con, row, slug: str, state: dict, today, text: str | None = None, apply: dict | None = None) -> dict:
    dash = audit.dashboard(con, slug, state, today)
    upcoming = dash["appointments"]["upcoming"]
    if text is None and upcoming:
        a = upcoming[0]
        text = (f"You're booked with {a['with']} {a['day_inline']} at {a['time_label']}. Want a different time? "
                "Pick one and I'll move it in one step.")
    elif text is None:
        text = f"Your advisor is {row['advisor_name']} ({row['advisor_office']}). Pick a time and it's booked."
    return _reply("appointment", text, {"appointments": dash["appointments"], "slots": dash["slots"],
                                       "advisor": row["advisor_name"], "office": row["advisor_office"],
                                       "holds": dash["holds"]}, apply=apply)


def run_tool(con, slug: str, state: dict | None, flow: dict | None, name: str, args: dict | None = None,
             today: datetime.date | None = None) -> dict | None:
    """Run one sample-data tool. `args` holds whatever the tool needs (course, times, avoid, where, option,
    program, query, slot). Returns None for an unknown tool or student."""
    today = today or datetime.date.today()
    row = store.student_row(con, slug)
    if not row or name not in TOOLS:
        return None
    state = store.clean_state(state)
    flow = flow if isinstance(flow, dict) else {}
    args = args or {}
    first = row["first_name"]

    if name in SITES:
        return _reply(name, SITES[name])
    if name in ACTION_SITE:             # the server works out the exact change and writes the review; nothing changes here
        return _reply(ACTION_SITE[name], "I've set that up for you to review. Nothing has changed yet.",
                      apply={"type": "site_action", "tool": name, "query": str(args.get("query") or args.get("course") or "")[:300],
                             "number": args.get("slot") if isinstance(args.get("slot"), int) else None})

    if name == "registration":
        dash = audit.dashboard(con, slug, state, today)
        reg, blocking = dash["registration"], [h for h in dash["holds"] if h["blocks"]]
        booked = next(iter(dash["appointments"]["upcoming"]), None)
        if blocking and blocking[0]["type"] == "advising" and booked:
            lead = (f"Registration opens {reg['day_label']} at {reg['time_label']}. Your advising hold is still on, but you're booked with your advisor "
                    f"{booked['day_inline']} at {booked['time_label']}, and it comes off after that meeting.")
        elif blocking:
            lead = (f"Registration opens {reg['day_label']} at {reg['time_label']}, but a hold is blocking you: "
                    f"{blocking[0]['title'].lower()}. {blocking[0]['how_to_clear']}")
        else:
            n = len(dash["plan"])
            lead = (f"Nothing is blocking you, and registration opens {reg['date_label']} at {reg['time_label']}. "
                    + (f"You have {n} class{'es' if n != 1 else ''} in your winter plan so far." if n else
                       "You haven't picked winter classes yet. Want me to suggest a plan, or find a specific class?"))
        return _reply("registration", lead, {"registration": reg, "holds": dash["holds"],
                                             "appointments": dash["appointments"], "checklist": dash["checklist"]},
                      chips=["Book my advisor", "Show my checklist"] if blocking else ["Build my winter plan", "Find a class", "Show my checklist"])

    if name == "appointment":
        return _appointment(con, row, slug, state, today)
    if name == "book_appointment":
        slots = store.slots(con, row["id"], today)
        wanted, asked = args.get("slot"), str(args.get("query") or "").strip()
        slot = slots[wanted - 1] if isinstance(wanted, int) and 1 <= wanted <= len(slots) else None
        if not slot and asked:
            slot = match_slot(slots, asked)
            if not slot:
                return _appointment(con, row, slug, state, today, f"Nothing is open {asked}. Here are the times that are.")
        if not slot:
            return _appointment(con, row, slug, state, today)
        moved = bool(store.appointments(con, row, state, today)["upcoming"])
        new_state = {**state, "appointment": {"slot": slot["id"]}, "cancelled": False}
        return _appointment(con, row, slug, new_state, today,
                            f"{'Moved. You' if moved else 'Booked. You'}'re meeting {row['advisor_name']} {slot['day_inline']} at "
                            f"{slot['time_label']} ({slot['mode'].lower()}).",
                            apply={"type": "book", "slot": slot["id"]})
    if name == "cancel_appointment":
        if not store.appointments(con, row, state, today)["upcoming"]:
            return _appointment(con, row, slug, state, today, "You don't have an advisor appointment booked. Want to pick a time?")
        return _appointment(con, row, slug, {**state, "appointment": None, "cancelled": True}, today,
                            "Cancelled. Pick a new time whenever you're ready.", apply={"type": "cancel_appointment"})

    if name == "checklist":
        check = audit.checklist(con, slug, state, today)
        return _reply("checklist", "You're ready to register." if check["ready"] else
                      f"{check['done']} of {check['total']} done. Here's what's left before registration opens.",
                      {"checklist": check}, chips=["Book my advisor", "Find a class"])
    if name == "remaining":
        left = audit.remaining(con, slug, state)
        n = left["count"]
        text = (f"You have {n} requirement{'s' if n != 1 else ''} left this year, {first}. Here's what to take in winter."
                if n else "You're caught up on this year's requirements. Here's what comes next.")
        return _reply("remaining", text, left, chips=["Build my winter plan", "Find a class"])
    if name == "whatif":
        program = audit.find_program(con, str(args.get("program") or "")) if args.get("program") else None
        if program:
            return _what_if(con, slug, program)
        return _reply("whatif_ask", "Which major or minor are you curious about? Type a name and I'll show how your "
                      "classes would count. No form to fill out.", {"programs": []},
                      flow={"name": "whatif", "step": "program"},
                      chips=["Computer Science", "Psychology", "Business Administration", "Kinesiology"])
    if name == "plan":
        prefs, changed = plan_prefs(state, args)
        drafted = store.plan_sections(con, {"plan": state.get("draft") or []})
        if drafted and not changed:         # they already have a plan in progress: show it as they left it
            credits = sum(p["lecture"]["credits"] or 0 for p in drafted)
            return _reply("plan", f"Here's your winter plan as you left it: {len(drafted)} class{'es' if len(drafted) != 1 else ''}, {credits:g} credits. "
                          "Nothing is added yet: change anything you like below, then review it.", {"picks": [], "kept": True},
                          chips=["Show my checklist", "What do I still need?"])
        if prefs is None and not (flow.get("name") == "plan" and flow.get("step") == "prefs"):
            return _reply("plan_prefs", "Sure. First, a few quick questions so the plan fits your week. Pick what you like below, or skip them and "
                          "I'll just build it.", {}, flow={"name": "plan", "step": "prefs"})
        plan = audit.winter_plan(con, slug, {**state, "draft": None}, prefs=finder.clean_prefs(prefs), target_credits=(prefs or {}).get("credits_target") or 15)
        n = len(plan["picks"])
        plan["fresh"], plan["prefs"] = True, prefs if changed else None
        return _reply("plan", f"Here's a winter plan to bring to {plan['advisor']}: {n} class{'es' if n != 1 else ''}, "
                      f"{plan['credits']:g} credits, with no time clashes. " + (" ".join(plan["bends"][:3]) + " " if plan["bends"] else "")
                      + "Nothing is added yet: change anything you like below, then review it.", plan, chips=["Show my checklist", "What do I still need?"])
    if name == "add_plan_all":
        plan = audit.winter_plan(con, slug, state)
        n = len(plan["picks"])
        if name == "add_plan_all" and n:
            have = {p["lecture"]["course"] for p in store.plan_sections(con, state)}
            items = [{"crn": p["option"]["lecture"]["crn"], "linked": p["option"]["linked"]["crn"] if p["option"]["linked"] else None}
                     for p in plan["picks"] if p["course"]["code"] not in have]
            new_state = {**state, "plan": state["plan"] + items}
            return _schedule(con, slug, new_state, today,
                             f"Done. I added {len(items)} class{'es' if len(items) != 1 else ''} to your sample winter plan: "
                             + ", ".join(p["course"]["code"] for p in plan["picks"]) + ".",
                             apply={"type": "plan_add_many", "items": items})
        return _reply("plan", f"Here's a winter plan to bring to {plan['advisor']}: {n} class{'es' if n != 1 else ''}, "
                      f"{plan['credits']:g} credits, with no time clashes. Nothing is added yet: change anything you like below, "
                      "then review it.", plan, chips=["Show my checklist", "What do I still need?"])

    if name == "find_class":
        named = str(args.get("course") or "").strip()
        code = _named(con, state, named) if named else (flow.get("course") if flow.get("name") == "finder" else None)
        if code and not store.course(con, code):
            code = None
        if not code:
            return _ask_course(con, slug, state, missed=named or None)
        prefs = {"times": args.get("times") or [], "avoid": args.get("avoid") or [], "mode": args.get("where") or "any",
                 "after": args.get("after"), "before": args.get("before")}
        asked = bool(prefs["times"] or prefs["avoid"] or prefs["mode"] != "any" or prefs["after"] or prefs["before"]
                     or args.get("show_options"))
        saved = state.get("prefs") if isinstance(state.get("prefs"), dict) else None
        if saved is not None:               # already answered for the plan: use those answers, never ask twice
            prefs = {**{k: saved.get(k) for k in ("times", "avoid", "mode", "after", "before") if saved.get(k)}, **{k: v for k, v in prefs.items() if v and v != "any"}}
            prefs.setdefault("mode", "any")
            asked = True
        if _drafted(con, state, code):       # swapping a class in the plan: show the choices straight away
            asked = True
        return _finder_options(con, slug, code, prefs, state) if asked else _ask_prefs(con, code)

    if name == "add_to_plan":
        named = str(args.get("course") or "").strip()
        code = (_named(con, state, named) if named else None) or (flow.get("course") if flow.get("name") == "finder" else None)
        if not code or not store.course(con, code):
            return _ask_course(con, slug, state, missed=named or None)
        prefs = flow.get("prefs") if flow.get("course") == code and isinstance(flow.get("prefs"), dict) else {}
        found = _find_sorted(con, slug, code, prefs, state)
        options = found["options"] or found["closest"]
        index = args.get("option") if isinstance(args.get("option"), int) and args.get("option") >= 1 else 1
        if state.get("draft") is not None and options and index <= len(options) and not found["in_plan"]:
            pick, was = options[index - 1], _drafted(con, state, code)
            item = {"crn": pick["lecture"]["crn"], "linked": pick["linked"]["crn"] if pick["linked"] else None}
            where = f"{pick['lecture']['type']} {pick['lecture']['section']}, {_when(pick['lecture'])}"
            return _reply("plan", (f"Swapped. {code} is now {where}." if was else f"Added {code} ({where}) to the plan you're working on.")
                          + " Here's the whole plan again. Nothing is added to your record until you review it.", {"picks": []},
                          apply={"type": "draft_put", **item}, chips=["Show my checklist"])
        if found["in_plan"]:
            return _schedule(con, slug, state, today, f"{code} is already in your sample winter plan.")
        if not options or index > len(options):
            return _finder_options(con, slug, code, prefs, state)
        pick = options[index - 1]
        item = {"crn": pick["lecture"]["crn"], "linked": pick["linked"]["crn"] if pick["linked"] else None}
        text = (f"Done. {code} ({pick['lecture']['type']} {pick['lecture']['section']}, {_when(pick['lecture'])}"
                + (f", with {pick['linked']['type'].lower()} {_when(pick['linked'])}" if pick["linked"] else "")
                + ") is in your sample winter plan.")
        return _schedule(con, slug, {**state, "plan": state["plan"] + [item]}, today, text, apply={"type": "plan_add", **item})

    if name == "drop_from_plan":
        named = str(args.get("course") or "").strip()
        code = _named(con, state, named) if named else None
        planned = store.plan_sections(con, state)
        drafted = _drafted(con, state, code) if code else None
        if drafted:
            return _reply("plan", f"Took {code} out of the plan you're working on. Here's the whole plan again. Nothing is added to your record until you review it.",
                          {"picks": []}, apply={"type": "draft_drop", "crn": drafted["lecture"]["crn"]}, chips=["Show my checklist"])
        hit = next((p for p in planned if p["lecture"]["course"] == code), None) if code else (planned[0] if len(planned) == 1 else None)
        if not hit:
            return _schedule(con, slug, state, today, ("That class isn't in your winter plan. Here's what is." if planned else None))
        crn = hit["lecture"]["crn"]
        new_state = {**state, "plan": [p for p in state["plan"] if p["crn"] != crn]}
        return _schedule(con, slug, new_state, today, f"Dropped {hit['lecture']['course']} from your sample winter plan.",
                         apply={"type": "plan_drop", "crn": crn})

    if name == "schedule":
        return _schedule(con, slug, state, today)
    if name == "forms":
        query = str(args.get("query") or "")
        found = store.forms(con, query) or store.forms(con, "")
        return _reply("forms", (f"I found {len(found)} form{'s' if len(found) != 1 else ''} that could be it. Each one shows "
                                "what it's for, who gets it, and a preview filled in with your sample details. "
                                "Nothing is ever submitted from here."), {"forms": found[:8], "query": query})
    if name == "billing":
        bill = store.billing(con, row["id"], state, today)
        if bill["balance"] <= 0:
            lead = "You're paid up. Nothing is due."
        elif bill["past_due"] > 0:
            lead = f"You owe ${bill['balance']:,.2f}, and ${bill['past_due']:,.2f} of it is past due. There's one place to pay it."
        else:
            lead = f"You owe ${bill['balance']:,.2f}, due {bill['due_label']}. There's one place to pay it."
        return _reply("billing", lead, {"billing": bill, "holds": store.holds(con, row["id"], state, today)},
                      chips=["How do I set up a payment plan?"])
    if name == "audit":
        report = audit.audit(con, slug, state)
        c = report["counts"]
        return _reply("audit", f"Here's your degree checklist in plain language: {c['met']} done, {c['in_progress']} in "
                      f"progress, {c['needed'] + c['not_met']} still to go. "
                      + "".join(f"One line needs attention: {r['label']} shows \"Minimum grade not met\", which usually means retaking it. "
                                for b in report["blocks"] for r in b["requirements"] if r["status"] == "not_met")
                      + "Tap any line to see what it means.", report,
                      chips=["What do I still need?", "Build my winter plan"])
    if name == "resources":
        query = str(args.get("query") or "")
        found = store.resources(con, query)[:6] if query else []
        if found:
            return _reply("resources", f"In BeaverHub that's most likely \"{found[0]['name']}\". Here's what each one is, "
                          "in plain words.", {"resources": found, "query": query})
        return _reply("resources", "BeaverHub lists about 130 tools, and a lot of the names overlap. Here they are in plain "
                      "words. Search for what you're trying to do.", {"resources": store.resources(con, "")[:4], "query": ""})
    return None


def route(con, text: str, slug: str, state: dict | None, flow: dict | None, today: datetime.date | None = None) -> dict | None:
    """Offline routing: the tool this message is asking for, picked by its wording, or None to let the real answer
    pipeline handle it. With a model connected, beaverbot/talk.py decides instead and calls run_tool itself."""
    if not store.student_row(con, slug):
        return None
    text = " ".join(text.split())
    flow = flow if isinstance(flow, dict) else {}
    tool = lambda name, **args: run_tool(con, slug, state, flow, name, args, today)      # noqa: E731

    # -- continuing a conversation ---------------------------------------------------------------
    in_finder = flow.get("name") == "finder"
    question = bool(INFO_START.search(text)) and not RX["finder"].search(text)
    if in_finder and not question:
        if re.search(r"\b(different|another|other) class\b|start over", text, re.I):
            return _ask_course(con, slug, store.clean_state(state))
        if re.search(r"other times|different times?|change times?", text, re.I) and flow.get("course"):
            return _ask_prefs(con, flow["course"]) if store.course(con, flow["course"]) else None
        if flow.get("step") == "options":
            m = re.search(r"\b(add|take|pick|choose|i'?ll take|go with)\b.{0,25}\b(first|second|third|1st|2nd|3rd|one|it|that|this|[123])\b", text, re.I)
            if m:
                index = {"second": 2, "2nd": 2, "2": 2, "third": 3, "3rd": 3, "3": 3}.get(m.group(2).lower(), 1)
                return tool("add_to_plan", option=index)
        named = course_in(con, text) if len(text.split()) <= 8 and not RX["remaining"].search(text) else None
        prefs = finder.parse_prefs(text)
        if named and not any(rx.search(text) for key, rx in RX.items() if key not in ("finder", "schedule")):
            return tool("find_class", course=named, times=prefs["times"], avoid=prefs["avoid"], where=prefs["mode"],
                        show_options=prefs["understood"])
        if prefs["understood"] and flow.get("course") and flow.get("step") in ("prefs", "options"):
            return tool("find_class", times=prefs["times"], avoid=prefs["avoid"], where=prefs["mode"], show_options=True)
    if flow.get("name") == "whatif" and flow.get("step") == "program" and audit.find_program(con, text):
        return tool("whatif", program=text)

    # -- new requests ------------------------------------------------------------------------------
    if RX["whatif"].search(text):
        m = re.search(r"\b(?:to|in|into|about)\s+(?:a |an |the )?([a-z][a-z &,-]{1,50}?)(?:\s+(?:major|minor|degree|program))?\s*\??$", text, re.I)
        return tool("whatif", program=m.group(1) if m else "")
    if re.search(r"\badd (them )?all\b", text, re.I):
        return tool("add_plan_all")
    if RX["plan"].search(text):
        return tool("plan")
    if RX["remaining"].search(text):
        return tool("remaining")
    if RX["checklist"].search(text):
        return tool("checklist")
    if RX["appointment"].search(text):
        return tool("cancel_appointment") if re.search(r"\bcancel\b", text, re.I) else tool("appointment")
    if RX["billing"].search(text) and not re.match(r"\s*(what happens|when is|how do i set up)", text, re.I):
        return tool("billing")
    if RX["registration"].search(text) and not (INFO_START.search(text) and not re.search(r"\b(i|my)\b", text, re.I)):
        return tool("registration")
    if RX["audit"].search(text):
        return tool("audit")
    if RX["forms"].search(text) and not INFO_START.search(text.replace("where", "", 1)) or re.search(r"\b(find|which|need) (a |the )?form\b", text, re.I):
        query = " ".join(w for w in re.findall(r"[a-z/]+", text.lower()) if w not in FILLER | {"form", "forms", "where", "which", "do", "how", "fill", "out"})
        return tool("forms", query=query)
    if RX["resources"].search(text):
        skip = set("where do i find in beaverhub beaver hub the a an how which tool link site can is my to for of".split())
        return tool("resources", query=" ".join(w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in skip))
    m = re.search(r"\b(drop|remove)\b\s+(.{2,40})", text, re.I)
    if m and not INFO_START.search(text):
        return tool("drop_from_plan", course=re.sub(r"\b(from|my|plan|schedule|class|the)\b", " ", m.group(2), flags=re.I))
    if RX["schedule"].search(text) and not (INFO_START.search(text) and not re.search(r"\bmy (schedule|plan|classes)\b", text, re.I)):
        return tool("schedule")
    wants_class = RX["finder"].search(text) or (COURSE_RE.search(text) and TIME_WORDS.search(text) and not INFO_START.search(text))
    if wants_class:
        named = course_in(con, text)
        prefs = finder.parse_prefs(text)
        if re.search(r"\b(add|put)\b", text, re.I) and (named or flow.get("course")):
            return tool("add_to_plan", course=named or "")
        return tool("find_class", course=named or "", times=prefs["times"], avoid=prefs["avoid"], where=prefs["mode"],
                    show_options=prefs["understood"])
    if in_finder and flow.get("step") == "course" and len(text.split()) <= 4 and not question:
        return _ask_course(con, slug, store.clean_state(state), missed=text)
    return None
