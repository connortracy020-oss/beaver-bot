"""The degree checklist for a made-up student, in plain language, plus what-if and a winter plan.

SAMPLE DATA. Requirements come from the public catalog as parsed by generate.py; the student and their grades
are invented. Every result is an estimate for the demo: a real advisor decides what counts.
"""
import datetime

from . import finder, store

YEAR_OF = {"First-year": 1, "Sophomore": 2, "Junior": 3, "Senior": 4}
LOW_GRADES = {"C-", "D+", "D", "D-"}

# Plain-language notes for the lines students find confusing in a degree audit (popup 11).
NOTES = {
    "met": ("Done", "This requirement is complete. Nothing to do."),
    "transfer": ("Done with transfer credit",
                 "A class you took at another school is counting here. \"Satisfied by\" names that class."),
    "in_progress": ("In progress", "You're taking this now. It counts once you finish the term with a passing grade."),
    "planned": ("In your plan", "You've put this in your sample plan. It isn't registered until you register."),
    "needed": ("Still needed", "You haven't taken this yet. It's a to-do, not a problem."),
    "choice": ("Still needed: pick from a list",
               "You choose which class fills this. Any one of the listed classes works, so pick what fits your term."),
    "credits": ("Still needed: see section",
                "This line is a bucket of credits, not one class. \"See section\" means the list of classes that can "
                "fill it is somewhere else on the audit. Your advisor can tell you which of your classes already count."),
    "not_met": ("Minimum grade not met",
                "You passed this class, but this major needs a C or better in it, so the audit doesn't count it yet. "
                "It usually means retaking the class. It does not mean you're in trouble. Bring it to your advisor "
                "before you register."),
}
GPA_NOTE = ("Your GPA lines", "The audit shows more than one GPA. \"Overall\" is every OSU class. \"Major\" is only the "
            "classes in your major, and some majors need it above a set number. A red mark beside a GPA line shows "
            "up while any requirement under it is unfinished, even when the number itself is fine.")
SNAPSHOT_NOTE = ("This is a snapshot", "An audit shows your record as of the last time it was refreshed. A grade "
                 "posted or a class added since then won't show until it refreshes.")


def _requirements(con, program_id: int) -> list[dict]:
    reqs = [dict(r) for r in con.execute("SELECT * FROM program_requirements WHERE program_id = ? ORDER BY seq", (program_id,))]
    for r in reqs:
        r["courses"] = [{"code": c["course_code"], "with": c["with_code"]} for c in con.execute(
            "SELECT course_code, with_code FROM requirement_courses WHERE requirement_id = ? ORDER BY rowid", (r["id"],))]
    return reqs


def _core_program(con) -> int | None:
    r = con.execute("SELECT id FROM programs WHERE kind = 'core' LIMIT 1").fetchone()
    return r[0] if r else None


def _titles(con, codes: list[str]) -> dict[str, str]:
    if not codes:
        return {}
    marks = ",".join("?" * len(codes))
    return {r["code"]: r["title"] for r in con.execute(f"SELECT code, title FROM courses WHERE code IN ({marks})", codes)}


def audit(con, slug: str, state: dict | None = None) -> dict | None:
    row = store.student_row(con, slug)
    if not row:
        return None
    state = store.clean_state(state)
    mine = store.student_courses(con, row["id"])
    by_req: dict[int, list[dict]] = {}
    for c in mine:
        if c["requirement_id"]:
            by_req.setdefault(c["requirement_id"], []).append(c)
    loose_low = {c["course_code"]: c for c in mine
                 if c["status"] == "completed" and not c["requirement_id"] and c["grade"] in LOW_GRADES}
    planned = {p["lecture"]["course"]: p for p in store.plan_sections(con, state)}
    term_names = {t["code"]: t["name"] for t in (dict(r) for r in con.execute("SELECT code, name FROM terms"))}

    blocks: list[dict] = []
    counts = {"met": 0, "in_progress": 0, "planned": 0, "needed": 0, "not_met": 0}
    core_id = _core_program(con)
    passed = {c["course_code"]: c for c in mine if c["status"] in ("completed", "transfer") and c["grade"] not in ("F", "W", "N", "U")}
    underway = {c["course_code"]: c for c in mine if c["status"] == "in_progress"}
    shared: set[str] = set()       # courses already counted toward one Core Education category
    for program_id, fallback in ((row["program_id"], "Major requirements"), (core_id, "Core Education")):
        if not program_id:
            continue
        for r in _requirements(con, program_id):
            rows = by_req.get(r["id"], [])
            codes = [c["code"] for c in r["courses"]]
            if not rows and program_id == core_id:
                # A class taken for the major also counts for the Core Education category it carries.
                code = next((c for c in codes if c in passed and c not in shared), None)                     or next((c for c in codes if c in underway and c not in shared), None)
                if code:
                    shared.add(code)
                    rows = [passed.get(code) or underway[code]]
            status, note = "needed", "needed"
            if any(c["status"] in ("completed", "transfer") for c in rows):
                status = "met"
                note = "transfer" if any(c["status"] == "transfer" for c in rows) else "met"
            elif any(c["status"] == "in_progress" for c in rows):
                status = note = "in_progress"
            elif any(code in planned for code in codes):
                status = note = "planned"
            elif any(code in loose_low for code in codes):
                status = note = "not_met"
                rows = [loose_low[code] for code in codes if code in loose_low]
            elif r["kind"] in ("choice", "credits"):
                note = r["kind"]
            counts[status] += 1
            block_name = r["block"] or fallback
            block = next((b for b in blocks if b["name"] == block_name and b["program"] == program_id), None)
            if not block:
                block = {"name": block_name, "program": program_id, "requirements": []}
                blocks.append(block)
            block["requirements"].append({
                "id": r["id"], "label": r["label"], "kind": r["kind"], "credits": r["credits"], "status": status,
                "note": note, "pick": r["pick_count"], "year": r["plan_year"], "term": r["plan_term"],
                "options": codes[:12], "more_options": max(0, len(codes) - 12),
                "courses": [{"code": c["course_code"], "title": c["title"], "grade": c["grade"], "credits": c["credits"],
                             "term": term_names.get(c["term_code"]) if c["term_code"] else None,
                             "status": c["status"], "transfer_from": c["transfer_from"]} for c in rows],
            })
    for b in blocks:
        done = sum(1 for r in b["requirements"] if r["status"] == "met")
        b["done"], b["total"] = done, len(b["requirements"])
    total = sum(counts.values()) or 1
    notes = {k: {"title": t, "text": x} for k, (t, x) in NOTES.items()}
    return {"student": store.profile(con, row), "blocks": blocks, "counts": counts,
            "percent": round(100 * (counts["met"] + 0.5 * counts["in_progress"]) / total),
            "notes": notes, "gpa_note": {"title": GPA_NOTE[0], "text": GPA_NOTE[1]},
            "snapshot_note": {"title": SNAPSHOT_NOTE[0], "text": SNAPSHOT_NOTE[1]}}


def remaining(con, slug: str, state: dict | None = None) -> dict | None:
    """What is left this year, and what to take in the registration term (popup 4)."""
    row = store.student_row(con, slug)
    report = audit(con, slug, state)
    if not row or not report:
        return None
    year = YEAR_OF.get(row["standing"], 1)
    taken = store.taken_codes(store.student_courses(con, row["id"]))
    major_blocks = [b for b in report["blocks"] if b["program"] == row["program_id"]]
    open_reqs = [r for b in major_blocks for r in b["requirements"] if r["status"] in ("needed", "not_met")]
    this_year = [r for r in open_reqs if r["year"] is not None and r["year"] <= year]
    caught_up = not this_year
    if caught_up:
        this_year = open_reqs[:3]       # nothing left for this year: show what comes next instead
    items = []
    for r in this_year:
        pick = _best_course(con, r, taken, row["campus"])
        items.append({"requirement": r["label"], "status": r["status"], "year": r["year"], "term": r["term"],
                      "kind": r["kind"], **pick})
    winter = [i for i in items if i.get("code") and i["offered"] and i["ready"]]
    return {"student": report["student"], "year": year, "count": 0 if caught_up else len(items), "items": items,
            "caught_up": caught_up,
            "take_now": winter[:4], "term": "Winter 2027",
            "all_open": len(open_reqs)}


def _best_course(con, req: dict, taken: dict, campus: str = "Corvallis") -> dict:
    """The course that would fill a requirement next term: offered, and with prerequisites covered if possible."""
    best = None
    options = req["options"]
    if req.get("more_options"):
        # A long list (a Core Education category): suggest the intro classes with the most open winter sections.
        options = [r[0] for r in con.execute("""
            SELECT rc.course_code FROM requirement_courses rc JOIN courses c ON c.code = rc.course_code
            JOIN sections s ON s.course_code = rc.course_code AND s.term_code = ? AND s.is_primary = 1
                 AND s.seats_taken < s.seats_total AND (s.campus = ? OR ? = 'Corvallis' AND s.campus = 'Corvallis')
            WHERE rc.requirement_id = ? AND c.credits_min >= 3 AND c.level BETWEEN 100 AND 299 AND c.honors = 0
            GROUP BY rc.course_code ORDER BY COUNT(*) DESC, rc.course_code LIMIT 8""",
            (store.REG_TERM, campus, campus, req["id"]))] or options
    for code in options:
        if code in taken and req["status"] != "not_met":
            continue
        offered = con.execute("SELECT COUNT(*) FROM sections WHERE term_code = ? AND course_code = ? AND is_primary = 1 "
                              "AND seats_taken < seats_total", (store.REG_TERM, code)).fetchone()[0]
        pre = finder.prerequisites(con, code, taken)
        ready = pre["status"] in ("met", "none", "review")
        rank = (bool(offered) and ready, bool(offered), ready)
        if best is None or rank > best[0]:
            title = (con.execute("SELECT title, credits_text FROM courses WHERE code = ?", (code,)).fetchone() or [None, None])
            best = (rank, {"code": code, "title": title[0], "credits": title[1], "offered": bool(offered),
                           "sections": offered, "ready": ready, "prereqs": pre})
    return best[1] if best else {"code": None, "title": None, "credits": req["credits"], "offered": False,
                                 "sections": 0, "ready": False, "prereqs": None}


def what_if(con, slug: str, program_id: int) -> dict | None:
    """How a student's classes would count toward a different program (popup 5). No form: one question."""
    row = store.student_row(con, slug)
    program = con.execute("SELECT * FROM programs WHERE id = ?", (program_id,)).fetchone()
    if not row or not program:
        return None
    mine = store.student_courses(con, row["id"])
    done = store.taken_codes(mine, include_in_progress=False)
    underway = {c["course_code"] for c in mine if c["status"] == "in_progress"}
    info = {c["course_code"]: c for c in mine}
    counted, in_progress, needed, used = [], [], [], set()
    for r in _requirements(con, program_id):
        codes = [c["code"] for c in r["courses"]]
        hit = next((c for c in codes if c in done and c not in used), None)
        now = next((c for c in codes if c in underway and c not in used), None)
        entry = {"label": r["label"], "block": r["block"], "kind": r["kind"], "credits": r["credits"],
                 "options": codes[:6]}
        if hit:
            used.add(hit)
            counted.append({**entry, "course": hit, "grade": info[hit]["grade"],
                            "transfer": info[hit]["status"] == "transfer"})
        elif now:
            used.add(now)
            in_progress.append({**entry, "course": now})
        else:
            needed.append(entry)
    total = len(counted) + len(in_progress) + len(needed)
    own = audit(con, slug)
    own_major = [r for b in own["blocks"] if b["program"] == row["program_id"] for r in b["requirements"]]
    own_done = sum(1 for r in own_major if r["status"] == "met")
    credits_counted = sum(info[c["course"]]["credits"] for c in counted)
    return {
        "student": store.profile(con, row),
        "program": {"id": program["id"], "name": program["name"], "degree": program["degree"], "kind": program["kind"],
                    "college": program["college"], "url": program["catalog_url"], "total_credits": program["total_credits"]},
        "counted": counted, "in_progress": in_progress, "needed": needed, "total": total,
        "percent": round(100 * (len(counted) + 0.5 * len(in_progress)) / total) if total else 0,
        "credits_counted": credits_counted,
        "current": {"name": own["student"]["program"]["name"] if own["student"]["program"] else None,
                    "done": own_done, "total": len(own_major),
                    "percent": round(100 * own_done / len(own_major)) if own_major else 0},
        "next_up": [n for n in needed if n["options"]][:4],
    }


def programs(con, text: str = "", limit: int = 12) -> list[dict]:
    words = [w for w in text.lower().replace(",", " ").split() if len(w) > 1 and w not in ("major", "minor", "the", "in", "to", "of")]
    rows = con.execute("""SELECT p.id, p.name, p.kind, p.degree, p.college,
                                 (SELECT COUNT(*) FROM program_requirements r WHERE r.program_id = p.id) AS reqs
                          FROM programs p WHERE p.level = 'undergraduate' AND p.kind IN ('major', 'minor')
                          ORDER BY p.kind, p.name""").fetchall()
    out = []
    for r in rows:
        if r["reqs"] < 3:
            continue
        name = r["name"].lower()
        if words and not all(w in name for w in words):
            continue
        score = (0 if not words else (name == " ".join(words)) * 2 + name.startswith(words[0]))
        out.append((-score, r["kind"], r["name"], dict(r)))
    out.sort(key=lambda x: x[:3])
    return [x[3] for x in out[:limit]]


def find_program(con, text: str) -> dict | None:
    """The program a phrase like "computer science" or "cs" most likely means."""
    alias = {"cs": "computer science", "comp sci": "computer science", "me": "mechanical engineering",
             "ece": "electrical and computer engineering", "psych": "psychology", "bio": "biology",
             "business": "business administration", "kin": "kinesiology", "math": "mathematics",
             "econ": "economics", "chem": "chemistry"}
    text = alias.get(text.strip().lower(), text)
    found = programs(con, text, limit=1)
    return found[0] if found else None


def winter_plan(con, slug: str, state: dict | None = None, target_credits: float = 15, prefs: dict | None = None) -> dict | None:
    """A simple, clash-free plan for the registration term to bring to an advisor (popup 6). `prefs` are the
    student's answers in the class finder's shape; where no open section fits them, the closest one is used and
    `bends` says which class and why."""
    row = store.student_row(con, slug)
    report = audit(con, slug, state)
    if not row or not report:
        return None
    state = store.clean_state(state)
    year = YEAR_OF.get(row["standing"], 1)
    mine = store.student_courses(con, row["id"])
    taken = store.taken_codes(mine)
    reqs = [(b, r) for b in report["blocks"] for r in b["requirements"] if r["status"] in ("needed", "not_met")]

    def priority(pair):
        # Retakes first, then this year's major classes (winter ones first), then Core Education, then later years.
        b, r = pair
        major = b["program"] == row["program_id"]
        on_time = r["year"] is not None and r["year"] <= year
        winter = r["term"] == "Winter"
        return (0 if r["status"] == "not_met" else 1, 0 if (major and on_time and winter) else 1,
                0 if (major and on_time) else 1, 0 if not major else 1, r["year"] or 9)

    reqs.sort(key=priority)
    picks, credits, work_state, bends = [], 0.0, {**state, "plan": list(state["plan"]), "draft": None}, []
    prefs = {"times": [], "avoid": [], **(prefs or {})}
    if prefs.get("mode") not in ("campus", "online"):
        prefs["mode"] = "online" if row["campus"] == "Ecampus" else "campus"
    core_used = 0
    for b, r in reqs:
        if credits >= target_credits - 1 or len(picks) >= 5:
            break
        if r["kind"] == "credits":
            continue
        is_core = b["program"] != row["program_id"]
        if is_core and core_used >= 2:
            continue
        choice = _best_course(con, r, taken, row["campus"])
        if not choice["code"] or not choice["offered"] or not choice["ready"]:
            continue
        if any(p["course"]["code"] == choice["code"] for p in picks):
            continue
        chosen = {p["course"]["code"] for p in picks}
        needs = {x[0] for x in con.execute("SELECT req_code FROM prerequisites WHERE course_code = ? AND req_code IS NOT NULL", (choice["code"],))}
        if needs & chosen:
            continue            # it builds on another class in this same plan, so it belongs in a later term
        found = finder.find(con, slug, choice["code"], prefs, work_state)
        option = next(iter(found["options"]), None)
        if not option:                  # nothing fits every preference: take the closest that still has no time clash
            option = next((o for o in found["closest"] if not any("overlap" in m for m in o["misses"])), None)
            if option:
                bends.append(f"{choice['code']}: the closest open section {option['misses'][0]}.")
        if not option:
            continue
        work_state["plan"].append({"crn": option["lecture"]["crn"], "linked": option["linked"]["crn"] if option["linked"] else None})
        credits += option["credits"] or 0
        core_used += is_core
        why = []
        if r["status"] == "not_met":
            why.append("Retake to meet the minimum grade")
        if r["year"] and not is_core:
            why.append(f"Year {r['year']}{' ' + r['term'].lower() if r['term'] else ''} in the catalog's sample plan")
        if is_core:
            why.append("Counts for Core Education")
        if choice["prereqs"] and choice["prereqs"]["met_by"]:
            why.append("Prerequisite covered by " + ", ".join(choice["prereqs"]["met_by"][:2]))
        picks.append({"course": found["course"], "requirement": r["label"], "block": b["name"], "why": why,
                      "option": option})
    return {"student": report["student"], "term": "Winter 2027", "picks": picks, "credits": credits, "bends": bends,
            "advisor": row["advisor_name"],
            "note": "A starting point to bring to your advisor, built from the catalog's sample plan and sample sections."}


def checklist(con, slug: str, state: dict | None, today: datetime.date) -> dict | None:
    """Pre-registration checklist (popup 3): holds cleared, advisor met, classes picked, time known."""
    row = store.student_row(con, slug)
    if not row:
        return None
    state = store.clean_state(state)
    holds = store.holds(con, row["id"], state, today)
    blocking = [h for h in holds if h["blocks"]]
    appts = store.appointments(con, row, state, today)
    reg = store.registration(row, today)
    plan = store.plan_sections(con, state)
    credits = sum(p["lecture"]["credits"] or 0 for p in plan)
    needs_advisor = any(h["type"] == "advising" for h in holds)
    met = state["met"] or not needs_advisor
    upcoming = appts["upcoming"][0] if appts["upcoming"] else None
    waiting = bool(blocking and blocking[0]["type"] == "advising" and upcoming)     # booked, hold clears after it
    items = [
        {"key": "holds", "done": not blocking, "title": "Holds cleared",
         "detail": "No holds are blocking registration." if not blocking else
                   f"{blocking[0]['title']}. It clears after your meeting {upcoming['day_inline']}." if waiting else
                   f"{blocking[0]['title']}. {blocking[0]['how_to_clear']}",
         "pending": waiting,
         "action": None if not blocking or waiting else ("appointment" if blocking[0]["type"] == "advising" else "billing")},
        {"key": "advisor", "done": met, "title": "Advisor met",
         "detail": ("You've met with your advisor." if state["met"] else
                    "No advisor meeting is required for you this term." if not needs_advisor else
                    f"Booked for {upcoming['day_inline']} at {upcoming['time_label']}." if upcoming else
                    f"Book a time with {row['advisor_name']}."),
         "pending": bool(upcoming) and not met,
         "action": None if met else ("reschedule" if upcoming else "appointment")},
        {"key": "classes", "done": len(plan) >= 3, "title": "Classes picked",
         "detail": (f"{len(plan)} class{'es' if len(plan) != 1 else ''} in your plan, {credits:g} credits."
                    if plan else "Nothing in your winter plan yet."),
         "pending": 0 < len(plan) < 3, "action": "plan" if len(plan) < 3 else "schedule"},
        {"key": "time", "done": True, "title": "Time known",
         "detail": f"Registration opens {reg['date_label']} at {reg['time_label']}.", "action": None},
    ]
    return {"items": items, "done": sum(1 for i in items if i["done"]), "total": len(items),
            "ready": all(i["done"] for i in items), "registration": reg}


def dashboard(con, slug: str, state: dict | None, today: datetime.date) -> dict | None:
    """Everything the signed-in demo needs about one student, in one response."""
    row = store.student_row(con, slug)
    if not row:
        return None
    clean = store.clean_state(state)
    holds = store.holds(con, row["id"], clean, today)
    return {
        "student": store.profile(con, row),
        "registration": store.registration(row, today),
        "holds": holds,
        "blocked": any(h["blocks"] for h in holds),
        "appointments": store.appointments(con, row, clean, today),
        "slots": store.slots(con, row["id"], today),
        "billing": store.billing(con, row["id"], clean, today),
        "tasks": store.tasks(con, row["id"], today),
        "schedule": store.schedule(con, row["id"], store.NOW_TERM),
        "plan": store.plan_sections(con, clean),
        "checklist": checklist(con, slug, clean, today),
        "state": clean,
    }
