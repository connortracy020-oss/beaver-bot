"""Read-only access to the sample database (data/demo.db) and the shapes the browser gets.

Everything served from here is SAMPLE DATA: invented sections and made-up students (docs/demo-build-plan.md).
The database is opened read-only. What a visitor changes in the demo (a booked appointment, a class added to the
plan) lives only in their browser tab and is sent along as `state`; nothing is written on the server.
"""
import datetime
import json
import sqlite3
import threading

from .. import config

DAY_NAMES = {"M": "Mon", "T": "Tue", "W": "Wed", "R": "Thu", "F": "Fri", "S": "Sat", "U": "Sun"}
REG_TERM = "202702"       # the term the demo registers for (Winter 2027)
NOW_TERM = "202701"       # the term in progress (Fall 2026)
PASSING_C = {"A", "A-", "B+", "B", "B-", "C+", "C", "S", "P", "T"}
GRADE_POINTS = {"A": 4.0, "A-": 3.7, "B+": 3.3, "B": 3.0, "B-": 2.7, "C+": 2.3, "C": 2.0, "C-": 1.7, "D+": 1.3,
                "D": 1.0, "D-": 0.7, "F": 0.0}
_local = threading.local()


def available() -> bool:
    return config.DEMO_DB.exists()


def connect() -> sqlite3.Connection:
    con = getattr(_local, "con", None)
    if con is None or getattr(_local, "path", None) != str(config.DEMO_DB):
        con = sqlite3.connect(f"file:{config.DEMO_DB.as_posix()}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        _local.con, _local.path = con, str(config.DEMO_DB)
    return con


def release() -> None:
    """Close this thread's connection (the server calls it as each request ends)."""
    con = getattr(_local, "con", None)
    if con is not None:
        _local.con = None
        con.close()


# ---- small formatters ----------------------------------------------------------------------------
def clock(minutes: int | None) -> str | None:
    if minutes is None:
        return None
    h, m = divmod(int(minutes), 60)
    return f"{(h - 1) % 12 + 1}:{m:02d} {'AM' if h < 12 else 'PM'}"


def clock_text(hhmm: str) -> str:
    h, m = (int(x) for x in hhmm.split(":"))
    return clock(h * 60 + m)


def business_day(today: datetime.date, offset: int) -> datetime.date:
    """`offset` working days from today (negative = back), so sample appointments never land on a weekend."""
    step = 1 if offset >= 0 else -1
    day, left = today, abs(offset)
    while left:
        day += datetime.timedelta(days=step)
        if day.weekday() < 5:
            left -= 1
    return day


def next_weekday(today: datetime.date, weekday: int) -> datetime.date:
    ahead = (weekday - today.weekday()) % 7
    return today + datetime.timedelta(days=ahead or 7)


def day_inline(label: str) -> str:
    """A day label for the middle of a sentence: "tomorrow", but still "Thursday, Nov 12"."""
    return label.lower() if label in ("Today", "Tomorrow") else label


def day_label(day: datetime.date, today: datetime.date) -> str:
    gap = (day - today).days
    if gap == 0:
        return "Today"
    if gap == 1:
        return "Tomorrow"
    return day.strftime("%A, %b ") + str(day.day)


# ---- catalog and sections -------------------------------------------------------------------------
def term(con, code: str) -> dict | None:
    r = con.execute("SELECT * FROM terms WHERE code = ?", (code,)).fetchone()
    return dict(r) if r else None


def course(con, code: str) -> dict | None:
    r = con.execute("SELECT * FROM courses WHERE code = ?", (code,)).fetchone()
    if not r:
        return None
    out = dict(r)
    out["attributes"] = [dict(a) for a in con.execute(
        "SELECT attr_code AS code, attr_name AS name FROM course_attributes WHERE course_code = ? ORDER BY attr_code", (code,))]
    return out


def meetings(con, crn: int) -> list[dict]:
    out = []
    for m in con.execute("SELECT * FROM meetings WHERE crn = ? ORDER BY id", (crn,)):
        tba = m["days"] is None or m["start_min"] is None
        out.append({"days": m["days"], "start": m["start_min"], "end": m["end_min"], "tba": tba,
                    "days_label": " ".join(DAY_NAMES.get(d, d) for d in (m["days"] or "")) or None,
                    "time_label": None if tba else f"{clock(m['start_min'])} to {clock(m['end_min'])}",
                    "building": m["building"], "room": m["room"],
                    "start_date": m["start_date"], "end_date": m["end_date"]})
    return out


def section(con, crn: int | None) -> dict | None:
    if crn is None:
        return None
    r = con.execute("""SELECT s.*, c.title, c.credits_text FROM sections s JOIN courses c ON c.code = s.course_code
                       WHERE s.crn = ?""", (crn,)).fetchone()
    if not r:
        return None
    return {"crn": r["crn"], "term": r["term_code"], "course": r["course_code"], "title": r["title"],
            "section": r["section"], "type": r["schedule_type"], "method": r["method"], "campus": r["campus"],
            "session": r["session"], "credits": r["credits"], "grade_mode": r["grade_mode"],
            "instructor": r["instructor"], "seats_total": r["seats_total"],
            "seats_open": max(0, r["seats_total"] - r["seats_taken"]), "wait_cap": r["wait_cap"],
            "wait_count": r["wait_count"], "fee": r["fee"], "restrictions": r["restrictions"],
            "primary": bool(r["is_primary"]), "meetings": meetings(con, r["crn"])}


def linked(con, lecture_crn: int) -> list[dict]:
    rows = con.execute("SELECT linked_crn FROM linked_sections WHERE lecture_crn = ? ORDER BY linked_crn", (lecture_crn,))
    return [s for s in (section(con, r[0]) for r in rows.fetchall()) if s]


def overlaps(a: list[dict], b: list[dict]) -> bool:
    """True when two sections' meetings share a day and their times cross."""
    for x in a:
        for y in b:
            if x["tba"] or y["tba"]:
                continue
            if set(x["days"]) & set(y["days"]) and x["start"] < y["end"] and y["start"] < x["end"]:
                return True
    return False


def search_courses(con, text: str, limit: int = 8) -> list[dict]:
    """Courses by code ("mth 252", "MTH252Z") or by words in the title ("calculus")."""
    import re
    text = " ".join(text.split())
    if not text:
        return []
    m = re.match(r"^([A-Za-z]{1,5})\s?-?(\d{2,3}[A-Za-z]{0,2})?$", text)
    rows = []
    if m:
        subject, number = m.group(1).upper(), (m.group(2) or "").upper()
        rows = con.execute("""SELECT code, title, credits_text, level FROM courses
                              WHERE subject = ? AND number LIKE ? ORDER BY number LIMIT ?""",
                           (subject, number + "%", limit)).fetchall()
    if not rows:
        words = [w for w in re.findall(r"[A-Za-z0-9]+", text.lower()) if len(w) > 1][:5]
        if words:
            clause = " AND ".join("(LOWER(title) LIKE ? OR LOWER(code) LIKE ?)" for _ in words)
            args = [x for w in words for x in (f"%{w}%", f"%{w}%")]
            found = con.execute(f"""SELECT code, title, credits_text, level,
                                           (SELECT COUNT(*) FROM sections s WHERE s.course_code = courses.code
                                            AND s.term_code = ? AND s.is_primary = 1) AS offered
                                    FROM courses WHERE {clause} AND honors = 0 LIMIT 200""", (REG_TERM, *args)).fetchall()

            def rank(r):
                # whole-word matches in the title first ("calculus" before "precalculus"), then the classes with
                # the most sections this term, then lower-level classes
                title = r["title"].lower()
                whole = sum(1 for w in words if re.search(rf"\b{re.escape(w)}\b", title))
                return (-whole, -r["offered"], r["level"], r["code"])
            rows = sorted(found, key=rank)[:limit]
    return [{"code": r["code"], "title": r["title"], "credits": r["credits_text"]} for r in rows]


# ---- students ------------------------------------------------------------------------------------
def students(con) -> list[dict]:
    rows = con.execute("""SELECT s.slug, s.first_name, s.last_name, s.pronouns, s.standing, s.campus, s.situation,
                                 s.blurb, p.name AS program, p.degree
                          FROM students s JOIN programs p ON p.id = s.program_id ORDER BY s.id""").fetchall()
    return [dict(r) for r in rows]


def student_row(con, slug: str) -> sqlite3.Row | None:
    return con.execute("SELECT * FROM students WHERE slug = ?", (slug,)).fetchone()


def clean_state(state) -> dict:
    """The demo state a browser sends, reduced to the shapes this module trusts."""
    state = state if isinstance(state, dict) else {}
    plan = []
    for item in state.get("plan") or []:
        if isinstance(item, dict) and isinstance(item.get("crn"), int):
            plan.append({"crn": item["crn"], "linked": item.get("linked") if isinstance(item.get("linked"), int) else None})
    appt = state.get("appointment") if isinstance(state.get("appointment"), dict) else None
    draft = state.get("draft")
    draft = [{"crn": i["crn"], "linked": i.get("linked") if isinstance(i.get("linked"), int) else None}
             for i in draft if isinstance(i, dict) and isinstance(i.get("crn"), int)][:8] if isinstance(draft, list) else None
    return {"plan": plan[:12], "draft": draft, "prefs": state.get("prefs") if isinstance(state.get("prefs"), dict) else None,
            "appointment": {"slot": appt["slot"]} if appt and isinstance(appt.get("slot"), int) else None,
            "cancelled": bool(state.get("cancelled")), "met": bool(state.get("met")),
            "registered": bool(state.get("registered")), "paid": bool(state.get("paid"))}


def apply_change(state: dict, change: dict | None) -> dict:
    """The demo state after a tool's `apply` instruction. The browser does the same thing in its own tab
    (static/js/demo/session.js); this copy is for tests and the conversation checker."""
    state = clean_state(state)
    kind = (change or {}).get("type")
    if kind == "plan_add":
        state["plan"] = [p for p in state["plan"] if p["crn"] != change["crn"]] + [{"crn": change["crn"], "linked": change.get("linked")}]
    elif kind == "plan_add_many":
        have = {p["crn"] for p in state["plan"]}
        state["plan"] += [{"crn": i["crn"], "linked": i.get("linked")} for i in change.get("items", []) if i["crn"] not in have]
    elif kind == "plan_drop":
        state["plan"] = [p for p in state["plan"] if p["crn"] != change["crn"]]
    elif kind == "book":
        state["appointment"], state["cancelled"] = {"slot": change["slot"]}, False
    elif kind == "cancel_appointment":
        state["appointment"], state["cancelled"] = None, True
    if kind and kind.startswith("plan_"):
        state["registered"] = False
    return state


def student_courses(con, sid: int) -> list[dict]:
    return [dict(r) for r in con.execute(
        "SELECT * FROM student_courses WHERE student_id = ? ORDER BY COALESCE(term_code, '0'), course_code", (sid,))]


def taken_codes(courses: list[dict], include_in_progress: bool = True) -> dict[str, str | None]:
    """course code -> grade for everything passed, transferred or (optionally) under way."""
    out = {}
    for c in courses:
        if c["status"] in ("completed", "transfer") or (include_in_progress and c["status"] == "in_progress"):
            if c["status"] == "completed" and c["grade"] in ("F", "W", "N", "U"):
                continue
            out[c["course_code"]] = c["grade"]
    return out


def plan_sections(con, state: dict) -> list[dict]:
    """The classes in the browser's sample plan, with their linked recitation or lab."""
    out = []
    for item in state["plan"]:
        lecture = section(con, item["crn"])
        if lecture and lecture["term"] == REG_TERM:
            out.append({"lecture": lecture, "linked": section(con, item["linked"]) if item["linked"] else None})
    return out


def schedule(con, sid: int, term_code: str) -> list[dict]:
    """The classes a student is taking in a term (from the database, not the browser's plan)."""
    out = []
    for r in con.execute("""SELECT * FROM student_courses WHERE student_id = ? AND term_code = ?
                            AND status = 'in_progress' ORDER BY course_code""", (sid, term_code)):
        out.append({"lecture": section(con, r["crn"]) or {"course": r["course_code"], "title": r["title"],
                                                          "credits": r["credits"], "meetings": []},
                    "linked": section(con, r["linked_crn"])})
    return out


def registration(row: sqlite3.Row, today: datetime.date) -> dict:
    opens = next_weekday(today, row["reg_weekday"])
    return {"term": "Winter 2027", "term_code": REG_TERM, "date": opens.isoformat(),
            "day_label": opens.strftime("%A"), "date_label": opens.strftime("%A, %b ") + str(opens.day),
            "time_label": clock_text(row["reg_time"]), "days_away": (opens - today).days}


def holds(con, sid: int, state: dict, today: datetime.date) -> list[dict]:
    out = []
    for h in con.execute("SELECT * FROM student_holds WHERE student_id = ? ORDER BY id", (sid,)):
        cleared = (h["type"] == "advising" and state["met"]) or (h["type"] == "financial" and state["paid"])
        out.append({"id": h["id"], "type": h["type"], "title": h["title"], "reason": h["reason"], "office": h["office"],
                    "how_to_clear": h["how_to_clear"], "blocks": bool(h["blocks_registration"]) and not cleared,
                    "cleared": cleared, "placed": business_day(today, h["placed_offset_days"]).isoformat(),
                    "url": h["info_url"]})
    return out


def slots(con, sid: int, today: datetime.date) -> list[dict]:
    out = []
    for s in con.execute("SELECT * FROM advisor_slots WHERE student_id = ? ORDER BY offset_days, start_time", (sid,)):
        day = business_day(today, s["offset_days"])
        label = day_label(day, today)
        out.append({"id": s["id"], "date": day.isoformat(), "day_label": label, "day_inline": day_inline(label),
                    "time_label": clock_text(s["start_time"]), "minutes": s["minutes"], "mode": s["mode"],
                    "location": s["location"]})
    return out


def appointments(con, row: sqlite3.Row, state: dict, today: datetime.date) -> dict:
    """Upcoming and past appointments, after applying what the visitor booked or cancelled in this tab."""
    upcoming, past = [], []
    for a in con.execute("SELECT * FROM appointments WHERE student_id = ? ORDER BY offset_days", (row["id"],)):
        day = business_day(today, a["offset_days"])
        item = {"id": a["id"], "with": a["with_name"], "role": a["with_role"], "topic": a["topic"],
                "date": day.isoformat(), "day_label": day_label(day, today),
                "day_inline": day_inline(day_label(day, today)), "time_label": clock_text(a["start_time"]),
                "minutes": a["minutes"], "mode": a["mode"], "location": a["location"], "status": a["status"]}
        if a["status"] == "upcoming":
            if not (state["cancelled"] or state["appointment"] or state["met"]):
                upcoming.append(item)
        else:
            past.append(item)
    if state["appointment"] and not state["met"]:
        slot = next((s for s in slots(con, row["id"], today) if s["id"] == state["appointment"]["slot"]), None)
        if slot:
            upcoming.append({"id": f"slot-{slot['id']}", "with": row["advisor_name"], "role": "Academic advisor",
                             "topic": "Advising before registration", "date": slot["date"],
                             "day_label": slot["day_label"], "day_inline": slot["day_inline"], "time_label": slot["time_label"],
                             "minutes": slot["minutes"], "mode": slot["mode"], "location": slot["location"],
                             "status": "upcoming", "booked_here": True})
    return {"upcoming": upcoming, "past": past[::-1]}


def billing(con, sid: int, state: dict, today: datetime.date) -> dict | None:
    b = con.execute("SELECT * FROM balances WHERE student_id = ?", (sid,)).fetchone()
    if not b:
        return None
    due = today + datetime.timedelta(days=b["due_offset_days"])
    import re
    credits = con.execute("SELECT SUM(credits) FROM student_courses WHERE student_id = ? AND term_code = ? AND status = 'in_progress'",
                          (sid, b["term_code"])).fetchone()[0] or 0
    tx = [{"date": (today + datetime.timedelta(days=t["offset_days"])).isoformat(),
           "description": re.sub(r"(uition: )\d+(?:\.\d+)? credits", lambda m: f"{m.group(1)}{credits:g} credits", t["description"]),
           "amount": t["amount"]}
          for t in con.execute("SELECT * FROM transactions WHERE student_id = ? ORDER BY offset_days, id", (sid,))]
    paid = state["paid"]
    return {"term": (term(con, b["term_code"]) or {}).get("name"), "balance": 0.0 if paid else b["balance"],
            "past_due": 0.0 if paid else b["past_due"], "due": due.isoformat(),
            "due_label": due.strftime("%A, %b ") + str(due.day), "days_until_due": b["due_offset_days"],
            "plan_enrolled": bool(b["plan_enrolled"]), "meal_plan": b["meal_plan"], "orange_cash": b["orange_cash"],
            "transactions": tx, "paid_in_demo": paid}


def tasks(con, sid: int, today: datetime.date) -> list[dict]:
    out = []
    for t in con.execute("SELECT * FROM student_tasks WHERE student_id = ? ORDER BY status DESC, due_offset_days", (sid,)):
        due = today + datetime.timedelta(days=t["due_offset_days"]) if t["due_offset_days"] is not None else None
        out.append({"id": t["id"], "title": t["title"], "detail": t["detail"], "status": t["status"], "kind": t["kind"],
                    "due": due.isoformat() if due else None,
                    "due_label": (due.strftime("%b ") + str(due.day)) if due else None})
    return out


def profile(con, row: sqlite3.Row) -> dict:
    program = con.execute("SELECT * FROM programs WHERE id = ?", (row["program_id"],)).fetchone()
    return {"slug": row["slug"], "first_name": row["first_name"], "last_name": row["last_name"],
            "name": f"{row['first_name']} {row['last_name']}", "pronouns": row["pronouns"], "email": row["email"],
            "sample_id": row["sample_id"], "standing": row["standing"], "campus": row["campus"],
            "transfer": bool(row["is_transfer"]), "gpa": row["gpa"], "major_gpa": row["major_gpa"],
            "credits": row["credits_earned"], "academic_standing": row["academic_standing"],
            "advisor": row["advisor_name"], "advisor_office": row["advisor_office"],
            "program": {"id": program["id"], "name": program["name"], "degree": program["degree"],
                        "college": program["college"], "url": program["catalog_url"]} if program else None,
            "situation": row["situation"], "blurb": row["blurb"]}


def forms(con, text: str = "", limit: int = 30) -> list[dict]:
    words = [w for w in text.lower().split() if len(w) > 2]
    out = []
    for r in con.execute("SELECT * FROM forms ORDER BY name"):
        hay = f"{r['name']} {r['purpose']} {r['when_to_use'] or ''} {r['goes_to']}".lower()
        score = sum(1 for w in words if w[: max(4, len(w) - 2)] in hay)
        if words and not score:
            continue
        item = dict(r)
        item["fields"] = json.loads(r["fields"] or "[]")
        out.append((score, item))
    out.sort(key=lambda x: -x[0])
    return [item for _, item in out[:limit]]


def resources(con, text: str = "", category: str = "", limit: int = 200) -> list[dict]:
    words = [w for w in text.lower().split() if len(w) > 1]
    out = []
    for r in con.execute("SELECT * FROM resources ORDER BY name COLLATE NOCASE"):
        if category and category != "All" and r["category"] != category:
            continue
        hay = f"{r['name']} {r['plain']} {r['use_for'] or ''} {r['same_as'] or ''}".lower()
        score = sum((3 if w in r["name"].lower() else 1) for w in words if w[: max(3, len(w) - 2)] in hay)
        if words and not score:
            continue
        item = dict(r)
        item["same_as"] = [s.strip() for s in (r["same_as"] or "").split(",") if s.strip()]
        out.append((score, item))
    if words:
        out.sort(key=lambda x: -x[0])
    return [item for _, item in out[:limit]]
