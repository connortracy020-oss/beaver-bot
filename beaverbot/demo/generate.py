"""Build data/demo.db, the SAMPLE database behind the Beaver Bot demo.

Beaver Bot is an independent student project. It is not affiliated with Oregon State University.

What is real and what is invented:

* Course and program facts (titles, credits, descriptions, prerequisites, requirement lists, sample plans) are
  parsed from the public Academic Catalog pages already stored in data/osu.sqlite. That file is opened read-only.
* Everything else is invented here with one seeded random generator: sections, CRNs, meeting times, rooms,
  seats, instructors, buildings, students, grades, holds, appointments and balances. Nothing is OSU's real
  schedule and nothing comes from a real person's account.

Run:  python -m beaverbot.demo.generate [--out data/demo.db] [--source data/osu.sqlite] [--seed N] [--quiet]
Use:  from beaverbot.demo.generate import build;  counts = build(out_path, source_path)

No network access. Standard library only. The same seed always gives the same rows (only meta.built_at moves).
"""
from __future__ import annotations

import argparse
import datetime
import json
import math
import os
import pathlib
import random
import re
import sqlite3
import sys
import tempfile
import time

DEFAULT_SEED = 20261109
DEFAULT_OUT = os.path.join("data", "demo.db")
DEFAULT_SOURCE = os.path.join("data", "osu.sqlite")
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")
SCHEMA_VERSION = "1"
MIN_SECTIONS = 60000
MAX_SECTIONS = 95000

COURSE_URL_PREFIX = "https://catalog.oregonstate.edu/courses/"
PROGRAM_URL_PREFIX = "https://catalog.oregonstate.edu/college-departments/"
CORE_URL = "https://catalog.oregonstate.edu/core-education/"
CORE_PREFIX = "Core Ed - "

# (code, name, season, start, end, status, view_only). Sections are generated for the last three only.
DEMO_TERMS = [
    ("202603", "Spring 2026", "Spring", "2026-03-30", "2026-06-12", "past", 1),
    ("202701", "Fall 2026", "Fall", "2026-09-23", "2026-12-11", "current", 1),
    ("202702", "Winter 2027", "Winter", "2027-01-04", "2027-03-19", "registration", 0),
    ("202703", "Spring 2027", "Spring", "2027-03-29", "2027-06-11", "future", 0),
]
SCHEDULE_TERMS = ["202701", "202702", "202703"]
CURRENT_TERM = "202701"
REG_TERM = "202702"
TERM_INDEX = {"Fall": 0, "Winter": 1, "Spring": 2}

# Courses the demo leans on: Winter 2027 always has three well-spread Corvallis lectures with recitations or labs.
DEMO_COURSES = ["MTH 251Z", "MTH 252Z", "MTH 254", "MTH 256", "CS 161", "CS 162", "CS 261", "CS 225", "CH 231",
              "PH 211", "PH 212", "ST 314", "WR 121Z", "WR 227Z", "PSY 201Z", "PSY 202Z", "BI 221", "ECON 201Z",
              "COMM 111Z", "ENGR 102", "ENGR 211", "ME 316", "BA 101", "KIN 131"]
FULL_LECTURE_COURSE = "MTH 252Z"          # one Winter lecture of this course is full, with a waitlist


# ======================================================================================================
# Pure text parsers (unit tested in tests/test_demo_data.py)
# ======================================================================================================

_SMALL_WORDS = {"a", "an", "and", "as", "at", "but", "by", "for", "from", "in", "into", "nor", "of", "on", "or",
                "per", "the", "to", "via", "vs", "with"}
_ROMAN = {"I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"}
_ACRONYMS = {"GIS", "DNA", "RNA", "AI", "OSU", "MIME", "COB", "CAD", "HVAC", "ROTC", "STEM", "GPS", "HIV", "AIDS",
             "NMR", "MRI", "PCR", "VLSI", "CMOS", "UX", "UI", "WIC", "ESL", "MBA", "USA", "LGBTQ", "LGBTQ+",
             "LGBTQIA+", "CPR", "PTAH", "GTA", "DEI"}
_CODE = r"[A-Z]{1,5} \d{3}[A-Z]{0,3}"
_CODE_RE = re.compile(_CODE)
_CODE_CELL = re.compile(r"^(?:or )?%s(?:\s*(?:&|/|and|or)\s*%s)*$" % (_CODE, _CODE))
_COURSE_HEAD = re.compile(r"^## ([A-Z][A-Z0-9]*) ([A-Z0-9]+), (.+), ([0-9][0-9.,\- or]*?) Credits?\s*$")
_NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
                 "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}


def strip_markers(title: str) -> str:
    """Drop the catalog's leading + * ^ markers (Core Ed, Bacc Core, WIC)."""
    return (title or "").strip().lstrip("+*^ ").strip()


def _cap(part: str) -> str:
    up = part.upper()
    if up in _ROMAN or up in _ACRONYMS:
        return up
    if re.fullmatch(r"\d+(ST|ND|RD|TH)", up):
        return up.lower()                                  # 21ST -> 21st
    if any(ch.isdigit() for ch in part):
        return up                                          # 3-D, H2O, B12
    return part[:1].upper() + part[1:].lower()


def _case_word(word: str, first: bool) -> str:
    m = re.match(r"^([^A-Za-z0-9]*)(.*?)([^A-Za-z0-9+]*)$", word)
    pre, core, post = m.group(1).replace("+", "").replace("*", "").replace("^", ""), m.group(2), m.group(3)
    if not core:
        return pre + post
    up = core.upper()
    if up in _ROMAN or up in _ACRONYMS or re.fullmatch(r"(?:[A-Z]\.)+[A-Z]?", up + post):
        return pre + up + post
    if not first and not pre and core.lower() in _SMALL_WORDS:
        return pre + core.lower() + post
    parts = re.split(r"([-/])", core)
    return pre + "".join(p if p in "-/" else _cap(p) for p in parts) + post


def title_case(text: str) -> str:
    """'+*INTRODUCTION TO COMPUTER SCIENCE II' -> 'Introduction to Computer Science II'."""
    words = strip_markers(text).split()
    out: list[str] = []
    for i, w in enumerate(words):
        first = i == 0 or out[-1].endswith((":", "--")) or out[-1] in ("-", "–", "—")
        out.append(_case_word(w, first))
    return " ".join(out)


def parse_credits(text: str) -> tuple[str, float, float]:
    """'4 Credits' -> ('4', 4, 4); '1-16 Credits' -> ('1-16', 1, 16); '0 or 4' -> ('0 or 4', 0, 4)."""
    t = re.sub(r"\s*Credits?\s*$", "", (text or "").strip()).strip()
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", t)]
    if not nums:
        return (t or "0", 0.0, 0.0)
    return (t, min(nums), max(nums))


def _split_top(text: str, sep: str) -> list[str]:
    """Split on `sep` wherever it is not inside parentheses."""
    parts, depth, start, i, n = [], 0, 0, 0, len(sep)
    while i < len(text):
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif depth == 0 and text.startswith(sep, i):
            parts.append(text[start:i])
            i += n
            start = i
            continue
        i += 1
    parts.append(text[start:])
    return parts


def _strip_outer_parens(s: str) -> str:
    s = s.strip()
    while s.startswith("(") and s.endswith(")"):
        depth = 0
        for i, ch in enumerate(s):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0 and i != len(s) - 1:
                    return s
        s = s[1:-1].strip()
    return s


def parse_prereq_text(text: str | None) -> list[dict]:
    """Flat parse of a catalog prerequisite line: AND across group_no, OR inside a group.

    Rows: {group_no, req_code, min_grade, concurrent, note}. A non-course alternative (placement test and so
    on) has req_code None and the text in note. Nested 'and' inside an alternative keeps its text in note too.
    """
    rows: list[dict] = []
    if not text or not text.strip():
        return rows
    t = text.strip().rstrip(".").replace(" or better", "\x00")
    group_no = 0
    for grp in _split_top(t, " and "):
        grp = _strip_outer_parens(grp)
        if not grp:
            continue
        flat: list[str] = []
        for alt in _split_top(grp, " or "):
            alt = alt.strip()
            inner = _strip_outer_parens(alt)
            if inner != alt and " or " in inner and " and " not in inner:
                flat.extend(x.strip() for x in _split_top(inner, " or "))
            else:
                flat.append(alt)
        group_no += 1
        for alt in flat:
            alt = alt.replace("\x00", " or better").strip()
            if not alt:
                continue
            m = re.match(r"^\(*\s*(%s)(?![A-Za-z0-9])" % _CODE, alt)
            grade = re.search(r"with ([A-DF][+-]?) or better", alt) or re.search(r"\[([A-DFSP][+-]?)\]", alt)
            if m:
                rows.append({"group_no": group_no, "req_code": m.group(1),
                             "min_grade": grade.group(1) if grade else None,
                             "concurrent": 1 if "concurrently" in alt.lower() else 0,
                             "note": alt if " and " in alt else None})
            else:
                rows.append({"group_no": group_no, "req_code": None, "min_grade": None, "concurrent": 0,
                             "note": alt})
    return rows


def parse_subject_page(main_text: str) -> dict:
    """Parse one catalog subject page ('# Computer Science (CS)' then '## CS 161, TITLE, 4 Credits' blocks)."""
    lines = (main_text or "").split("\n")
    subject, subject_name = None, None
    if lines:
        m = re.match(r"^# (.*?)\s*\(([A-Z][A-Z0-9]*)\)\s*$", lines[0].strip())
        if m:
            subject_name, subject = m.group(1).strip(), m.group(2)
    courses: list[dict] = []
    cur = None
    for raw in lines[1:]:
        line = raw.rstrip()
        if line.startswith("## "):
            cur = None
            m = _COURSE_HEAD.match(line)
            if not m or not re.search(r"\d", m.group(2)):
                continue                       # LDEA / UDEA placeholders and anything unreadable
            subj, number, title, credits = m.group(1), m.group(2), m.group(3), m.group(4)
            ctext, cmin, cmax = parse_credits(credits)
            digits = re.match(r"\d+", number)
            cur = {"code": "%s %s" % (subj, number), "subject": subj, "number": number,
                   "level": (int(digits.group(0)) // 100) * 100 if digits else 0,
                   "raw_title": title.strip(), "title": title_case(title),
                   "credits_text": ctext, "credits_min": cmin, "credits_max": cmax,
                   "description": None, "prereq_text": None, "coreq_text": None, "recommended_text": None,
                   "equivalent_text": None, "repeatable_text": None, "ecampus": 0, "honors": 0, "attrs": []}
            courses.append(cur)
            continue
        if line.startswith("#") or cur is None or not line.strip():
            if line.startswith("#"):
                cur = None
            continue
        s = line.strip()
        if re.match(r"^Prerequisites?:", s):
            cur["prereq_text"] = s.split(":", 1)[1].strip()
        elif re.match(r"^Corequisites?:", s):
            cur["coreq_text"] = s.split(":", 1)[1].strip()
        elif s.startswith("Recommended:"):
            cur["recommended_text"] = s.split(":", 1)[1].strip()
        elif s.startswith("Equivalent to:"):
            cur["equivalent_text"] = s.split(":", 1)[1].strip()
        elif s.startswith("This course is repeatable"):
            cur["repeatable_text"] = s
        elif s.startswith("Attributes:"):
            for piece in s.split(":", 1)[1].split(";"):
                am = re.match(r"^\s*([A-Z0-9]+)\s+[–—-]\s+(.*?)\s*$", piece)
                if am and all(a[0] != am.group(1) for a in cur["attrs"]):
                    cur["attrs"].append((am.group(1), am.group(2)))
        elif s == "Available via Ecampus":
            cur["ecampus"] = 1
        else:
            cur["description"] = (cur["description"] + " " + s) if cur["description"] else s
    for c in courses:
        if any(a[0] == "HNRS" for a in c["attrs"]) or re.search(r"\dHZ?$", c["number"]):
            c["honors"] = 1
    return {"subject": subject, "subject_name": subject_name, "courses": courses}


_PROGRAM_TITLE = re.compile(
    r"^(?P<mname>.*?) (?P<mkind>Undergraduate Major|Graduate Major|Major) \((?P<deg>[^()]*)\)$"
    r"|^(?P<nname>.*?) (?P<nkind>Graduate Minor|Minor)$"
    r"|^(?P<oname>.*?) Option$"
    r"|^(?P<cname>.*?) (?P<ckind>Graduate Certificate|Undergraduate Certificate|Certificate)$")


def parse_program_title(title: str | None) -> dict | None:
    """'Computer Science Undergraduate Major (BA, BS, HBA, HBS)' -> name/kind/degree/level. None if not a program.

    An option's level is None here: it follows its parent major.
    """
    m = _PROGRAM_TITLE.match((title or "").strip())
    if not m:
        return None
    if m.group("mname") is not None:
        degree = m.group("deg").strip()
        if m.group("mkind") == "Graduate Major":
            level = "graduate"
        elif m.group("mkind") == "Undergraduate Major":
            level = "undergraduate"
        else:
            tokens = [d.strip() for d in degree.split(",")]
            level = "undergraduate" if any(re.match(r"^H?B", d) for d in tokens) else "graduate"
        return {"name": m.group("mname").strip(), "kind": "major", "degree": degree, "level": level}
    if m.group("nname") is not None:
        return {"name": m.group("nname").strip(), "kind": "minor", "degree": None,
                "level": "graduate" if m.group("nkind") == "Graduate Minor" else "undergraduate"}
    if m.group("oname") is not None:
        return {"name": m.group("oname").strip(), "kind": "option", "degree": None, "level": None}
    return {"name": m.group("cname").strip(), "kind": "certificate", "degree": None,
            "level": "graduate" if m.group("ckind") == "Graduate Certificate" else "undergraduate"}


def program_on_ecampus(main_text: str) -> int:
    """1 when the Overview's location list names Ecampus."""
    lines = (main_text or "").split("\n")
    for i, line in enumerate(lines):
        if "following locations" in line:
            for nxt in lines[i + 1:i + 8]:
                if not nxt.startswith("- "):
                    break
                if nxt[2:].strip().lower() == "ecampus":
                    return 1
    return 0


def _cells(line: str) -> list[str]:
    cells = [c.strip() for c in line.split("|")]
    while len(cells) < 3:
        cells.append("")
    return cells


def parse_code_cell(cell: str):
    """A course-list code cell -> ([(code, with_code or None), ...], is_or_row), or None when it is not courses.

    'CH 201 & CH 204' -> one entry with with_code; 'ME 320/ECE 356' and 'A or B' -> alternatives.
    """
    c = (cell or "").strip()
    if not _CODE_CELL.match(c):
        return None
    is_or = c.startswith("or ")
    if is_or:
        c = c[3:]
    alts: list[tuple[str, str | None]] = []
    for part in re.split(r"\s+or\s+", c):
        for piece in part.split("/"):
            codes = _CODE_RE.findall(piece)
            if codes:
                alts.append((codes[0], " & ".join(codes[1:]) or None))
    return alts, is_or


def _credit_cell(cell: str) -> float | None:
    c = (cell or "").strip()
    m = re.match(r"^(\d+(?:\.\d+)?)(?:\s*-\s*\d+(?:\.\d+)?)?$", c)
    return float(m.group(1)) if m else None


def _clean_label(text: str) -> str:
    t = strip_markers(text)
    t = re.sub(r"\s+\d(?:\s*,\s*\d)*$", "", t)          # trailing footnote marks: 'Electives 2', '... 1, 2'
    return re.sub(r"\s+", " ", t).strip()


def parse_pick(label: str) -> tuple[int | None, float | None]:
    """'Select two of the following:' -> (2, None); 'Select 16 upper-division CS credits' -> (None, 16.0)."""
    low = (label or "").lower()
    m = re.search(r"\b(?:select|choose|take|complete)\s+(?:at least\s+|a minimum of\s+|any\s+)?"
                  r"(\d+|%s)\b" % "|".join(_NUMBER_WORDS), low)
    if not m:
        return (1, None) if "one of the following" in low else (None, None)
    n = _NUMBER_WORDS.get(m.group(1)) or int(m.group(1))
    rest = low[m.end(1):]
    ic = rest.find("credit")
    ik = min([i for i in (rest.find("course"), rest.find("of the following"), rest.find("series"),
                          rest.find("track"), rest.find("sequence")) if i != -1] or [-1])
    if (ic != -1 and (ik == -1 or ic < ik)) or n > 12:
        return (None, float(n))
    return (n, None)


def _is_select(text: str) -> bool:
    low = text.lower()
    return bool(re.match(r"^(select|choose|complete|take)\b", low)) or (low.endswith(":") and "following" in low)


def _is_note(text: str) -> bool:
    low = text.lower()
    return (len(text) > 110 or text.endswith(".") or " or higher" in low
            or bool(re.match(r"^(any|note|students)\b", low)) or (low.startswith("other ") and len(text) > 40))


def parse_course_lists(main_text: str, default_block: str = "Requirements", titles: dict | None = None) -> dict:
    """Parse every '### Course List' table on a program page.

    Returns {"total_credits": float|None, "requirements": [ {block, seq, kind, label, credits, pick_count,
    courses: [(code, with_code)], plan_year, plan_term} ]}. kind is course | choice | credits.
    `titles` maps course code -> catalog title, used for nicer labels.
    """
    titles = titles or {}
    reqs: list[dict] = []
    total = None
    lines = (main_text or "").split("\n")
    i = 0

    table = 0

    def new_req(block, kind, label, credits, pick=None):
        r = {"block": block or default_block, "seq": len(reqs) + 1, "kind": kind, "label": label,
             "credits": credits, "pick_count": pick, "courses": [], "plan_year": None, "plan_term": None,
             "_title": None, "_table": table}
        reqs.append(r)
        return r

    def add_courses(r, alts):
        for code, with_code in alts:
            if all(code != c[0] for c in r["courses"]):
                r["courses"].append((code, with_code))

    while i < len(lines):
        if not re.match(r"^#{2,6} Course List\s*$", lines[i].strip()):
            i += 1
            continue
        i += 1
        table += 1
        block, pending, open_req, last_req = default_block, None, None, None
        while i < len(lines) and "|" in lines[i]:
            c0, c1, c2 = _cells(lines[i])[:3]
            i += 1
            if c0 == "Code" and c1 == "Title":
                continue
            text = c0 or c1
            if not text:
                continue
            if c0.lower().startswith("total credits") or c0.lower() == "total":
                val = _credit_cell(c2)
                if val is not None:
                    total = val if total is None else max(total, val)
                continue
            parsed = parse_code_cell(c0)
            credits = _credit_cell(c2)
            if parsed:
                alts, is_or = parsed
                if is_or:
                    if last_req is not None:
                        add_courses(last_req, alts)
                    continue
                if credits is None and open_req is not None:
                    add_courses(open_req, alts)          # a list row under 'Select ...'; a sub-header is dropped
                    pending = None
                    last_req = open_req
                    continue
                if pending:
                    block, pending = pending, None
                if credits is None:
                    open_req = new_req(block, "choice", block, None, None)
                    add_courses(open_req, alts)
                    last_req = open_req
                    continue
                open_req = None
                last_req = new_req(block, "course", "", credits)
                last_req["_title"] = _clean_label(c1)
                add_courses(last_req, alts)
                continue
            label = _clean_label(text)
            if credits is not None:
                if pending:
                    block, pending = pending, None
                pick, hint = parse_pick(label)
                open_req = last_req = new_req(block, "credits", label, credits, pick)
            elif _is_select(label):
                if pending:
                    block, pending = pending, None
                pick, hint = parse_pick(label)
                open_req = last_req = new_req(block, "credits", label, hint, pick)
            elif _is_note(label):
                continue
            else:
                pending = label                           # a block header (or a sub-header inside a choice)
    # A table with no courses at all (a "summary of requirements") repeats what the detailed tables say: drop it.
    detailed = {r["_table"] for r in reqs if r["courses"]}
    if detailed:
        reqs = [r for r in reqs if r["_table"] in detailed]
    for seq, r in enumerate(reqs, 1):
        r["seq"] = seq
        del r["_table"]
        if r["kind"] == "credits" and r["courses"]:
            r["kind"] = "choice"
        if r["kind"] == "credits":
            r["pick_count"] = None
        if r["kind"] == "course":
            code, with_code = r["courses"][0]
            if with_code:
                name = title_case(r["_title"]) if r["_title"] else ""
                label = ("%s & %s %s" % (code, with_code, name)).strip()
            else:
                label = ("%s %s" % (code, titles.get(code) or title_case(r["_title"] or ""))).strip()
            others = [c for c, _w in r["courses"][1:]]
            if others:
                label += " (or %s)" % ", ".join(others)
            r["label"] = label
        del r["_title"]
    return {"total_credits": total, "requirements": reqs}


_YEARS = {"First": 1, "Second": 2, "Third": 3, "Fourth": 4, "Fifth": 5}


def parse_plan_grid(main_text: str) -> list[dict]:
    """Parse the first '### Plan of Study Grid' on a page -> [{year, term, codes, text, credits}]."""
    lines = (main_text or "").split("\n")
    rows: list[dict] = []
    for i, line in enumerate(lines):
        if not re.match(r"^#{2,6} Plan of Study Grid\s*$", line.strip()):
            continue
        year, term = None, None
        for raw in lines[i + 1:]:
            if "|" not in raw:
                break
            c0, c1, c2 = _cells(raw)[:3]
            ym = re.match(r"^(First|Second|Third|Fourth|Fifth) Year$", c0)
            if ym:
                year, term = _YEARS[ym.group(1)], None
                continue
            if c0 in ("Fall", "Winter", "Spring", "Summer"):
                term = c0
                continue
            if not c0 or year is None or term is None:
                continue
            codes = _CODE_RE.findall(c0) if re.match(r"^%s" % _CODE, c0) else []
            rows.append({"year": year, "term": term, "codes": codes, "text": _clean_label(c0),
                         "credits": _credit_cell(c2)})
        break
    return rows


def _norm_label(text: str) -> str:
    t = re.sub(r"[^a-z0-9]+", " ", _clean_label(text or "").lower()).strip()
    return re.sub(r"s$", "", t)


def apply_plan(reqs: list[dict], plan_rows: list[dict]) -> None:
    """Fill plan_year / plan_term on the requirements a sample plan mentions (first mention wins)."""
    by_code: dict[str, list[dict]] = {}
    for r in reqs:
        for code, with_code in r["courses"]:
            for c in [code] + (with_code.split(" & ") if with_code else []):
                by_code.setdefault(c, []).append(r)
    for row in plan_rows:
        if not (1 <= row["year"] <= 4) or row["term"] not in TERM_INDEX:
            continue
        target = None
        if row["codes"]:
            cands: list[dict] = []
            for code in row["codes"]:
                for r in by_code.get(code, []):
                    if r["plan_year"] is None and all(r is not x for x in cands):
                        cands.append(r)
            cands.sort(key=lambda r: (r["kind"] != "course", r["seq"]))
            target = cands[0] if cands else None
        else:
            key = _norm_label(row["text"])
            if len(key) >= 6:
                for r in reqs:
                    if r["plan_year"] is None and r["kind"] != "course" and _norm_label(r["label"]).startswith(key):
                        target = r
                        break
                if target is None:
                    for r in reqs:
                        if r["plan_year"] is None and _norm_label(r["block"]) == key:
                            target = r
                            break
        if target is not None:
            target["plan_year"], target["plan_term"] = row["year"], row["term"]


def college_name(segment: str, titles: dict | None = None) -> str | None:
    """'engineering' -> 'College of Engineering' (the catalog's own page title when it is stored)."""
    if not segment:
        return None
    if titles and titles.get(segment):
        return titles[segment]
    special = {"honors": "Honors College", "rotc": "Reserve Officer Training Corps",
               "graduate-education": "Graduate Education"}
    if segment in special:
        return special[segment]
    words = [w if w in _SMALL_WORDS else w.capitalize() for w in segment.split("-")]
    return "College of " + " ".join(words)


# ======================================================================================================
# Reading the stored catalog (read-only) and building the catalog tables in memory
# ======================================================================================================

def _connect_readonly(path: str) -> sqlite3.Connection:
    if not os.path.exists(path):
        raise FileNotFoundError("Source database not found: %s" % path)
    return sqlite3.connect(pathlib.Path(path).resolve().as_uri() + "?mode=ro", uri=True)


def load_source(source_path: str) -> dict:
    """Read what the generator needs from the crawl database. Never writes to it."""
    con = _connect_readonly(source_path)
    try:
        subject_pages, program_pages, college_titles = [], [], {}
        for url, title, text, retrieved in con.execute(
                "SELECT url, title, main_text, retrieved_at FROM pages "
                "WHERE url LIKE ? AND gone_at IS NULL ORDER BY url", (COURSE_URL_PREFIX + "%",)):
            rest = url[len(COURSE_URL_PREFIX):]
            if rest.endswith("/") and rest.count("/") == 1 and text:
                subject_pages.append((url, title, text, retrieved))
        for url, title, text, retrieved in con.execute(
                "SELECT url, title, main_text, retrieved_at FROM pages "
                "WHERE url LIKE ? AND gone_at IS NULL ORDER BY url", (PROGRAM_URL_PREFIX + "%",)):
            rest = url[len(PROGRAM_URL_PREFIX):].strip("/")
            if rest and "/" not in rest and title:
                college_titles[rest] = title.strip()
            program_pages.append((url, title, text or "", retrieved))
        page_urls = [r[0] for r in con.execute("SELECT url FROM pages WHERE gone_at IS NULL ORDER BY url")]
        try:
            doc_urls = [r[0] for r in con.execute("SELECT url FROM documents WHERE gone_at IS NULL ORDER BY url")]
        except sqlite3.Error:
            doc_urls = []
    finally:
        con.close()
    return {"subject_pages": subject_pages, "program_pages": program_pages, "college_titles": college_titles,
            "page_urls": set(page_urls), "doc_urls": set(doc_urls)}


class Catalog:
    """Courses, programs and requirements parsed from the stored catalog pages, with a few lookup tables."""

    def __init__(self):
        self.courses: dict[str, dict] = {}
        self.programs: list[dict] = []
        self.core: dict | None = None
        self.core_by_attr: dict[str, dict] = {}
        self.refs: dict[str, int] = {}
        self.retrieved = None
        self.zero_requirement_programs = 0

    # -- lookups -----------------------------------------------------------------------------------
    def resolve(self, code: str) -> str | None:
        """A course code as the catalog has it now: tries the Z / non-Z form, then 'Equivalent to' lines."""
        if code in self.courses:
            return code
        for alt in (code + "Z", code[:-1] if code.endswith("Z") else None):
            if alt and alt in self.courses:
                return alt
        subject = code.split(" ")[0]
        for c in sorted(self.courses):
            course = self.courses[c]
            if course["subject"] == subject and not course["honors"] and course["equivalent_text"]:
                if code in [x.strip() for x in course["equivalent_text"].split(",")]:
                    return c
        return None

    def find_program(self, name: str, kind: str = "major", level: str = "undergraduate") -> dict | None:
        pool = [p for p in self.programs if p["kind"] == kind and p["level"] == level]
        for p in pool:
            if p["name"].lower() == name.lower():
                return p
        for p in pool:
            if p["name"].lower().startswith(name.lower()):
                return p
        return None

    def core_req(self, text: str) -> dict | None:
        """The Core Education category a plan line such as 'Arts & Humanities General' means."""
        if not self.core:
            return None

        def norm(s):
            s = re.sub(r"\bcore ed(ucation)?\b[:\- ]*", " ", s.lower())
            s = s.replace("&", " and ").replace("arts", "art").replace("foundations", " ")
            return re.sub(r"[^a-z0-9]+", " ", s).strip()
        key = norm(text)
        if not key:
            return None
        for r in self.core["reqs"]:
            if norm(r["label"]) == key:
                return r
        for r in self.core["reqs"]:
            if norm(r["label"]).startswith(key) or key.startswith(norm(r["label"])):
                return r
        return None


def is_independent(course: dict) -> bool:
    """Research, thesis, internship, reading-and-conference style courses: one 'to be announced' section."""
    spread = course["credits_max"] - course["credits_min"]
    digits = re.match(r"\d+", course["number"])
    num = int(digits.group(0)) if digits else 0
    keyword = re.search(r"RESEARCH|THESIS|DISSERTATION|INTERNSHIP|PRACTICUM|READING AND CONFERENCE|INDEPENDENT STUD"
                        r"|PROJECTS?$|WORKSHOP|SPECIAL TOPICS|SELECTED TOPICS|ED ABROAD|EXTERNSHIP|CLERKSHIP"
                        r"|SPECIAL STUDIES|SPECIAL PROBLEMS", course.get("raw_title", "").upper())
    if course["level"] == 0:
        return True
    if spread >= 2 and (course["credits_max"] >= 6 or keyword):
        return True
    if course["level"] >= 400 and num % 100 in (1, 3, 5, 6, 10, 99):
        return True
    return False


def build_catalog(src: dict, log=print) -> Catalog:
    cat = Catalog()
    retrieved_dates = []

    # ---- courses ----
    for url, _title, text, retrieved in src["subject_pages"]:
        page = parse_subject_page(text)
        day = (retrieved or "")[:10] or None
        used = False
        for c in page["courses"]:
            if c["code"] in cat.courses:
                continue                               # the same code on a second page: keep the first
            c["subject_name"] = page["subject_name"] if c["subject"] == page["subject"] else None
            c["catalog_url"] = url
            c["retrieved_at"] = day
            c["independent"] = is_independent(c)
            cat.courses[c["code"]] = c
            used = True
        if used and day:
            retrieved_dates.append(day)
    titles = {code: c["title"] for code, c in cat.courses.items()}

    # ---- programs ----
    by_url: dict[str, dict] = {}
    next_req_id = 1
    for url, title, text, retrieved in src["program_pages"]:
        info = parse_program_title(title)
        if not info:
            continue
        rest = url[len(PROGRAM_URL_PREFIX):].strip("/")
        segment = rest.split("/")[0] if rest else ""
        parent = by_url.get(url.rstrip("/").rsplit("/", 1)[0] + "/") if info["kind"] == "option" else None
        level = info["level"] or (parent["level"] if parent else "undergraduate")
        default_block = {"major": "Major requirements", "minor": "Minor requirements",
                         "option": "Option requirements", "certificate": "Certificate requirements"}[info["kind"]]
        parsed = parse_course_lists(text, default_block, titles)
        plan = parse_plan_grid(text)
        apply_plan(parsed["requirements"], plan)
        for r in parsed["requirements"]:
            r["id"] = next_req_id
            next_req_id += 1
        program = {"id": len(cat.programs) + 1, "name": info["name"], "kind": info["kind"], "degree": info["degree"],
                   "level": level, "college": college_name(segment, src["college_titles"]),
                   "parent_id": parent["id"] if parent else None, "total_credits": parsed["total_credits"],
                   "ecampus": program_on_ecampus(text), "catalog_url": url, "reqs": parsed["requirements"],
                   "plan": plan}
        cat.programs.append(program)
        by_url[url] = program
        if not parsed["requirements"]:
            cat.zero_requirement_programs += 1
        if (retrieved or "")[:10]:
            retrieved_dates.append(retrieved[:10])

    # ---- how many programs name each course (drives how many sections it gets) ----
    for p in cat.programs:
        seen = set()
        for r in p["reqs"]:
            for code, with_code in r["courses"]:
                seen.add(code)
                if with_code:
                    seen.update(with_code.split(" & "))
        for code in sorted(seen):
            cat.refs[code] = cat.refs.get(code, 0) + 1

    # ---- the synthetic Core Education program ----
    categories: dict[str, str] = {}
    members: dict[str, list[str]] = {}
    for code in sorted(cat.courses):
        for attr_code, attr_name in cat.courses[code]["attrs"]:
            if attr_name.startswith(CORE_PREFIX):
                categories.setdefault(attr_code, attr_name[len(CORE_PREFIX):].strip())
                members.setdefault(attr_code, []).append(code)
    core = {"id": len(cat.programs) + 1, "name": "Core Education", "kind": "core", "degree": None,
            "level": "undergraduate", "college": None, "parent_id": None, "total_credits": None, "ecampus": 0,
            "catalog_url": CORE_URL, "reqs": [], "plan": []}
    for seq, attr_code in enumerate(sorted(categories), 1):
        r = {"id": next_req_id, "block": "Core Education", "seq": seq, "kind": "choice",
             "label": categories[attr_code], "credits": None, "pick_count": 1,
             "courses": [(code, None) for code in members[attr_code]], "plan_year": None, "plan_term": None,
             "attr": attr_code}
        next_req_id += 1
        core["reqs"].append(r)
        cat.core_by_attr[attr_code] = r
    cat.programs.append(core)
    cat.core = core
    cat.retrieved = max(retrieved_dates) if retrieved_dates else None
    log("catalog: %d courses, %d programs (%d with no parsed requirements), %d requirements"
        % (len(cat.courses), len(cat.programs), cat.zero_requirement_programs,
           sum(len(p["reqs"]) for p in cat.programs)))
    return cat


# ======================================================================================================
# Invented names, buildings and rooms
# ======================================================================================================

FIRST_NAMES = ["Willow", "Birch", "Aspen", "Cedar", "Rowan", "Hazel", "Linden", "Sage", "Hollis", "Laurel",
               "Alder", "Maple", "Olive", "Ash", "Fern", "Reed", "Brooke", "River", "Forrest", "Heath",
               "Ivy", "Jasper", "Flint", "Clay", "Dale", "Glen", "Wren", "Robin", "Lark", "Finch",
               "Sam", "Alex", "Jordan", "Morgan", "Casey", "Riley", "Avery", "Quinn", "Taylor", "Jamie",
               "Nico", "Mina", "Theo", "Lena", "Omar", "Anika", "Kenji", "Marisol", "Anders", "Imani",
               "Soren", "Tala", "Idris", "Noor"]
LAST_NAMES = ["Lodgepole", "Paddletail", "Streamwright", "Gnawsworth", "Dambuilder", "Twigsby", "Barkwell",
              "Mossbank", "Fernhollow", "Riffleton", "Chipwood", "Sawdustin", "Logjammer", "Burlwood",
              "Kindlewick", "Pondsworth", "Timbertooth", "Whittlebrook", "Splashworth", "Mudlodge",
              "Willowgnaw", "Aldernibble", "Cedarchomp", "Reedwhistle", "Brooktumble", "Pebbleflume",
              "Driftlog", "Saplington", "Knotwhittle", "Planewright", "Chiselbrook", "Dovetailer", "Lathewick",
              "Mortisewood", "Tenonby", "Sprucepaddle", "Hemlockfin", "Rapidsnout", "Eddywhisker",
              "Currentail", "Lodgewright", "Dampaddle", "Twigweaver", "Stickstacker", "Barknibbler",
              "Pondkeeper", "Slapwater", "Gravelbar", "Oxbowman", "Flumewright", "Sluicewood", "Canopyfall",
              "Understory", "Rootwad", "Snagwood", "Cobblestream", "Trickleby", "Burrowbank", "Gnawlog",
              "Woodchipper", "Shavingsworth", "Sandpaperly", "Routerby", "Jointerwick"]
TITLES = ["Dr.", "Dr.", "Dr.", "Prof.", "Prof.", ""]

BUILDINGS = ["Alder Hall", "Riverbend Science Center", "Tamarack Hall", "Lodgepole Hall", "Millrace Engineering Center",
             "Cottonwood Hall", "Driftwood Laboratory", "Headwaters Hall", "Sawtooth Center", "Fernhollow Hall",
             "Larchwood Hall", "Paddletail Pavilion", "Sprucewood Hall", "Confluence Center", "Timberline Hall",
             "Gravelbar Hall", "Mossy Bank Hall", "Oxbow Hall", "Kingfisher Hall", "Blue Heron Hall",
             "Osprey Nest Hall", "Dipper Creek Hall", "Steelhead Science Hall", "Coho Run Hall", "Trillium Hall",
             "Camas Meadow Hall", "Salal Hall", "Huckleberry Hall", "Snowmelt Hall", "Eddyline Hall",
             "Riffle Hall", "Backwater Hall", "Logjam Laboratory", "Dovetail Design Studio", "Whittle Workshop",
             "Chisel Hall", "Sawdust Studio", "Grain and Knot Hall", "Lathe Hall", "Burlwood Hall",
             "Canopy Hall", "Understory Hall", "Old Growth Auditorium", "Beaver Lodge Learning Center"]
CASCADES_BUILDINGS = ["Pumice Flat Hall", "Lava Tube Hall", "Ponderosa Ridge Hall"]
ROOM_TIERS = [28, 48, 80, 150, 320]                    # the largest room in each size class
DAYS = "MTWRF"


def make_instructors(rng: random.Random, count: int = 520) -> list[str]:
    combos = [(f, l) for f in FIRST_NAMES for l in LAST_NAMES]
    rng.shuffle(combos)
    names = []
    for first, last in combos[:count]:
        title = rng.choice(TITLES)
        names.append(("%s %s %s" % (title, first, last)).strip())
    return names


def make_rooms(rng: random.Random, buildings: list[str], per_tier=(16, 16, 8, 3, 2)) -> list[tuple]:
    """[(building, room, capacity)] for invented buildings: mostly small rooms, a few big halls each."""
    rooms = []
    lows = [16, 30, 50, 90, 180]
    for b in buildings:
        used = set()
        for tier, n in enumerate(per_tier):
            for _ in range(n):
                cap = rng.randint(lows[tier], ROOM_TIERS[tier])
                floor = rng.randint(1, 2) if tier >= 3 else rng.randint(1, 4)
                while True:
                    label = "%d%02d" % (floor, rng.randint(1, 40))
                    if label not in used:
                        used.add(label)
                        break
                rooms.append((b, label, cap))
    return rooms


class RoomBook:
    """Which rooms are free when. One bit per five minutes of a weekday, per room."""

    def __init__(self, rooms: list[tuple]):
        self.rooms = rooms
        self.by_tier: list[list[int]] = [[] for _ in ROOM_TIERS]
        for i, (_b, _r, cap) in enumerate(rooms):
            for t, top in enumerate(ROOM_TIERS):
                if cap <= top:
                    self.by_tier[t].append(i)
                    break
        self.busy: dict[tuple[int, int], int] = {}

    def reset(self):
        self.busy = {}

    def _free(self, ri: int, days: str, mask: int) -> bool:
        return all((self.busy.get((ri, DAYS.index(d)), 0) & mask) == 0 for d in days)

    def _book(self, ri: int, days: str, mask: int):
        for d in days:
            key = (ri, DAYS.index(d))
            self.busy[key] = self.busy.get(key, 0) | mask

    def find(self, rng: random.Random, days: str, start: int, end: int, seats: int):
        """Book and return (building, room) for a free room that fits, or None."""
        mask = ((1 << max(1, (end - start + 4) // 5)) - 1) << (start // 5)
        first = next((t for t, top in enumerate(ROOM_TIERS) if seats <= top), len(ROOM_TIERS) - 1)
        for t in range(first, len(ROOM_TIERS)):
            pool = self.by_tier[t]
            if not pool:
                continue
            for _ in range(10):
                ri = pool[rng.randrange(len(pool))]
                if self.rooms[ri][2] >= seats and self._free(ri, days, mask):
                    self._book(ri, days, mask)
                    return self.rooms[ri][0], self.rooms[ri][1]
        for t in range(first, len(ROOM_TIERS)):
            for ri in self.by_tier[t]:
                if self.rooms[ri][2] >= seats and self._free(ri, days, mask):
                    self._book(ri, days, mask)
                    return self.rooms[ri][0], self.rooms[ri][1]
        return None


# ======================================================================================================
# The invented schedule
# ======================================================================================================

# Subjects whose 100-300 level courses of 4+ credits get a lecture plus linked recitations or labs.
LINKED_SUBJECTS = {"MTH", "CH", "PH", "BI", "ST", "CS", "ENGR", "ECE", "ME", "CE", "CHE", "BB", "MB", "Z", "BOT",
                   "ECON", "BIOE", "ENVE", "IE", "MATS", "NSE", "DS", "GEO", "ATS", "OC", "FW", "HORT", "CROP",
                   "SOIL", "ANS", "FST", "NUTR", "KIN", "BEE", "ROB", "ESE", "MFGE", "CCE", "CEM", "WSE", "FE",
                   "FOR", "ENSC", "GEOG", "RNG", "ENT", "TOX"}
LAB_SUBJECTS = {"CH", "PH", "BI", "BB", "MB", "Z", "BOT", "GEO", "ATS", "OC", "FW", "HORT", "CROP", "SOIL", "ANS",
                "FST", "NUTR", "KIN", "ENT", "BEE", "MATS", "ECE", "RNG", "TOX", "WSE", "FOR", "FE"}
SMALL_CLASS_SUBJECTS = {"WR", "COMM", "SPAN", "FR", "GER", "ITAL", "JPN", "CHN", "KOR", "ARAB", "ASL", "RUS", "ENG",
                        "LING", "WLC", "IEPA", "IEPG", "IEPH", "ALS"}
STUDIO_SUBJECTS = {"ART", "DSGN", "GD", "TA", "DANC"}
ENGINEERING_SUBJECTS = {"ENGR", "CS", "ECE", "ME", "CE", "CHE", "BIOE", "ENVE", "IE", "MATS", "NSE", "ROB", "ESE",
                        "MFGE", "CCE", "CEM", "AAE", "AI", "MIME", "ESC"}
BUSINESS_SUBJECTS = {"BA", "ACTG", "FIN", "BANA", "MGMT", "MRKT", "SCLM", "HM", "BIS", "DSGN"}
PROFESSIONAL_SUBJECTS = {"PHAR", "VMB", "VMC"}

GRADE_NORMAL = "Normal grading (A-F)"
GRADE_PASS = "Pass/No pass"

# (days, start minute, minutes). Standard patterns with weights; early and late slots are thinner on purpose.
MWF_50 = [(480, 3), (540, 9), (600, 12), (660, 12), (720, 11), (780, 11), (840, 10), (900, 8), (960, 5), (1020, 2)]
TR_80 = [(510, 3), (600, 12), (720, 12), (840, 11), (960, 7), (1080, 3)]
MW_80 = [(510, 2), (840, 5), (960, 5), (1050, 3)]
EVENING = [(1020, 4), (1080, 6), (1140, 2)]
WANTED = {
    "early": [("MWF", 480, 50), ("MWF", 540, 50), ("TR", 510, 80)],                       # starts before 10 am
    "midday": [("MWF", 720, 50), ("MWF", 780, 50), ("TR", 720, 80)],
    "late": [("MWF", 960, 50), ("TR", 960, 80), ("MW", 960, 80)],                        # 4 pm
    "early_tr": [("TR", 510, 80)],                                                       # mornings, no Friday
    "late_no_fri": [("TR", 960, 80), ("MW", 960, 80)],
    "morning": [("MWF", 540, 50), ("MWF", 600, 50), ("MWF", 660, 50)],
    "evening_class": [("MW", 1050, 80), ("TR", 1080, 80)],
    "evening": [("MW", 1050, 80), ("TR", 1080, 80), ("T", 1080, 170), ("W", 1080, 170), ("R", 1020, 170),
                ("M", 1140, 110)],                                                        # 5 pm or later
}


def _weighted(rng: random.Random, pairs):
    total = sum(w for _v, w in pairs)
    x = rng.random() * total
    for v, w in pairs:
        x -= w
        if x < 0:
            return v
    return pairs[-1][0]


class Schedule:
    """Generates sections, meetings and lecture-to-recitation links for the three demo terms."""

    def __init__(self, cat: Catalog, rng: random.Random, force: dict, log=print):
        self.cat, self.rng, self.force, self.log = cat, rng, force, log
        self.sections: list[dict] = []
        self.meetings: list[tuple] = []
        self.links: list[tuple] = []
        self.by_course: dict[tuple, list[dict]] = {}
        self.meet_by_crn: dict[int, list[tuple]] = {}
        self.linked_of: dict[int, list[dict]] = {}
        self.crns = list(range(10000, 100000))
        rng.shuffle(self.crns)
        self.rooms = RoomBook(make_rooms(rng, BUILDINGS))
        self.cascades_rooms = RoomBook(make_rooms(rng, CASCADES_BUILDINGS, per_tier=(10, 10, 4, 1, 0)))
        self.term_dates = {t[0]: (t[3], t[4]) for t in DEMO_TERMS}
        self.demo_courses: dict[str, str] = {}
        for wanted in DEMO_COURSES:
            code = cat.resolve(wanted)
            if code:
                self.demo_courses[code] = wanted
        self.full_course = cat.resolve(FULL_LECTURE_COURSE)
        self.no_room = 0

        names = make_instructors(rng)
        subjects: dict[str, int] = {}
        for code in sorted(cat.courses):
            s = cat.courses[code]["subject"]
            subjects[s] = subjects.get(s, 0) + 1
        self.pool: dict[str, list[str]] = {}
        pos = 0
        for s in sorted(subjects):
            size = max(3, min(14, subjects[s] // 8 + 2))
            self.pool[s] = [names[(pos + k) % len(names)] for k in range(size)]
            pos += size
        self.instructor_names = names
        self.profiles = {code: self._profile(cat.courses[code]) for code in sorted(cat.courses)}

    # ---- per-course decisions (made once, so a course looks the same from term to term) ----------
    def _profile(self, c: dict) -> dict:
        rng = self.rng
        code, level, subj, refs = c["code"], c["level"], c["subject"], self.cat.refs.get(c["code"], 0)
        g = code in self.demo_courses
        title = c.get("raw_title", "").upper()
        p = {"g": g, "refs": refs, "kind": "class", "linked": False, "lab": subj in LAB_SUBJECTS,
             "stype": "Lecture", "n": 1}
        if c["independent"] and not g:
            p["kind"] = "indep"
            p["stype"] = "Seminar" if re.search(r"SEMINAR|WORKSHOP|TOPICS", title) else "Independent Study"
            p["terms"] = [t for t in SCHEDULE_TERMS if rng.random() < 0.9]
            return p
        if subj == "PAC":
            p["stype"] = "Activity"
        elif subj in STUDIO_SUBJECTS and re.search(r"STUDIO|DRAWING|PAINTING|CERAMIC|PRINTMAKING|SCULPTURE|"
                                                    r"PHOTOGRAPH|TECHNIQUE|WORKSHOP|DESIGN I", title):
            p["stype"] = "Studio"
        elif "SEMINAR" in title or (level >= 500 and c["credits_max"] <= 2):
            p["stype"] = "Seminar"
        p["linked"] = g or (p["stype"] == "Lecture" and not c["honors"] and c["credits_min"] >= 4 and (
            (100 <= level <= 300 and (subj in LINKED_SUBJECTS or (subj == "PSY" and level == 200)))
            or (100 <= level <= 200 and refs >= 2 and subj not in SMALL_CLASS_SUBJECTS)
            or (level == 400 and subj in LAB_SUBJECTS and refs >= 1)))
        root = math.sqrt(refs)
        if c["honors"] and not g:
            n = 1
        elif level < 300:
            if p["linked"]:
                n = 1 + min(7, int(root * 0.9)) + (1 if rng.random() < 0.5 else 0)
            else:
                n = 2 + min(7, int(root)) + (1 if rng.random() < 0.5 else 0)
            if subj in SMALL_CLASS_SUBJECTS:
                n = min(14, n * 2)
            if p["stype"] == "Activity":
                n = rng.randint(1, 4)
        elif level < 500:
            n = 1 + min(4, int(root)) + (1 if rng.random() < 0.5 else 0)
        else:
            n = 1 + (1 if rng.random() < 0.4 else 0)
        if p["linked"]:
            n = min(n, 9)
        if g:
            n = max(n, 4)
        p["n"] = n
        if g:
            terms = list(SCHEDULE_TERMS)
        elif level < 300:
            terms = [t for t in SCHEDULE_TERMS if rng.random() < 0.9] or [rng.choice(SCHEDULE_TERMS)]
        else:
            x = rng.random()
            if level < 500:
                k = 3 if x < (0.5 if refs >= 5 else 0.25) else (2 if x < 0.88 else 1)
            else:
                k = 2 if x < 0.75 else 1
            chosen = rng.sample(SCHEDULE_TERMS, k)
            terms = [t for t in SCHEDULE_TERMS if t in chosen]
        p["terms"] = terms
        return p

    # ---- small helpers ---------------------------------------------------------------------------
    def _instructor(self, subject: str):
        if self.rng.random() < 0.06:
            return None
        return self.rng.choice(self.pool[subject])

    def _enroll(self, term: str, seats: int, full: bool | None = None, keep_open: bool = False):
        """(seats_taken, wait_cap, wait_count) with the term's fill pattern."""
        rng = self.rng
        lo, hi, p_full = {"202701": (0.30, 0.98, 0.15), "202702": (0.10, 0.70, 0.05)}.get(term, (0.03, 0.45, 0.02))
        if full is None:
            full = (not keep_open) and rng.random() < p_full
        if full:
            wait_cap = rng.choice([0, 5, 10, 10, 15, 20])
            return seats, wait_cap, (rng.randint(0, wait_cap) if wait_cap else 0)
        taken = min(seats - 1, max(0, int(round(seats * rng.uniform(lo, hi)))))
        wait_cap = rng.choice([5, 10, 15]) if rng.random() < 0.3 else 0
        return taken, wait_cap, 0

    def _fee(self, c: dict, p: dict):
        rng = self.rng
        if p["stype"] == "Activity":
            return float(rng.choice([25, 35, 45, 60, 75, 95])) if rng.random() < 0.9 else None
        if p["stype"] == "Studio" or c["subject"] in STUDIO_SUBJECTS:
            return float(rng.choice([45, 60, 75, 90, 120, 150, 180])) if rng.random() < 0.6 else None
        if p["linked"] and p["lab"]:
            return float(rng.choice([15, 20, 25, 30, 35, 40, 45, 50, 60, 75])) if rng.random() < 0.55 else None
        return float(rng.choice([15, 20, 25, 30, 40, 60])) if rng.random() < 0.02 else None

    def _grade_mode(self, p: dict) -> str:
        chance = {"Activity": 0.35, "Seminar": 0.45, "Independent Study": 0.5}.get(p["stype"], 0.0)
        return GRADE_PASS if self.rng.random() < chance else GRADE_NORMAL

    def _restriction(self, c: dict, campus: str):
        rng = self.rng
        if c["honors"]:
            return "Honors College students only"
        if campus == "INTO OSU":
            return "INTO OSU students only"
        if c["subject"] in PROFESSIONAL_SUBJECTS:
            return "Students admitted to the professional program only"
        if c["level"] >= 500:
            return "Graduate students only" if rng.random() < 0.10 else None
        if c["level"] >= 300 and c["subject"] in ENGINEERING_SUBJECTS:
            return "Majors in the College of Engineering only" if rng.random() < 0.12 else None
        if c["level"] >= 300 and c["subject"] in BUSINESS_SUBJECTS:
            return "Majors in the College of Business only" if rng.random() < 0.15 else None
        return None

    def _seats(self, c: dict, p: dict) -> int:
        rng, level, refs = self.rng, c["level"], p["refs"]
        if p["stype"] == "Activity":
            return rng.randint(20, 35)
        if p["stype"] == "Studio":
            return rng.randint(16, 22)
        if p["stype"] == "Seminar":
            return rng.randint(8, 20)
        if c["honors"]:
            return rng.randint(12, 24)
        if c["subject"] in SMALL_CLASS_SUBJECTS:
            return rng.randint(20, 30) if level < 300 else rng.randint(15, 28)
        if level < 300:
            if refs >= 20:
                return rng.randint(80, 150)
            return rng.randint(45, 120) if refs >= 5 else rng.randint(30, 70)
        if level < 500:
            return rng.randint(25, 45) if refs >= 8 else rng.randint(12, 45)
        return rng.randint(12, 35)

    def _pattern(self, c: dict, p: dict, want: str | None):
        rng = self.rng
        if want:
            return rng.choice(WANTED[want])
        credits = c["credits_min"] if c["credits_min"] > 0 else c["credits_max"]
        if p["stype"] == "Studio":
            return rng.choice(["MW", "TR"]), rng.choice([480, 600, 720, 840, 960]), 110
        if p["stype"] == "Activity" or credits <= 1:
            days = rng.choice(["MW", "TR", "M", "T", "W", "R", "F"]) if p["stype"] == "Activity" else rng.choice(DAYS)
            return days, _weighted(rng, MWF_50), 50
        if credits <= 2:
            if rng.random() < 0.5:
                return rng.choice(["TR", "MW"]), _weighted(rng, MWF_50), 50
            return rng.choice(DAYS), rng.choice([480, 600, 720, 840, 960, 1080]), 110
        if credits >= 5:
            return rng.choice(["MTWF", "MTWRF", "MTWR"]), _weighted(rng, MWF_50), 50
        x = rng.random()
        if x < 0.45:
            return "MWF", _weighted(rng, MWF_50), 50
        if x < 0.82:
            return "TR", _weighted(rng, TR_80), 80
        if x < 0.92:
            return "MW", _weighted(rng, MW_80), 80
        return rng.choice("MTWR"), _weighted(rng, EVENING), 170

    def _place(self, book: RoomBook, c: dict, p: dict, want: str | None, seats: int):
        """(days, start, end, building, room). Tries other times when every fitting room is taken."""
        days, start, minutes = None, None, None
        for _ in range(12):
            days, start, minutes = self._pattern(c, p, want)
            room = book.find(self.rng, days, start, start + minutes, seats)
            if room:
                return days, start, start + minutes, room[0], room[1]
        self.no_room += 1
        return days, start, start + minutes, None, None

    def _add(self, term, c, number, stype, method, campus, credits, grade_mode, seats, taken, wait_cap, wait_count,
             fee, restrictions, primary, meetings, instructor="?"):
        if not self.crns:
            raise RuntimeError("Ran out of five-digit CRNs: too many sections were generated.")
        crn = self.crns.pop()
        sec = {"crn": crn, "term_code": term, "course_code": c["code"], "section": "%03d" % number,
               "schedule_type": stype, "method": method, "campus": campus, "session": "Full term",
               "credits": float(credits), "grade_mode": grade_mode,
               "instructor": self._instructor(c["subject"]) if instructor == "?" else instructor,
               "seats_total": seats, "seats_taken": taken, "wait_cap": wait_cap, "wait_count": wait_count,
               "fee": fee, "restrictions": restrictions, "is_primary": 1 if primary else 0}
        self.sections.append(sec)
        self.by_course.setdefault((term, c["code"]), []).append(sec)
        start_date, end_date = self.term_dates[term]
        rows = []
        for days, start, end, building, room in meetings:
            row = (crn, days, start, end, start_date, end_date, building, room)
            self.meetings.append(row)
            rows.append(row)
        self.meet_by_crn[crn] = rows
        return sec

    # ---- generators ------------------------------------------------------------------------------
    def _credits(self, c: dict) -> float:
        return c["credits_min"] if c["credits_min"] > 0 else c["credits_max"]

    def _independent(self, c: dict, p: dict, term: str):
        rng = self.rng
        seats = rng.randint(5, 30)
        taken = rng.randint(0, max(1, seats * 2 // 3))
        self._add(term, c, 1, p["stype"], "In person", "Corvallis", self._credits(c), self._grade_mode(p), seats,
                  taken, 0, 0, None, self._restriction(c, "Corvallis"), True, [(None, None, None, None, None)])
        if c["ecampus"] and rng.random() < 0.8:
            seats = rng.randint(10, 40)
            self._add(term, c, 400, "Online", "Online", "Ecampus", self._credits(c), self._grade_mode(p), seats,
                      rng.randint(0, seats * 2 // 3), 0, 0, None, self._restriction(c, "Ecampus"), True,
                      [(None, None, None, None, None)])

    def _online(self, c: dict, p: dict, term: str, number: int, keep_open: bool):
        rng = self.rng
        seats = int(rng.triangular(40, 120, 75))
        taken, wait_cap, wait_count = self._enroll(term, seats, keep_open=keep_open)
        self._add(term, c, number, "Online", "Online", "Ecampus", self._credits(c), GRADE_NORMAL, seats, taken,
                  wait_cap, wait_count, None, self._restriction(c, "Ecampus"), True,
                  [(None, None, None, None, None)])

    def _linked_times(self, lecture, minutes: int, count: int, spread: bool = False) -> list[tuple]:
        """Distinct (day, start) choices for recitations or labs that stay clear of the lecture itself.

        With `spread`, the first choice is in the lecture's own part of the day and not on a Friday, and the
        second is in a different part, so "mornings only" or "evenings only" can find a full pairing.
        """
        rng = self.rng
        l_days, l_start, l_end = lecture[0] or "", lecture[1] or 0, lecture[2] or 0
        step = 60 if minutes <= 50 else (120 if minutes <= 110 else 180)
        cands = []
        for d in DAYS:
            for start in range(480, 1081, 60):
                if start + minutes > 1200:
                    continue
                if d in l_days and start < l_end and l_start < start + minutes:
                    continue
                cands.append((d, start))
        if not cands:
            return []
        picks: list[tuple] = []

        def part(start):
            return 0 if start < 720 else (1 if start < 1020 else 2)
        if spread:
            same = [x for x in cands if part(x[1]) == part(l_start) and x[0] != "F"]
            if same:
                picks.append(rng.choice(same))
            other = [x for x in cands if part(x[1]) != part(l_start) and part(x[1]) < 2 and x[0] != "F"]
            if other:
                picks.append(rng.choice(other))
        elif rng.random() < 0.5:                            # run through one afternoon, then the next day
            d0 = rng.randrange(5)
            first = rng.choice([720, 780, 840])
            for k in range(5):
                d = DAYS[(d0 + k) % 5]
                for start in range(first, 1081, step):
                    if (d, start) in cands and (d, start) not in picks and len(picks) < count:
                        picks.append((d, start))
        rest = [x for x in cands if x not in picks]
        rng.shuffle(rest)
        rest.sort(key=lambda x: (x[1] >= 1020) + (x[1] >= 1080))      # 5 pm and later only when the day is full
        return picks + rest

    def _lecture(self, c: dict, p: dict, term: str, i: int, want, campus: str, full=None, keep_open=False):
        rng = self.rng
        book = self.cascades_rooms if campus == "Cascades" else self.rooms
        base = {"Corvallis": 0, "Cascades": 500, "INTO OSU": 600}[campus]
        linked = p["linked"] and campus != "INTO OSU"
        credits = self._credits(c)
        restriction = self._restriction(c, campus)
        fee = self._fee(c, p)
        grade_mode = self._grade_mode(p)
        if not linked:
            seats = self._seats(c, p)
            if campus == "Cascades":
                seats = rng.randint(20, 40)
            elif campus == "INTO OSU":
                seats = rng.randint(15, 25)
            days, start, end, building, room = self._place(book, c, p, want, seats)
            meetings = [(days, start, end, building, room)]
            method = "In person"
            if campus == "Corvallis" and p["stype"] == "Lecture" and len(days) > 1 and rng.random() < 0.015:
                method = "Hybrid"                           # one day in the room, the rest online
                meetings = [(days[0], start, end, building, room), (None, None, None, None, None)]
            taken, wait_cap, wait_count = self._enroll(term, seats, full=full, keep_open=keep_open)
            self._add(term, c, base + i + 1, p["stype"], method, campus, credits, grade_mode, seats, taken, wait_cap,
                      wait_count, fee, restriction, True, meetings)
            return
        # lecture + linked recitations or labs
        is_lab = p["lab"]
        if campus == "Cascades":
            n_link, size = rng.choice([1, 2]), rng.choice([16, 18, 20, 24])
        else:
            n_link = rng.randint(4, 8) if p["refs"] >= 15 else (rng.randint(4, 6) if p["refs"] >= 4
                                                                  else rng.randint(3, 6))
            size = rng.choice([15, 16, 18, 20, 22, 24]) if is_lab else rng.choice([20, 24, 25, 28, 30, 32, 35])
        seats = n_link * size
        lecture_meeting = self._place(book, c, p, want, seats)
        minutes = rng.choice([110, 110, 170]) if is_lab else rng.choice([50, 50, 110])
        times = self._linked_times(lecture_meeting, minutes, n_link, spread=p["g"])
        if full is None:
            full = (not keep_open) and rng.random() < {"202701": 0.15, "202702": 0.05}.get(term, 0.02)
        lecturer = self._instructor(c["subject"])
        planned = []
        ti = 0
        for j in range(n_link):
            placed = None
            while ti < len(times) and placed is None:
                d, start = times[ti]
                ti += 1
                room = book.find(rng, d, start, start + minutes, size)
                if room:
                    placed = (d, start, start + minutes, room[0], room[1])
            if placed is None:
                d, start = times[j % len(times)] if times else ("F", 1080)
                placed = (d, start, start + minutes, None, None)
                self.no_room += 1
            if full:
                taken, wait_cap, wait_count = self._enroll(term, size, full=True)
            else:
                taken, wait_cap, wait_count = self._enroll(term, size, keep_open=keep_open or rng.random() < 0.5)
            planned.append((placed, taken, wait_cap, wait_count))
        if not full and all(t >= size for _m, t, _c, _w in planned):
            m, _t, _c, _w = planned[0]
            planned[0] = (m, size - 1 - rng.randint(0, size // 3), 0, 0)   # a lecture with room has an open pairing
        taken = sum(t for _m, t, _c, _w in planned)
        if full:
            wait_cap = rng.choice([10, 15, 20]) if c["code"] == self.full_course else rng.choice([0, 5, 10, 15, 20])
            wait_count = rng.randint(max(1, wait_cap // 3), wait_cap) if wait_cap else 0
        else:
            wait_cap, wait_count = (rng.choice([5, 10, 15]) if rng.random() < 0.3 else 0), 0
        lec = self._add(term, c, base + i + 1, "Lecture", "In person", campus, credits, grade_mode, seats, taken,
                        wait_cap, wait_count, fee, restriction, True, [lecture_meeting], instructor=lecturer)
        self.linked_of[lec["crn"]] = []
        for j, (meeting, ltaken, lcap, lcount) in enumerate(planned):
            sub = self._add(term, c, base + (i + 1) * 10 + j, "Laboratory" if is_lab else "Recitation", "In person",
                            campus, 0, grade_mode, size, ltaken, lcap, lcount, None, restriction, False, [meeting])
            self.links.append((lec["crn"], sub["crn"]))
            self.linked_of[lec["crn"]].append(sub)

    def _class(self, c: dict, p: dict, term: str):
        rng = self.rng
        code = c["code"]
        forced = self.force.get((term, code), ())
        g = p["g"]
        safe = term == REG_TERM and (g or bool(forced))     # the demo needs open seats here in Winter
        special = term == REG_TERM and code == self.full_course
        n = p["n"]
        for i in range(n):
            want = None
            if g:                                           # a spread the class finder can always work with
                want = ("early_tr", "midday", "late_no_fri", "evening_class", "morning")[i] if i < 5 else None
            elif n >= 4:
                want = "early" if i == 0 else ("evening" if i == 1 else None)
            if special:
                self._lecture(c, p, term, i, want, "Corvallis", full=(i == 1), keep_open=(i != 1))
            elif safe and (g or i == 0):
                self._lecture(c, p, term, i, want, "Corvallis", full=False, keep_open=True)
            else:
                self._lecture(c, p, term, i, want, "Corvallis")
        if c["ecampus"] and (g or "Ecampus" in forced or rng.random() < 0.9):
            count = 1 + sum(1 for edge in (3, 10, 30, 60) if p["refs"] >= edge)
            for j in range(count):
                self._online(c, p, term, 400 + j, keep_open=safe or special)
        if c["level"] < 300 and not c["honors"] and p["stype"] == "Lecture" and rng.random() < 0.04:
            self._lecture(c, p, term, 0, None, "Cascades", full=False if (safe or special) else None,
                          keep_open=safe or special)
        if c["level"] == 100 and not c["honors"] and p["stype"] == "Lecture" and rng.random() < 0.015:
            self._lecture(c, p, term, 0, None, "INTO OSU", full=False if (safe or special) else None,
                          keep_open=safe or special)

    def generate(self):
        for term in SCHEDULE_TERMS:
            self.rooms.reset()
            self.cascades_rooms.reset()
            before = len(self.sections)
            for code in sorted(self.cat.courses):
                c, p = self.cat.courses[code], self.profiles[code]
                if term not in p["terms"] and (term, code) not in self.force:
                    continue
                if p["kind"] == "indep":
                    self._independent(c, p, term)
                else:
                    self._class(c, p, term)
            self.log("schedule: %s has %d sections" % (term, len(self.sections) - before))
        if self.no_room:
            self.log("schedule: %d meetings could not get a room and are listed without one" % self.no_room)
        return self

    # ---- picking sections for a made-up student --------------------------------------------------
    def _times(self, crn: int):
        return [(m[1], m[2], m[3]) for m in self.meet_by_crn.get(crn, []) if m[1]]

    @staticmethod
    def _clash(a, b) -> bool:
        for d1, s1, e1 in a:
            for d2, s2, e2 in b:
                if set(d1) & set(d2) and s1 < e2 and s2 < e1:
                    return True
        return False

    def options(self, term: str, code: str, campus: str) -> list[tuple]:
        """[(lecture, linked or None)] a student on `campus` could take, best matches first."""
        secs = [s for s in self.by_course.get((term, code), []) if s["is_primary"]]
        mine = [s for s in secs if s["campus"] == campus and not s["restrictions"]]
        if not mine:
            mine = [s for s in secs if s["campus"] in ("Corvallis", "Ecampus") and not s["restrictions"]] or secs
        out = []
        for s in mine:
            subs = self.linked_of.get(s["crn"])
            if subs:
                out.extend((s, sub) for sub in subs)
            else:
                out.append((s, None))
        return out

    def pick(self, rng: random.Random, term: str, wanted: list[tuple]) -> dict:
        """Choose sections for [(code, campus)] that do not overlap. Returns {code: (crn, linked_crn)}."""
        choices = []
        for code, campus in wanted:
            opts = self.options(term, code, campus)
            rng.shuffle(opts)

            def cost(o):
                late = 0
                for sec in o:
                    if sec is not None:
                        late += sum(1 for _d, start, _e in self._times(sec["crn"]) if start >= 1020 or start < 510)
                full = (o[0]["seats_taken"] >= o[0]["seats_total"]) + (
                    o[1] is not None and o[1]["seats_taken"] >= o[1]["seats_total"])
                return full * 10 + late
            opts.sort(key=cost)
            choices.append((code, opts[:40]))
        order = sorted(range(len(choices)), key=lambda k: len(choices[k][1]))
        result: dict[str, tuple] = {}
        busy: list[list] = []

        def solve(k: int) -> bool:
            if k == len(order):
                return True
            code, opts = choices[order[k]]
            if not opts:
                result[code] = (None, None)
                return solve(k + 1)
            for lec, sub in opts:
                times = self._times(lec["crn"]) + (self._times(sub["crn"]) if sub else [])
                if any(self._clash(times, other) for other in busy):
                    continue
                busy.append(times)
                result[code] = (lec["crn"], sub["crn"] if sub else None)
                if solve(k + 1):
                    return True
                busy.pop()
            return False

        if not solve(0):                                    # no clash-free set: take first choices anyway
            for code, opts in choices:
                result[code] = (opts[0][0]["crn"], opts[0][1]["crn"] if opts[0][1] else None) if opts else (None, None)
        return result


# ======================================================================================================
# Made-up students
# ======================================================================================================

GRADE_POINTS = {"A": 4.0, "A-": 3.7, "B+": 3.3, "B": 3.0, "B-": 2.7, "C+": 2.3, "C": 2.0, "C-": 1.7, "D+": 1.3,
                "D": 1.0, "D-": 0.7, "F": 0.0}
GRADE_LADDER = ["C", "C+", "B-", "B", "B+", "A-", "A"]      # what ordinary completed rows can get
ELECTIVE_SUBJECTS = {"ANTH", "ART", "ATS", "ENG", "ES", "FILM", "GEOG", "HST", "MUS", "OC", "PHL", "PS", "REL",
                     "SOC", "SUS", "WGSS", "FW", "NUTR", "HDFS", "QS", "ED", "TA", "H"}
TRANSFER_SCHOOL = "Sample Community College"


def _past_term(code: str) -> tuple:
    """A terms row for an earlier term code such as 202502 (Winter 2025). Dates are approximate sample dates."""
    ay, part = int(code[:4]), code[4:]
    if part == "01":
        return (code, "Fall %d" % (ay - 1), "Fall", "%d-09-24" % (ay - 1), "%d-12-12" % (ay - 1), "past", 1)
    if part == "02":
        return (code, "Winter %d" % ay, "Winter", "%d-01-06" % ay, "%d-03-20" % ay, "past", 1)
    if part == "03":
        return (code, "Spring %d" % ay, "Spring", "%d-03-30" % ay, "%d-06-12" % ay, "past", 1)
    return (code, "Summer %d" % (ay - 1), "Summer", "%d-06-22" % (ay - 1), "%d-09-04" % (ay - 1), "past", 1)


class StudentPlan:
    """One made-up student's course history, built from their catalog program's parsed requirements."""

    def __init__(self, cat: Catalog, rng: random.Random, spec: dict, program: dict):
        self.cat, self.rng, self.spec, self.program = cat, rng, spec, program
        self.campus = spec["campus"]
        self.start_ay = spec["start_ay"]
        self.prefer = list(spec.get("prefer", ()))
        self.bad = dict(spec.get("bad", {}))
        self.own = list(program["reqs"]) if program["kind"] != "core" else []
        self.own_codes = set()
        for r in self.own:
            for code, with_code in r["courses"]:
                self.own_codes.add(code)
                if with_code:
                    self.own_codes.update(with_code.split(" & "))
        self.rows: list[dict] = []
        self.codes: set[str] = set()
        self.titles: set[str] = set()
        self.by_req: dict[int, list[dict]] = {}

    # ---- basics ----------------------------------------------------------------------------------
    def term_for(self, year: int, term_index: int) -> str:
        return "%d%02d" % (self.start_ay + year - 1, term_index + 1)

    def count(self, status: str) -> int:
        return sum(1 for r in self.rows if r["status"] == status)

    def add(self, code, term, status, req=None, grade=None, transfer_from=None):
        c = self.cat.courses.get(code)
        if c is None or code in self.codes:
            return None
        credits = c["credits_min"] if c["credits_min"] > 0 else c["credits_max"]
        if c["credits_min"] != c["credits_max"] and c["credits_min"] <= 3 <= c["credits_max"]:
            credits = 3.0
        fixed = grade is not None
        if code in self.bad and status == "completed":
            grade, fixed, req = self.bad[code], True, None       # below the grade the major needs: fills nothing
        if status == "transfer":
            grade = "T"
            term = None
            if not transfer_from:
                transfer_from = "%s at %s" % (re.sub(r"(\d)Z$", r"\1", code), TRANSFER_SCHOOL)
        row = {"course_code": code, "title": c["title"], "term_code": term, "status": status, "grade": grade,
               "credits": float(credits), "crn": None, "linked_crn": None, "transfer_from": transfer_from,
               "requirement_id": req["id"] if req else None, "_fixed": fixed, "_order": len(self.rows)}
        self.rows.append(row)
        self.codes.add(code)
        self.titles.add(c["title"])
        if req:
            self.by_req.setdefault(req["id"], []).append(row)
        return row

    def _options(self, req: dict) -> list[tuple]:
        out = []
        for code, with_code in req["courses"]:
            extra = with_code.split(" & ") if with_code else []
            if code in self.cat.courses and code not in self.codes and all(
                    x in self.cat.courses and x not in self.codes for x in extra):
                out.append((code, extra))
        return out

    def _rank(self, code: str) -> tuple:
        c = self.cat.courses[code]
        return (code not in self.prefer, bool(c["honors"]), bool(c["independent"]),
                self.campus == "Ecampus" and not c["ecampus"])

    def open_reqs(self) -> list[dict]:
        """Own-program requirements nothing on the record points at yet."""
        return [r for r in self.own if r["id"] not in self.by_req]

    def next_reqs(self) -> list[dict]:
        """Open course and choice requirements the student could take next, in sample-plan order."""
        todo = [r for r in self.open_reqs() if r["kind"] in ("course", "choice") and self._options(r)]
        todo.sort(key=lambda r: ((r["plan_year"] or 9), TERM_INDEX.get(r["plan_term"], 9), r["seq"]))
        return todo

    def line(self, *needles) -> dict | None:
        """An own-program 'credits' line whose label contains one of the needles (first needle wins)."""
        for needle in needles:
            for r in self.own:
                if r["kind"] == "credits" and needle in r["label"].lower():
                    return r
        return None

    def auto_req(self, code: str) -> dict | None:
        """Where a course counts: an open requirement of the program, else a Core Ed category, else electives."""
        for r in self.own:
            if r["id"] in self.by_req or r["kind"] == "credits":
                continue
            for c, with_code in r["courses"]:
                if code == c or (with_code and code in with_code.split(" & ")):
                    return r
        for attr_code, _name in self.cat.courses[code]["attrs"] if code in self.cat.courses else []:
            r = self.cat.core_by_attr.get(attr_code)
            if r and r["id"] not in self.by_req:
                return r
        return self.line("unrestricted elective", "elective")

    # ---- filling requirements --------------------------------------------------------------------
    def take_req(self, req: dict, term, status, n: int | None = None) -> list[dict]:
        opts = self._options(req)
        if not opts:
            return []
        if req["kind"] == "choice":
            self.rng.shuffle(opts)
        opts.sort(key=lambda o: self._rank(o[0]))
        added: list[dict] = []
        if req["kind"] != "choice":
            want_n, want_credits = 1, None
        elif n:
            want_n, want_credits = n, None
        elif req["pick_count"]:
            want_n, want_credits = req["pick_count"], None
        else:
            want_n, want_credits = 6, (req["credits"] or 1)
        got_n, got_credits = 0, 0.0
        for code, extra in opts:
            if got_n >= want_n or (want_credits is not None and got_credits >= want_credits):
                break
            for x in [code] + extra:
                row = self.add(x, term, status, req)
                if row:
                    added.append(row)
                    got_credits += row["credits"]
            got_n += 1
        return added

    def _req_has(self, req: dict, codes) -> bool:
        for code, with_code in req["courses"]:
            if code in codes or (with_code and any(x in codes for x in with_code.split(" & "))):
                return True
        return False

    def complete_planned(self, before: tuple, defer=(), skip=()):
        """Complete everything the sample plan puts before (year, term_index). `defer` goes to this term instead."""
        for r in sorted(self.own, key=lambda r: r["seq"]):
            if r["plan_year"] is None or r["kind"] == "credits" or r["id"] in self.by_req:
                continue
            pos = (r["plan_year"], TERM_INDEX[r["plan_term"]])
            if pos >= before or self._req_has(r, skip):
                continue
            if self._req_has(r, defer):
                self.take_req(r, CURRENT_TERM, "in_progress")
            else:
                self.take_req(r, self.term_for(*pos), "completed")

    def start_planned(self, at: tuple, skip=()):
        for r in sorted(self.own, key=lambda r: r["seq"]):
            if r["plan_year"] is None or r["kind"] == "credits" or r["id"] in self.by_req:
                continue
            if (r["plan_year"], TERM_INDEX[r["plan_term"]]) == at and not self._req_has(r, skip):
                self.take_req(r, CURRENT_TERM, "in_progress")

    def take_core(self, text: str, term, status, prefer=()):
        """Add one course from a Core Education category (e.g. 'Arts & Humanities General')."""
        req = self.cat.core_req(text)
        if not req:
            return None
        target = req if req["id"] not in self.by_req else self.line("core ed")
        pool = [code for code, _w in req["courses"] if code in self.cat.courses and code not in self.codes
                and self.cat.courses[code]["title"] not in self.titles]
        if not pool:
            return None
        for code in prefer:
            if code in pool:
                return self.add(code, term, status, target)

        def key(code):
            c = self.cat.courses[code]
            return (bool(c["honors"]), bool(c["independent"]), self.campus == "Ecampus" and not c["ecampus"],
                    code in self.own_codes, bool(c["prereq_text"]), c["level"] > 200,
                    not (3 <= c["credits_min"] <= 4))
        best = min(key(code) for code in pool)
        return self.add(self.rng.choice([code for code in pool if key(code) == best]), term, status, target)

    def take_elective(self, term, status, req=None, subjects=None, levels=(100, 200)):
        """Add a free elective (or an upper-division course in `subjects`)."""
        def ok(c, strict):
            if c["code"] in self.codes or c["code"] in self.own_codes or c["honors"] or c["independent"]:
                return False
            if c["title"] in self.titles:
                return False
            if c["level"] not in levels or c["credits_min"] != c["credits_max"] or not (3 <= c["credits_min"] <= 4):
                return False
            if self.campus == "Ecampus" and not c["ecampus"] and strict:
                return False
            if subjects is not None:
                return c["subject"] in subjects
            if strict and (c["prereq_text"] or c["coreq_text"] or c["subject"] not in ELECTIVE_SUBJECTS):
                return False
            return True
        for strict in (True, False):
            pool = [code for code in sorted(self.cat.courses) if ok(self.cat.courses[code], strict)]
            if pool:
                return self.add(self.rng.choice(pool), term, status, req)
        return None

    def transfer(self, code: str):
        if code in self.cat.courses and code not in self.codes:
            return self.add(code, None, "transfer", self.auto_req(code))
        return None

    def spread(self, terms: list[str]):
        """Give a term to completed rows that have none yet: lower-level courses first, a few per term."""
        todo = [r for r in self.rows if r["status"] == "completed" and r["term_code"] is None]
        todo.sort(key=lambda r: (self.cat.courses[r["course_code"]]["level"], r["_order"]))
        if not todo or not terms:
            return
        for i, r in enumerate(todo):
            r["term_code"] = terms[min(len(terms) - 1, i * len(terms) // len(todo))]

    def limit_open(self, year: int, keep: int, fill_term: str):
        """Leave exactly `keep` requirements from sample-plan years up to `year` unstarted (when there are enough)."""
        open_now = [r for r in self.open_reqs() if r["plan_year"] is not None and r["plan_year"] <= year]
        open_now.sort(key=lambda r: (r["plan_year"] != year, r["kind"] != "course", r["seq"]))
        for r in open_now[keep:]:
            if r["kind"] in ("course", "choice") and self.take_req(r, fill_term, "completed"):
                continue
            self.take_elective(fill_term, "completed", req=r)

    def ensure(self, in_progress: int, backfill_terms=(), leave=()):
        """Fallbacks for a catalog that lacks the wanted program: still give the student a believable record.

        `leave` lists requirements that must stay unstarted. An Ecampus student only gets Ecampus courses here
        unless the catalog has none left.
        """
        leave_ids = {r["id"] for r in leave}
        online = self.campus == "Ecampus"

        def usable(r):
            first = sorted(self._options(r), key=lambda o: self._rank(o[0]))[:1]
            return (r["id"] not in leave_ids and first and not self.cat.courses[first[0][0]]["independent"]
                    and (not online or self.cat.courses[first[0][0]]["ecampus"]))
        if backfill_terms and not any(r["status"] in ("completed", "transfer") for r in self.rows):
            todo = [r for r in self.next_reqs() if r["id"] not in leave_ids]
            for i, r in enumerate(todo[:len(backfill_terms) * 3]):
                self.take_req(r, backfill_terms[i // 3], "completed", n=1)
        guard = 0
        while self.count("in_progress") < in_progress and guard < 20:
            guard += 1
            todo = [r for r in self.next_reqs() if usable(r)]
            if todo and self.take_req(todo[0], CURRENT_TERM, "in_progress", n=1):
                continue
            if self.take_elective(CURRENT_TERM, "in_progress"):
                continue
            extra = [code for code in sorted(self.cat.courses) if code not in self.codes
                     and not self.cat.courses[code]["independent"] and not self.cat.courses[code]["honors"]]
            extra.sort(key=lambda code: (online and not self.cat.courses[code]["ecampus"],
                                         code in self.own_codes, self.cat.courses[code]["level"], code))
            if not extra or not self.add(extra[0], CURRENT_TERM, "in_progress", None):
                break

    # ---- grades ----------------------------------------------------------------------------------
    @staticmethod
    def gpa_of(rows: list[dict]) -> float | None:
        graded = [r for r in rows if r["status"] == "completed" and r["grade"] in GRADE_POINTS]
        credits = sum(r["credits"] for r in graded)
        if not credits:
            return None
        return sum(GRADE_POINTS[r["grade"]] * r["credits"] for r in graded) / credits

    def _tune(self, rows: list[dict], movable: list[dict], target: float):
        rng = self.rng
        movable = [r for r in movable if not r["_fixed"]]
        for _ in range(4000):
            gpa = self.gpa_of(rows)
            if gpa is None or not movable or abs(gpa - target) <= 0.012:
                break
            r = rng.choice(movable)
            k = GRADE_LADDER.index(r["grade"])
            if gpa < target and k < len(GRADE_LADDER) - 1:
                r["grade"] = GRADE_LADDER[k + 1]
            elif gpa > target and k > 0:
                r["grade"] = GRADE_LADDER[k - 1]

    def major_subjects(self) -> list[str]:
        counts: dict[str, int] = {}
        for r in self.own:
            if r["kind"] == "course" and r["courses"]:
                s = r["courses"][0][0].split(" ")[0]
                counts[s] = counts.get(s, 0) + 1
        return [s for s, _n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:2]]

    def grade(self, target: float, major_target: float | None = None) -> dict:
        """Hand out grades so the overall (and major) GPA land near the targets, then report the real numbers."""
        rng = self.rng
        done = [r for r in self.rows if r["status"] == "completed"]
        for r in done:
            if not r["_fixed"]:
                r["grade"] = rng.choice(GRADE_LADDER)
        subjects = self.major_subjects()
        major = [r for r in done if r["course_code"].split(" ")[0] in subjects]
        if major_target is not None and major:
            self._tune(major, major, major_target)
            self._tune(done, [r for r in done if all(r is not m for m in major)], target)
        else:
            self._tune(done, done, target)
        gpa, major_gpa = self.gpa_of(done), self.gpa_of(major)
        earned = sum(r["credits"] for r in self.rows if r["status"] == "transfer" or (
            r["status"] == "completed" and GRADE_POINTS.get(r["grade"], 0) > 0))
        return {"gpa": round(gpa, 2) if gpa is not None else None,
                "major_gpa": round(major_gpa, 2) if major_gpa is not None else None,
                "credits_earned": float(earned)}

    def forces(self) -> list[tuple]:
        """(term, course, campus) offerings the schedule must contain for this student's story to work."""
        out = [(CURRENT_TERM, r["course_code"], self.campus) for r in self.rows if r["status"] == "in_progress"]
        for req in self.open_reqs():
            if req["kind"] in ("course", "choice") and len(req["courses"]) <= 8:
                for code, extra in self._options(req)[:3]:
                    for x in [code] + extra:
                        out.append((REG_TERM, x, self.campus))
        for code in self.bad:                               # the retake has to be on offer
            if code in self.cat.courses:
                out.append((REG_TERM, code, self.campus))
        return out


# ---- the five stories ----------------------------------------------------------------------------------

def _script_juniper(p: StudentPlan):
    """Sophomore in Computer Science: year one done, four classes now, exactly three year-two requirements left."""
    p.complete_planned(before=(2, 0), defer={"MTH 252Z", "COMM 114", "COMM 111Z"})
    p.start_planned(at=(2, 0), skip={"WR 314", "WR 323"})
    p.take_core("Arts & Humanities General", "202601", "completed")
    p.take_core("Scientific Inquiry & Analysis", "202602", "completed")
    p.take_core("Social Science", "202602", "completed")
    p.take_elective("202602", "completed", req=p.line("unrestricted elective", "elective"))
    p.take_core("Arts & Humanities Global", "202603", "completed")
    p.take_core("Scientific Inquiry & Analysis", "202603", "completed")
    p.take_core("Difference, Power & Oppression", CURRENT_TERM, "in_progress")
    year_two = [r for r in p.open_reqs() if r["plan_year"] == 2 and r["kind"] in ("course", "choice")][:3]
    p.ensure(4, backfill_terms=["202601", "202602", "202603"], leave=year_two)
    p.limit_open(2, 3, "202603")


def _script_mateo(p: StudentPlan):
    """Transfer junior in Business Administration with math, writing and CS 161 that also fit Computer Science."""
    for code in ["BA 101Z", "COMM 111Z", "ECON 201Z", "ECON 202Z", "MTH 111Z", "MTH 241", "MTH 251Z", "WR 121Z",
                 "WR 227Z", "BA 211Z", "BA 213Z", "BA 226Z", "BA 169Z", "CS 161", "PSY 201Z"]:
        p.transfer(code)
    p.take_core("Arts & Humanities General", None, "transfer")
    if p.count("transfer") < 8:                             # a catalog without those codes: transfer what exists
        for r in p.next_reqs()[:10]:
            p.take_req(r, None, "transfer", n=1)
    for r in p.next_reqs()[:5]:
        p.take_req(r, "202603", "completed", n=1)
    p.take_core("Difference, Power & Oppression", "202603", "completed")
    for r in p.next_reqs()[:5]:
        p.take_req(r, CURRENT_TERM, "in_progress", n=1)
    p.ensure(4)


def _script_priya(p: StudentPlan):
    """Part-time senior in Psychology on Ecampus: nearly everything done over many terms, two classes now."""
    reqs = [r for r in sorted(p.own, key=lambda r: r["seq"]) if r["kind"] in ("course", "choice")]
    single = [r for r in reqs if r["kind"] == "course"]
    capstone = single[-1] if single else None
    big = max([r for r in reqs if r["kind"] == "choice"], key=lambda r: (len(r["courses"]), -r["seq"]), default=None)
    for r in reqs:
        if r is capstone:
            continue
        if r is big:
            p.take_req(r, None, "completed", n=1)
            now = [o for o in p._options(r) if not p.cat.courses[o[0]]["independent"]
                   and p.cat.courses[o[0]]["ecampus"] and not p.cat.courses[o[0]]["honors"]]
            p.rng.shuffle(now)
            for code, _extra in now[:2]:
                p.add(code, CURRENT_TERM, "in_progress", r)
            continue
        p.take_req(r, None, "completed")
    foundation = p.line("foundational")
    for code in ["WR 227Z", "MTH 105Z", "ST 243Z", "COMM 111Z"]:
        if code in p.cat.courses and code not in p.codes:
            p.add(code, None, "completed", foundation or p.auto_req(code))
    for text in ["Writing Foundations", "Transitions", "Arts & Humanities General", "Arts & Humanities Global",
                 "Scientific Inquiry & Analysis", "Difference, Power & Oppression", "Seeking Solutions",
                 "Quantitative Literacy & Analysis", "Communication, Media & Society"]:
        req = p.cat.core_req(text)
        if req and req["id"] not in p.by_req and not any(
                req["attr"] in [a[0] for a in p.cat.courses[code]["attrs"]] for code in sorted(p.codes)):
            p.take_core(text, None, "completed")
    bucket = p.line("remaining core ed", "elective")
    guard = 0
    while sum(r["credits"] for r in p.rows if r["status"] == "completed") < 138 and guard < 30:
        guard += 1
        if not p.take_elective(None, "completed", req=bucket, levels=(100, 200, 300)):
            break
    terms = ["%d%02d" % (ay, k) for ay in range(2022, 2027) for k in (1, 2, 3)]
    p.spread(terms)
    p.ensure(2, backfill_terms=terms[-6:])


def _script_devon(p: StudentPlan):
    """First-year in Kinesiology, first term on campus."""
    p.transfer("WR 121Z")                                   # dual credit from high school
    for r in p.rows:
        if r["status"] == "transfer":
            r["transfer_from"] = "%s at %s (dual credit in high school)" % (
                re.sub(r"(\d)Z$", r"\1", r["course_code"]), TRANSFER_SCHOOL)
    p.start_planned(at=(1, 0))
    p.take_core("Transitions", CURRENT_TERM, "in_progress")
    p.take_core("Quantitative Literacy & Analysis", CURRENT_TERM, "in_progress", prefer=("MTH 111Z", "MTH 105Z"))
    p.ensure(4)


def _script_tessa(p: StudentPlan):
    """Senior in Mechanical Engineering: three requirements left, one of them a retake."""
    p.complete_planned(before=(4, 0))
    p.start_planned(at=(4, 0))
    subjects = set(p.major_subjects()) or None
    option = p.line("option course", "option")
    for term, status in [("202601", "completed"), ("202602", "completed"), ("202603", "completed"),
                         ("202603", "completed"), (CURRENT_TERM, "in_progress"), (CURRENT_TERM, "in_progress")]:
        if option is not None:
            p.take_elective(term, status, req=option, subjects={"ME", "MATS", "ROB", "AAE", "MFGE"} if subjects
                            and "ME" in subjects else subjects, levels=(400,))
    p.take_core("Arts & Humanities General", "202401", "completed")
    p.take_core("Difference, Power & Oppression", "202503", "completed")
    p.take_core("Arts & Humanities Global", "202602", "completed")
    p.take_core("Seeking Solutions", "202603", "completed")
    bucket = p.line("remaining core ed", "unrestricted elective", "elective")
    if bucket is not None:
        p.take_elective("202501", "completed", req=bucket)
    keep = {"MIME 498", "ENGR 416"} | set(p.bad)
    for r in p.next_reqs():                                 # anything the sample plan does not place: done earlier
        if r["plan_year"] is None and not p._req_has(r, keep):
            p.take_req(r, "202603", "completed")
    p.ensure(4, backfill_terms=["202401", "202402", "202403", "202501", "202502", "202503", "202601", "202602",
                                "202603"])
    if not any(r["grade"] == "D+" for r in p.rows):         # fallback program: still show one low grade
        done = [r for r in p.rows if r["status"] == "completed" and r["requirement_id"] in
                [q["id"] for q in p.own]]
        if done:
            r = done[-1]
            p.by_req.pop(r["requirement_id"], None)
            r["grade"], r["_fixed"], r["requirement_id"] = "D+", True, None


STUDENTS = [
    {
        "slug": "juniper", "first_name": "Juniper", "last_name": "Alder", "pronouns": "she/her",
        "sample_id": "SAMPLE-0001", "program": "Computer Science", "standing": "Sophomore", "campus": "Corvallis",
        "is_transfer": 0, "gpa_target": 3.4, "major_gpa_target": None, "start_ay": 2026, "script": _script_juniper,
        "prefer": ["COMM 111Z"], "academic_standing": "Good standing", "advisor_name": "Cedar Gnawsworth",
        "reg_weekday": 0, "reg_time": "07:00",
        "situation": "Advising hold blocks registration, and no advisor meeting is booked yet",
        "blurb": "Juniper is a sophomore in Computer Science with an advising hold. She has to meet her advisor "
                 "before she can register next Monday. She has three requirements left this year.",
        "holds": [{"type": "advising", "title": "Advising hold",
                   "reason": "Meet with your advisor before registering. Your college asks you to go over your "
                             "plan with an advisor before Winter registration.",
                   "office": "{office}",
                   "how_to_clear": "Book an advising meeting and attend it. Your advisor removes the hold after "
                                   "you meet, usually the same day.",
                   "blocks": 1, "placed": -14,
                   "urls": ["https://holds.oregonstate.edu/hold/advising-hold", "https://holds.oregonstate.edu/"]}],
        "tasks": [("Meet with your advisor", "This clears your advising hold so you can register.", 5, "open", "task"),
                  ("Complete the pre-registration checklist",
                   "Check your holds, your registration time and your Winter 2027 plan.", 6, "open", "task"),
                  ("Confirm your contact information", "You confirmed your address and phone number.", -20, "done",
                   "task")],
        "appointments": [("{advisor}", "Academic advisor", "Spring check-in and fall planning", -168, "10:30", 30,
                          "In person", "{office}, Alder Hall 210", "past")],
        "slots": [(1, "09:00", 30, "In person"), (1, "14:30", 30, "Zoom"), (2, "08:30", 30, "Zoom"),
                  (2, "11:00", 30, "In person"), (3, "13:00", 30, "In person"), (3, "16:30", 30, "Zoom"),
                  (4, "10:00", 30, "Phone"), (4, "15:30", 30, "In person"), (5, "09:30", 30, "Zoom"),
                  (5, "12:00", 30, "In person")],
        "balance": {"due": 12, "past_due": 0.0, "plan": 0, "meal": 86.25, "orange": 23.40},
        "transactions": [(-48, "Tuition: 16 credits", 4212.00), (-48, "Student incidental fee", 465.50),
                         (-48, "Student building fee", 55.00), (-48, "Health services fee", 135.00),
                         (-48, "Residence hall room", 3180.00), (-48, "Dining plan", 1450.00),
                         (-48, "Housing deposit applied", -200.00),
                         (-40, "Course fee", 45.00), (-35, "Orange Cash deposit", 100.00),
                         (-33, "Scholarship", -1500.00), (-33, "Federal student loan (subsidized)", -1750.00),
                         (-33, "Federal student loan (unsubsidized)", -1000.00), (-30, "Payment received", -3449.00),
                         (-20, "Payment received", -500.00)],
    },
    {
        "slug": "mateo", "first_name": "Mateo", "last_name": "Rivers", "pronouns": "he/him",
        "sample_id": "SAMPLE-0002", "program": "Business Administration", "standing": "Junior", "campus": "Corvallis",
        "is_transfer": 1, "gpa_target": 3.2, "major_gpa_target": None, "start_ay": 2026, "script": _script_mateo,
        "prefer": [], "academic_standing": "Good standing", "advisor_name": "Hazel Paddlewright",
        "reg_weekday": 1, "reg_time": "07:00",
        "situation": "Transfer student on a payment plan, thinking about switching to Computer Science",
        "blurb": "Mateo transferred in with about 60 credits and is in his second term at Oregon State. He has an "
                 "advisor meeting coming up and a payment plan installment due soon. He is wondering how his "
                 "classes would count toward Computer Science.",
        "holds": [],
        "tasks": [("Bring your questions to your advisor meeting",
                   "Your advisor meeting is coming up. Ask how your credits fit a change of major.", 3, "open", "task"),
                  ("Pay your next payment plan installment", "The next installment is due in nine days.", 9, "open",
                   "task"),
                  ("Look at a what-if for Computer Science",
                   "See how the classes you have would count toward a different major.", 14, "open", "success_plan"),
                  ("Send your final transcript", "Your transcript from Sample Community College arrived.", -60,
                   "done", "task")],
        "appointments": [("{advisor}", "Academic advisor", "Winter registration and change of major questions", 3,
                          "14:00", 30, "In person", "{office}, Riverbend Science Center 118", "upcoming")],
        "slots": [(1, "10:00", 30, "Zoom"), (2, "09:00", 30, "In person"), (2, "15:00", 30, "In person"),
                  (4, "11:30", 30, "Zoom"), (5, "13:30", 30, "In person"), (6, "08:30", 30, "Phone"),
                  (7, "16:00", 30, "Zoom")],
        "balance": {"due": 9, "past_due": 0.0, "plan": 1, "meal": None, "orange": 12.00},
        "transactions": [(-48, "Tuition: 16 credits", 4212.00), (-48, "Student incidental fee", 465.50),
                         (-48, "Student building fee", 55.00), (-48, "Health services fee", 135.00),
                         (-45, "Payment plan enrollment fee", 45.00), (-33, "Transfer scholarship", -1000.00),
                         (-33, "Federal student loan", -1212.50), (-42, "Payment plan installment 1", -675.00),
                         (-12, "Payment plan installment 2", -675.00)],
    },
    {
        "slug": "priya", "first_name": "Priya", "last_name": "Cedar", "pronouns": "she/her",
        "sample_id": "SAMPLE-0003", "program": "Psychology", "standing": "Senior", "campus": "Ecampus",
        "is_transfer": 0, "gpa_target": 3.55, "major_gpa_target": None, "start_ay": 2022, "script": _script_priya,
        "prefer": [], "academic_standing": "Good standing", "advisor_name": "Linden Mudlodge",
        "reg_weekday": 0, "reg_time": "07:00",
        "situation": "Online and part-time. A past-due balance blocks registration",
        "blurb": "Priya studies Psychology online, part-time, and works during the day. A past-due balance of "
                 "$612.00 has put a financial hold on her registration. She is close to graduating.",
        "holds": [{"type": "financial", "title": "Past-due balance hold",
                   "reason": "Your account has a past-due balance of $612.00. You cannot register until it is "
                             "paid or you set up a payment arrangement.",
                   "office": "Student Accounts",
                   "how_to_clear": "Pay the past-due amount, or contact Student Accounts about a payment plan. "
                                   "The hold comes off after the payment posts.",
                   "blocks": 1, "placed": -8,
                   "urls": ["https://holds.oregonstate.edu/hold/balance-due-hold",
                            "https://holds.oregonstate.edu/hold/financial-registration-hold",
                            "https://holds.oregonstate.edu/"]}],
        "tasks": [("Pay your past-due balance", "$612.00 was due eight days ago. Paying it clears your hold.", -8,
                   "open", "task"),
                  ("Apply to graduate", "You are close to finishing. Apply two terms before your last term.", 30,
                   "open", "task"),
                  ("Complete the pre-registration checklist",
                   "Check your holds, your registration time and your Winter 2027 plan.", 6, "open", "task"),
                  ("Update your mailing address", "You updated your address.", -90, "done", "task")],
        "appointments": [("{advisor}", "Academic advisor", "Graduation check", -75, "12:15", 30, "Zoom",
                          "Zoom link sent by email", "past")],
        "slots": [(1, "12:00", 30, "Zoom"), (2, "17:00", 30, "Zoom"), (3, "07:30", 30, "Phone"),
                  (4, "12:30", 30, "Zoom"), (6, "17:30", 30, "Phone"), (7, "12:00", 30, "Zoom")],
        "balance": {"due": -8, "past_due": 612.00, "plan": 0, "meal": None, "orange": None},
        "transactions": [(-48, "Ecampus tuition: 8 credits", 2800.00),
                         (-48, "Online course fee", 62.00), (-33, "Federal grant", -1000.00),
                         (-33, "State grant", -450.00), (-30, "Payment received", -409.00),
                         (-15, "Payment received", -409.00), (-7, "Late payment charge", 18.00)],
    },
    {
        "slug": "devon", "first_name": "Devon", "last_name": "Brook", "pronouns": "they/them",
        "sample_id": "SAMPLE-0004", "program": "Kinesiology", "standing": "First-year", "campus": "Corvallis",
        "is_transfer": 0, "gpa_target": None, "major_gpa_target": None, "start_ay": 2027, "script": _script_devon,
        "prefer": ["CH 121", "MTH 111Z"], "academic_standing": "Good standing", "advisor_name": "Rowan Twigsby",
        "reg_weekday": 3, "reg_time": "07:00",
        "situation": "First term, living on campus, registering for the first time",
        "blurb": "Devon is in their first term in Kinesiology and lives on campus. They have never registered "
                 "on their own before. A health hold needs attention, but it does not block registration.",
        "holds": [{"type": "health", "title": "Immunization record missing",
                   "reason": "Student Health Services does not have your immunization record yet. This hold does "
                             "not stop you from registering for Winter.",
                   "office": "Student Health Services",
                   "how_to_clear": "Send your immunization record to Student Health Services. The hold comes off "
                                   "after they review it.",
                   "blocks": 0, "placed": -21,
                   "urls": ["https://holds.oregonstate.edu/hold/student-health-services-hold-immunization",
                            "https://studenthealth.oregonstate.edu/policies-and-guidelines/registration-holds",
                            "https://holds.oregonstate.edu/"]}],
        "tasks": [("Finish your math placement", "Your placement result decides which math class you can take.", 7,
                   "open", "task"),
                  ("Meet your advisor", "Your first-year advising meeting is already booked.", 7, "open", "task"),
                  ("Send your immunization record", "This clears your health hold.", 14, "open", "task"),
                  ("Complete new student orientation", "You finished orientation before the term began.", -50,
                   "done", "task")],
        "appointments": [("{advisor}", "Academic advisor", "First-year advising: planning Winter classes", 5,
                          "11:00", 30, "In person", "{office}, Camas Meadow Hall 140", "upcoming")],
        "slots": [(1, "13:00", 30, "In person"), (2, "10:30", 30, "In person"), (3, "15:00", 30, "Zoom"),
                  (6, "09:00", 30, "In person"), (7, "14:00", 30, "Zoom"), (8, "11:00", 30, "In person")],
        "balance": {"due": 12, "past_due": 0.0, "plan": 0, "meal": 412.75, "orange": 58.10},
        "transactions": [(-48, "Tuition: 12 credits", 4212.00), (-48, "Student incidental fee", 465.50),
                         (-48, "Student building fee", 55.00), (-48, "Health services fee", 135.00),
                         (-48, "Residence hall room", 3180.00), (-48, "Dining plan", 1450.00),
                         (-48, "New student fee", 350.00), (-44, "Orange Cash deposit", 50.00),
                         (-48, "Housing deposit applied", -200.00), (-33, "Scholarship", -2000.00),
                         (-33, "Federal student loan", -1750.00), (-25, "Payment received", -5000.00)],
    },
    {
        "slug": "tessa", "first_name": "Tessa", "last_name": "Fern", "pronouns": "she/her",
        "sample_id": "SAMPLE-0005", "program": "Mechanical Engineering", "standing": "Senior", "campus": "Corvallis",
        "is_transfer": 0, "gpa_target": 2.74, "major_gpa_target": 2.31, "start_ay": 2024, "script": _script_tessa,
        "prefer": ["COMM 111Z"], "bad": {"ME 316": "D+"}, "academic_standing": "Good standing",
        "advisor_name": "Sage Timbertooth", "reg_weekday": 0, "reg_time": "07:00",
        "situation": "Senior with three requirements left, and one confusing line on her degree checklist",
        "blurb": "Tessa is a senior in Mechanical Engineering with three requirements left. One required class "
                 "shows a D+ where her major needs a C or better, so it reads as not met and she needs to retake it.",
        "holds": [],
        "tasks": [("Apply to graduate", "Apply now so your degree can be checked before your last term.", 21, "open",
                   "task"),
                  ("Talk with your advisor about the class you need to retake",
                   "A D+ does not meet the C or better your major asks for. Plan the retake for Winter.", 10, "open",
                   "success_plan"),
                  ("Confirm your capstone team", "Your capstone team was confirmed.", -30, "done", "task")],
        "appointments": [("{advisor}", "Academic advisor", "Senior year plan", -140, "15:30", 30, "In person",
                          "{office}, Millrace Engineering Center 102", "past")],
        "slots": [(1, "11:00", 30, "In person"), (3, "09:30", 30, "Zoom"), (4, "14:00", 30, "In person"),
                  (6, "10:00", 30, "Zoom"), (8, "15:30", 30, "In person")],
        "balance": {"due": 12, "past_due": 0.0, "plan": 0, "meal": None, "orange": 7.25},
        "transactions": [(-48, "Tuition: 15 credits", 4212.00), (-48, "Engineering program fee", 480.00),
                         (-48, "Student incidental fee", 465.50), (-48, "Student building fee", 55.00),
                         (-48, "Health services fee", 135.00), (-40, "Capstone materials fee", 60.00),
                         (-33, "Scholarship", -2500.00), (-33, "Federal student loan", -1800.00),
                         (-20, "Payment received", -1107.50)],
    },
]


def choose_program(cat: Catalog, name: str, index: int) -> tuple[dict, bool]:
    """The catalog program a sample student uses, and whether it is the one asked for."""
    wanted = cat.find_program(name)
    if wanted:
        return wanted, True
    majors = [p for p in cat.programs if p["kind"] == "major" and p["level"] == "undergraduate" and p["reqs"]]
    majors = majors or [p for p in cat.programs if p["kind"] == "major" and p["reqs"]]
    majors = majors or [p for p in cat.programs if p["kind"] != "core" and p["reqs"]]
    majors = majors or [p for p in cat.programs if p["kind"] != "core"] or [cat.core]
    return majors[index % len(majors)], False


def plan_students(cat: Catalog, rng: random.Random, log=print) -> list[StudentPlan]:
    plans = []
    for i, spec in enumerate(STUDENTS):
        program, exact = choose_program(cat, spec["program"], i)
        plan = StudentPlan(cat, rng, spec, program)
        plan.exact = exact
        spec["script"](plan)
        plans.append(plan)
        log("student %s: %s%s, %d rows" % (spec["slug"], program["name"],
                                           "" if exact else " (fallback for %s)" % spec["program"], len(plan.rows)))
    return plans


# ======================================================================================================
# Plain-language map of BeaverHub tool names, and common forms
# ======================================================================================================
# Each resource: (name, category, needs_login, plain, use_for, candidate URLs). A URL is used only when that exact
# address is a stored public page in the crawl database; otherwise the resource gets no link. Nothing is guessed.

_R = "https://registrar.oregonstate.edu/"
_F = "https://finance.oregonstate.edu/"
_FA = "https://financialaid.oregonstate.edu/"
_T = "https://technology.oregonstate.edu/"
_UNKNOWN = "A link on BeaverHub. No public page about it is stored, so Beaver Bot cannot describe it yet."

RESOURCES = [
    ("Academic Advising", "Academic", 0,
     "The advisors in your college who help you pick classes and stay on track to graduate.",
     "Use this to find your advisor or book an advising meeting.", ["https://advising.oregonstate.edu/"]),
    ("Academic Calendar", "Academic", 0,
     "The important dates for each term: when classes start, add and drop deadlines, and finals week.",
     "Use this to check a deadline before you add, drop or withdraw.", [_R + "osu-academic-calendar"]),
    ("Academic Catalog", "Academic", 0,
     "OSU's book of every major, minor and course, with the requirements for each.",
     "Use this to read what a course covers or what a program requires.", ["https://catalog.oregonstate.edu/"]),
    ("Academic Regulations", "Academic", 0,
     "The university's rules about grades, credits, repeating classes and graduating.",
     "Use this to look up the rule behind a deadline or a grade question.",
     ["https://catalog.oregonstate.edu/regulations/",
      "https://ecampus.oregonstate.edu/services/policies-and-regulations.htm"]),
    ("Academic Standing", "Academic", 1,
     "Shows whether you are in good standing or on warning, probation or suspension, based on your grades.",
     "Use this to see where you stand after grades post.", [_R + "grades-honor-roll-and-academic-standing"]),
    ("Academic Success Center", "Academic", 0,
     "A campus center with coaching, study help and workshops for any student.",
     "Use this to get help with study habits, managing time or a hard class.", ["https://success.oregonstate.edu/"]),
    ("Academics for Student Athletes", "Academic", 0,
     "The advising and study support office for students on OSU sports teams.",
     "Use this if you are a student athlete and need advising or tutoring.", []),
    ("Account Summary by Term", "Financial", 1,
     "A term-by-term list of what you were charged and what was paid.",
     "Use this to see the charges and payments for one term.", [_F + "student-accounts/student-billing"]),
    ("Advance Standing Report", "Academic", 1,
     "A report that shows how credits from other schools or exams came in to OSU.",
     "Use this to check which transfer credits arrived and what they count as.",
     ["https://admissions.oregonstate.edu/advanced-standing-report"]),
    ("Associated Students of OSU", "Getting Involved", 0,
     "OSU's student government, which also runs services for students.",
     "Use this to get involved in student government or find its services.", ["https://asosu.oregonstate.edu/"]),
    ("Athletic Events", "Getting Involved", 0,
     "Schedules and student tickets for Beaver sports.",
     "Use this to find a game and get a student ticket.", []),
    ("Baccalaureate Core Courses", "Academic", 0,
     "The general education classes every undergraduate needs. Newer students know it as Core Education.",
     "Use this to find classes that count for general education.",
     ["https://coreeducation.oregonstate.edu/", "https://catalog.oregonstate.edu/core-education/"]),
    ("Basic Needs Center", "Wellness", 0,
     "A center that helps students with food, housing, textbooks and money emergencies.",
     "Use this if you are short on food, rent or textbook money.", ["https://basicneeds.oregonstate.edu/"]),
    ("Biosphere", "Academic", 1, _UNKNOWN,
     "Ask your advisor or the Service Desk what it is for before you rely on it.", []),
    ("Box", "Technology", 1,
     "Online file storage that OSU provides.",
     "Use this to store and share files for class or work.", [_T + "services/box"]),
    ("Canvas", "Technology", 1,
     "The website where your classes live: assignments, grades, announcements and messages from instructors.",
     "Use this to turn in work and check your grades in a class.", [_T + "services/canvas"]),
    ("Career Development Center", "Academic", 0,
     "The office that helps with resumes, interviews, internships and finding a job.",
     "Use this to get your resume reviewed or plan a job search.", ["https://career.oregonstate.edu/"]),
    ("Center for Advancing Financial Education", "Financial", 0,
     "A free service that teaches budgeting, borrowing and planning your money, with one-on-one appointments.",
     "Use this to make a budget or understand your loans.", [_FA + "financial-literacy"]),
    ("Center for Advocacy Prevention & Education", "Wellness", 0,
     "A confidential center that supports students affected by sexual violence, stalking or relationship harm.",
     "Use this to talk with a confidential advocate.", ["https://cape.oregonstate.edu/"]),
    ("Fraternity & Sorority Life", "Getting Involved", 0,
     "The office for OSU's fraternities and sororities.",
     "Use this to learn about joining a chapter.", []),
    ("Change Credits", "Academic", 1,
     "A registration tool for classes that can be taken for a range of credits.",
     "Use this to change how many credits you take in a variable-credit class.", [_R + "register"]),
    ("Change Grading Basis", "Academic", 1,
     "The request to switch a class between a letter grade and S/U grading.",
     "Use this before the deadline if you want a class graded S/U.", [_R + "change-grading-basis"]),
    ("Emergency Loan Eligibility", "Financial", 1,
     "A check of whether you can take a short-term emergency loan from OSU.",
     "Use this before you ask for an emergency loan.", [_F + "emergency-loans"]),
    ("Check Your Registration Status", "Academic", 1,
     "Shows your registration time, your holds, and whether you are cleared to register.",
     "Use this before registration opens to make sure nothing blocks you.",
     [_R + "eligibility-register", _R + "student-holds"]),
    ("Clubs & Organizations", "Getting Involved", 0,
     "The list of student clubs and how to join or start one.",
     "Use this to find a club that fits you.", ["https://clubs.oregonstate.edu/", "https://see.oregonstate.edu/ela"]),
    ("Colleges and Departments", "Academic", 0,
     "The list of OSU's colleges and the departments and programs inside each.",
     "Use this to find the college or department that runs your program.",
     ["https://catalog.oregonstate.edu/college-departments/"]),
    ("Collegiate Recovery", "Wellness", 0,
     "A community and support program for students in recovery from alcohol or drug use.",
     "Use this to find support for recovery while you are in school.",
     ["https://studenthealth.oregonstate.edu/prevention-wellness-2/recovery"]),
    ("Commencement", "Academic", 0,
     "The graduation ceremony and everything about taking part in it.",
     "Use this to plan for the ceremony once you have applied to graduate.",
     ["https://commencement.oregonstate.edu/"]),
    ("Community Engagement & Leadership", "Getting Involved", 0,
     "The office for volunteering, service projects and leadership programs.",
     "Use this to find a volunteer project or a leadership program.", ["https://see.oregonstate.edu/cel"]),
    ("Connect", "Getting Involved", 1, _UNKNOWN,
     "Ask your advisor or the Service Desk what it is for before you rely on it.", []),
    ("Cost of Attendance", "Financial", 0,
     "OSU's estimate of a year's costs: tuition, fees, housing, food, books and personal costs.",
     "Use this to plan a budget or understand your aid offer.", [_FA + "cost-attendance"]),
    ("Counseling & Psychological Services", "Wellness", 0,
     "Confidential mental health counseling for students.",
     "Use this to talk with a counselor or find support in a hard time.", ["https://counseling.oregonstate.edu/"]),
    ("Course Search", "Academic", 0,
     "The search for classes offered in a term, with times, seats and instructors.",
     "Use this to find sections of a class before you register.", [_R + "registration"]),
    ("Craft Center", "Getting Involved", 0,
     "A studio space where students can make ceramics, woodwork, jewelry and more.",
     "Use this to take a craft class or use a studio.", ["https://see.oregonstate.edu/craft-center"]),
    ("Cultural Resource Centers", "Getting Involved", 0,
     "Centers on campus that offer community, events and support tied to culture and identity.",
     "Use this to find a center and its events.", ["https://see.oregonstate.edu/dce"]),
    ("DAS Forms", "Accessibility", 1,
     "The forms Disability Access Services uses for accommodations.",
     "Use this to request or change an accommodation.", ["https://ds.oregonstate.edu/forms"]),
    ("DAS Testing Center", "Accessibility", 0,
     "The place where students with testing accommodations take their exams.",
     "Use this to schedule an exam with your accommodations.", ["https://ds.oregonstate.edu/testing-center"]),
    ("Degree Partnership Program", "Academic", 0,
     "A program that lets you be enrolled at OSU and a partner community college at the same time.",
     "Use this if you want to take classes at both schools.", [_FA + "degree-partnership-program"]),
    ("Direct Deposit", "Financial", 1,
     "Lets OSU send refunds straight to your bank account.",
     "Use this to get a refund faster than a paper check.", [_F + "student-accounts"]),
    ("Directory", "Technology", 0,
     "A search for OSU people and offices.",
     "Use this to find an office's contact details.", []),
    ("Disability Access Services", "Accessibility", 0,
     "The office that arranges accommodations for students with disabilities.",
     "Use this to set up accommodations for classes, exams or housing.", ["https://ds.oregonstate.edu/"]),
    ("Diversity & Cultural Engagement", "Getting Involved", 0,
     "The office that runs the cultural resource centers and programs for belonging on campus.",
     "Use this to find community, events and support.", ["https://see.oregonstate.edu/dce"]),
    ("Duo", "Technology", 1,
     "The two-step sign-in app that protects your OSU account.",
     "Use this to approve a sign-in or set up a new phone.", [_T + "services/duo"]),
    ("Ecampus", "Academic", 0,
     "OSU's online campus: online classes, degrees and support for online students.",
     "Use this to find online classes and services for online students.",
     ["https://ecampus.oregonstate.edu/services/student-services/", "https://ecampus.oregonstate.edu/soc/"]),
    ("Educational Opportunities Program", "Academic", 0,
     "A support program with advising and community for students who have had less access to college.",
     "Use this to ask about joining and the support it offers.", []),
    ("Emergency Loans", "Financial", 0,
     "Short-term loans from OSU for a sudden money need.",
     "Use this when you need a small amount quickly and can repay it soon.", [_F + "emergency-loans"]),
    ("FERPA", "Academic", 0,
     "The federal law that keeps your education records private.",
     "Use this to learn who can see your records and how to share them.", [_R + "FERPA"]),
    ("Final Exams", "Academic", 0,
     "The finals week schedule and the rules about final exams.",
     "Use this to find when your final is.", [_R + "exams/final-examination-schedule", _R + "exams"]),
    ("Financial Aid", "Financial", 0,
     "The office for grants, loans, work-study and the aid application.",
     "Use this to ask about your aid or what you still need to turn in.", [_FA]),
    ("Financial Aid Portal", "Financial", 1,
     "Where you see your aid offer, accept or decline aid, and find missing documents.",
     "Use this to accept your aid and check for anything missing.", [_FA]),
    ("Financial Literacy", "Financial", 0,
     "Lessons and tools about budgeting, credit and borrowing.",
     "Use this to learn how to manage money in college.", [_FA + "financial-literacy"]),
    ("Food@OSU", "Wellness", 0,
     "Where to eat on campus: dining halls, cafes, menus and hours.",
     "Use this to find what is open and what is on the menu.", ["https://food.oregonstate.edu/"]),
    ("ONID", "Technology", 1,
     "Your OSU username and account. It signs you in to almost everything.",
     "Use this to set up your account or change your password.",
     ["https://ecampus.oregonstate.edu/services/start/onid_sign_up.htm"]),
    ("Google Drive", "Technology", 1,
     "Google's file storage and documents under your OSU account.",
     "Use this to write and share documents for class.", []),
    ("Graduation Preparation", "Academic", 0,
     "The steps to graduate: applying, checking your degree and meeting deadlines.",
     "Use this when you are about two terms from finishing.", [_R + "graduating-from-osu"]),
    ("Handshake", "Academic", 1,
     "OSU's job and internship board.",
     "Use this to search and apply for jobs and internships.",
     ["https://career.oregonstate.edu/find-jobs-internships/handshake-job-tool"]),
    ("Health Insurance", "Wellness", 0,
     "Information about student health insurance and using your own plan at Student Health Services.",
     "Use this to check what your insurance covers on campus.", ["https://studenthealth.oregonstate.edu/insurance"]),
    ("Holcomb Center for Military & Veteran Resources", "Academic", 0,
     "The center that helps veterans, service members and their families with benefits and campus life.",
     "Use this to ask about education benefits or meet other veterans.", ["https://veterans.oregonstate.edu/"]),
    ("Honors College Advising", "Academic", 0,
     "Advisors for students in the Honors College.",
     "Use this to plan honors classes and your thesis.", ["https://honors.oregonstate.edu/current-students"]),
    ("Library tutorials guides study rooms and workshops", "Academic", 0,
     "The library's help for research, plus rooms you can book to study.",
     "Use this to book a study room or learn how to find sources.",
     ["https://library.oregonstate.edu/", "https://library.oregonstate.edu/study-rooms"]),
    ("Look Up Classes", "Academic", 0,
     "The search for classes offered in a term, with times, seats and instructors.",
     "Use this to find sections of a class before you register.", [_R + "registration"]),
    ("Math & Statistics Learning Center", "Academic", 0,
     "A drop-in center with tutors for math and statistics classes.",
     "Use this to get help with math homework.",
     ["https://math.oregonstate.edu/undergraduate/mathematics-statistics-learning-center"]),
    ("Math Placement Test", "Academic", 1,
     "The online test that decides which math class you can start in.",
     "Use this before you register for your first math class.",
     ["https://math.oregonstate.edu/undergraduate/math-placement-assessment"]),
    ("Microsoft Office 365", "Technology", 1,
     "Word, Excel, PowerPoint and other Microsoft tools that come with your OSU account.",
     "Use this to install Office or work in it online.", [_T + "services/microsoft-365"]),
    ("My Class Schedule", "Academic", 1,
     "Your own classes for a term, with times and rooms.",
     "Use this to see where and when your classes meet.", []),
    ("My Profile", "Academic", 1,
     "Your personal details on file: name, addresses, phone and emergency contact.",
     "Use this to update your address or phone number.", [_R + "biographical-information-updates"]),
    ("My Textbooks", "Academic", 1,
     "The books and materials for the classes you are registered in.",
     "Use this to see what to buy for each class.",
     ["https://ecampus.oregonstate.edu/services/student-services/textbooks.htm"]),
    ("MyDegrees", "Academic", 1,
     "Your degree checklist: what you have finished and what is still needed.",
     "Use this to see what you have left before you plan a term.", [_R + "mydegrees-planner"]),
    ("MyUHDS", "Wellness", 1,
     "The housing website where you apply for a room, pick a meal plan and manage your housing contract.",
     "Use this to apply for housing or change your meal plan.", ["https://uhds.oregonstate.edu/housing-portal"]),
    ("Office of Advocacy", "Getting Involved", 0,
     "A student government office that helps students who are in a dispute with the university.",
     "Use this if you face a conduct, grade or policy dispute and want someone on your side.",
     ["https://asosu.oregonstate.edu/"]),
    ("International Services", "Academic", 0,
     "The office that supports international students with immigration status and settling in.",
     "Use this for questions about your visa status or work rules.",
     ["https://internationalservices.oregonstate.edu/"]),
    ("Dean of Students", "Wellness", 0,
     "The office that helps students through emergencies, hard times and questions about student life.",
     "Use this when something serious is getting in the way of school.", ["https://studentlife.oregonstate.edu/"]),
    ("Registrar", "Academic", 0,
     "The office that keeps your records and runs registration, transcripts and graduation.",
     "Use this for questions about registering, records or deadlines.", [_R]),
    ("On Campus Employment", "Financial", 0,
     "Jobs for students at OSU, including work-study jobs.",
     "Use this to find a job on campus.",
     ["https://career.oregonstate.edu/find-jobs-internships/internships-campus-jobs-research"]),
    ("Orange Cash", "Financial", 1,
     "Money you load onto your OSU ID card to spend on campus.",
     "Use this to add money or check your balance.", ["https://food.oregonstate.edu/orange-cash"]),
    ("Order Official Transcript", "Academic", 1,
     "Where you order a certified copy of your OSU record to send to a school or an employer.",
     "Use this when someone asks for a transcript sent by the university.", [_R + "transcripts"]),
    ("Oregon Residency Affidavits", "Financial", 0,
     "The form used to show you qualify for in-state tuition.",
     "Use this if you think you should be charged resident tuition.", ["https://admissions.oregonstate.edu/residency"]),
    ("OSU Alerts", "Technology", 1,
     "Emergency text, phone and email alerts from OSU.",
     "Use this to choose how emergency alerts reach you.", []),
    ("Campus Map", "Transportation", 0,
     "A map of campus buildings, parking and accessible routes.",
     "Use this to find a building or the nearest parking.", ["https://map.oregonstate.edu/"]),
    ("OSU Email", "Technology", 1,
     "Your OSU email account, where the university sends its notices.",
     "Use this to read messages from instructors and offices.", [_T + "services/email"]),
    ("Events Calendar", "Getting Involved", 0,
     "A calendar of events on campus.",
     "Use this to find something to do this week.", [_T + "services/osu-events-calendar"]),
    ("Parking & Transportation", "Transportation", 0,
     "Parking permits, the campus shuttle, bikes and buses.",
     "Use this to buy a permit or plan how to get to campus.",
     ["https://transportation.oregonstate.edu/", "https://transportation.oregonstate.edu/parking"]),
    ("Pay My Bill", "Financial", 1,
     "Where you pay what you owe OSU for tuition, fees, housing and dining.",
     "Use this to make a payment or set up a payment plan.", [_F + "student-accounts/student-billing"]),
    ("Petition for Late Change of Registration", "Academic", 0,
     "A request to add, drop or withdraw from a class after the deadline.",
     "Use this when something outside your control made you miss a registration deadline.",
     [_R + "late-change-registration"]),
    ("Priority Registration", "Academic", 0,
     "The schedule that decides which day you can start registering, based on your credits and group.",
     "Use this to find the day and time your registration opens.", [_R + "what-is-priority-registration"]),
    ("Public Safety", "Wellness", 0,
     "OSU's campus police and safety office.",
     "Use this to report a safety concern or find safety services.", ["https://publicsafety.oregonstate.edu/"]),
    ("Recreational Sports", "Wellness", 0,
     "The gym, pool, climbing wall, fitness classes and intramural sports.",
     "Use this to work out, join a class or play on a team.", ["https://recsports.oregonstate.edu/"]),
    ("Register/Add/Drop Classes", "Academic", 1,
     "Where you sign up for classes and add or drop them.",
     "Use this when your registration time opens.", [_R + "register", _R + "registration"]),
    ("SafeRide", "Transportation", 0,
     "A night ride service for students, run by student government.",
     "Use this to get a ride home at night.", []),
    ("Schedule of Classes: Scheduler", "Academic", 1,
     "A tool that builds possible weekly schedules from the classes you want.",
     "Use this to compare schedules before you register.", [_R + "scheduler"]),
    ("ScholarDollars", "Financial", 1,
     "OSU's scholarship application. One application matches you to many scholarships.",
     "Use this to apply for OSU scholarships each year.", ["https://scholarships.oregonstate.edu/scholardollars"]),
    ("Scholarships", "Financial", 0,
     "The office and information for OSU scholarships.",
     "Use this to see which scholarships exist and their deadlines.", ["https://scholarships.oregonstate.edu/"]),
    ("Service Desk", "Technology", 0,
     "OSU's help desk for accounts, sign-in, software and device problems.",
     "Use this when you cannot sign in or a tool will not work.", [_T + "help"]),
    ("Student Financial Services Agreement", "Financial", 1,
     "A yearly agreement about paying your bill that you accept before you can register.",
     "Use this if a hold says you need to accept the agreement.",
     ["https://holds.oregonstate.edu/hold/student-finance-agreement-hold"]),
    ("Software List", "Technology", 0,
     "The software OSU offers students for free or at a lower price.",
     "Use this before you buy software for a class.", [_T]),
    ("Enrollment Verification", "Academic", 1,
     "A letter that proves you are enrolled, for insurance, loans or a job.",
     "Use this when someone asks for proof that you are a student.", [_R + "verify-your-enrollment"]),
    ("Statement of Degree", "Academic", 1,
     "A letter that proves you finished your degree before your diploma arrives.",
     "Use this when an employer or school needs proof of your degree.", [_R + "verifying-and-statement-of-degree"]),
    ("Student Billing", "Financial", 0,
     "How OSU bills you: what is on a bill, when it is due and how to pay.",
     "Use this to understand a charge or a due date.", [_F + "student-accounts/student-billing"]),
    ("Student Care", "Wellness", 0,
     "A team that helps students through a crisis or a hard stretch and connects them with support.",
     "Use this if you or a friend is struggling and you are not sure where to start.",
     ["https://care.oregonstate.edu/"]),
    ("Student Community Standards", "Academic", 0,
     "The office for the student conduct code and academic integrity.",
     "Use this if you got a conduct notice or want to understand the code.", ["https://scs.oregonstate.edu/"]),
    ("Student Consent to Release", "Academic", 1,
     "Lets you name people, such as a parent, who may be given information from your records.",
     "Use this if you want a family member to be able to talk with OSU about your account.",
     [_R + "access-to-your-records"]),
    ("Student Health Services", "Wellness", 0,
     "The campus clinic for medical care, vaccines and a pharmacy.",
     "Use this to make a medical appointment.", ["https://studenthealth.oregonstate.edu/"]),
    ("Student Jobs", "Financial", 0,
     "Listings for jobs open to students.",
     "Use this to look for part-time work.", ["https://career.oregonstate.edu/find-jobs-internships"]),
    ("Student Learning Experience Survey", "Academic", 1,
     "The end-of-term survey where you give feedback on your classes.",
     "Use this in the last weeks of the term to rate each class.",
     ["https://ecampus.oregonstate.edu/services/start/online-course-evaluation.htm"]),
    ("Study Abroad", "Academic", 0,
     "Programs for studying, interning or doing research in another country.",
     "Use this to explore programs and how aid applies to them.", [_FA + "study-abroad"]),
    ("Tax Information", "Financial", 0,
     "Information about taxes on scholarships and payments from OSU.",
     "Use this at tax time to see what counts as income.",
     [_F + "student-accounts/student-payment-taxability-resource"]),
    ("1098T Forms", "Financial", 1,
     "The yearly tax form that shows what you paid in tuition.",
     "Use this when you or your family file taxes.", [_F + "student-accounts/1098t-tuition-statement"]),
    ("Third-Party Billing", "Financial", 0,
     "Lets an employer or agency be billed for your tuition instead of you.",
     "Use this if a sponsor has agreed to pay your tuition.", [_F + "student-accounts/third-party-billing"]),
    ("Transfer Credit Tools", "Academic", 0,
     "Tools that show how classes from other schools count at OSU.",
     "Use this to check a class before you take it somewhere else.",
     ["https://transfer.oregonstate.edu/transfer-credit-central",
      "https://admissions.oregonstate.edu/credit-articulation-tables"]),
    ("TRiO", "Academic", 0,
     "A support program with advising and tutoring for first-generation students, students with lower incomes "
     "and students with disabilities.",
     "Use this to ask whether you can join and what support it offers.", []),
    ("Tuition & Fee Tables", "Financial", 0,
     "The tables that list tuition and fees by campus, level and number of credits.",
     "Use this to estimate what a term will cost.", [_F + "student-accounts/student-fee-information"]),
    ("Tutoring Services", "Academic", 0,
     "Places on campus and online where you can get help with a class.",
     "Use this to find tutoring for a subject.",
     ["https://library.oregonstate.edu/valley/spaces/tutoring", "https://success.oregonstate.edu/"]),
    ("Planned Educational Leave", "Academic", 0,
     "A way to take planned time away from OSU and keep your place when you return.",
     "Use this before you take a term or more off.", [_R + "undergraduate-planned-educational-leave-program"]),
    ("Undergraduate Research", "Academic", 0,
     "The office that helps undergraduates find research projects and funding.",
     "Use this to find a research mentor or a paid project.", ["https://undergradresearch.oregonstate.edu/"]),
    ("University Housing & Dining", "Wellness", 0,
     "The office for residence halls, meal plans and dining centers.",
     "Use this for questions about your room or meal plan.", ["https://uhds.oregonstate.edu/"]),
    ("University Ombuds", "Wellness", 0,
     "A confidential, neutral office that helps people work through conflicts at OSU.",
     "Use this to talk through a conflict in private.", []),
    ("Unofficial Transcripts", "Academic", 1,
     "A copy of your grades and classes that you can view or print yourself.",
     "Use this when you just need to see your record or share an informal copy.", [_R + "transcripts"]),
    ("Veterans tuition forms", "Financial", 1,
     "The forms veterans and military families use to have education benefits applied to a term.",
     "Use this each term so your benefits are certified.", [_R + "veterans"]),
    ("View Account Statements", "Financial", 1,
     "Your monthly billing statements from OSU.",
     "Use this to download a statement.", [_F + "student-accounts/student-billing"]),
    ("Withdrawal from Term Survey", "Academic", 1,
     "The survey that starts a withdrawal from every class in a term.",
     "Use this only if you need to leave all of your classes this term. Talk with your advisor first.",
     [_R + "withdraw"]),
    ("Workday", "Technology", 1,
     "The system student employees use for hiring paperwork, hours and pay.",
     "Use this if you have a campus job.", [_T + "services/workday"]),
    ("Writing Center", "Academic", 0,
     "Free help with any piece of writing, at any stage.",
     "Use this to get feedback on a paper or a resume.", ["https://writingcenter.oregonstate.edu/"]),
    ("Zoom", "Technology", 1,
     "Video meetings under your OSU account.",
     "Use this for online classes, office hours and advising meetings.", [_T + "services/zoom"]),
]

# Names that lead to the same job. A name outside RESOURCES is kept as another name students may see.
SAME_AS_GROUPS = [
    ["Look Up Classes", "Course Search", "Schedule of Classes: Scheduler"],
    ["Pay My Bill", "Student Billing", "View Student Account Information", "View Account Statements",
     "Account Summary by Term"],
    ["Emergency Loans", "Emergency Loan Eligibility"],
    ["Financial Literacy", "Center for Advancing Financial Education"],
    ["Scholarships", "ScholarDollars"],
    ["Financial Aid", "Financial Aid Portal"],
    ["Order Official Transcript", "Unofficial Transcripts"],
    ["Diversity & Cultural Engagement", "Cultural Resource Centers"],
    ["Disability Access Services", "DAS Forms", "DAS Testing Center"],
    ["Student Jobs", "On Campus Employment", "Handshake"],
    ["Check Your Registration Status", "Priority Registration"],
    ["Tutoring Services", "Academic Success Center"],
    ["Tax Information", "1098T Forms"],
    ["Graduation Preparation", "Commencement"],
    ["FERPA", "Student Consent to Release"],
    ["Enrollment Verification", "Statement of Degree"],
    ["University Housing & Dining", "MyUHDS"],
    ["Office of Advocacy", "Associated Students of OSU"],
    ["Baccalaureate Core Courses", "Core Education"],
    ["Register/Add/Drop Classes", "Change Credits"],
]

_BASIC = ["Full name", "Student ID", "Email"]
_SIGN = ["Signature", "Date"]
_RF = _R + "sites/registrar.oregonstate.edu/files/forms/"

# (name, purpose, goes_to, when_to_use, kind, fields, candidate URLs). Kept only when a URL is in the crawl.
FORMS = [
    ("Change of Grading Basis", "Switches one class between a letter grade (A-F) and S/U grading.",
     "Office of the Registrar", "Before the S/U deadline for the term, after you talk with your advisor.", "Page",
     _BASIC + ["Term", "Course", "CRN", "Advisor"] + _SIGN, [_R + "change-grading-basis"]),
    ("Petition for Late Change of Registration",
     "Asks to add, drop or withdraw from a class after the deadline has passed.", "Office of the Registrar",
     "When something outside your control kept you from making the change on time.", "Page",
     _BASIC + ["Term", "Course", "CRN", "Reason", "Advisor"] + _SIGN, [_R + "late-change-registration"]),
    ("Contract for Completion of Incomplete Grade",
     "Sets out the work you still owe in a class and the date you will finish it.",
     "Your instructor, then the Office of the Registrar",
     "When you cannot finish a class on time for a reason your instructor accepts.", "PDF",
     _BASIC + ["Term", "Course", "CRN", "Reason"] + _SIGN,
     [_RF + "contract-for-completion-of-incomplete-i-grade.pdf", _R + "incomplete-grades"]),
    ("Extension of Time to Remove Incomplete Grade Petition",
     "Asks for more time to finish the work for an incomplete grade.", "Office of the Registrar",
     "When the deadline to finish an incomplete is close and you need longer.", "PDF",
     _BASIC + ["Term", "Course", "Reason"] + _SIGN,
     [_RF + "extension-of-time-to-remove-incomplete-grade-petition.pdf"]),
    ("Examination for Credit or Waiver",
     "Asks to earn credit for a class, or have it waived, by passing an exam instead of taking it.",
     "Office of the Registrar", "When you already know the material of a class your program requires.", "PDF",
     _BASIC + ["Major", "Term", "Course"] + _SIGN, [_RF + "examination-for-credit-or-waiver.pdf"]),
    ("Petition for Exception to OSU Reinstatement Regulations",
     "Asks to return sooner than the rules allow after an academic suspension.", "Office of the Registrar",
     "After a suspension, when you believe your situation has changed.", "PDF",
     _BASIC + ["Major", "Term", "Reason", "Advisor"] + _SIGN,
     [_RF + "petition-for-exception-osu-reinstatement-regulations_0.pdf",
      _RF + "petition-for-exception-osu-reinstatement-regulations.pdf", _R + "academic-suspension-and-reinstatement"]),
    ("Readmission", "Reopens your record so you can register after time away from OSU.",
     "Office of the Registrar", "When you have been away for several terms and want to come back.", "Page",
     _BASIC + ["Major", "Term"], [_R + "readmission"]),
    ("Planned Educational Leave", "Holds your place at OSU while you take planned time away.",
     "Office of the Registrar", "Before a term or more away for work, family, health or travel.", "Page",
     _BASIC + ["Major", "Term", "Reason"] + _SIGN, [_R + "undergraduate-planned-educational-leave-program"]),
    ("Enrollment Verification", "Gives you a letter that proves you are enrolled.", "Office of the Registrar",
     "When an insurer, lender, landlord or employer asks for proof that you are a student.", "Page",
     _BASIC + ["Term"], [_R + "verify-your-enrollment"]),
    ("Transcript Request", "Orders a copy of your OSU academic record.", "Office of the Registrar",
     "When a school, employer or scholarship asks for your transcript.", "Page", _BASIC, [_R + "transcripts"]),
    ("Statement of Degree", "Gives you a letter that proves you finished your degree.", "Office of the Registrar",
     "After your last term, when you need proof before your diploma arrives.", "Page",
     _BASIC + ["Major", "Term"], [_R + "verifying-and-statement-of-degree"]),
    ("Student Consent to Release Information",
     "Names the people who may be given information from your education records.", "Office of the Registrar",
     "When you want a parent, partner or sponsor to be able to talk with OSU about you.", "Page",
     _BASIC + _SIGN, [_R + "access-to-your-records", _R + "FERPA"]),
    ("Oregon Residency Affidavit", "States the facts that show you qualify for in-state tuition.",
     "Office of Admissions", "When you believe you should be charged resident tuition.", "PDF",
     _BASIC + ["Term"] + _SIGN,
     ["https://admissions.oregonstate.edu/sites/admissions.oregonstate.edu/files/residency_affidavit.pdf",
      "https://admissions.oregonstate.edu/residency"]),
    ("Satisfactory Academic Progress Appeal",
     "Asks to keep your financial aid after your grades or pace fell below the aid rules.", "Financial Aid",
     "When you get a notice that your aid is suspended for academic progress.", "Page",
     _BASIC + ["Major", "Term", "Reason", "Advisor"] + _SIGN, [_FA + "satisfactory-academic-progress"]),
    ("Special Conditions Appeal", "Asks Financial Aid to look again at your aid after your finances change.",
     "Financial Aid", "After a job loss, big medical bills or another change in your family's income.", "Page",
     _BASIC + ["Term", "Reason"] + _SIGN,
     [_FA + "special-conditions-appeal-changes-your-financial-situation"]),
    ("Emergency Loan Request", "Asks for a short-term loan from OSU.", "Student Accounts",
     "When you have a sudden cost and can repay within the term.", "Page",
     _BASIC + ["Term", "Reason"], [_F + "emergency-loans"]),
    ("1098-T Tuition Statement", "Gets the tax form that shows the tuition you paid in a year.",
     "Student Accounts", "At tax time, if you or your family claim an education credit.", "Page", _BASIC,
     [_F + "student-accounts/1098t-tuition-statement"]),
    ("Third-Party Billing Authorization", "Has an employer or agency billed for your tuition.",
     "Student Accounts", "When a sponsor has agreed in writing to pay your tuition.", "Page",
     _BASIC + ["Term"], [_F + "student-accounts/third-party-billing"]),
    ("Tuition Refund Appeal", "Asks for tuition back after you dropped or withdrew past the refund date.",
     "Student Accounts", "When illness or another serious event forced you to leave classes late.", "Page",
     _BASIC + ["Term", "Course", "Reason"] + _SIGN, [_F + "student-accounts/tuition-refund-appeal"]),
    ("Payment Plan Enrollment", "Splits a term's bill into smaller payments.", "Student Accounts",
     "When you cannot pay the whole bill by the due date.", "Page", _BASIC + ["Term"],
     [_F + "student-accounts/payment-plans"]),
    ("Disability Access Services Application", "Starts a request for accommodations.",
     "Disability Access Services", "When a disability or health condition affects classes, exams or housing.",
     "Page", _BASIC + ["Term", "Reason"], ["https://ds.oregonstate.edu/gettingstarted",
                                           "https://ds.oregonstate.edu/getting-started-das-1"]),
    ("DAS Documentation Information Form", "Lets a health provider describe how a condition affects you.",
     "Disability Access Services", "When DAS asks for documentation to support an accommodation.", "PDF",
     ["Full name", "Student ID", "Date"],
     ["https://ds.oregonstate.edu/sites/ds.oregonstate.edu/files/2025-04/dasdocform_19.pdf"]),
    ("Graduation Application", "Tells OSU you plan to finish, so your degree can be checked.",
     "Office of the Registrar", "About two terms before your last term.", "Page",
     _BASIC + ["Major", "Class standing", "Term"], [_R + "graduating-from-osu"]),
    ("Change of Major, Minor or Option", "Adds, drops or changes your major, minor or option.",
     "Your college advising office", "After you talk with an advisor in the program you want.", "Page",
     _BASIC + ["Major", "Class standing", "Advisor"], [_R + "change-academic-program"]),
    ("Joint Campus Registration", "Registers you for a class at another Oregon public university while at OSU.",
     "Office of the Registrar", "When a class you need is offered at a partner campus.", "PDF",
     _BASIC + ["Term", "Course"] + _SIGN, [_RF + "joint-campus-registration.pdf"]),
    ("Audit Registration", "Signs you up to sit in on a class without earning credit.", "Office of the Registrar",
     "When you want to follow a class without a grade.", "Page", _BASIC + ["Term", "Course", "CRN"] + _SIGN,
     [_R + "audit-registration"]),
    ("Transfer Course Equivalency Petition", "Asks OSU to look again at how a class from another school counts.",
     "Office of Admissions", "When a transfer class came in as general credit and you think it matches an OSU class.",
     "PDF", _BASIC + ["Major", "Course", "Reason"] + _SIGN,
     ["https://admissions.oregonstate.edu/sites/admissions.oregonstate.edu/files/2024-01/"
      "transfer_course_equivalency_petition.pdf"]),
    ("Withdrawal from the Term", "Withdraws you from every class in the term.", "Office of the Registrar",
     "Only when you need to leave all of your classes. Talk with your advisor and Financial Aid first.", "Page",
     _BASIC + ["Term", "Reason"], [_R + "withdraw"]),
    ("Restriction Override Request", "Asks a department to let you into a class that is restricted or full.",
     "The department that offers the class", "When registration blocks you from a class you are ready for.", "Page",
     _BASIC + ["Term", "Course", "CRN", "Reason"], [_R + "restriction-overrides"]),
    ("Personal Information Update", "Changes the name, address or phone number OSU has for you.",
     "Office of the Registrar", "After you move or change your name.", "Page", _BASIC + ["Date"],
     [_R + "biographical-information-updates"]),
]


def resource_rows(page_urls: set) -> list[tuple]:
    known = [r[0] for r in RESOURCES]
    rows = []
    for name, category, login, plain, use_for, urls in RESOURCES:
        same = []
        for group in SAME_AS_GROUPS:
            if name in group:
                same.extend(x for x in group if x != name and x not in same)
        url = next((u for u in urls if u in page_urls), None)
        rows.append((name, plain, use_for, ", ".join(same) or None, category, login, url))
    assert len(set(known)) == len(known)
    return rows


def form_rows(page_urls: set, doc_urls: set) -> list[tuple]:
    rows = []
    for name, purpose, goes_to, when, kind, fields, urls in FORMS:
        url = next((u for u in urls if u in page_urls or u in doc_urls), None)
        if not url:
            continue
        if not url.lower().endswith(".pdf") and kind == "PDF":
            kind = "Page"
        rows.append((name, purpose, goes_to, when, url, kind, json.dumps(fields)))
    return rows


# ======================================================================================================
# Writing the database
# ======================================================================================================

TABLES = ["meta", "courses", "prerequisites", "course_attributes", "programs", "program_requirements",
          "requirement_courses", "terms", "sections", "meetings", "linked_sections", "students", "student_courses",
          "student_holds", "student_tasks", "appointments", "advisor_slots", "balances", "transactions",
          "resources", "forms"]


def _replace_file(tmp: str, out_path: str, log=print):
    """Move the finished file into place in one step, so a half-built database is never visible.

    On Windows the move fails while another program (the demo server) has the old file open. Then the new
    contents are copied in through SQLite's backup API instead, which swaps them in as one transaction.
    """
    last = None
    for _ in range(4):
        try:
            os.replace(tmp, out_path)
            return
        except PermissionError as exc:
            last = exc
            time.sleep(0.5)
    try:
        src = sqlite3.connect(tmp)
        dst = sqlite3.connect(out_path, timeout=60)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        os.remove(tmp)
        log("note: %s was open in another program, so its contents were replaced in place" % out_path)
    except Exception as exc:
        raise RuntimeError("Could not replace %s (is another program holding it open?): %s; %s"
                           % (out_path, last, exc))


def _insert_catalog(con: sqlite3.Connection, cat: Catalog):
    courses, prereqs, attrs = [], [], []
    for code in sorted(cat.courses):
        c = cat.courses[code]
        courses.append((code, c["subject"], c["subject_name"], c["number"], c["level"], c["title"], c["credits_text"],
                        c["credits_min"], c["credits_max"], c["description"], c["prereq_text"], c["coreq_text"],
                        c["recommended_text"], c["equivalent_text"], c["repeatable_text"], c["ecampus"], c["honors"],
                        c["catalog_url"], c["retrieved_at"]))
        for kind, text in (("prereq", c["prereq_text"]), ("coreq", c["coreq_text"])):
            for r in parse_prereq_text(text):
                prereqs.append((code, kind, r["group_no"], r["req_code"], r["min_grade"], r["concurrent"], r["note"]))
        for attr_code, attr_name in c["attrs"]:
            attrs.append((code, attr_code, attr_name))
    con.executemany("INSERT INTO courses VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", courses)
    con.executemany("INSERT INTO prerequisites (course_code, kind, group_no, req_code, min_grade, concurrent, note) "
                    "VALUES (?,?,?,?,?,?,?)", prereqs)
    con.executemany("INSERT INTO course_attributes VALUES (?,?,?)", attrs)
    programs, reqs, req_courses = [], [], []
    for p in cat.programs:
        programs.append((p["id"], p["name"], p["kind"], p["degree"], p["level"], p["college"], p["parent_id"],
                         p["total_credits"], p["ecampus"], p["catalog_url"]))
        for r in p["reqs"]:
            reqs.append((r["id"], p["id"], r["block"], r["seq"], r["kind"], r["label"], r["credits"],
                         r["pick_count"], r["plan_year"], r["plan_term"]))
            for code, with_code in r["courses"]:
                req_courses.append((r["id"], code, with_code))
    con.executemany("INSERT INTO programs VALUES (?,?,?,?,?,?,?,?,?,?)", programs)
    con.executemany("INSERT INTO program_requirements VALUES (?,?,?,?,?,?,?,?,?,?)", reqs)
    con.executemany("INSERT INTO requirement_courses VALUES (?,?,?)", req_courses)


def _insert_schedule(con: sqlite3.Connection, sched: Schedule):
    con.executemany(
        "INSERT INTO sections VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(s["crn"], s["term_code"], s["course_code"], s["section"], s["schedule_type"], s["method"], s["campus"],
          s["session"], s["credits"], s["grade_mode"], s["instructor"], s["seats_total"], s["seats_taken"],
          s["wait_cap"], s["wait_count"], s["fee"], s["restrictions"], s["is_primary"]) for s in sched.sections])
    con.executemany("INSERT INTO meetings (crn, days, start_min, end_min, start_date, end_date, building, room) "
                    "VALUES (?,?,?,?,?,?,?,?)", sched.meetings)
    con.executemany("INSERT INTO linked_sections VALUES (?,?)", sched.links)


def _insert_students(con: sqlite3.Connection, cat: Catalog, sched: Schedule, plans: list, rng: random.Random,
                     page_urls: set, log=print) -> dict:
    used_terms = set()
    programs_used = {}
    for sid, plan in enumerate(plans, 1):
        spec, program = plan.spec, plan.program
        current = [r for r in plan.rows if r["status"] == "in_progress"]
        picks = sched.pick(rng, CURRENT_TERM, [(r["course_code"], plan.campus) for r in current])
        for r in current:
            r["crn"], r["linked_crn"] = picks.get(r["course_code"], (None, None))
        stats = plan.grade(spec["gpa_target"] or 3.0, spec["major_gpa_target"])
        college = program.get("college")
        office = ("%s advising" % college) if college else "Academic advising"
        advisor = spec["advisor_name"]
        programs_used[spec["slug"]] = program["name"] + ("" if plan.exact else " (fallback)")
        con.execute(
            "INSERT INTO students VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (sid, spec["slug"], spec["first_name"], spec["last_name"], spec["pronouns"],
             "%s.%s@example.com" % (spec["first_name"].lower(), spec["last_name"].lower()), spec["sample_id"],
             program["id"], None, spec["standing"], spec["campus"], spec["is_transfer"], stats["gpa"],
             stats["major_gpa"], stats["credits_earned"], spec["academic_standing"], advisor, office,
             spec["reg_weekday"], spec["reg_time"], spec["situation"], spec["blurb"]))
        order = {"transfer": 0, "completed": 1, "in_progress": 2, "planned": 3}
        for r in sorted(plan.rows, key=lambda r: (order[r["status"]], r["term_code"] or "", r["_order"])):
            if r["term_code"]:
                used_terms.add(r["term_code"])
            con.execute(
                "INSERT INTO student_courses (student_id, course_code, title, term_code, status, grade, credits, crn, "
                "linked_crn, transfer_from, requirement_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (sid, r["course_code"], r["title"], r["term_code"], r["status"], r["grade"], r["credits"], r["crn"],
                 r["linked_crn"], r["transfer_from"], r["requirement_id"]))
        for h in spec["holds"]:
            url = next((u for u in h["urls"] if u in page_urls), None)
            con.execute(
                "INSERT INTO student_holds (student_id, type, title, reason, office, how_to_clear, "
                "blocks_registration, placed_offset_days, info_url) VALUES (?,?,?,?,?,?,?,?,?)",
                (sid, h["type"], h["title"], h["reason"], h["office"].replace("{office}", office), h["how_to_clear"],
                 h["blocks"], h["placed"], url))
        for title, detail, due, status, kind in spec["tasks"]:
            con.execute("INSERT INTO student_tasks (student_id, title, detail, due_offset_days, status, kind) "
                        "VALUES (?,?,?,?,?,?)", (sid, title, detail, due, status, kind))
        for who, role, topic, offset, start, minutes, mode, location, status in spec["appointments"]:
            con.execute(
                "INSERT INTO appointments (student_id, with_name, with_role, topic, offset_days, start_time, minutes, "
                "mode, location, status) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (sid, who.replace("{advisor}", advisor), role, topic, offset, start, minutes, mode,
                 location.replace("{office}", office), status))
        for offset, start, minutes, mode in spec["slots"]:
            location = {"In person": office, "Zoom": "Zoom link sent by email",
                        "Phone": "Your advisor calls the number on file"}[mode]
            con.execute("INSERT INTO advisor_slots (student_id, offset_days, start_time, minutes, mode, location) "
                        "VALUES (?,?,?,?,?,?)", (sid, offset, start, minutes, mode, location))
        b = spec["balance"]
        balance = round(sum(amount for _o, _d, amount in spec["transactions"]), 2)
        con.execute("INSERT INTO balances VALUES (?,?,?,?,?,?,?,?)",
                    (sid, CURRENT_TERM, balance, b["due"], b["past_due"], b["plan"], b["meal"], b["orange"]))
        for offset, description, amount in spec["transactions"]:
            con.execute("INSERT INTO transactions (student_id, term_code, offset_days, description, amount) "
                        "VALUES (?,?,?,?,?)", (sid, CURRENT_TERM, offset, description, amount))
    demo_codes = {t[0] for t in DEMO_TERMS}
    con.executemany("INSERT INTO terms VALUES (?,?,?,?,?,?,?)",
                    [_past_term(code) for code in sorted(used_terms - demo_codes)] + DEMO_TERMS)
    return programs_used


def build(out_path=DEFAULT_OUT, source_path=DEFAULT_SOURCE, seed: int = DEFAULT_SEED, log=print,
          min_sections: int = MIN_SECTIONS, max_sections: int | None = MAX_SECTIONS) -> dict:
    """Build the demo database from scratch and return its row counts.

    out_path      where demo.db goes (written to a temp file beside it, then moved into place)
    source_path   the crawl database; opened read-only, never written
    seed          one seed for every invented value: the same seed gives the same rows
    log           a function taking one string (print), or None for silence
    min_sections / max_sections   the size check on the sections table; tests relax it (0 and None)

    Returns {table: row count, ..., "student_programs": {slug: program name}, "seconds": float,
    "zero_requirement_programs": int, "path": str}.
    """
    log = log or (lambda *_a: None)
    started = time.time()
    out_path, source_path = os.fspath(out_path), os.fspath(source_path)
    rng = random.Random(seed)

    src = load_source(source_path)
    cat = build_catalog(src, log)
    if not cat.courses:
        raise RuntimeError("No catalog course pages were found in %s" % source_path)
    plans = plan_students(cat, rng, log)
    force: dict[tuple, set] = {}
    for plan in plans:
        for term, code, campus in plan.forces():
            force.setdefault((term, code), set()).add(campus)
    sched = Schedule(cat, rng, force, log).generate()
    count = len(sched.sections)
    if count < min_sections or (max_sections is not None and count > max_sections):
        raise RuntimeError("Generated %d sections, outside the expected %s to %s. Adjust the schedule knobs."
                           % (count, min_sections, max_sections))

    out_dir = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(out_dir, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".demo-build-", suffix=".tmp", dir=out_dir)
    os.close(fd)
    con = None
    try:
        con = sqlite3.connect(tmp)
        with open(SCHEMA_PATH, encoding="utf-8") as fh:
            con.executescript(fh.read())
        _insert_catalog(con, cat)
        _insert_schedule(con, sched)
        programs_used = _insert_students(con, cat, sched, plans, rng, src["page_urls"], log)
        con.executemany("INSERT INTO resources (name, plain, use_for, same_as, category, needs_login, url) "
                        "VALUES (?,?,?,?,?,?,?)", resource_rows(src["page_urls"]))
        con.executemany("INSERT INTO forms (name, purpose, goes_to, when_to_use, url, kind, fields) "
                        "VALUES (?,?,?,?,?,?,?)", form_rows(src["page_urls"], src["doc_urls"]))
        built_at = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()
        con.executemany("INSERT INTO meta VALUES (?,?)", [
            ("seed", str(seed)), ("built_at", built_at), ("schema_version", SCHEMA_VERSION),
            ("courses", str(len(cat.courses))), ("programs", str(len(cat.programs))), ("sections", str(count)),
            ("catalog_retrieved", cat.retrieved or ""),
            ("note", "Sample data. Course and program facts come from the public catalog; sections, students and "
                     "everything about them are invented."),
        ])
        con.commit()
        counts = {t: con.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0] for t in TABLES}
        con.close()
        con = None
        _replace_file(tmp, out_path, log)
    except BaseException:
        if con is not None:
            con.close()
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    counts["student_programs"] = programs_used
    counts["zero_requirement_programs"] = cat.zero_requirement_programs
    counts["seconds"] = round(time.time() - started, 1)
    counts["path"] = out_path
    log("wrote %s: %d courses, %d programs, %d sections in %.1f s"
        % (out_path, counts["courses"], counts["programs"], counts["sections"], counts["seconds"]))
    return counts


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m beaverbot.demo.generate",
        description="Build the Beaver Bot demo database (sample data only). No network access.")
    parser.add_argument("--out", default=DEFAULT_OUT, help="where to write the database (default: %(default)s)")
    parser.add_argument("--source", default=DEFAULT_SOURCE,
                        help="the crawl database, opened read-only (default: %(default)s)")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="random seed (default: %(default)s)")
    parser.add_argument("--quiet", action="store_true", help="print nothing unless something fails")
    args = parser.parse_args(argv)
    counts = build(args.out, args.source, seed=args.seed, log=None if args.quiet else print)
    if not args.quiet:
        for table in TABLES:
            print("  %-22s %d" % (table, counts[table]))
        for slug, name in counts["student_programs"].items():
            print("  student %-14s %s" % (slug, name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
