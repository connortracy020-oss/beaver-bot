"""The demo database generator: the catalog parsers on inline text, a full build from a tiny fake catalog in a
temporary folder, and (only when data/demo.db exists) checks on the real build. No network, no real database."""
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path

from beaverbot.demo import generate as g

EN_DASH = "–"

SUBJECT_CS = f"""# Computer Science (CS)
CS Course Schedule

## CS LDEA, LOWER DIVISION ED ABROAD, 0-16 Credits
This course is repeatable for 99 credits.

## CS 161, INTRODUCTION TO COMPUTER SCIENCE I, 4 Credits
Overview of fundamental concepts of computer science.
Includes algorithm design.
Prerequisite: MTH 112 (may be taken concurrently) with C or better or MTH 112Z (may be taken concurrently) with C or better or Math Placement Test with a score of 33
Available via Ecampus

## CS 162, INTRODUCTION TO COMPUTER SCIENCE II, 4 Credits
Basic programming techniques.
Prerequisite: CS 161 with C or better
Equivalent to: CS 162H
Available via Ecampus

## CS 162H, INTRODUCTION TO COMPUTER SCIENCE II, 4 Credits
Basic programming techniques.
Attributes: HNRS {EN_DASH} Honors Course Designator
Prerequisite: CS 161 with C or better
Equivalent to: CS 162

## CS 199, SPECIAL TOPICS/COMPUTER SCIENCE, 1-16 Credits
This course is repeatable for 16 credits.

## CS 225, DISCRETE STRUCTURES IN COMPUTER SCIENCE, 4 Credits
Logic, sets and proofs.
Available via Ecampus

## CS 261, DATA STRUCTURES, 4 Credits
Lists, trees and graphs.
Prerequisite: (CS 162 with C or better or CS 162H with C or better) and (CS 225 [C] or MTH 231 [C])
Available via Ecampus

## CS 290, WEB DEVELOPMENT, 4 Credits
Web applications.
Recommended: CS 162

## CS 340, INTRODUCTION TO DATABASES, 4 Credits
Database design.
Corequisites: CS 290

## CS 391, *SOCIAL AND ETHICAL ISSUES IN COMPUTER SCIENCE, 3 Credits
Ethics in computing.
Attributes: CFSS {EN_DASH} Core Ed - Social Science

## CS 401, RESEARCH, 1-16 Credits
This course is repeatable for 16 credits.
"""

SUBJECT_MTH = f"""# Mathematics (MTH)

## MTH 105Z, +*MATH IN SOCIETY, 4 Credits
Mathematics for everyday life.
Attributes: CFQL {EN_DASH} Core Ed - Quantitative Literacy & Analysis; CSMA {EN_DASH} Bacc Core, Skills, Math
Recommended: MTH 095 or MTH 103

## MTH 112Z, +*PRECALCULUS II: TRIGONOMETRY, 4 Credits
Trigonometry.
Attributes: CFQL {EN_DASH} Core Ed - Quantitative Literacy & Analysis

## MTH 231, ELEMENTS OF DISCRETE MATHEMATICS, 4 Credits
Discrete mathematics.

## MTH 251Z, +*DIFFERENTIAL CALCULUS, 4 Credits
Derivatives.
Attributes: CFQL {EN_DASH} Core Ed - Quantitative Literacy & Analysis
Prerequisite: MTH 112Z with C- or better
Available via Ecampus

## MTH 252Z, INTEGRAL CALCULUS, 4 Credits
Integrals.
Prerequisite: MTH 251Z with C- or better
Available via Ecampus

## MTH 254, VECTOR CALCULUS I, 4 Credits
Vectors.
Prerequisite: MTH 252Z with C- or better
"""

SUBJECT_WR = f"""# Written English (WR)

## WR 121Z, +*COMPOSITION I, 4 Credits
College writing.
Attributes: CFWF {EN_DASH} Core Ed - Writing Foundations
Available via Ecampus

## WR 227Z, +*TECHNICAL WRITING, 4 Credits
Technical writing.
Attributes: CSWE {EN_DASH} Core Ed - Writing Elevation
Prerequisite: WR 121Z with C- or better
Available via Ecampus

## WR 314, +*WRITING IN BUSINESS, 3 Credits
Business writing.
Prerequisite: WR 121Z with C- or better
"""

SUBJECT_HST = f"""# History (HST)

## HST 101, +*HISTORY OF WESTERN CIVILIZATION, 4 Credits
Ancient world.
Attributes: CFAH {EN_DASH} Core Ed - Art & Humanities General
Available via Ecampus

## HST 104, +*WORLD HISTORY I: ANCIENT CIVILIZATIONS, 3 Credits
World history.
Attributes: CFGH {EN_DASH} Core Ed - Art & Humanities Global

## HST 201, +*HISTORY OF THE UNITED STATES, 4 Credits
United States history.
Attributes: CFDP {EN_DASH} Core Ed - Difference, Power & Oppression
Available via Ecampus

## HST 210, RELIGION IN THE UNITED STATES, 4 Credits
Religion and society.

## HST 220, THE AMERICAN WEST, 4 Credits
The West.
Available via Ecampus
"""

PROGRAM_CS = """## Overview
This program is available at the following locations:
- Corvallis
- Ecampus
Options available:
- Cybersecurity
Major Code: 307

### Course List
Code | Title | Credits
Communication and Writing | Communication and Writing |
WR 121Z | +*COMPOSITION I | 4
WR 314 | +*WRITING IN BUSINESS | 3
or WR 227Z | +*TECHNICAL WRITING | +*TECHNICAL WRITING
Mathematics | Mathematics |
MTH 251Z | +*DIFFERENTIAL CALCULUS | 4
MTH 252Z | INTEGRAL CALCULUS | 4
Computer Science | Computer Science |
CS 161 | INTRODUCTION TO COMPUTER SCIENCE I | 4
CS 162 | INTRODUCTION TO COMPUTER SCIENCE II | 4
CS 225 | DISCRETE STRUCTURES IN COMPUTER SCIENCE | 4
or MTH 231 | ELEMENTS OF DISCRETE MATHEMATICS | ELEMENTS OF DISCRETE MATHEMATICS
CS 261 | DATA STRUCTURES | 4
CS 290 & CS 340 | WEB DEVELOPMENT and INTRODUCTION TO DATABASES | 8
Applied Electives | Applied Electives |
Select one of the following: | Select one of the following: | 4
CS 391 | *SOCIAL AND ETHICAL ISSUES IN COMPUTER SCIENCE |
HST 210 | RELIGION IN THE UNITED STATES |
Select 16 upper-division CS credits | Select 16 upper-division CS credits | 16
Unrestricted Electives 2 | Unrestricted Electives 2 | 6-12
Total Credits | Total Credits | 180
*
  Baccalaureate Core course.
2
  Unrestricted Electives are any credits not used elsewhere
Major Code: 307

## Sample Plan
Degree plans are subject to change.

### Plan of Study Grid
First Year | First Year | First Year
Fall | Fall | Credits
MTH 251Z | +*DIFFERENTIAL CALCULUS | 4
WR 121Z | +*COMPOSITION I | 4
Core Ed: Arts & Humanities General | Core Ed: Arts & Humanities General | 3-4
| Credits | 12
Winter | Winter | Winter
CS 161 | INTRODUCTION TO COMPUTER SCIENCE I | 4
MTH 252Z | INTEGRAL CALCULUS | 4
| Credits | 8
Spring | Spring | Spring
CS 225 or MTH 231 | DISCRETE STRUCTURES IN COMPUTER SCIENCE or ELEMENTS OF DISCRETE MATHEMATICS | 4
| Credits | 4
Second Year | Second Year | Second Year
Fall | Fall | Fall
CS 162 | INTRODUCTION TO COMPUTER SCIENCE II | 4
WR 314 or WR 227Z | +*WRITING IN BUSINESS or +*TECHNICAL WRITING | 3
| Credits | 7
Winter | Winter | Winter
CS 261 | DATA STRUCTURES | 4
| Credits | 4
Spring | Spring | Spring
CS 290 & CS 340 | WEB DEVELOPMENT and INTRODUCTION TO DATABASES | 8
Unrestricted Elective | Unrestricted Elective | 4
| Credits | 12
| Total Credits | 180
"""

PROGRAM_OPTION = """## Overview
This option is available within the Computer Science major at the following locations:
- Corvallis

### Course List
Code | Title | Credits
CS 290 | WEB DEVELOPMENT | 4
CS 340 | INTRODUCTION TO DATABASES | 4
Total Credits | Total Credits | 8
"""

PROGRAM_MINOR = """## Overview
This program is available at the following locations:
- Corvallis

### Course List
Code | Title | Credits
Core | Core |
MTH 251Z & MTH 252Z | +*DIFFERENTIAL CALCULUS and INTEGRAL CALCULUS | 8
Select two courses from the following: | Select two courses from the following: | 8
MTH 231 | ELEMENTS OF DISCRETE MATHEMATICS |
MTH 254 | VECTOR CALCULUS I |
Total Credits | Total Credits | 16
"""

CATALOG = "https://catalog.oregonstate.edu/"


def make_source(path: Path) -> None:
    """A tiny stand-in for the crawl database: the two tables and columns the generator reads."""
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE pages (url TEXT, title TEXT, main_text TEXT, retrieved_at TEXT, gone_at TEXT, "
                "duplicate_of TEXT)")
    con.execute("CREATE TABLE documents (url TEXT, title TEXT, purpose TEXT, kind TEXT, owning_office TEXT, "
                "gone_at TEXT)")
    eng = CATALOG + "college-departments/engineering/"
    pages = [
        (CATALOG + "courses/cs/", "Computer Science (CS)", SUBJECT_CS, "2026-10-22T20:00:00+00:00", None),
        (CATALOG + "courses/mth/", "Mathematics (MTH)", SUBJECT_MTH, "2026-10-21T20:00:00+00:00", None),
        (CATALOG + "courses/wr/", "Written English (WR)", SUBJECT_WR, "2026-10-21T20:00:00+00:00", None),
        (CATALOG + "courses/hst/", "History (HST)", SUBJECT_HST, "2026-10-21T20:00:00+00:00", None),
        (CATALOG + "courses/old/", "Old (OLD)", "# Old (OLD)\n\n## OLD 101, GONE COURSE, 3 Credits\nGone.",
         "2026-10-21T20:00:00+00:00", "2026-10-30"),
        (eng, "College of Engineering", "About the college.", "2026-10-21T20:00:00+00:00", None),
        (eng + "computer-science-ba-bs-hba-hbs/", "Computer Science Undergraduate Major (BA, BS, HBA, HBS)", PROGRAM_CS,
         "2026-10-21T20:00:00+00:00", None),
        (eng + "computer-science-ba-bs-hba-hbs/cybersecurity-option/", "Cybersecurity Option", PROGRAM_OPTION,
         "2026-10-21T20:00:00+00:00", None),
        (CATALOG + "college-departments/science/mathematics-minor/", "Mathematics Minor", PROGRAM_MINOR,
         "2026-10-21T20:00:00+00:00", None),
        ("https://writingcenter.oregonstate.edu/", "Writing Center", "Help with writing.", "2026-10-20", None),
        ("https://registrar.oregonstate.edu/change-grading-basis", "Change of Grading Basis", "How to.", "2026-10-20",
         None),
    ]
    con.executemany("INSERT INTO pages VALUES (?,?,?,?,?,NULL)", pages)
    con.commit()
    con.close()


def dump(path: Path) -> dict:
    """Every table's rows, without the one value that is allowed to change between builds."""
    con = sqlite3.connect(path)
    out = {}
    for (table,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall():
        rows = con.execute(f"SELECT * FROM {table}").fetchall()
        if table == "meta":
            rows = [r for r in rows if r[0] != "built_at"]
        out[table] = rows
    con.close()
    return out


def overlap(a, b) -> bool:
    """Two (days, start, end) meetings share a day and a minute."""
    return bool(set(a[0]) & set(b[0])) and a[1] < b[2] and b[1] < a[2]


class Parsers(unittest.TestCase):
    def test_title_case(self):
        self.assertEqual(g.title_case("+*INTRODUCTION TO COMPUTER SCIENCE II"), "Introduction to Computer Science II")
        self.assertEqual(g.title_case("^MIME CAPSTONE DESIGN I"), "MIME Capstone Design I")
        self.assertEqual(g.title_case("THE ART OF WAR IN THE WEST"), "The Art of War in the West")
        self.assertEqual(g.title_case("SPECIAL TOPICS/COMPUTER SCIENCE"), "Special Topics/Computer Science")
        self.assertEqual(g.title_case("ENGINEERING GRAPHICS AND 3-D MODELING"), "Engineering Graphics and 3-D Modeling")
        self.assertEqual(g.title_case("PRECALCULUS II: TRIGONOMETRY"), "Precalculus II: Trigonometry")
        self.assertEqual(g.title_case("FILM STUDIES: 1945-PRESENT"), "Film Studies: 1945-Present")

    def test_credits_forms(self):
        self.assertEqual(g.parse_credits("4 Credits"), ("4", 4.0, 4.0))
        self.assertEqual(g.parse_credits("1 Credit"), ("1", 1.0, 1.0))
        self.assertEqual(g.parse_credits("1-16 Credits"), ("1-16", 1.0, 16.0))
        self.assertEqual(g.parse_credits("0 or 4"), ("0 or 4", 0.0, 4.0))
        self.assertEqual(g.parse_credits("3-4"), ("3-4", 3.0, 4.0))
        self.assertEqual(g.parse_credits("0 Credits"), ("0", 0.0, 0.0))

    def test_subject_page(self):
        page = g.parse_subject_page(SUBJECT_CS)
        self.assertEqual((page["subject"], page["subject_name"]), ("CS", "Computer Science"))
        by = {c["code"]: c for c in page["courses"]}
        self.assertNotIn("CS LDEA", by)
        c = by["CS 161"]
        self.assertEqual((c["subject"], c["number"], c["level"]), ("CS", "161", 100))
        self.assertEqual(c["title"], "Introduction to Computer Science I")
        self.assertEqual(c["description"], "Overview of fundamental concepts of computer science. Includes algorithm design.")
        self.assertTrue(c["prereq_text"].startswith("MTH 112 (may be taken concurrently)"))
        self.assertEqual((c["ecampus"], c["honors"]), (1, 0))
        self.assertEqual(by["CS 162"]["equivalent_text"], "CS 162H")
        self.assertEqual((by["CS 162H"]["honors"], by["CS 162H"]["ecampus"]), (1, 0))
        self.assertEqual(by["CS 162H"]["attrs"], [("HNRS", "Honors Course Designator")])
        self.assertEqual((by["CS 199"]["credits_text"], by["CS 199"]["credits_min"], by["CS 199"]["credits_max"]),
                         ("1-16", 1.0, 16.0))
        self.assertEqual(by["CS 199"]["repeatable_text"], "This course is repeatable for 16 credits.")
        self.assertEqual(by["CS 290"]["recommended_text"], "CS 162")
        self.assertEqual(by["CS 340"]["coreq_text"], "CS 290")
        self.assertEqual(by["CS 391"]["title"], "Social and Ethical Issues in Computer Science")

    def test_attributes(self):
        by = {c["code"]: c for c in g.parse_subject_page(SUBJECT_MTH)["courses"]}
        self.assertEqual(by["MTH 105Z"]["title"], "Math in Society")
        self.assertEqual(by["MTH 105Z"]["attrs"], [("CFQL", "Core Ed - Quantitative Literacy & Analysis"),
                                                   ("CSMA", "Bacc Core, Skills, Math")])
        self.assertEqual(by["MTH 105Z"]["recommended_text"], "MTH 095 or MTH 103")

    def test_prerequisite_groups(self):
        rows = g.parse_prereq_text("MTH 112 (may be taken concurrently) with C or better or MTH 112Z (may be taken "
                                   "concurrently) with C or better or Math Placement Test with a score of 33")
        self.assertEqual([r["group_no"] for r in rows], [1, 1, 1])
        self.assertEqual([r["req_code"] for r in rows], ["MTH 112", "MTH 112Z", None])
        self.assertEqual((rows[0]["min_grade"], rows[0]["concurrent"]), ("C", 1))
        self.assertEqual(rows[2]["note"], "Math Placement Test with a score of 33")
        rows = g.parse_prereq_text("(CS 162 with C or better or CS 162H with C or better) and (CS 225 [C] or "
                                   "MTH 231 [C-])")
        self.assertEqual([(r["group_no"], r["req_code"], r["min_grade"]) for r in rows],
                         [(1, "CS 162", "C"), (1, "CS 162H", "C"), (2, "CS 225", "C"), (2, "MTH 231", "C-")])
        self.assertEqual(g.parse_prereq_text(None), [])

    def test_program_title(self):
        self.assertEqual(g.parse_program_title("Computer Science Undergraduate Major (BA, BS, HBA, HBS)"),
                         {"name": "Computer Science", "kind": "major", "degree": "BA, BS, HBA, HBS",
                          "level": "undergraduate"})
        self.assertEqual(g.parse_program_title("Kinesiology Graduate Major (MS, PhD)")["level"], "graduate")
        self.assertEqual(g.parse_program_title("Computer Science - Applied Major (BS, HBS)")["level"], "undergraduate")
        self.assertEqual(g.parse_program_title("Psychology Minor"),
                         {"name": "Psychology", "kind": "minor", "degree": None, "level": "undergraduate"})
        self.assertEqual(g.parse_program_title("History Graduate Minor")["level"], "graduate")
        self.assertEqual(g.parse_program_title("Cybersecurity Option")["kind"], "option")
        self.assertEqual(g.parse_program_title("Data Analytics Graduate Certificate")["kind"], "certificate")
        self.assertIsNone(g.parse_program_title("College of Engineering"))
        self.assertEqual(g.program_on_ecampus(PROGRAM_CS), 1)
        self.assertEqual(g.program_on_ecampus(PROGRAM_MINOR), 0)
        self.assertEqual(g.college_name("liberal-arts"), "College of Liberal Arts")

    def test_course_list(self):
        parsed = g.parse_course_lists(PROGRAM_CS, "Major requirements", {"CS 161": "Introduction to Computer Science I"})
        self.assertEqual(parsed["total_credits"], 180.0)
        reqs = parsed["requirements"]
        by = {r["label"]: r for r in reqs}
        self.assertEqual([r["seq"] for r in reqs], list(range(1, len(reqs) + 1)))
        self.assertNotIn("Total Credits", by)
        # block headers
        self.assertEqual(by["WR 121Z Composition I"]["block"], "Communication and Writing")
        self.assertEqual(by["CS 161 Introduction to Computer Science I"]["block"], "Computer Science")
        # an "or" row adds an alternative to the row above
        wr = by["WR 314 Writing in Business (or WR 227Z)"]
        self.assertEqual((wr["kind"], wr["credits"], wr["courses"]), ("course", 3.0, [("WR 314", None), ("WR 227Z", None)]))
        self.assertEqual(by["CS 225 Discrete Structures in Computer Science (or MTH 231)"]["courses"],
                         [("CS 225", None), ("MTH 231", None)])
        # an "&" row keeps the second course as with_code
        pair = next(r for r in reqs if r["courses"] and r["courses"][0] == ("CS 290", "CS 340"))
        self.assertEqual((pair["kind"], pair["credits"]), ("course", 8.0))
        # choice and credits lines
        choice = by["Select one of the following:"]
        self.assertEqual((choice["kind"], choice["pick_count"], choice["credits"], choice["block"]),
                         ("choice", 1, 4.0, "Applied Electives"))
        self.assertEqual([c for c, _w in choice["courses"]], ["CS 391", "HST 210"])
        credits = by["Select 16 upper-division CS credits"]
        self.assertEqual((credits["kind"], credits["credits"], credits["pick_count"], credits["courses"]),
                         ("credits", 16.0, None, []))
        self.assertEqual(by["Unrestricted Electives"]["credits"], 6.0)     # footnote mark dropped, range -> low end

    def test_code_cells_and_pick(self):
        self.assertEqual(g.parse_code_cell("ME 320/ECE 356"), ([("ME 320", None), ("ECE 356", None)], False))
        self.assertEqual(g.parse_code_cell("CH 201 & CH 204"), ([("CH 201", "CH 204")], False))
        self.assertEqual(g.parse_code_cell("or ST 351 & ST 352"), ([("ST 351", "ST 352")], True))
        self.assertIsNone(g.parse_code_cell("Any WR course higher than WR 121Z"))
        self.assertEqual(g.parse_pick("Select two of the following:"), (2, None))
        self.assertEqual(g.parse_pick("Select at least three lab courses from the following:"), (3, None))
        self.assertEqual(g.parse_pick("Select 9-12 credits from the following courses"), (None, 9.0))

    def test_summary_table_is_dropped(self):
        text = ("### Course List\nCode | Title | Credits\nCore Ed 1 | Core Ed 1 | 36\nElectives | Electives | 39\n"
                "Total Credits | Total Credits | 180\n\n### Course List\nCode | Title | Credits\n"
                "PSY 201Z | +*INTRODUCTION TO PSYCHOLOGY I | 4\nRemaining Electives | Remaining Electives | 108\n")
        parsed = g.parse_course_lists(text)
        self.assertEqual([r["label"] for r in parsed["requirements"]],
                         ["PSY 201Z Introduction to Psychology I", "Remaining Electives"])
        self.assertEqual(parsed["total_credits"], 180.0)

    def test_plan_grid(self):
        plan = g.parse_plan_grid(PROGRAM_CS)
        self.assertEqual(plan[0], {"year": 1, "term": "Fall", "codes": ["MTH 251Z"], "text": "MTH 251Z", "credits": 4.0})
        self.assertEqual((plan[2]["codes"], plan[2]["text"]), ([], "Core Ed: Arts & Humanities General"))
        either = next(p for p in plan if p["codes"] == ["CS 225", "MTH 231"])
        self.assertEqual((either["year"], either["term"]), (1, "Spring"))
        self.assertFalse(any(p["text"] == "" or "Credits" in p["text"] for p in plan))
        reqs = g.parse_course_lists(PROGRAM_CS)["requirements"]
        g.apply_plan(reqs, plan)
        where = {r["label"].split(" (")[0]: (r["plan_year"], r["plan_term"]) for r in reqs}
        self.assertEqual(where["CS 162 Introduction to Computer Science II"], (2, "Fall"))
        self.assertEqual(where["WR 314 Writing in Business"], (2, "Fall"))
        self.assertEqual(where["CS 261 Data Structures"], (2, "Winter"))
        self.assertEqual(where["Unrestricted Electives"], (2, "Spring"))
        self.assertEqual(where["Select 16 upper-division CS credits"], (None, None))


class TinyBuild(unittest.TestCase):
    """End to end on a fake catalog with one major. The wanted majors are mostly missing, so this also proves
    the generator falls back and still produces five students."""

    @classmethod
    def setUpClass(cls):
        cls.dir = Path(tempfile.mkdtemp())
        cls.source = cls.dir / "source.sqlite"
        make_source(cls.source)
        before = dump(cls.source)
        cls.out = cls.dir / "demo.db"
        cls.counts = g.build(cls.out, cls.source, seed=7, log=None, min_sections=0, max_sections=None)
        cls.second = cls.dir / "again.db"
        g.build(cls.second, cls.source, seed=7, log=None, min_sections=0, max_sections=None)
        cls.other = cls.dir / "other.db"
        g.build(cls.other, cls.source, seed=8, log=None, min_sections=0, max_sections=None)
        cls.source_unchanged = dump(cls.source) == before
        cls.con = sqlite3.connect(cls.out)
        cls.con.row_factory = sqlite3.Row

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def q(self, sql, *args):
        return self.con.execute(sql, args).fetchall()

    def test_tables_are_filled_and_source_is_untouched(self):
        self.assertTrue(self.source_unchanged)
        for table in ("meta", "courses", "prerequisites", "course_attributes", "programs", "program_requirements",
                      "requirement_courses", "terms", "sections", "meetings", "linked_sections", "students",
                      "student_courses", "student_holds", "student_tasks", "appointments", "advisor_slots", "balances",
                      "transactions", "resources", "forms"):
            self.assertGreater(self.counts[table], 0, table)
            self.assertEqual(self.counts[table], self.q(f"SELECT COUNT(*) FROM {table}")[0][0], table)
        self.assertFalse(list(self.dir.glob("*.tmp")))
        codes = {r["code"] for r in self.q("SELECT code FROM courses")}
        self.assertIn("CS 161", codes)
        self.assertNotIn("OLD 101", codes)                       # the page is marked gone
        self.assertNotIn("CS LDEA", codes)
        meta = {r["key"]: r["value"] for r in self.q("SELECT * FROM meta")}
        self.assertEqual((meta["seed"], meta["schema_version"], meta["catalog_retrieved"]), ("7", "1", "2026-10-22"))
        self.assertEqual(int(meta["sections"]), self.counts["sections"])

    def test_programs(self):
        rows = {r["name"]: r for r in self.q("SELECT * FROM programs")}
        self.assertEqual(set(rows), {"Computer Science", "Cybersecurity", "Mathematics", "Core Education"})
        major = rows["Computer Science"]
        self.assertEqual((major["kind"], major["level"], major["college"], major["total_credits"], major["ecampus"]),
                         ("major", "undergraduate", "College of Engineering", 180.0, 1))
        self.assertEqual(rows["Cybersecurity"]["parent_id"], major["id"])
        self.assertEqual((rows["Core Education"]["kind"], rows["Core Education"]["catalog_url"]),
                         ("core", "https://catalog.oregonstate.edu/core-education/"))
        core = self.q("SELECT * FROM program_requirements WHERE program_id = ? ORDER BY seq", rows["Core Education"]["id"])
        self.assertIn("Quantitative Literacy & Analysis", [r["label"] for r in core])
        self.assertTrue(all(r["kind"] == "choice" and r["pick_count"] == 1 and r["block"] == "Core Education" for r in core))
        ql = next(r for r in core if r["label"] == "Quantitative Literacy & Analysis")
        self.assertEqual([r[0] for r in self.q("SELECT course_code FROM requirement_courses WHERE requirement_id = ? "
                                               "ORDER BY course_code", ql["id"])], ["MTH 105Z", "MTH 112Z", "MTH 251Z"])
        pair = self.q("SELECT with_code FROM requirement_courses WHERE course_code = 'CS 290' AND with_code IS NOT NULL")
        self.assertEqual(pair[0][0], "CS 340")
        self.assertEqual(self.q("SELECT kind, req_code FROM prerequisites WHERE course_code = 'CS 340'")[0][:],
                         ("coreq", "CS 290"))

    def test_sections(self):
        secs = self.q("SELECT * FROM sections")
        crns = [s["crn"] for s in secs]
        self.assertEqual(len(crns), len(set(crns)))
        self.assertTrue(all(10000 <= c <= 99999 for c in crns))
        self.assertEqual({s["term_code"] for s in secs}, {"202701", "202702", "202703"})
        ranges = {"Corvallis": (0, 399), "Ecampus": (400, 499), "Cascades": (500, 599), "INTO OSU": (600, 699)}
        for s in secs:
            low, high = ranges[s["campus"]]
            self.assertTrue(low <= int(s["section"]) <= high, dict(s))
            self.assertTrue(0 <= s["seats_taken"] <= s["seats_total"], dict(s))
            self.assertEqual(s["credits"] == 0, s["is_primary"] == 0, dict(s))
        self.assertFalse(self.q("SELECT 1 FROM sections GROUP BY term_code, course_code, section HAVING COUNT(*) > 1"))
        online = self.q("SELECT s.*, m.days, m.building FROM sections s JOIN meetings m USING (crn) WHERE campus = 'Ecampus'")
        self.assertTrue(online)
        self.assertTrue(all(s["method"] == "Online" and s["days"] is None and s["building"] is None for s in online))
        self.assertFalse(self.q("SELECT 1 FROM sections s JOIN courses c ON c.code = s.course_code "
                                "WHERE s.campus = 'Ecampus' AND c.ecampus = 0"))
        honors = self.q("SELECT restrictions FROM sections WHERE course_code = 'CS 162H'")
        self.assertTrue(honors and all(r[0] == "Honors College students only" for r in honors))
        # a variable-credit topics course is one section with no set meeting time
        topics = self.q("SELECT s.schedule_type, m.days FROM sections s JOIN meetings m USING (crn) "
                        "WHERE course_code = 'CS 199' AND campus = 'Corvallis'")
        self.assertTrue(all(r["days"] is None for r in topics))

    def test_linked_sections(self):
        links = self.q("SELECT * FROM linked_sections")
        self.assertTrue(links)
        secs = {s["crn"]: s for s in self.q("SELECT * FROM sections")}
        meets = {}
        for m in self.q("SELECT * FROM meetings WHERE days IS NOT NULL"):
            meets.setdefault(m["crn"], []).append((m["days"], m["start_min"], m["end_min"]))
        for link in links:
            lec, sub = secs[link["lecture_crn"]], secs[link["linked_crn"]]
            self.assertEqual((lec["course_code"], lec["term_code"], lec["campus"]),
                             (sub["course_code"], sub["term_code"], sub["campus"]))
            self.assertEqual((lec["is_primary"], sub["is_primary"], sub["credits"]), (1, 0, 0))
            self.assertIn(sub["schedule_type"], ("Recitation", "Laboratory"))
            for a in meets.get(lec["crn"], []):
                for b in meets.get(sub["crn"], []):
                    self.assertFalse(overlap(a, b), (dict(lec), dict(sub)))

    def test_no_room_is_double_booked(self):
        rooms = {}
        for m in self.q("SELECT s.term_code, m.* FROM meetings m JOIN sections s USING (crn) "
                        "WHERE m.building IS NOT NULL AND m.days IS NOT NULL"):
            for day in m["days"]:
                rooms.setdefault((m["term_code"], m["building"], m["room"], day), []).append((m["start_min"], m["end_min"]))
        self.assertTrue(rooms)
        for key, times in rooms.items():
            times.sort()
            for earlier, later in zip(times, times[1:]):
                self.assertLessEqual(earlier[1], later[0], key)

    def test_winter_spread_for_demo_courses(self):
        for code in ("MTH 251Z", "CS 161"):
            lectures = self.q("SELECT s.*, m.start_min FROM sections s JOIN meetings m USING (crn) WHERE term_code = '202702' "
                              "AND course_code = ? AND campus = 'Corvallis' AND is_primary = 1", code)
            starts = [s["start_min"] for s in lectures]
            self.assertGreaterEqual(len(lectures), 3)
            self.assertTrue(any(s < 600 for s in starts) and any(660 <= s <= 840 for s in starts) and any(s >= 960 for s in starts))
            for lec in lectures:
                times = self.q("SELECT DISTINCT m.days, m.start_min FROM linked_sections k JOIN meetings m ON m.crn = k.linked_crn "
                               "WHERE k.lecture_crn = ?", lec["crn"])
                self.assertGreaterEqual(len(times), 3)
            self.assertTrue(self.q("SELECT 1 FROM sections WHERE term_code = '202702' AND course_code = ? AND campus = 'Ecampus'", code))
        full = self.q("SELECT * FROM sections WHERE term_code = '202702' AND course_code = 'MTH 252Z' AND is_primary = 1 "
                      "AND seats_taken >= seats_total")
        self.assertEqual(len(full), 1)
        self.assertGreater(full[0]["wait_cap"], 0)

    def test_five_students_even_without_their_majors(self):
        students = self.q("SELECT * FROM students ORDER BY id")
        self.assertEqual([s["slug"] for s in students], ["juniper", "mateo", "priya", "devon", "tessa"])
        self.assertEqual(self.counts["student_programs"]["juniper"], "Computer Science")
        self.assertIn("fallback", self.counts["student_programs"]["tessa"])
        program_ids = {r[0] for r in self.q("SELECT id FROM programs")}
        for s in students:
            self.assertTrue(s["email"].endswith("@example.com"))
            self.assertRegex(s["sample_id"], r"^SAMPLE-\d{4}$")
            self.assertIn(s["program_id"], program_ids)
            rows = self.q("SELECT * FROM student_courses WHERE student_id = ?", s["id"])
            self.assertTrue(any(r["status"] == "in_progress" for r in rows), s["slug"])
            self.assertFalse(any(r["status"] == "planned" for r in rows))
            self.assertEqual(len({r["course_code"] for r in rows}), len(rows))
            graded = [r for r in rows if r["status"] == "completed"]
            if graded:
                points = sum(g.GRADE_POINTS[r["grade"]] * r["credits"] for r in graded)
                self.assertAlmostEqual(s["gpa"], points / sum(r["credits"] for r in graded), places=2)
            else:
                self.assertIsNone(s["gpa"])
            earned = sum(r["credits"] for r in rows if r["status"] == "transfer"
                         or (r["status"] == "completed" and g.GRADE_POINTS[r["grade"]] > 0))
            self.assertAlmostEqual(s["credits_earned"], earned)
            balance = self.q("SELECT * FROM balances WHERE student_id = ?", s["id"])[0]
            total = self.q("SELECT SUM(amount), COUNT(*) FROM transactions WHERE student_id = ?", s["id"])[0]
            self.assertAlmostEqual(balance["balance"], total[0], places=2)
            self.assertTrue(8 <= total[1] <= 14)
        self.assertEqual({r["term_code"] for r in self.q("SELECT term_code FROM student_courses WHERE term_code IS NOT NULL")}
                         - {r["code"] for r in self.q("SELECT code FROM terms")}, set())

    def test_current_classes_point_at_real_sections_that_do_not_clash(self):
        for s in self.q("SELECT * FROM students"):
            busy = []
            for r in self.q("SELECT * FROM student_courses WHERE student_id = ? AND status = 'in_progress'", s["id"]):
                sec = self.q("SELECT * FROM sections WHERE crn = ?", r["crn"])
                self.assertTrue(sec, (s["slug"], r["course_code"]))
                self.assertEqual((sec[0]["term_code"], sec[0]["course_code"], sec[0]["is_primary"]),
                                 ("202701", r["course_code"], 1))
                online = self.q("SELECT ecampus FROM courses WHERE code = ?", r["course_code"])[0][0]
                if s["campus"] == "Ecampus" and online:           # the tiny catalog runs out of online courses
                    self.assertEqual(sec[0]["campus"], "Ecampus")
                if self.q("SELECT 1 FROM linked_sections WHERE lecture_crn = ?", r["crn"]):
                    self.assertTrue(self.q("SELECT 1 FROM linked_sections WHERE lecture_crn = ? AND linked_crn = ?",
                                           r["crn"], r["linked_crn"]))
                mine = [(m["days"], m["start_min"], m["end_min"]) for m in self.q(
                    "SELECT * FROM meetings WHERE crn IN (?, ?) AND days IS NOT NULL", r["crn"], r["linked_crn"] or -1)]
                for a in mine:
                    for b in busy:
                        self.assertFalse(overlap(a, b), (s["slug"], r["course_code"]))
                busy += mine

    def test_requirement_links_and_sample_situations(self):
        own = self.q("SELECT sc.student_id, r.program_id, s.program_id AS mine, p.kind FROM student_courses sc "
                     "JOIN program_requirements r ON r.id = sc.requirement_id JOIN programs p ON p.id = r.program_id "
                     "JOIN students s ON s.id = sc.student_id")
        self.assertTrue(own)
        self.assertTrue(all(r["program_id"] == r["mine"] or r["kind"] == "core" for r in own))
        holds = {(r["slug"], r["type"]): r["blocks_registration"] for r in self.q(
            "SELECT s.slug, h.type, h.blocks_registration FROM student_holds h JOIN students s ON s.id = h.student_id")}
        self.assertEqual(holds, {("juniper", "advising"): 1, ("priya", "financial"): 1, ("devon", "health"): 0})
        upcoming = {r[0] for r in self.q("SELECT s.slug FROM appointments a JOIN students s ON s.id = a.student_id "
                                         "WHERE a.status = 'upcoming'")}
        self.assertEqual(upcoming, {"mateo", "devon"})
        slots = self.q("SELECT offset_days FROM advisor_slots a JOIN students s ON s.id = a.student_id WHERE s.slug = 'juniper'")
        self.assertGreaterEqual(len([1 for r in slots if 1 <= r[0] <= 7]), 8)
        priya = self.q("SELECT b.* FROM balances b JOIN students s ON s.id = b.student_id WHERE s.slug = 'priya'")[0]
        self.assertTrue(priya["past_due"] > 0 and priya["due_offset_days"] < 0)
        # juniper is on the real fake-catalog major: exactly three sample-plan requirements up to year 2 are unstarted
        left = self.q("SELECT r.label FROM program_requirements r JOIN students s ON s.program_id = r.program_id "
                      "WHERE s.slug = 'juniper' AND r.plan_year <= 2 AND NOT EXISTS "
                      "(SELECT 1 FROM student_courses sc WHERE sc.student_id = s.id AND sc.requirement_id = r.id)")
        self.assertEqual(len(left), 3, [r[0] for r in left])

    def test_resources_and_forms_only_link_to_stored_pages(self):
        names = [r["name"] for r in self.q("SELECT name FROM resources")]
        self.assertEqual(len(names), len(set(names)))
        self.assertGreaterEqual(len(names), 120)
        urls = {r["name"]: r["url"] for r in self.q("SELECT name, url FROM resources")}
        self.assertEqual(urls["Writing Center"], "https://writingcenter.oregonstate.edu/")
        self.assertIsNone(urls["Canvas"])                         # its page is not in the fake crawl: no guessed link
        self.assertEqual({u for u in urls.values() if u}, {"https://writingcenter.oregonstate.edu/",
                                                            "https://registrar.oregonstate.edu/change-grading-basis"})
        same = self.q("SELECT same_as FROM resources WHERE name = 'Course Search'")[0][0]
        self.assertIn("Look Up Classes", same)
        categories = {r[0] for r in self.q("SELECT DISTINCT category FROM resources")}
        self.assertLessEqual(categories, {"Academic", "Technology", "Financial", "Wellness", "Transportation",
                                          "Getting Involved", "Accessibility"})
        forms = self.q("SELECT * FROM forms")
        self.assertEqual([f["url"] for f in forms], ["https://registrar.oregonstate.edu/change-grading-basis"])
        self.assertIn(forms[0]["kind"], ("PDF", "Online form", "Page"))
        for table, columns in (("resources", "plain || ' ' || COALESCE(use_for, '')"),
                               ("forms", "purpose || ' ' || goes_to || ' ' || COALESCE(when_to_use, '')"),
                               ("student_holds", "title || reason || how_to_clear"),
                               ("student_tasks", "title || COALESCE(detail, '')"), ("students", "situation || blurb")):
            text = " ".join(r[0] for r in self.q(f"SELECT {columns} FROM {table}")).lower()
            self.assertNotIn("official", text, table)
            self.assertNotIn("guarantee", text, table)

    def test_same_seed_same_rows_and_new_seed_new_sections(self):
        first, again, other = dump(self.out), dump(self.second), dump(self.other)
        self.assertEqual(set(first), set(again))
        for table in first:
            self.assertEqual(first[table], again[table], table)
        self.assertNotEqual(first["sections"], other["sections"])
        self.assertEqual(first["courses"], other["courses"])        # catalog facts do not depend on the seed

    def test_size_check_fails_loudly(self):
        with self.assertRaises(RuntimeError):
            g.build(self.dir / "too-small.db", self.source, seed=7, log=None)
        self.assertFalse((self.dir / "too-small.db").exists())
        self.assertFalse(list(self.dir.glob("*.tmp")))


REAL = Path(__file__).resolve().parents[1] / "data" / "demo.db"
REAL_BUILDINGS = ["Kelley", "Weniger", "LINC", "Kidder", "Milam", "Withycombe", "Strand", "Bexell", "Owen", "Dearborn",
                  "Gilkey", "Wiegand", "Austin", "Johnson", "Batcheller", "Rogers", "Covell", "Gleeson", "Cordley", "Nash",
                  "Waldo", "Moreland", "Gilbert", "Langton", "Learning Innovation Center", "Valley Library",
                  "Memorial Union"]


@unittest.skipUnless(REAL.exists(), "data/demo.db has not been built")
class RealBuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = sqlite3.connect(REAL.as_uri() + "?mode=ro", uri=True)
        cls.con.row_factory = sqlite3.Row

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def q(self, sql, *args):
        return self.con.execute(sql, args).fetchall()

    def test_size_and_crns(self):
        count = self.q("SELECT COUNT(*), COUNT(DISTINCT crn), MIN(crn), MAX(crn) FROM sections")[0]
        self.assertTrue(60000 <= count[0] <= 95000, count[0])
        self.assertEqual(count[0], count[1])
        self.assertTrue(10000 <= count[2] and count[3] <= 99999)
        self.assertGreater(self.q("SELECT COUNT(DISTINCT instructor) FROM sections")[0][0], 400)

    def test_students(self):
        slugs = {r["slug"] for r in self.q("SELECT slug FROM students")}
        self.assertEqual(slugs, {"juniper", "mateo", "priya", "devon", "tessa"})
        self.assertFalse(self.q("SELECT 1 FROM students WHERE email NOT LIKE '%@example.com'"))
        self.assertFalse(self.q("SELECT 1 FROM students WHERE sample_id NOT GLOB 'SAMPLE-[0-9][0-9][0-9][0-9]'"))
        programs = {r["slug"]: r["name"] for r in self.q("SELECT s.slug, p.name FROM students s JOIN programs p ON p.id = s.program_id")}
        self.assertEqual(programs, {"juniper": "Computer Science", "mateo": "Business Administration", "priya": "Psychology",
                                    "devon": "Kinesiology", "tessa": "Mechanical Engineering"})

    def test_juniper(self):
        hold = self.q("SELECT h.* FROM student_holds h JOIN students s ON s.id = h.student_id WHERE s.slug = 'juniper'")
        self.assertEqual([(h["type"], h["blocks_registration"]) for h in hold], [("advising", 1)])
        left = self.q("SELECT r.label, r.plan_year FROM program_requirements r JOIN students s ON s.program_id = r.program_id "
                      "WHERE s.slug = 'juniper' AND r.plan_year <= 2 AND NOT EXISTS "
                      "(SELECT 1 FROM student_courses sc WHERE sc.student_id = s.id AND sc.requirement_id = r.id)")
        self.assertEqual(len(left), 3, [r[0] for r in left])
        self.assertTrue(all(r["plan_year"] == 2 for r in left))
        self.assertFalse(self.q("SELECT 1 FROM appointments a JOIN students s ON s.id = a.student_id "
                                "WHERE s.slug = 'juniper' AND a.status = 'upcoming'"))
        self.assertEqual(self.q("SELECT COUNT(*) FROM student_courses sc JOIN students s ON s.id = sc.student_id "
                                "WHERE s.slug = 'juniper' AND sc.status = 'in_progress' AND sc.crn IS NOT NULL")[0][0], 4)

    def test_tessa_has_three_requirements_left_and_one_low_grade(self):
        left = self.q("SELECT r.label FROM program_requirements r JOIN students s ON s.program_id = r.program_id "
                      "WHERE s.slug = 'tessa' AND NOT EXISTS "
                      "(SELECT 1 FROM student_courses sc WHERE sc.student_id = s.id AND sc.requirement_id = r.id)")
        self.assertEqual(len(left), 3, [r[0] for r in left])
        low = self.q("SELECT sc.* FROM student_courses sc JOIN students s ON s.id = sc.student_id "
                     "WHERE s.slug = 'tessa' AND sc.grade = 'D+'")
        self.assertEqual(len(low), 1)
        self.assertIsNone(low[0]["requirement_id"])

    def test_priya_is_online_and_past_due(self):
        rows = self.q("SELECT x.campus, x.section FROM student_courses sc JOIN students s ON s.id = sc.student_id "
                      "JOIN sections x ON x.crn = sc.crn WHERE s.slug = 'priya' AND sc.status = 'in_progress'")
        self.assertTrue(rows)
        self.assertTrue(all(r["campus"] == "Ecampus" and r["section"].startswith("4") for r in rows))

    def test_full_lecture_and_demo_courses(self):
        full = self.q("SELECT * FROM sections WHERE term_code = '202702' AND course_code = 'MTH 252Z' AND is_primary = 1 "
                      "AND seats_taken >= seats_total")
        self.assertEqual(len(full), 1)
        self.assertTrue(full[0]["wait_cap"] > 0 and full[0]["campus"] == "Corvallis")
        for code in ("MTH 251Z", "CS 161"):
            lectures = self.q("SELECT s.*, m.start_min FROM sections s JOIN meetings m USING (crn) WHERE term_code = '202702' "
                              "AND course_code = ? AND campus = 'Corvallis' AND is_primary = 1", code)
            starts = [s["start_min"] for s in lectures]
            self.assertGreaterEqual(len(lectures), 3)
            self.assertTrue(any(s < 600 for s in starts), code)
            self.assertTrue(any(660 <= s <= 840 for s in starts), code)
            self.assertTrue(any(s >= 960 for s in starts), code)
            self.assertGreaterEqual(sum(1 for s in lectures if s["seats_taken"] < s["seats_total"]), 2)
            for lec in lectures:
                times = self.q("SELECT DISTINCT m.days, m.start_min FROM linked_sections k JOIN meetings m ON m.crn = k.linked_crn "
                               "WHERE k.lecture_crn = ?", lec["crn"])
                self.assertGreaterEqual(len(times), 3, (code, lec["section"]))
            self.assertTrue(self.q("SELECT 1 FROM sections WHERE term_code = '202702' AND course_code = ? AND campus = 'Ecampus'", code))

    def test_invented_names_only(self):
        buildings = [r[0] for r in self.q("SELECT DISTINCT building FROM meetings WHERE building IS NOT NULL")]
        self.assertGreater(len(buildings), 20)
        for building in buildings:
            for real in REAL_BUILDINGS:
                self.assertIsNone(re.search(rf"\b{re.escape(real)}\b", building, re.I), building)
        text = " ".join(str(r[0]) for r in self.q("SELECT email FROM students"))
        self.assertEqual(set(re.findall(r"@([\w.]+)", text)), {"example.com"})
        self.assertFalse(self.q("SELECT 1 FROM student_courses WHERE transfer_from LIKE '%@%'"))


if __name__ == "__main__":
    unittest.main()
