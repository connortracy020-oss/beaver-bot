"""Which hosts and paths each tier covers. Phase 1+ crawls only what `in_scope` accepts.

Rules are path prefixes, matched case-insensitively. `include` empty = the whole host.
Excludes win over includes. PII and login rules in config.py apply on top of these.
"""
import re
from urllib.parse import unquote, urlsplit

NEWS = ["/all-stories", "/feature-story", "/news", "/stories", "/events", "/announcement", "/podcasts"]


def under(path: str, section: str) -> bool:
    """True when `path` is the section itself or inside it ("/news/x"), not a lookalike ("/newstudent")."""
    section = section.rstrip("/").lower()
    return path == section or path.startswith(section + "/")

TIER1 = {
    # /log-emails-sent-students-* is a feed of dated mass emails (Tier 3), full of named people; each email's own
    # page under /student-emails/ is marked noindex by OSU (440 of them in Phase 2), so don't request them at all.
    "registrar.oregonstate.edu": {"office": "Office of the Registrar", "include": [],
                                  "exclude": ["/archive", "/project", "/office-registrar-projects",
                                              "/log-emails-sent-students", "/student-emails"]},
    "catalog.oregonstate.edu": {"office": "Academic Catalog (Office of the Registrar)", "include": [],
                                "exclude": ["/miscadmin/"]},  # 905 sitemap entries, sampled one is a 404
    "advising.oregonstate.edu": {"office": "Academic Advising", "include": [],
                                 "exclude": ["/weekly-transfer-advising-email-archives"]},
    "financialaid.oregonstate.edu": {"office": "Office of Financial Aid", "include": [], "exclude": []},
    "finance.oregonstate.edu": {"office": "Student Accounts (Office of the Controller)",
                                "include": ["/student-accounts", "/student-resources", "/emergency-loans"],
                                "exclude": []},
    "ds.oregonstate.edu": {"office": "Disability Access Services", "include": [], "exclude": []},
    "studentlife.oregonstate.edu": {"office": "Office of the Dean of Students", "include": [], "exclude": []},
    "scs.oregonstate.edu": {"office": "Student Community Standards", "include": [], "exclude": []},
    "studenthealth.oregonstate.edu": {"office": "Student Health Services", "include": [], "exclude": []},
    "counseling.oregonstate.edu": {"office": "Counseling & Psychological Services", "include": [], "exclude": []},
    "uhds.oregonstate.edu": {"office": "University Housing & Dining Services", "include": [], "exclude": []},
    "library.oregonstate.edu": {"office": "OSU Libraries", "include": [],
                                "exclude": ["/employment", "/awards"]},  # /awards: staff award winners by year
    "technology.oregonstate.edu": {"office": "University Information Technology", "include": [],
                                   "exclude": ["/canvas-outage", "/osu-wordpress-outage", "/status"]},
    "engineering.oregonstate.edu": {"office": "College of Engineering",
                                    "include": ["/academics", "/student-life", "/tools-services",
                                                "/eecs/myeecs", "/cce/mycce", "/mime/mymime", "/nse/mynse",
                                                "/cbee/mycbee"],
                                    "exclude": []},
    "ecampus.oregonstate.edu": {"office": "Oregon State Ecampus",
                                "include": ["/students", "/services", "/soc", "/tuition", "/ask-ecampus",
                                            "/forms", "/contact"],
                                "exclude": ["/services/admissions"]},
    "map.oregonstate.edu": {"office": "Campus Map", "include": ["/"], "exclude": [], "link_only": True},
}

# Found on OSU's Current Students hub; student-facing and small. Approved into Tier 1 on 2026-10-22.
TIER1.update({
    "success.oregonstate.edu": {"office": "Academic Success Center", "include": [], "exclude": []},
    "holds.oregonstate.edu": {"office": "Holds @ OSU", "include": [], "exclude": []},
    "care.oregonstate.edu": {"office": "Student Care (Dean of Students)", "include": [], "exclude": []},
    "basicneeds.oregonstate.edu": {"office": "Basic Needs Center", "include": [], "exclude": []},
})

# Other names a Tier 1 site answers to. scs.oregonstate.edu's sitemap lists its pages under sccs.oregonstate.edu,
# so a redirect between the two stays in scope.
ALIASES = {"scs.oregonstate.edu": ["sccs.oregonstate.edu"]}
TIER1["sccs.oregonstate.edu"] = TIER1["scs.oregonstate.edu"]

# Tier 2 (proposed 2026-10-23, docs/tier2-plan.md; crawled only after the owner's approval). Student-facing sections
# only. People/staff pages, login pages and news/events are skipped by the shared rules as for Tier 1.
TIER2 = {
    "scholarships.oregonstate.edu": {"office": "Scholarship Office", "include": [], "exclude": []},
    "food.oregonstate.edu": {"office": "Food @ OSU (University Housing & Dining Services)", "include": [],
                             "exclude": []},
    "transportation.oregonstate.edu": {"office": "Transportation Services", "include": [],
                                       "exclude": ["/motorpool", "/service-vehicle-permits"]},  # departmental fleet
    "writingcenter.oregonstate.edu": {"office": "Writing Center", "include": [], "exclude": ["/employment"]},
    "career.oregonstate.edu": {"office": "Career Development Center", "include": [],
                               "exclude": ["/employers", "/faculty-staff-tools", "/alumni", "/hello-world",
                                           "/work-in-progress"]},
    "experience.oregonstate.edu": {"office": "OSU Experience", "include": ["/career"], "exclude": []},
}

# Tier 2b (docs/tier2b-plan.md, approved for a pilot on 2026-10-29): the rest of the Tier 2 list. `include_re` and
# `exclude_re` are regexes on the lowercased path. A college site keeps only paths that read as student-facing.
# `office` names come from each site's own name, confirmed in the pilot.
STUDENT_PATH_RE = (r"/(undergrad[\w-]*|graduate[\w-]*|academics?[\w-]*|academic-programs?|programs?(-admissions)?|"
                   r"advising[\w-]*|admissions?|scholarships?[\w-]*|students?|current-students|future-students|"
                   r"prospective-students|majors?|minors?|degrees?|double-degree|internships?|careers?|faq|"
                   r"student-(services|life|experience|resources|success)[\w-]*|premed|pre-health|certificates?|"
                   r"online[\w-]*|pac|biology-prerequisites-and-overrides)(/|$)")
NOT_STUDENT_RE = (r"/(research[\w-]*|news[\w-]*|[\w-]*-news[\w-]*|impact|blog|faculty[\w-]*|people|directory|alumni[\w-]*|giving|"
                  r"events?|seminars?|media|article|good-news|pet-memorial|vdl[\w-]*|extension|stories|story|"
                  r"graduating-student-stories[\w-]*|adviser-search|spotlights?|continuing-and-professional-education|"
                  r"[\w-]*thank-you|"
                  # Lists of named people (full crawl, 2026-10-29): student rosters, profiles, award recipients,
                  # student-show pages, faculty and staff directories.
                  r"[\w-]*student-profiles?|current-phd-students|graduate-teaching-assistants|phd-careers|"
                  r"(past|previous)-recipients[\w-]*|student-works|(showcase|horizons|emerge)-?\d{2,4}|"
                  r"[\w-]*-faculty[\w-]*|[\w-]*-team|advisory-council)"
                  r"(/|$)")


def _whole(office, exclude=(), exclude_re=None):
    # Drupal "/group/<id>" pages are empty group landing pages; student advisory boards are rosters of named students.
    rule = {"office": office, "include": [], "exclude": ["/group/", "/student-advisory-board", *exclude]}
    return {**rule, "exclude_re": exclude_re} if exclude_re else rule


def _college(office, exclude=()):
    return {"office": office, "include": [], "exclude": list(exclude),
            "include_re": STUDENT_PATH_RE, "exclude_re": NOT_STUDENT_RE}


TIER2B = {
    # A. Getting in and moving through
    "admissions.oregonstate.edu": _whole("Office of Admissions", ["/test"]),
    # Resume (2026-10-29): "/story" and "/story-page" profile one named student each, with their project summaries.
    "graduate.oregonstate.edu": _whole("Office of Graduate Education", ["/faculty", "/postdocs",
                                                                        "/meet-office-graduate-education"],
                                       exclude_re=r"(^|/)(story|story-page|stories-[\w-]*)(/|$)"),
    "transfer.oregonstate.edu": _whole("Transfer Students (Office of Admissions)"),
    "internationalservices.oregonstate.edu": _whole("Office of International Services"),
    "intoosu.oregonstate.edu": _whole("INTO OSU"),
    "summer.oregonstate.edu": _whole("Summer Session"),
    "commencement.oregonstate.edu": _whole("Commencement", ["/class-", "/ceremony-archive", "/commencement-speaker",
                                                             "/message-your-asosu-president", "/presidents-reception"],
                                    exclude_re=r"^/ceremony-(19|20)\d\d"),  # past ceremonies
    # Full crawl: research-showcase and thesis-fair pages list each student presenter; awards and staff pages are
    # rosters. Its PDFs are mostly students' own thesis slides and alumni newsletters (see DOC_INCLUDE_RE below).
    # Resume (2026-10-29): "/envoy/<name>" is one profile page per graduating student.
    "honors.oregonstate.edu": _whole("Honors College", ["/faculty-resources", "/faculty-awards", "/slug-staff",
                                                        "/meet-hc-student-ambassadors", "/career-mentors", "/envoy"],
                                     exclude_re=r"research-showcases?(/|$)|thesis[\w-]*-fair"),
    # B. Campus life, safety and support
    # Pilot: club pages are mostly unfinished templates, and some list student officers by name. Keep the main page.
    "clubs.oregonstate.edu": {**_whole("Student Organizations"), "include_re": r"^/$"},
    # Full crawl: the site root holds a profile page per student-government member ("/first-last"), and committee,
    # senate and judicial pages record named students. Keep the student-facing sections only.
    "asosu.oregonstate.edu": {**_whole("ASOSU (student government)", ["/test"]),
                              "include_re": r"^/($|about-us|contact|get-involved|our-units|student-resources|advocacy|"
                                            r"studentfeedback|student-gov)",
                              "exclude_re": r"^/student-gov/(judicial/(meet|opinions)|records|elections/committee|"
                                            r"executive/pres-vp|senate/(committees|legislation|meetings|flc)|"
                                            r"sfc/deliberations)"},
    "recsports.oregonstate.edu": _whole("Recreational Sports", [
        "/aquatics/swim-lessons/meet-your-swim-instructor",
        "/fitness-wellness/fitness-training-assessments/personal-training/meet-your-personal-trainers"],
        exclude_re=r"(minutes|agenda)(/|$)"),  # advisory-board meeting records
    "mu.oregonstate.edu": _whole("Memorial Union", ["/test"]),
    "familyresources.oregonstate.edu": _whole("Family Resource Center", ["/family-resource-center-team"]),
    "diversity.oregonstate.edu": _whole("Office of Institutional Diversity", [
        "/faculty-recruitment", "/data", "/mlkcommemoration/legacy-awards", "/mlk%20commemoration/legacy-awards",
        "/inclusive-excellence-advocate-award-previous-recipients", "/equity-leaders-consortium"],
        exclude_re=r"^/state-inclusive-excellence/."),  # one profile page per named student or staff member
    "cape.oregonstate.edu": _whole("Center for Advocacy, Prevention & Education (CAPE)"),
    "eoa.oregonstate.edu": _whole("Office of Equal Opportunity and Access", ["/annual-report", "/workforce-insights"]),
    "publicsafety.oregonstate.edu": _whole("Department of Public Safety", ["/osu-jobs"]),
    # Resume (2026-10-29): the Gold Star memorial has a page per named service member; its landing page stays.
    "veterans.oregonstate.edu": _whole("Military & Veteran Resources", ["/meet-coordinator", "/gold-star-project-"]),
    "undergradresearch.oregonstate.edu": _whole("Undergraduate Research", [
        "/past-recipients", "/undergraduate-research-ambassadors", "/ursa-engage-faculty-mentors", "/mentor-year"]),
    "coreeducation.oregonstate.edu": _whole("Core Education", ["/faculty-resources", "/implementation-resources"]),
    "see.oregonstate.edu": _whole("Student Experiences & Engagement", ["/omn-advisory-board", "/see-jobs",
                                                                       "/ela/orange-media-network/omn-awards"]),
    "policy.oregonstate.edu": _whole("University Policies and Standards"),
    # C. The other colleges: student-facing paths only
    "business.oregonstate.edu": _college("College of Business"),
    "liberalarts.oregonstate.edu": _college("College of Liberal Arts", [  # winners by year, nothing else
        "/sps/psychology/undergraduate-psychology/information-students/student-awards"]),
    "health.oregonstate.edu": _college("College of Health", ["/pac/class"]),  # one page per PAC class; the catalog has them
    "agsci.oregonstate.edu": _college("College of Agricultural Sciences", [  # extension and research stations
        "/coarec", "/nwrec", "/harec", "/eoarc", "/cbarc", "/smallfarms", "/oregon-vegetables", "/nurspest",
        "/thesource", "/beaverlandscapes", "/leadershipacademy",
        "/bpp", "/bee", "/botany-and-plant-pathology"]),  # department pages that redirect to their own sites
    "education.oregonstate.edu": _college("College of Education", ["/program/program-default-values",
                                                                   "/program/undergraduate-program-template"]),
    "ceoas.oregonstate.edu": _college("College of Earth, Ocean, and Atmospheric Sciences", ["/ceoas-outreach"]),
    "www.forestry.oregonstate.edu": _college("College of Forestry"),
    "science.oregonstate.edu": _college("College of Science"),
    "vetmed.oregonstate.edu": _college("Carlson College of Veterinary Medicine"),
    "pharmacy.oregonstate.edu": _college("College of Pharmacy", ["/programs-admissions/continuing-education"]),
    "math.oregonstate.edu": _college("Department of Mathematics"),
    "ib.oregonstate.edu": _college("Department of Integrative Biology"),
}
# graduate.oregonstate.edu's sitemap lists its pages under gradschool.oregonstate.edu, which redirects to it.
ALIASES["graduate.oregonstate.edu"] = ["gradschool.oregonstate.edu"]
TIER2B["gradschool.oregonstate.edu"] = TIER2B["graduate.oregonstate.edu"]

# Every approved host's rules, for lookups by host. A crawl phase still only contacts its own host list.
SCOPE = {**TIER1, **TIER2, **TIER2B}

# PDFs that are records about named students, not help for them (full Tier 2b crawl, 2026-10-29): meeting minutes and
# agendas, election results and voter guides, research-showcase and lightning-talk programs; and (resume) students'
# own work: project executive summaries (not the guidelines for writing one), dissertation abstracts, a sample paper.
# Matched against the file name and the linking text, on every site.
STUDENT_RECORDS_DOC_RE = re.compile(r"(?<![a-z])(minutes|agendas?|lightning[ _-]?talks?|election[ _-]?results|"
                                    r"voter[ _-]?guide|preliminary[ _-]?results)(?![a-z])|showcase|"
                                    r"executive[ _-]?summary(?![ _-]?guidelines)|dissertation|"
                                    r"tayler_-_jewish_marriage", re.IGNORECASE)
# Sites whose PDFs are mostly such records keep only the PDFs named here. ASOSU: governing documents, not its 600+
# minutes, bills and budgets. Honors: guides for students and parents, not students' thesis slides or alumni news.
DOC_INCLUDE_RE = {
    "asosu.oregonstate.edu": r"constitution|statutes|code[ _-]?of[ _-]?conduct|judicial[ _-]?(council[ _-]?)?polic|"
                             r"unit[ _-]?rules|operations[ _-]?manual",
    # Narrow on purpose: a thesis title can say "policies" or "guide".
    "honors.oregonstate.edu": r"(?<![a-z])(brochure|nsp|new[ _-]?student|launch|parent|checklist|pedagogy|"
                              r"thesis[ _-]?poster|how can i|what now|handbook|faq)",
}


def document_in_scope(url: str, purpose: str | None = None) -> bool:
    """Whether to keep a PDF linked from an in-scope page (its host's page rules don't apply to file paths)."""
    parts = urlsplit(url)
    name = unquote(parts.path.rsplit("/", 1)[-1]) + " | " + (purpose or "")
    if STUDENT_RECORDS_DOC_RE.search(name):
        return False
    keep = DOC_INCLUDE_RE.get((parts.hostname or "").lower())
    return not keep or bool(re.search(keep, name, re.IGNORECASE))


def canonical_host(url: str) -> str:
    """Rewrite an alias host to the site's own name (sccs -> scs, gradschool -> graduate)."""
    for host, aliases in ALIASES.items():
        for alias in aliases:
            url = url.replace(f"://{alias}/", f"://{host}/")
            if url.endswith(f"://{alias}"):
                url = url[: -len(alias)] + host
    return url

# Hosts we never crawl, with the reason recorded in the plan.
EXCLUDED_HOSTS = {
    "classes.oregonstate.edu": "bot protection: robots.txt answered HTTP 202 (challenge); stopped, not retried",
    "guides.library.oregonstate.edu": "robots.txt disallows every named AI crawler (GPTBot, CCBot, Google-Extended, ...) "
                                      "and sets Crawl-delay 10; we honour the intent and skip it",
    "fa.oregonstate.edu": "TLS certificate chain fails verification; student billing lives on finance.oregonstate.edu",
    "directory.oregonstate.edu": "people directory (PII)",
    "search.oregonstate.edu": "site search (robots-style /search/ and a JS app)",
}


def rule_for(host: str, tiers=(TIER1,)) -> dict | None:
    for tier in tiers:
        if host in tier:
            return tier[host]
    return None


def in_scope(url: str, tiers=(TIER1,)) -> bool:
    parts = urlsplit(url)
    rule = rule_for((parts.hostname or "").lower(), tiers)
    if rule is None:
        return False
    path = parts.path.lower() or "/"
    if any(path.startswith(p.lower()) for p in rule["exclude"]) or any(under(path, p) for p in NEWS):
        return False
    if rule.get("exclude_re") and re.search(rule["exclude_re"], path):
        return False
    if rule.get("link_only"):
        return path == "/"
    if rule.get("include_re") and not re.search(rule["include_re"], path):
        return False
    return not rule["include"] or any(path.startswith(p.lower()) for p in rule["include"])


_NAME_STOP = {"osu", "oregon", "state", "university", "office", "of", "the", "and", "student", "students"}
_UNIT_RE = re.compile(r"\b(office|center|services|school|college|department|engineering|science|controller)\b", re.I)


def _name_words(name: str) -> set[str]:
    return set(re.findall(r"[a-z]+", name.lower())) - _NAME_STOP


def office_for(host: str, site_name: str | None) -> str | None:
    """The office that owns a page. A site's Drupal label is often a section ("Valley", "Parking", "Learning
    Corner"), not an office, so the host's office wins, unless the label names a distinct unit such as an
    engineering department."""
    office = (SCOPE.get(host) or {}).get("office")
    if not site_name or not office:
        return office or site_name
    if _name_words(site_name) <= _name_words(office):  # "Financial Aid" is "Office of Financial Aid"
        return office
    return site_name if _UNIT_RE.search(site_name) else office


def is_section_label(host: str, site_name: str | None) -> bool:
    """True when the page's own label names a section of the site rather than an office."""
    office = (SCOPE.get(host) or {}).get("office")
    words = _name_words(site_name or "")
    return bool(site_name and office and office_for(host, site_name) == office
                and (not words or not words <= _name_words(office)))  # a bare "Students" is a section too


_STATIC_RE = re.compile(r"\.(css|js|png|jpe?g|gif|svg|ico|webp|woff2?|ttf|mp4|mp3|zip)$", re.IGNORECASE)


def is_asset(url: str) -> bool:
    """Logos, images, stylesheets and scripts are never downloaded (we copy information, not branding)."""
    return bool(_STATIC_RE.search(urlsplit(url).path))
