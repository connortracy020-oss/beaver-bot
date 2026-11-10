"""A schedule being worked out in the chat, before anything is added. SAMPLE DATA ONLY.

When Beaver Bot suggests classes, the student gets them as a list they can edit right there: remove one, swap its
section, replace it with another class that meets the same requirement, or add a class. The list being edited is
not the student's record. It is a draft, held by the page like the contents of a form, and every time it changes
the page asks this module what the draft looks like now: each class's times and credits, any clashes, and the
credit total. Nothing here changes anything. When the student is happy, the draft goes through the same review,
confirm and undo steps as every other change (systems.Registration, "add_many").
"""
from . import audit, finder, store
from .hub import Refused
from .systems import FULL_TIME, MAX_CREDITS, Ctx, Registration, class_row, legacy, read, stamp, _time_line, _when

MAX_ROWS = 8
_reg = Registration()


def _term(ctx: Ctx, term) -> dict:
    info = _reg.term_info(ctx, term if isinstance(term, str) else store.REG_TERM)
    if info["mode"] == "current":
        raise Refused("blocked", 409, f"{info['name']} is under way, and adding or swapping classes closed after week 1.")
    return info


def _meets(lec: dict, linked: dict | None) -> list[dict]:
    return lec["meetings"] + (linked["meetings"] if linked else [])


def _requirements(ctx: Ctx) -> list[dict]:
    """The student's open requirements, each with every course that would fill it."""
    report = audit.audit(ctx.con, ctx.slug, legacy(ctx))
    out = []
    for b in report["blocks"]:
        for r in b["requirements"]:
            if r["status"] in ("needed", "not_met", "planned") and r["kind"] != "credits":
                codes = [x[0] for x in ctx.con.execute("SELECT course_code FROM requirement_courses WHERE requirement_id = ?", (r["id"],))]
                out.append({"id": r["id"], "label": r["label"], "block": b["name"], "major": b["program"] == ctx.row["program_id"], "codes": set(codes or r["options"])})
    return out


def _requirement_for(reqs: list[dict], code: str) -> dict | None:
    hits = [r for r in reqs if code in r["codes"]]
    return next((r for r in hits if r["major"]), hits[0] if hits else None)


def _pick_linked(ctx: Ctx, lec: dict, wanted, busy: list[list[dict]]) -> dict | None:
    options = store.linked(ctx.con, lec["crn"])
    if not options:
        return None
    hit = next((o for o in options if o["crn"] == wanted), None) if isinstance(wanted, int) else None
    if hit:
        return hit
    free = [o for o in options if o["seats_open"] > 0 and not any(store.overlaps(o["meetings"], b) for b in busy)]
    return (free or [o for o in options if o["seats_open"] > 0] or options)[0]


def _rows(ctx: Ctx, term: str, items) -> list[dict]:
    """The draft's classes, cleaned: real sections of this term, one per course, each with its linked section."""
    existing = _reg._others(ctx, term)
    busy = [_meets(o["lecture"], o["linked"]) for o in existing]
    rows, seen = [], set()
    for entry in (items if isinstance(items, list) else [])[:MAX_ROWS]:
        crn = entry.get("crn") if isinstance(entry, dict) else None
        lec = store.section(ctx.con, crn) if isinstance(crn, int) else None
        if not lec or lec["term"] != term or not lec["primary"] or lec["course"] in seen:
            continue
        seen.add(lec["course"])
        linked = _pick_linked(ctx, lec, entry.get("linked"), busy + [_meets(r["lecture"], r["linked"]) for r in rows])
        rows.append({"lecture": lec, "linked": linked})
    return rows


def evaluate(ctx: Ctx, term, items) -> dict:
    """What the draft looks like now. Changes nothing."""
    info = _term(ctx, term)
    term = info["code"]
    existing = _reg._others(ctx, term)
    rows = _rows(ctx, term, items)
    reqs = _requirements(ctx)
    mine = store.student_courses(ctx.con, ctx.row["id"])
    taken = store.taken_codes(mine)
    out, conflicts = [], []
    for n, r in enumerate(rows):
        lec, linked = r["lecture"], r["linked"]
        code, notes, clash = lec["course"], [], []
        blocked = any(o["lecture"]["course"] == code for o in existing)
        if blocked:
            notes.append(f"{code} is already in your {info['name']} classes, so it won't be added again.")
        pre = finder.prerequisites(ctx.con, code, taken)
        if pre["status"] == "missing":
            notes.append(f"{code} needs {' and '.join(pre['missing'])} first, which isn't on your record.")
        if lec["seats_open"] <= 0:
            notes.append("This section is full right now.")
        elif linked and linked["seats_open"] <= 0:
            notes.append(f"That {linked['type'].lower()} is full right now.")
        for m, other in enumerate(rows):
            if m != n and store.overlaps(_meets(lec, linked), _meets(other["lecture"], other["linked"])):
                clash.append(other["lecture"]["course"])
                if m > n:
                    conflicts.append({"a": code, "b": other["lecture"]["course"]})
        for o in existing:
            if o["lecture"]["course"] != code and store.overlaps(_meets(lec, linked), _meets(o["lecture"], o["linked"])):
                clash.append(o["lecture"]["course"])
                conflicts.append({"a": code, "b": o["lecture"]["course"]})
        for c in clash:
            other = next((x["lecture"] for x in rows + existing if x["lecture"]["course"] == c), None)
            notes.append(f"It meets at the same time as {c} ({_when(other)}).")
        req = _requirement_for(reqs, code)
        row = class_row(lec, linked)
        row.update({"requirement": req["label"] if req else None, "can_replace": bool(req and len(req["codes"]) > 1),
                    "sections": ctx.con.execute("SELECT COUNT(*) FROM sections WHERE term_code = ? AND course_code = ? AND is_primary = 1", (term, code)).fetchone()[0],
                    "linked_options": len(store.linked(ctx.con, lec["crn"])), "notes": notes, "clash": clash, "blocked": blocked,
                    "seats_open": lec["seats_open"], "seats_total": lec["seats_total"]})
        out.append(row)
    adding = sum(r["credits"] for r in out if not r["blocked"])
    held = sum(o["credits"] for o in existing)
    total = adding + held
    warnings = []
    if total > MAX_CREDITS:
        warnings.append(f"That makes {total:g} credits. The limit is {MAX_CREDITS} without your college's approval.")
    return {**stamp(ctx, "Class search", "the class schedule"), "term": {"code": term, "name": info["name"]}, "rows": out,
            "existing": [class_row(o["lecture"], o["linked"], o["credits"], action=o["status"]) for o in existing],
            "credits": {"adding": adding, "existing": held, "total": total, "min": FULL_TIME, "max": MAX_CREDITS, "full_time": total >= FULL_TIME, "over": total > MAX_CREDITS},
            "conflicts": conflicts, "warnings": warnings,
            "items": [{"crn": r["crn"], "linked": r["linked"]["crn"] if r["linked"] else None} for r in out]}


def _default_section(ctx: Ctx, term: str, code: str, busy: list[list[dict]]) -> dict | None:
    """The section to start a newly chosen class on: open and clash-free if there is one."""
    best = None
    online = ctx.row["campus"] == "Ecampus"
    for (crn,) in ctx.con.execute("SELECT crn FROM sections WHERE term_code = ? AND course_code = ? AND is_primary = 1 ORDER BY section", (term, code)):
        lec = store.section(ctx.con, crn)
        if lec["campus"] in ("Cascades", "INTO OSU") or (lec["restrictions"] and "Honors" in lec["restrictions"]):
            continue
        linked = _pick_linked(ctx, lec, None, busy)
        clash = any(store.overlaps(_meets(lec, linked), b) for b in busy)
        home = (lec["campus"] == "Ecampus") == online            # an online student starts on an online section, and the reverse
        rank = (home, lec["seats_open"] > 0 and not clash, lec["seats_open"] > 0, not clash)
        if best is None or rank > best[0]:
            best = (rank, lec, linked, clash)
    return {"lecture": best[1], "linked": best[2], "clash": best[3], "home": best[0][0]} if best else None


def options(ctx: Ctx, term, items, replace=None, query: str = "") -> dict:
    """Classes that could go into the draft: ones meeting the same requirement as the class being replaced, ones
    matching what the student typed, or (with neither) the classes their open requirements call for."""
    info = _term(ctx, term)
    term = info["code"]
    rows = _rows(ctx, term, items)
    existing = _reg._others(ctx, term)
    keep = [r for r in rows if r["lecture"]["crn"] != replace]
    busy = [_meets(r["lecture"], r["linked"]) for r in keep] + [_meets(o["lecture"], o["linked"]) for o in existing]
    have = {r["lecture"]["course"] for r in keep} | {o["lecture"]["course"] for o in existing}
    reqs = _requirements(ctx)
    mine = store.student_courses(ctx.con, ctx.row["id"])
    taken, passed = store.taken_codes(mine), store.taken_codes(mine, include_in_progress=False)
    offered = lambda code: ctx.con.execute("SELECT COUNT(*) FROM sections WHERE term_code = ? AND course_code = ? AND is_primary = 1",      # noqa: E731
                                           (term, code)).fetchone()[0]
    heading, codes = None, []
    query = " ".join(str(query or "").split())[:60]
    if query:
        codes = [c["code"] for c in store.search_courses(ctx.con, query, 12)]
    elif isinstance(replace, int):
        old = next((r["lecture"] for r in rows if r["lecture"]["crn"] == replace), None)
        req = _requirement_for(reqs, old["course"]) if old else None
        if req:
            heading = req["label"]
            codes = sorted(c for c in req["codes"] if c != old["course"])
            # the classes with the most sections this term first, lower-level before upper
            codes.sort(key=lambda c: (-min(offered(c), 3), c.split()[-1], c))
    else:
        codes = [c for r in sorted(reqs, key=lambda r: not r["major"]) for c in sorted(r["codes"], key=lambda c: (-min(offered(c), 3), c.split()[-1], c))[:12]]
    out, per_req = [], {}
    suggesting = not query and not isinstance(replace, int)
    for code in dict.fromkeys(codes):
        if code in have or code in passed or len(out) >= 8:
            continue
        info_c = store.course(ctx.con, code)
        pick = _default_section(ctx, term, code, busy) if info_c else None
        if not pick:
            continue
        pre = finder.prerequisites(ctx.con, code, taken)
        if not query and (pre["status"] == "missing" or not pick["home"]):
            continue            # suggestions are classes the student could take; a search still shows it, with the reason
        req = _requirement_for(reqs, code)
        if suggesting and req:                  # a spread across requirements, not eight ways to fill one
            per_req[req["id"]] = per_req.get(req["id"], 0) + 1
            if per_req[req["id"]] > 2 or any(h in req["codes"] for h in have):
                continue
        row = class_row(pick["lecture"], pick["linked"])
        notes = []
        if pre["status"] == "missing":
            notes.append(f"{code} needs {' and '.join(pre['missing'])} first, which isn't on your record.")
        if pick["lecture"]["seats_open"] <= 0:
            notes.append("This section is full right now.")
        if pick["clash"]:
            notes.append("Every open section meets at the same time as a class in this list.")
        row.update({"requirement": req["label"] if req else None, "notes": notes, "item": {"crn": row["crn"], "linked": pick["linked"]["crn"] if pick["linked"] else None}})
        out.append(row)
    return {"term": {"code": term, "name": info["name"]}, "requirement": heading, "query": query, "courses": out}


def suggested(ctx: Ctx) -> list[dict]:
    """The starting draft: the suggested plan for the registration term, as crns."""
    plan = audit.winter_plan(ctx.con, ctx.slug, legacy(ctx))
    return [{"crn": p["option"]["lecture"]["crn"], "linked": p["option"]["linked"]["crn"] if p["option"]["linked"] else None} for p in (plan or {}).get("picks", [])]


def sections(ctx: Ctx, term, items, crn) -> dict:
    """Every section of one class in the draft, to swap to: its time, open seats, whether it clashes with the rest
    of the draft, and the recitations or labs that go with it."""
    info = _term(ctx, term)
    term = info["code"]
    rows = _rows(ctx, term, items)
    mine = next((r for r in rows if r["lecture"]["crn"] == crn), None)
    if not mine:
        raise Refused("not_found", 404)
    busy = [_meets(r["lecture"], r["linked"]) for r in rows if r is not mine] + [_meets(o["lecture"], o["linked"]) for o in _reg._others(ctx, term)]
    out = []
    for (other,) in ctx.con.execute("SELECT crn FROM sections WHERE term_code = ? AND course_code = ? AND is_primary = 1 ORDER BY section", (term, mine["lecture"]["course"])):
        lec = store.section(ctx.con, other)
        if lec["campus"] in ("Cascades", "INTO OSU") or (lec["restrictions"] and "Honors" in lec["restrictions"]):
            continue
        when = lambda sec: next(({"days": m["days"], "start": m["start"]} for m in sec["meetings"] if not m["tba"]), {"days": "", "start": None})      # noqa: E731
        out.append({"crn": lec["crn"], "times": [_time_line(lec)], **when(lec), "seats_open": lec["seats_open"], "seats_total": lec["seats_total"],
                    "instructor": lec["instructor"], "campus": lec["campus"], "current": lec["crn"] == crn,
                    "clash": any(store.overlaps(lec["meetings"], b) for b in busy),
                    "linked": [{"crn": k["crn"], "times": [_time_line(k)], **when(k), "seats_open": k["seats_open"], "seats_total": k["seats_total"],
                                "current": bool(mine["linked"]) and k["crn"] == mine["linked"]["crn"],
                                "clash": any(store.overlaps(k["meetings"], b) for b in busy)} for k in store.linked(ctx.con, lec["crn"])]})
    return {"term": {"code": term, "name": info["name"]}, "code": mine["lecture"]["course"], "name": mine["lecture"]["title"], "sections": out}


def chat_card(ctx: Ctx, reply: dict) -> dict | None:
    """The card shown under a chat reply. Every reply tool has one (intents.REPLY_TOOLS)."""
    tool, data = reply.get("tool"), reply.get("data") or {}
    if tool == "plan":
        if data.get("fresh"):                 # a newly built suggestion becomes the working draft
            if isinstance(data.get("prefs"), dict):
                ctx.state["prefs"] = {**(ctx.state.get("prefs") or {}), **data["prefs"]}
            ctx.state.setdefault("prefs", {})
            save(ctx, [{"crn": p["option"]["lecture"]["crn"], "linked": p["option"]["linked"]["crn"] if p["option"]["linked"] else None} for p in data.get("picks", [])],
                 bends=data.get("bends"))
        elif saved(ctx) is None:
            save(ctx, suggested(ctx))
        return current(ctx)
    if tool == "plan_prefs":
        return {"kind": "prefs", **stamp(ctx, "Class planning", "your answers, kept by Beaver Bot"), "prefs": ctx.state.get("prefs") or {},
                "limits": {"min": FULL_TIME, "max": MAX_CREDITS}, "term": {"code": store.REG_TERM, "name": (store.term(ctx.con, store.REG_TERM) or {}).get("name")}}
    if tool == "schedule":
        name = lambda code: (store.term(ctx.con, code) or {}).get("name")       # noqa: E731
        return {"kind": "classes", "groups": [
            {"term": {"code": code, "name": name(code)},
             "rows": [class_row(o["lecture"], o["linked"], o["credits"], action=o["status"]) for o in _reg._others(ctx, code)]}
            for code in (store.REG_TERM, store.NOW_TERM)]}
    if tool == "finder_options":
        shown = data.get("options") or data.get("closest") or []
        rows = []
        for o in shown:
            row = class_row(o["lecture"], o["linked"], o.get("credits"))
            row.update({"misses": list(o.get("misses") or []), "seats_open": o["lecture"]["seats_open"], "seats_total": o["lecture"]["seats_total"],
                        "item": {"crn": o["lecture"]["crn"], "linked": o["linked"]["crn"] if o["linked"] else None}})
            rows.append(row)
        code = rows[0]["code"] if rows else None
        swap = next((i["crn"] for i in (saved(ctx) or {}).get("items", []) if code and (store.section(ctx.con, i["crn"]) or {}).get("course") == code), None)
        return {"kind": "options", "term": {"code": store.REG_TERM, "name": (store.term(ctx.con, store.REG_TERM) or {}).get("name")}, "rows": rows,
                "in_plan": bool(data.get("in_plan")), "closest": not data.get("options"), "swap": swap, "drafting": saved(ctx) is not None, "code": code}
    # Every other reply: a short version of that connected site's panel, read fresh from this visitor's sandbox.
    if tool in SITE_OF:
        system, options, panel = SITE_OF[tool]
        return {"kind": "site", "system": system, "view": options.get("view"), "panel": panel, "data": read(ctx, system, **options)}
    if tool in OWN_DATA:               # what the tool itself found (forms, BeaverHub tools, a what-if, class suggestions)
        return {"kind": "site", "system": tool, "view": None, "panel": OWN_DATA[tool], "data": {**stamp(ctx, *OWN_SOURCE[tool]), **data}}
    return None


# reply tool -> (connected system, how to read it, the panel its "Open" link goes to)
SITE_OF = {"registration": ("registration", {"term": store.REG_TERM}, ["schedule", {"term": store.REG_TERM}]), "appointment": ("advising", {}, ["advising", {}]),
           "checklist": ("degree", {"view": "checklist"}, ["degree", {"view": "checklist"}]), "remaining": ("degree", {"view": "remaining"}, ["degree", {"view": "remaining"}]),
           "audit": ("degree", {"view": "audit"}, ["degree", {"view": "audit"}]), "billing": ("billing", {}, ["billing", {}]),
           "housing": ("housing", {}, ["housing", {}]), "id_card": ("card", {}, ["card", {}]), "parking": ("parking", {}, ["parking", {}]),
           "careers": ("careers", {}, ["careers", {}]), "library": ("library", {}, ["library", {}]), "coursework": ("canvas", {}, ["canvas", {}]),
           "wellness": ("wellness", {}, ["wellness", {}])}
OWN_DATA = {"whatif": ["degree", {"view": "whatif"}], "whatif_ask": ["degree", {"view": "whatif"}], "forms": ["finders", {}], "resources": ["finders", {}],
            "finder_course": ["finder", {}], "finder_prefs": ["finder", {}]}
OWN_SOURCE = {"whatif": ("Degree progress", "MyDegrees"), "whatif_ask": ("Degree progress", "MyDegrees"), "forms": ("Forms", "the forms library"),
              "resources": ("BeaverHub tools", "BeaverHub"), "finder_course": ("Class search", "the class schedule"), "finder_prefs": ("Class search", "the class schedule")}


def site_facts(ctx: Ctx, tool: str) -> str | None:
    """What a connected site shows, in a sentence or two, so the words of a reply match the card under it."""
    if tool not in SITE_OF:
        return None
    import datetime
    d = read(ctx, SITE_OF[tool][0], **SITE_OF[tool][1])
    n = lambda count, one, many=None: f"{count} {one if count == 1 else (many or one + 's')}"      # noqa: E731
    day = lambda iso: (lambda x: f"{x.strftime('%a, %b')} {x.day}")(datetime.date.fromisoformat(iso))      # noqa: E731
    if tool == "housing":
        if not d["on_campus"]:
            return "You don't live in university housing, so there's no room or mailbox on file."
        return (f"You live in {d['room']['hall']} {d['room']['room']} ({d['room']['type'].lower()} room). Your mailbox is {d['mail']['box']}; its combination stays "
                f"hidden until you approve a fresh check in Housing. You have {n(len(d['requests']), 'maintenance request')} on file.")
    if tool == "id_card":
        return f"Your ID card is {d['card'].lower()}. " + " ".join(f"{a['name']}: ${a['balance']:,.2f}." for a in d["accounts"])
    if tool == "parking":
        offers = " ".join(f"{p['name']}: {'sold out, with a waitlist' if p['sold_out'] else '$' + format(p['price'], ',.0f')}." for p in d["for_sale"])
        return (f"{d['eligibility']} {offers} You have {n(len(d['permits']), 'parking permit')}, {n(len(d['vehicles']), 'vehicle')} on file "
                f"and {n(len(d['tickets']), 'citation')}.").replace("  ", " ")
    if tool == "careers":
        done = sum(1 for c in d["checklist"] if c["done"])
        return (f"There are {n(len(d['jobs']), 'opening')} listed. " + ("You have a career appointment booked. " if d["appointment"] else "You have no career appointment booked. ")
                + f"{done} of {len(d['checklist'])} getting-ready steps are done.")
    if tool == "library":
        return f"You have {n(len(d['loans']), 'item')} checked out, ${d['fines']:,.2f} in fines and {n(len(d['bookings']), 'study room booking')}. {d['limit']}"
    if tool == "coursework":
        if not d["todo"]:
            return "Nothing is due in your classes right now."
        return "Due next: " + "; ".join(f"{t['title']} for {t['course']} on {day(t['due'])}" for t in d["todo"][:4]) + f". {n(len(d['todo']), 'thing')} due in all."
    if tool == "wellness":
        return " ".join(f"{i['office']}: {i['line']}" for i in d["items"]) + " I only see that something exists and where to open it, never the details."
    return None


# ---- the working draft and the student's answers, kept in the session's sandbox ----------------------------------
# A suggested plan is a draft the student keeps working on, from the card's buttons or by asking in the chat. It lives
# on the server with the rest of the visitor's sandbox, so both ways of editing change the same list. It is still only
# a draft: nothing reaches the student's classes until they review and confirm it.
PREF_CHOICES = {"times": {"morning", "midday", "afternoon", "evening"}, "days": {"mwf", "tr", "four", "five"}, "gap": {"tight", "short", "long"},
                "credits": {"12", "13-15", "16+"}, "mode": {"campus", "online"}, "busy": {"evenings", "fridays", "mornings"}}
TARGET = {"12": 12, "13-15": 15, "16+": 17}


def saved(ctx: Ctx) -> dict | None:
    return ctx.state.get("draft")


def save(ctx: Ctx, items: list[dict], changed: int | None = None, bends: list[str] | None = None, undo: bool = False) -> None:
    old = saved(ctx) or {}
    clean = [{"crn": r["lecture"]["crn"], "linked": r["linked"]["crn"] if r["linked"] else None} for r in _rows(ctx, store.REG_TERM, items)]
    ctx.state["draft"] = {"items": clean, "prev": None if undo else old.get("items"), "changed": changed, "version": old.get("version", 0) + 1,
                          "bends": bends if bends is not None else ([] if undo else old.get("bends", []))}


def clean_answers(raw) -> dict:
    """The preference panel's answers, reduced to the choices it offers. Free text is kept as a short note only."""
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for key in ("times", "busy"):
        out[key] = [v for v in raw.get(key) or [] if v in PREF_CHOICES[key]] if isinstance(raw.get(key), list) else []
    for key in ("days", "gap", "credits", "mode"):
        out[key] = raw.get(key) if raw.get(key) in PREF_CHOICES[key] else None
    out["no8"] = bool(raw.get("no8"))
    out["note"] = " ".join(str(raw.get("note") or "").split())[:120]
    return out


def finder_shape(answers: dict) -> dict:
    """Answers -> what the class finder understands: parts of the day, days to avoid, earliest and latest times."""
    avoid = {"mwf": ["T", "R"], "tr": ["M", "W", "F"], "four": ["F"]}.get(answers.get("days"), [])
    busy = answers.get("busy") or []
    after = 10 * 60 if "mornings" in busy else 9 * 60 if answers.get("no8") else None
    return {"times": list(answers.get("times") or []), "avoid": sorted(set(avoid) | ({"F"} if "fridays" in busy else set())), "mode": answers.get("mode") or "any",
            "after": after, "before": 17 * 60 if "evenings" in busy else None, "credits_target": TARGET.get(answers.get("credits"), 15)}


def _gap_bends(rows: list[dict], gap: str | None) -> list[str]:
    """Where the day's spacing isn't what they asked for. The plan isn't rebuilt around this; it is pointed out."""
    if gap not in ("tight", "long"):
        return []
    out = []
    for day in "MTWRF":
        meets = sorted((m["start"], m["end"], r["lecture"]["course"]) for r in rows for sec in (r["lecture"], r["linked"]) if sec
                       for m in sec["meetings"] if not m["tba"] and day in m["days"])
        for (_, end, a), (start, _, b) in zip(meets, meets[1:]):
            wait = start - end
            if gap == "long" and 0 <= wait < 60 and a != b:
                out.append(f"{a} and {b} are less than an hour apart on {store.DAY_NAMES[day]}.")
            if gap == "tight" and wait > 60 and a != b:
                out.append(f"{a} and {b} have a gap of over an hour on {store.DAY_NAMES[day]}.")
    return list(dict.fromkeys(out))[:2]


def build(ctx: Ctx, answers=None) -> None:
    """Build the suggested plan from the saved answers (or new ones) and make it the working draft."""
    if answers is not None:
        ctx.state["prefs"] = {**clean_answers(answers), **finder_shape(clean_answers(answers)), "answered": True}
    prefs = ctx.state.setdefault("prefs", {})
    plan = audit.winter_plan(ctx.con, ctx.slug, {**legacy(ctx), "draft": None}, prefs=finder.clean_prefs(prefs), target_credits=prefs.get("credits_target") or 15)
    items = [{"crn": p["option"]["lecture"]["crn"], "linked": p["option"]["linked"]["crn"] if p["option"]["linked"] else None} for p in plan["picks"]]
    save(ctx, items, bends=plan["bends"] + _gap_bends(_rows(ctx, store.REG_TERM, items), prefs.get("gap")))


def current(ctx: Ctx) -> dict:
    """The working draft as the card shows it."""
    d = saved(ctx) or {"items": [], "prev": None, "changed": None, "version": 0, "bends": []}
    return {"kind": "draft", **evaluate(ctx, store.REG_TERM, d["items"]), "version": d["version"], "changed": d["changed"], "can_undo": d["prev"] is not None,
            "bends": d.get("bends", []), "prefs": ctx.state.get("prefs") or {}, "limits": {"min": FULL_TIME, "max": MAX_CREDITS}}


def edit(ctx: Ctx, body: dict) -> dict:
    """One change to the working draft, from a button on the card or from the chat. Returns the draft as it is now."""
    op, d = body.get("op"), saved(ctx) or {"items": []}
    items = [dict(i) for i in d["items"]]
    course = lambda crn: (store.section(ctx.con, crn) or {}).get("course") if isinstance(crn, int) else None      # noqa: E731
    if op == "set":
        save(ctx, body.get("items") if isinstance(body.get("items"), list) else [])
    elif op == "put":                      # a section chosen for the plan: it replaces that course if it is there, never sits beside it
        code = course(body.get("crn"))
        if not code:
            raise Refused("unknown_section", 400)
        new = {"crn": body["crn"], "linked": body.get("linked") if isinstance(body.get("linked"), int) else None}
        at = next((n for n, i in enumerate(items) if course(i["crn"]) == code), None)
        if at is None:
            items.append(new)
        else:
            items[at] = new
        save(ctx, items, changed=body["crn"])
    elif op == "drop":
        save(ctx, [i for i in items if i["crn"] != body.get("crn")])
    elif op == "undo":
        if d.get("prev") is None:
            raise Refused("cannot_undo", 409)
        save(ctx, d["prev"], undo=True)
    elif op == "build":
        build(ctx, None if body.get("keep") else (body.get("prefs") or {}))
    elif op == "clear":                    # the draft was confirmed into the student's plan, so it is finished
        ctx.state.pop("draft", None)
        return {"ok": True}
    else:
        raise Refused("unknown_change", 400)
    return current(ctx)
