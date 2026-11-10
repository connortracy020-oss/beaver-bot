"""The 12 task-based categories, how pages map onto them, and which office to send a student to.

    python -m assistant.categories    # assigns categories in the DB and writes docs/categories.md

Categories follow student tasks, not OSU's office structure (docs/structure-map.md). A page gets one primary
category from its site and section, plus secondary ones from title keywords. The office stays as metadata:
`owning_office` on the page.
"""
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from osu_crawl import db
from osu_crawl.config import ROOT
from osu_crawl.scope import is_section_label, office_for


@dataclass
class Category:
    id: str
    name: str
    covers: str
    example: str
    # (host, path regex) pairs that make this the page's primary category; None = the whole host.
    sites: list[tuple[str, str | None]]
    # Title words that add this category as a secondary one on any site.
    keywords: str
    # Where to send a student when we can't answer: (office, URL).
    contacts: list[tuple[str, str]] = field(default_factory=list)


# Tier 2b's colleges: their student-facing pages are about programs, so "courses" unless a section says otherwise.
COLLEGES = ["business", "liberalarts", "health", "agsci", "education", "ceoas", "www.forestry", "science", "vetmed",
            "pharmacy", "math", "ib"]
COLLEGE_HOSTS = [f"{c}.oregonstate.edu" for c in COLLEGES]

CATEGORIES = [
    # Added with Tier 2b (owner-approved 2026-10-29): applying, transfer credit and visas are their own student tasks.
    Category("admissions", "Getting in: admissions, transfer & international",
             "applying as a first-year, transfer, international or graduate student, transfer credit, INTO OSU, "
             "visas and immigration status for international students",
             "Will my community college classes transfer to OSU?",
             [("graduate.oregonstate.edu", r"^/(future-students|admissions?|apply|prospective|international)"),
              *[(h, r"/(admissions?|programs-admissions|admission-aid|apply)(/|$|-)") for h in COLLEGE_HOSTS],
              ("admissions.oregonstate.edu", None), ("transfer.oregonstate.edu", None), ("intoosu.oregonstate.edu", None),
              ("internationalservices.oregonstate.edu", None)],
             r"\b(admissions?|transfer credit|transferring|international students?|visas?|i-20|f-1|j-1|immigration|"
             r"into osu)\b",
             [("Office of Admissions", "https://admissions.oregonstate.edu/contact-information"),
              ("Transfer Students (Office of Admissions)", "https://transfer.oregonstate.edu/contact-us"),
              ("Office of International Services", "https://internationalservices.oregonstate.edu/international-osu/contact-ois")]),
    Category("registration", "Registration & classes",
             "registering, adding/dropping/withdrawing, holds, priority registration, overrides, grading basis, exams, transcripts",
             "How do I drop a class after the first week, and will I get a refund?",
             [("registrar.oregonstate.edu", r"^/(how-register|register|registration|drop|withdraw|add|audit|change-grading-basis|"
               r"grading|exams?|override|what-is-priority-registration|priority-registration|transcripts?|student-records|"
               r"enrollment|verification|graduat|commencement|incomplete|readmission|reinstatement|academic-suspension)"),
              ("holds.oregonstate.edu", None),
              ("ecampus.oregonstate.edu", r"^/(soc|services/registration|ask-ecampus/category/registration)"),
              ("registrar.oregonstate.edu", None), ("summer.oregonstate.edu", None),
              ("commencement.oregonstate.edu", None)],
             r"\b(register|registration|drop|withdraw|add/drop|hold|override|waitlist|audit|transcript|grading basis|final exam)",
             [("Office of the Registrar", "https://registrar.oregonstate.edu/contact-us")]),
    Category("dates", "Dates & deadlines",
             "the academic calendar (current terms first; archived terms only when asked)",
             "When is the last day to withdraw from a fall term class?",
             [("registrar.oregonstate.edu", r"^/(osu-academic-calendar|academic-calendar|osus-4-year-calendar|scheduling-deadlines|"
               r"faculty-grade-deadlines|dates)")],
             r"\b(calendar|deadlines?|important dates)\b",
             [("Office of the Registrar", "https://registrar.oregonstate.edu/osu-academic-calendar")]),
    Category("courses", "Courses & degree requirements",
             "catalog programs and courses, core education, academic regulations, microcredentials, the colleges' "
             "programs, the Honors College, undergraduate research, graduate degree requirements",
             "What are the prerequisites for CS 261?",
             [("catalog.oregonstate.edu", None),
              ("registrar.oregonstate.edu", r"^/(microcredential|standalone-certificates|double-degrees|catalog-and-curriculum|mydegrees)"),
              ("engineering.oregonstate.edu", r"^/(academics|eecs/academics|mime/academics|cce/academics|cbee/academics|nse/academics)"),
              ("honors.oregonstate.edu", None), ("coreeducation.oregonstate.edu", None),
              ("undergradresearch.oregonstate.edu", None), ("graduate.oregonstate.edu", None),
              *[(h, None) for h in COLLEGE_HOSTS]],
             r"\b(degree|major|minor|course|curriculum|prerequisite|core education|certificate|microcredential)\b",
             [("Office of the Registrar (Academic Catalog)", "https://registrar.oregonstate.edu/contact-us")]),
    Category("paying", "Paying for college",
             "tuition and fees, billing and payment plans, financial aid, scholarships, emergency funds, 1098-T",
             "How do I set up a payment plan for my tuition bill?",
             [("financialaid.oregonstate.edu", None), ("finance.oregonstate.edu", None),
              ("scholarships.oregonstate.edu", None), ("ecampus.oregonstate.edu", r"^/tuition"),
              ("graduate.oregonstate.edu", r"^/finance|fellowship|funding|assistantship"),
              ("veterans.oregonstate.edu",
               r"chapter-|gi-bill|education-benefits|benefits|scholarship|tuition|yellow-ribbon|vr-e|vrrap"),
              *[(h, r"/(scholarships?[\w-]*|financial-aid|funding|tuition)(/|$)") for h in COLLEGE_HOSTS]],
             r"\b(tuition|fees?|billing|bill|payment|scholarships?|financial aid|fafsa|loans?|grants?|1098|refund|cost)\b",
             [("Office of Financial Aid", "https://financialaid.oregonstate.edu/contact-us"),
              ("Student Accounts (billing)", "https://finance.oregonstate.edu/student-accounts"),
              ("Scholarship Office", "https://scholarships.oregonstate.edu/contact-us")]),
    # Renamed from "Housing, dining & getting around" with Tier 2b (owner-approved 2026-10-29).
    Category("living", "Housing, dining & campus life",
             "housing options and applications, rates, move-in, dining plans and locations, parking, buses and biking, "
             "recreation, the Memorial Union, clubs and student government, cultural centers, campus safety",
             "How do I get a parking permit, and how much does it cost?",
             [("uhds.oregonstate.edu", None), ("food.oregonstate.edu", None), ("transportation.oregonstate.edu", None),
              ("map.oregonstate.edu", None), ("recsports.oregonstate.edu", None), ("mu.oregonstate.edu", None),
              ("clubs.oregonstate.edu", None), ("asosu.oregonstate.edu", None), ("see.oregonstate.edu", None),
              ("publicsafety.oregonstate.edu", None)],
             r"\b(housing|residence hall|dining|meal plan|parking|permit|beaver bus|transit|bike|intramurals?|"
             r"sport clubs?|student organizations?|cultural centers?)\b",
             [("University Housing & Dining Services", "https://uhds.oregonstate.edu/contact-uhds"),
              ("Transportation Services", "https://transportation.oregonstate.edu/contact-us"),
              ("Recreational Sports", "https://recsports.oregonstate.edu/about/contact"),
              ("Department of Public Safety", "https://publicsafety.oregonstate.edu/contact")]),
    Category("health", "Health, counseling & crisis",
             "Student Health Services, Counseling & Psychological Services (CAPS), 24/7 crisis resources, wellbeing",
             "I'm feeling overwhelmed — how do I talk to a counselor?",
             [("studenthealth.oregonstate.edu", None), ("counseling.oregonstate.edu", None),
              ("cape.oregonstate.edu", None)],  # survivor advocacy
             r"\b(health|counsel|crisis|mental|immuniz|insurance|wellness|wellbeing|suicide)\b",
             [("Counseling & Psychological Services (24/7: 541-737-2131)", "https://counseling.oregonstate.edu/hours-location"),
              ("Student Health Services", "https://studenthealth.oregonstate.edu/locations")]),
    Category("accessibility", "Accessibility",
             "Disability Access Services: accommodations, testing, the DAS student handbook",
             "How do I request testing accommodations for my midterms?",
             [("ds.oregonstate.edu", None), ("ecampus.oregonstate.edu", r"^/services/student-services/ssd")],
             r"\b(accommodation|disabilit|accessib|das\b)",
             [("Disability Access Services", "https://ds.oregonstate.edu/hours-and-contact-information")]),
    Category("support", "Support, success & careers",
             "advising, tutoring and academic coaching, the Writing Center, the library, Basic Needs, Student Care, career services",
             "Where can I get help with my resume?",
             [("advising.oregonstate.edu", None), ("success.oregonstate.edu", None), ("writingcenter.oregonstate.edu", None),
              ("library.oregonstate.edu", None), ("basicneeds.oregonstate.edu", None), ("care.oregonstate.edu", None),
              ("career.oregonstate.edu", None), ("experience.oregonstate.edu", None),
              ("engineering.oregonstate.edu", r"^/(student-life|tools-services|eecs/myeecs|cce/mycce|mime/mymime|nse/mynse|cbee/mycbee)"),
              ("ecampus.oregonstate.edu", r"^/services/student-services"),
              *[(h, r"/(advising[\w-]*|careers?|internships?|student-(services|success|resources)[\w-]*)(/|$)")
                for h in COLLEGE_HOSTS],
              ("familyresources.oregonstate.edu", None), ("veterans.oregonstate.edu", None)],
             r"\b(advis|tutor|coaching|writing|library|basic needs|food pantry|career|resume|internship|job)\b",
             [("Academic Advising", "https://advising.oregonstate.edu/"), ("Academic Success Center", "https://success.oregonstate.edu/"),
              ("Career Development Center", "https://career.oregonstate.edu/about/contact"),
              ("Basic Needs Center", "https://basicneeds.oregonstate.edu/lets-connect"),
              ("OSU Libraries", "https://library.oregonstate.edu/contact"),
              ("Family Resource Center", "https://familyresources.oregonstate.edu/contact"),
              ("Military & Veteran Resources", "https://veterans.oregonstate.edu/contact-us")]),
    Category("rights", "Rights, conduct & policies",
             "Code of Student Conduct, academic integrity, FERPA and privacy, freedom of expression, reporting",
             "What happens if I'm accused of academic misconduct?",
             [("scs.oregonstate.edu", None), ("sccs.oregonstate.edu", None), ("studentlife.oregonstate.edu", None),
              ("registrar.oregonstate.edu", r"^/(ferpa|directory-information|non-directory-information|student-privacy|"
               r"guidelines-release-information)"),
              ("policy.oregonstate.edu", None), ("eoa.oregonstate.edu", None), ("diversity.oregonstate.edu", None)],
             r"\b(conduct|integrity|ferpa|privacy|policy|policies|rights|misconduct|expression|protest|"
             r"discrimination|harassment|title ix|bias)\b",
             [("Student Community Standards", "https://scs.oregonstate.edu/contact-us"),
              ("Office of the Dean of Students", "https://studentlife.oregonstate.edu/about-us"),
              ("Office of Equal Opportunity and Access (reporting)", "https://eoa.oregonstate.edu/report")]),
    Category("tech", "Technology help",
             "accounts and passwords, Duo, software, Wi-Fi, where to get IT help",
             "How do I reset my ONID password?",
             [("technology.oregonstate.edu", None)],
             r"\b(password|onid|duo|wi-?fi|software|canvas|email|microsoft|zoom|vpn)\b",
             [("UIT Service Desk", "https://technology.oregonstate.edu/help")]),
    Category("ecampus", "Online (Ecampus) students",
             "everything above as it applies to online students, plus the Ask Ecampus FAQ",
             "Do online students pay the same tuition as on-campus students?",
             [("ecampus.oregonstate.edu", None)],
             r"\b(ecampus|online students?|distance)\b",
             [("Oregon State Ecampus", "https://ecampus.oregonstate.edu/contact/")]),
]
BY_ID = {c.id: c for c in CATEGORIES}

# Pages that are navigation or site furniture, not content to answer from.
NO_PURPOSE = [("registrar.oregonstate.edu", r"^/(site-index|clone-)"),  # A-Z link lists; unpublished Drupal clones
              ("uhds.oregonstate.edu", r"^/(layouts|elements|visuals|page-examples)(/|$)")]


def categorize(url: str, title: str = "") -> list[str]:
    """Primary category first (from site and section), then secondary ones from title keywords."""
    parts = urlsplit(url)
    host, path = (parts.hostname or "").lower(), parts.path.lower() or "/"
    if any(host == h and re.search(rx, path) for h, rx in NO_PURPOSE):
        return []
    primary = None
    # Specific section rules win over whole-site rules (registrar /osu-academic-calendar is "dates", not "registration").
    for specific in (True, False):
        for c in CATEGORIES:
            for h, rx in c.sites:
                if host == h and ((rx is not None and re.search(rx, path)) if specific else rx is None):
                    primary = primary or c.id
        if primary:
            break
    cats = [primary] if primary else []
    for c in CATEGORIES:
        if c.id not in cats and re.search(c.keywords, title or "", re.IGNORECASE):
            cats.append(c.id)
    return cats


def assign(con: sqlite3.Connection) -> Counter:
    con.execute("""CREATE TABLE IF NOT EXISTS page_categories (
        page_id INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
        category TEXT NOT NULL,
        is_primary INTEGER NOT NULL,
        PRIMARY KEY (page_id, category))""")
    con.execute("DELETE FROM page_categories")
    counts = Counter()
    for pid, url, title in con.execute("SELECT id, url, title FROM pages WHERE gone_at IS NULL").fetchall():
        cats = categorize(url, title or "")
        for i, c in enumerate(cats):
            con.execute("INSERT INTO page_categories(page_id, category, is_primary) VALUES (?,?,?)", (pid, c, int(i == 0)))
        counts[cats[0] if cats else "(none)"] += 1
    con.commit()
    return counts


# ---- docs/categories.md ------------------------------------------------------------------------

SHARED_TOPICS = [
    ("Tuition refunds after dropping or withdrawing", ["registrar", "finance", "financialaid"],
     "The refund deadlines are on the Registrar's academic calendar; the money side (bills, credits) is Student "
     "Accounts; aid adjustments are Financial Aid. No single page owns the whole answer."),
    ("Registration holds", ["holds", "registrar", "finance"],
     "Holds @ OSU explains each hold type, but each hold is cleared by a different office (Student Accounts, "
     "Student Health, Registrar, advising)."),
    ("Food insecurity and meal help", ["basicneeds", "uhds", "studentlife", "food"],
     "Basic Needs Center, UHDS (meal plans, food insecurity pages) and Food @ OSU all cover parts; the older HSRC "
     "pages on studentlife are unpublished (Access denied)."),
    ("Services for online students", ["ecampus", "ds", "advising", "career", "library"],
     "Ecampus describes DAS, advising, career and library services for online students, but the service itself "
     "belongs to the main office; answers should cite both."),
    ("Exam schedules and conflicts", ["registrar", "ecampus"],
     "The Registrar owns final exam policy; Ecampus owns proctoring for online exams."),
    ("Transfer credit", ["admissions", "transfer", "catalog", "coreeducation"],
     "Admissions publishes the course-by-course tables for each community college; Transfer Students advises; the "
     "catalog and Core Education say how credit counts toward a degree."),
    ("Veterans' education benefits", ["veterans", "registrar", "finance"],
     "Military & Veteran Resources explains the GI Bill chapters and has the VA certifying team; the Registrar "
     "explains how dropping classes affects benefits; the bill itself is Student Accounts'."),
]


def build_doc(con: sqlite3.Connection) -> str:
    q = lambda s, *a: con.execute(s, a).fetchall()
    host_office = {r[0]: r[1] for r in q("SELECT domain, owning_office FROM pages GROUP BY domain")}
    lines = ["# Categories", "",
             f"The {len(CATEGORIES)} task-based categories from [structure-map.md](structure-map.md) (\"Getting in\" "
             "and the campus-life scope of \"Housing, dining & campus life\" added with Tier 2b), with an example question, "
             "the main official sources, and the office to send a student to when we can't answer.",
             "",
             "- **How pages are assigned:** `python -m assistant.categories` gives every page a primary category "
             "from its site and section, plus secondary ones from title keywords. The results go in the "
             "`page_categories` table.",
             "- **Sources are OSU's own:** each source below is a crawled OSU page, shown with its owning office. "
             "Every answer must link to one.", ""]
    totals = dict(q("SELECT category, COUNT(*) FROM page_categories WHERE is_primary=1 GROUP BY 1"))
    for i, c in enumerate(CATEGORIES, start=1):
        lines += [f"## {i}. {c.name}", "", f"**Covers:** {c.covers}.  ",
                  f"**Example question:** *{c.example}*  ",
                  f"**Pages (primary):** {totals.get(c.id, 0)}", "", "**Main official sources**", "",
                  "| Page | Owner | Why it's a main source |", "|---|---|---|"]
        # The pages other OSU sites point to most (links in page content, counted by linking site, then by page).
        rows = q("""SELECT p.url, p.title, p.owning_office,
                           COUNT(DISTINCT substr(l.from_url, 9, instr(substr(l.from_url, 9), '/') - 1)) AS sites,
                           COUNT(DISTINCT l.from_url) AS inlinks
                    FROM page_categories pc JOIN pages p ON p.id = pc.page_id
                    LEFT JOIN links l ON l.to_url = p.url AND l.region = 'main' AND l.from_url <> p.url
                    WHERE pc.category = ? AND pc.is_primary = 1 AND p.archived = 0 AND p.url NOT LIKE '%?page=%'
                    GROUP BY p.id ORDER BY sites DESC, inlinks DESC, LENGTH(p.url) LIMIT 6""", c.id)
        for url, title, office, sites, n in rows:
            lines.append(f"| [{title}]({url}) | {office} | linked from {n} OSU pages on {sites} site{'' if sites == 1 else 's'} |")
        lines += ["", "**When we can't answer, send the student to:** " +
                  "; ".join(f"[{o}]({u})" for o, u in c.contacts), ""]

    # Pages without a clear owner or purpose.
    none_rows = q("""SELECT p.domain, COUNT(*) FROM pages p WHERE NOT EXISTS
                     (SELECT 1 FROM page_categories pc WHERE pc.page_id = p.id) GROUP BY 1 ORDER BY 2 DESC""")
    lines += ["## Pages with no clear owner", "",
              "Every stored page has an owning *site*. But for the questions students ask, three groups have no clear owner:",
              "",
              "### A. Topics split across offices",
              "",
              "The answer has to combine pages, and the app should name every office involved.", "",
              "| Topic | Sites | Why it's split |", "|---|---|---|"]
    for topic, sites, why in SHARED_TOPICS:
        lines.append(f"| {topic} | {', '.join(sites)} | {why} |")
    lines += ["", "### B. Pages whose own label names a section, not an office",
              "",
              "The Drupal site name on these pages is a section (\"Valley\", \"Parking\", \"Explore Careers\", "
              "\"Learning Corner\"). Their owner is taken from the site that hosts them.", "",
              "| Site | Pages | Section labels |", "|---|---:|---|"]
    sections = defaultdict(Counter)
    for dom, label in q("SELECT domain, site_name FROM pages"):
        if is_section_label(dom, label):
            sections[dom][label] += 1
    for dom, labels in sorted(sections.items(), key=lambda kv: -sum(kv[1].values())):
        shown = ", ".join(f"{l} ({n})" for l, n in labels.most_common())
        lines.append(f"| {dom} | {sum(labels.values())} | {shown} |")
    lines += ["", "### C. Navigation and site furniture, not content",
              "",
              "These pages get no category and should not be cited.", ""]
    nav = q("""SELECT p.domain, COUNT(*), MIN(p.url) FROM pages p WHERE NOT EXISTS
               (SELECT 1 FROM page_categories pc WHERE pc.page_id = p.id) GROUP BY 1 ORDER BY 2 DESC""")
    lines += ["| Site | Pages | Example |", "|---|---:|---|"] + [f"| {d} | {n} | {u} |" for d, n, u in nav]
    lines += ["", "- **Registrar `/site-index`:** 48 pages, the office's own A–Z link list.",
              "- **Registrar `/clone-…`:** 2 unpublished Drupal copies (\"Clone of Change of Grading Basis\") that "
              "duplicate a live page.",
              "- **UHDS `/layouts`, `/elements`, `/visuals`, `/page-examples`:** Drupal style-guide pages that OSU left "
              "published.", ""]
    return "\n".join(lines)


def normalize_owners(con: sqlite3.Connection) -> int:
    """Backfill owning_office with the crawler's current rule (scope.office_for); section labels stay in site_name."""
    changed = 0
    for pid, dom, site_name, office in con.execute("SELECT id, domain, site_name, owning_office FROM pages").fetchall():
        new = office_for(dom, site_name)
        if new != office:
            con.execute("UPDATE pages SET owning_office=? WHERE id=?", (new, pid))
            changed += 1
    con.commit()
    return changed


if __name__ == "__main__":
    con = db.connect()
    print("owners normalized:", normalize_owners(con))
    counts = assign(con)
    print("primary categories:", dict(counts.most_common()))
    (ROOT / "docs" / "categories.md").write_text(build_doc(con), encoding="utf-8")
    print("wrote docs/categories.md", file=sys.stderr)
