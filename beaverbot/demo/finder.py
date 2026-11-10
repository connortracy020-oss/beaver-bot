"""The class finder: sample sections that fit what a student asked for.

Given a course and preferences (parts of the day, days to avoid, on campus or online), it looks through the
invented sections for the registration term and returns up to three options. Each option is a lecture paired
with one linked recitation or lab that also fits, and has been checked for open seats, prerequisites,
restrictions and clashes with the classes already in the student's sample plan.

SAMPLE DATA: times, seats, rooms and instructors are made up (docs/demo-build-plan.md).
"""
import re

from . import store

PARTS = {"morning": (0, 12 * 60), "midday": (10 * 60, 14 * 60), "afternoon": (12 * 60, 17 * 60), "evening": (17 * 60, 24 * 60)}
PART_LABEL = {"morning": "mornings", "midday": "midday", "afternoon": "afternoons", "evening": "evenings"}
DAY_WORDS = {"M": r"mon(day)?s?", "T": r"tue(s|sday)?s?", "W": r"wed(nesday)?s?", "R": r"thu(r|rs|rsday)?s?",
             "F": r"fri(day)?s?"}
MAX_OPTIONS = 3


def parse_prefs(text: str) -> dict:
    """Preferences from plain words: "mornings, no Fridays, on campus" -> times, avoid, mode."""
    low = text.lower()
    times = [p for p, rx in (("morning", r"morning|\bam\b|early|before noon|ma[nñ]ana"),
                             ("afternoon", r"afternoon|after lunch|midday|tarde"),
                             ("evening", r"evening|night|after (5|five|work)|noche")) if re.search(rx, low)]
    avoid = []
    for letter, rx in DAY_WORDS.items():
        if re.search(rf"\b(no|not|avoid|except|without|skip|free|off)\b[^.;]{{0,40}}\b{rx}\b", low):
            avoid.append(letter)
    only = [letter for letter, rx in DAY_WORDS.items() if re.search(rf"\bonly\b[^.;]{{0,30}}\b{rx}\b", low)]
    if re.search(r"\bmwf\b", low) and not avoid:
        avoid = ["T", "R"]
    if re.search(r"\b(tr|tuesdays? (and|&) thursdays?|tue/thu)\b", low) and not avoid and not only:
        avoid = ["M", "W", "F"]
    if only:
        avoid = [d for d in "MTWRF" if d not in only]
    mode = "any"
    if re.search(r"online|ecampus|remote|en l[ií]nea", low):
        mode = "online"
    if re.search(r"on[- ]campus|in[- ]person|face to face|presencial", low):
        mode = "campus"
    anytime = bool(re.search(r"\b(any ?time|anything|no preference|whatever|don'?t care|flexible)\b", low))
    return {"times": [] if anytime else times, "avoid": [] if anytime else avoid, "mode": mode,
            "understood": bool(times or avoid or mode != "any" or anytime)}


def _minutes(value) -> int | None:
    """ "15:00" -> 900. Anything else -> None."""
    if isinstance(value, int) and 0 <= value < 1440:
        return value
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", str(value or "").strip())
    return int(m.group(1)) * 60 + int(m.group(2)) if m and int(m.group(1)) < 24 and int(m.group(2)) < 60 else None


def clean_prefs(prefs) -> dict:
    prefs = prefs if isinstance(prefs, dict) else {}
    times = [t for t in prefs.get("times") or [] if t in PARTS]
    return {"times": [] if {"morning", "afternoon", "evening"} <= set(times) else times,           # all three is the same as no preference
            "avoid": [d for d in prefs.get("avoid") or [] if isinstance(d, str) and len(d) == 1 and d in "MTWRF"],
            "mode": prefs.get("mode") if prefs.get("mode") in ("campus", "online", "any") else "any",
            "after": _minutes(prefs.get("after")), "before": _minutes(prefs.get("before"))}      # "not before 3 pm", "done by noon"


def prefs_label(prefs: dict) -> str:
    bits = []
    if prefs["times"]:
        bits.append(" or ".join(PART_LABEL[t] for t in prefs["times"]))
    if prefs["avoid"]:
        bits.append("no " + ", ".join(store.DAY_NAMES[d] for d in prefs["avoid"]))
    if prefs.get("after") is not None:
        bits.append(f"starting {store.clock(prefs['after'])} or later")
    if prefs.get("before") is not None:
        bits.append(f"done by {store.clock(prefs['before'])}")
    bits.append({"campus": "on campus", "online": "online", "any": "on campus or online"}[prefs["mode"]])
    return ", ".join(bits)


def _misses(sec: dict, prefs: dict) -> list[str]:
    """Why a section doesn't fit the preferences, in words. Empty means it fits."""
    out = []
    online = sec["campus"] == "Ecampus" or sec["method"] == "Online"
    if prefs["mode"] == "online" and not online:
        out.append("meets in person")
    if prefs["mode"] == "campus" and online:
        out.append("is online")
    for m in sec["meetings"]:
        if m["tba"]:
            continue
        early = prefs.get("after") is not None and m["start"] < prefs["after"]          # "no 8 AMs" holds whatever time of day was picked
        if early or (prefs["times"] and not any(PARTS[p][0] <= m["start"] < PARTS[p][1] for p in prefs["times"])):
            out.append(f"starts at {store.clock(m['start'])}")
        if prefs.get("before") is not None and m["end"] > prefs["before"]:
            out.append(f"ends at {store.clock(m['end'])}")
        clash = [store.DAY_NAMES[d] for d in m["days"] if d in prefs["avoid"]]
        if clash:
            out.append("meets " + " and ".join(clash))
    return out


def prerequisites(con, code: str, taken: dict[str, str | None]) -> dict:
    """Whether a student's classes cover a course's prerequisites: every group needs one satisfied row."""
    rows = con.execute("SELECT * FROM prerequisites WHERE course_code = ? AND kind = 'prereq' ORDER BY group_no", (code,)).fetchall()
    text = (con.execute("SELECT prereq_text FROM courses WHERE code = ?", (code,)).fetchone() or [None])[0]
    if not rows:
        return {"status": "none", "text": text, "missing": [], "met_by": []}
    groups: dict[int, list] = {}
    for r in rows:
        groups.setdefault(r["group_no"], []).append(r)
    missing, met_by, review = [], [], False
    for group in groups.values():
        hit = next((r["req_code"] for r in group if r["req_code"] and r["req_code"] in taken), None)
        if hit:
            met_by.append(hit)
        elif any(r["req_code"] is None for r in group):
            review = True       # a placement score or similar could cover it; we can't tell
        else:
            codes = [r["req_code"] for r in group]
            missing.append(codes[0] + (" (or an equivalent)" if len(codes) > 1 else ""))
    status = "missing" if missing else ("review" if review else "met")
    return {"status": status, "text": text, "missing": missing, "met_by": met_by}


def find(con, slug: str, code: str, prefs: dict, state: dict, term_code: str = store.REG_TERM) -> dict:
    row = store.student_row(con, slug)
    info = store.course(con, code)
    if not row or not info:
        return {"course": None, "options": [], "closest": []}
    prefs = clean_prefs(prefs)
    state = store.clean_state(state)
    mine = store.student_courses(con, row["id"])
    taken = store.taken_codes(mine)
    planned = store.plan_sections(con, state)
    # a plan still being worked out in the chat takes up time too, apart from the class being looked for
    drafted = [p for p in store.plan_sections(con, {"plan": state.get("draft") or []}) if p["lecture"]["course"] != code
               and not any(q["lecture"]["course"] == p["lecture"]["course"] for q in planned)]
    busy = [(p["lecture"]["course"], p["lecture"]["meetings"] + (p["linked"]["meetings"] if p["linked"] else [])) for p in drafted] + [(p["lecture"]["course"], p["lecture"]["meetings"] + (p["linked"]["meetings"] if p["linked"] else []))
            for p in planned]
    already = next((p for p in planned if p["lecture"]["course"] == code), None)
    home = row["campus"]

    lectures = [store.section(con, r[0]) for r in con.execute(
        "SELECT crn FROM sections WHERE term_code = ? AND course_code = ? AND is_primary = 1 ORDER BY section",
        (term_code, code))]
    fits, near, full = [], [], 0
    for lec in lectures:
        if lec["campus"] in ("Cascades", "INTO OSU") or (lec["restrictions"] and "Honors" in lec["restrictions"]):
            continue
        if home == "Ecampus" and lec["campus"] != "Ecampus" and prefs["mode"] != "campus":
            continue
        misses = _misses(lec, prefs)
        clash = next((c for c, meets in busy if c != code and store.overlaps(lec["meetings"], meets)), None)
        if lec["seats_open"] <= 0:
            full += 1
            continue
        if clash:
            misses.append(f"overlaps {clash} in your plan")
        options = store.linked(con, lec["crn"])
        pick, alternatives = None, []
        if options:
            ranked = []
            for sec in options:
                if sec["seats_open"] <= 0:
                    continue
                sec_misses = _misses(sec, {**prefs, "mode": "any"})
                if any(c != code and store.overlaps(sec["meetings"], meets) for c, meets in busy):
                    sec_misses.append("overlaps your plan")
                start = min((m["start"] for m in sec["meetings"] if not m["tba"]), default=0)
                ranked.append((len(sec_misses), start, sec, sec_misses))
            ranked.sort(key=lambda r: r[:2])
            if not ranked:
                continue                       # every linked section is full: the lecture can't be taken
            pick = ranked[0][2]
            misses += [f"its {pick['type'].lower()} {m}" for m in ranked[0][3]]
            alternatives = [r[2] for r in ranked[1:3] if not r[3]]
        option = {"lecture": lec, "linked": pick, "alternatives": alternatives, "misses": misses,
                  "credits": lec["credits"], "fits": not misses}
        (fits if not misses else near).append(option)

    def spread(options: list[dict]) -> list[dict]:
        """Up to three, preferring different times of day over three near-identical sections."""
        # Someone who asked for a time of day or certain days wants a class that meets then, so sections with set
        # meeting times come before online ones with none (unless they asked for online).
        wants_time = bool(prefs["times"] or prefs["avoid"] or prefs["after"] is not None or prefs["before"] is not None)
        untimed = lambda o: all(m["tba"] for m in o["lecture"]["meetings"])       # noqa: E731
        options.sort(key=lambda o: (untimed(o) if wants_time and prefs["mode"] != "online" else False,
                                    -o["lecture"]["seats_open"] / max(1, o["lecture"]["seats_total"]) // 0.34,
                                    o["lecture"]["section"]))
        out, seen = [], set()
        for o in options:
            key = next(((m["days"], m["start"] // 120) for m in o["lecture"]["meetings"] if not m["tba"]), ("online", 0))
            if key not in seen:
                seen.add(key)
                out.append(o)
        out += [o for o in options if o not in out]
        return out[:MAX_OPTIONS]

    near.sort(key=lambda o: len(o["misses"]))
    return {
        "course": {"code": info["code"], "title": info["title"], "credits": info["credits_text"],
                   "description": info["description"], "prereq_text": info["prereq_text"],
                   "catalog_url": info["catalog_url"], "attributes": info["attributes"]},
        "term": (store.term(con, term_code) or {}).get("name"),
        "prefs": prefs, "prefs_label": prefs_label(prefs),
        "prereqs": prerequisites(con, code, taken),
        "taken": code in store.taken_codes(mine, include_in_progress=False),
        "in_progress": any(c["course_code"] == code and c["status"] == "in_progress" for c in mine),
        "in_plan": bool(already),
        "options": spread(fits), "closest": [] if fits else near[:MAX_OPTIONS],
        "counts": {"sections": len(lectures), "full": full, "fit": len(fits)},
    }


def details(con, code: str, term_code: str = store.REG_TERM) -> dict | None:
    """Everything the class details popup shows for one course in one term."""
    info = store.course(con, code)
    if not info:
        return None
    sections = []
    for r in con.execute("SELECT crn FROM sections WHERE term_code = ? AND course_code = ? AND is_primary = 1 ORDER BY section",
                         (term_code, code)):
        lec = store.section(con, r[0])
        lec["linked"] = store.linked(con, lec["crn"])
        sections.append(lec)
    prereq_rows = [dict(r) for r in con.execute("SELECT * FROM prerequisites WHERE course_code = ? ORDER BY kind, group_no", (code,))]
    return {"course": info, "term": (store.term(con, term_code) or {}).get("name"), "sections": sections,
            "prerequisites": prereq_rows}
