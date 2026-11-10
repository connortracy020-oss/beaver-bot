"""Which OSU office owns a topic, in the words students use for it.

Keyword search only matches exact words, and students don't use OSU's. A student says "meal plan"; University
Housing & Dining's page says "dining plan", so a college FAQ that happens to say "meal plan" used to win. Each
topic here has: the student wording that signals it, OSU's own words for it (added to the search), the site or
sites of the office that owns it (ranked above another site's page about the same thing), and the office to send
a student to when we can't answer.

Hosts and contacts are OSU sites this project already stores; nothing here makes a request.
"""
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit


@dataclass
class Topic:
    id: str
    asks: str                                   # regex over the student's question
    words: str                                  # OSU's wording, added to the search
    hosts: list[tuple[str, str | None]]         # (host, path regex or None for the whole site) that own the topic
    contacts: list[tuple[str, str]] = field(default_factory=list)


def _h(*names: str) -> list[tuple[str, str | None]]:
    return [(f"{n}.oregonstate.edu", None) for n in names]


def _need(subject: str) -> str:
    """A question that names this subject and is about studying it or getting help with it, in either order."""
    wants = r"stud(y|ying|ies)|help\w*|tutor\w*|struggl\w*|homework|rooms?|place|spot|groups?|stuck|failing|ayuda|estudiar|tutor[ií]as?"
    return rf"^(?=.*\b(?:{subject})\b)(?=.*\b(?:{wants})\b)"


UHDS = ("University Housing & Dining Services", "https://uhds.oregonstate.edu/contact-uhds")
REGISTRAR = ("Office of the Registrar", "https://registrar.oregonstate.edu/contact-us")
ACCOUNTS = ("Student Accounts (billing)", "https://finance.oregonstate.edu/student-accounts")
AID = ("Office of Financial Aid", "https://financialaid.oregonstate.edu/contact-us")
ASC = ("Academic Success Center", "https://success.oregonstate.edu/")
ADVISING = ("Academic Advising", "https://advising.oregonstate.edu/")
CAPS = ("Counseling & Psychological Services (24/7: 541-737-2131)", "https://counseling.oregonstate.edu/hours-location")
SHS = ("Student Health Services", "https://studenthealth.oregonstate.edu/locations")

TOPICS = [
    Topic("dining", r"\bmeal ?plans?\b|\bdining\b|\bdining (dollars|plans?)\b|\borange cash\b|\bmeal swipes?\b|\bfood (plan|on campus)\b|"
                    r"\bwhere (can|do) i eat\b|\bcafeteria\b|\bplan de comidas\b",
          "dining plan dining dollars rates", [("uhds.oregonstate.edu", r"^/(dining|rates-guides|food)"), *_h("food")], [UHDS]),
    Topic("housing", r"\bdorms?\b|\bresidence halls?\b|\bhousing\b|\broommates?\b|\bmove[- ]?in\b|\blive on campus\b|\bon[- ]campus (living|room)\b|"
                     r"\broom (rate|cost|price)s?\b|\bmy ra\b|\bresident assistant\b",
          "residence hall housing room rates", _h("uhds"), [UHDS]),
    Topic("tutoring", r"\btutor\w*\b|\bstudy (help|table|skills|group)s?\b|\bstruggling (in|with)\b|\bfailing\b|\bacademic coach\w*\b|"
                      r"\bsupplemental instruction\b|\bhelp with (my )?(class|classes|math|chem\w*|physics|homework|studying)\b",
          "tutoring academic success center learning corner", _h("success"), [ASC]),
    # A subject plus a wish to study it or get help with it: the subject's own help center, not the generic answer.
    # "study rooms for math" is about math first; without this the words "study rooms" bury it under library pages.
    Topic("math-help", _need(r"math\w*|calc\w*|algebra|trig\w*|statistics|stats?|mth ?\d{3}\w?|st ?\d{3}\w?|matem[aá]ticas?|c[aá]lculo"),
          "Mathematics and Statistics Learning Center MSLC math tutoring study group Kidder Hall Pi Hole",
          [("math.oregonstate.edu", r"learning-center|tutoring"), ("science.oregonstate.edu", r"academic-support"), ("library.oregonstate.edu", r"spaces/tutoring")],
          [("Mathematics and Statistics Learning Center", "https://math.oregonstate.edu/undergraduate/mathematics-statistics-learning-center")]),
    Topic("chem-help", _need(r"chem\w*|ch ?\d{3}\w?|qu[ií]mica"), "chemistry tutoring Mole Hole chemistry support academic support centers",
          [("science.oregonstate.edu", r"academic-support"), ("library.oregonstate.edu", r"spaces/tutoring")],
          [("College of Science academic support centers", "https://science.oregonstate.edu/academics/academic-support-tutoring")]),
    Topic("physics-help", _need(r"physics|ph ?\d{3}\w?|f[ií]sica"), "physics tutoring Wormhole physics support academic support centers",
          [("science.oregonstate.edu", r"academic-support"), ("library.oregonstate.edu", r"spaces/tutoring")],
          [("College of Science academic support centers", "https://science.oregonstate.edu/academics/academic-support-tutoring")]),
    Topic("cs-help", _need(r"cs ?\d{3}\w?|computer science|coding|programming|engr ?\d{3}\w?|engineering|programaci[oó]n"),
          "College of Engineering peer tutoring program computer science tutoring academic support",
          [("engineering.oregonstate.edu", r"academic-support|student-experience/support"), ("success.oregonstate.edu", None)],
          [("College of Engineering Peer Tutoring", "https://engineering.oregonstate.edu/tools-services/academic-support/college-engineering-peer-tutoring-program")]),
    Topic("writing", r"\b(essay|paper)s?\b|\bwriting (help|center|tutor)\b|\bproofread\w*\b|\bcitations?\b",
          "writing center writing consultation", _h("writingcenter"), [("Writing Center", "https://writingcenter.oregonstate.edu/")]),
    Topic("major", r"\b(change|switch|chang\w+|declare|pick|choose|add|drop)\b[^.?]{0,25}\b(majors?|minors?|degree program)\b|\bundeclared\b|"
                   r"\bdouble major\b|\bmy advis[eo]r\b|\bacademic advis\w+\b|\bwho is my advis[eo]r\b",
          "change of major academic advising advisor", _h("advising"), [ADVISING]),
    Topic("counseling", r"\bcounsel\w*\b|\btherap\w*\b|\bshrink\b|\bmental health\b|\banxi\w+\b|\bdepress\w*\b|\bstress\w*\b|\boverwhelmed\b|"
                        r"\bsomeone to talk to\b|\bcaps\b",
          "counseling psychological services CAPS", _h("counseling"), [CAPS]),
    Topic("health", r"\bsick\b|\bdoctors?\b|\bnurse\b|\bvaccin\w*\b|\bimmuni[sz]\w*\b|\bhealth (insurance|center|services|fee)\b|\bclinic\b|"
                    r"\bflu\b|\bcovid\b|\bprescriptions?\b|\bpharmacy\b|\bstd\b|\bsti\b|\bbirth control\b|\bphysical therapy\b|\binjur\w+\b",
          "student health services", _h("studenthealth"), [SHS]),
    Topic("billing", r"\bpayment plans?\b|\bpay\w* (my |for )?(bill|tuition|fees?|balance)\b|\b(my )?bill\b|\blate fees?\b|\brefunds?\b|\bowe\b|"
                     r"\bmybill\b|\btuition (is )?due\b|\binstal?lments?\b|\bdirect deposit\b|\b1098\b|\bpast due\b|\bbalance\b",
          "student accounts billing payment", [("finance.oregonstate.edu", r"^/(student-accounts|students?|tuition|billing)"), *_h("finance")], [ACCOUNTS]),
    Topic("aid", r"\bfafsa\b|\bfinancial aid\b|\bgrants?\b|\bloans?\b|\bwork[- ]study\b|\baid (package|offer|award)\b|\bpell\b|\bsap\b|"
                 r"\bmoney for (school|college)\b|\bafford (school|college|tuition)\b",
          "financial aid", _h("financialaid"), [AID]),
    Topic("scholarships", r"\bscholarships?\b|\bscholardollars\b", "scholarships ScholarDollars", _h("scholarships", "financialaid"),
          [("Scholarship Office", "https://scholarships.oregonstate.edu/contact-us")]),
    Topic("cost", r"\bhow much (is|does|are|will)\b[^.?]{0,30}\b(tuition|osu|oregon state|cost|fees?)\b|\bcost of attendance\b|\btuition (rate|cost)s?\b|"
                  r"\bin[- ]state tuition\b|\bresidency\b",
          "tuition fees cost of attendance", _h("financialaid", "finance"), [AID, ACCOUNTS]),
    Topic("registration", r"\bregist\w+\b|\b(add|drop|withdraw\w*)\b[^.?]{0,20}\b(class|classes|course|courses|term)\b|\bwait ?list\w*\b|\boverrides?\b|"
                          r"\bholds?\b|\btranscripts?\b|\bgrading basis\b|\bpass[/ -]?(fail|no pass)\b|\bs/u\b|\bincompletes?\b|\bcrn\b|"
                          r"\bsign up for classes\b|\baudit a class\b|\bretake\b|\brepeat a (class|course)\b|\benrollment verification\b",
          "registration register add drop withdraw", _h("registrar", "holds"), [REGISTRAR]),
    Topic("dates", r"\bdeadlines?\b|\blast day\b|\bdue date\b|\bwhen (does|do|is|are|can)\b[^.?]{0,40}\b(term|quarter|classes|finals|break|start|begin|end|"
                   r"registration|register|add|drop|withdraw)\b|\bacademic calendar\b|\bfinals week\b|\bspring break\b",
          "academic calendar", [("registrar.oregonstate.edu", r"^/osu-academic-calendar")],
          [("Office of the Registrar", "https://registrar.oregonstate.edu/osu-academic-calendar")]),
    Topic("graduation", r"\bgraduat\w+\b[^.?]{0,30}\b(apply|application|ceremony|requirements?|check|audit)\b|\bapply to graduate\b|\bcommencement\b|"
                        r"\bdiploma\b|\bcap and gown\b|\bcredits? to graduate\b",
          "graduation commencement degree", _h("registrar", "commencement"), [REGISTRAR]),
    Topic("parking", r"\bpark\w*\b|\bpermits?\b|\bbus(es)?\b|\bbike\w*\b|\bshuttle\b|\bbeaver bus\b|\bscooters?\b|\bcar on campus\b|\bcommut\w+\b",
          "parking permit transportation", _h("transportation"), [("Transportation Services", "https://transportation.oregonstate.edu/contact-us")]),
    Topic("recreation", r"\bgym\b|\bdixon\b|\bintramurals?\b|\brec (center|sports)\b|\bfitness\b|\bclimbing\b|\bpool\b|\bwork ?out\b|\bsport clubs?\b",
          "recreational sports Dixon", _h("recsports"), [("Recreational Sports", "https://recsports.oregonstate.edu/about/contact")]),
    Topic("clubs", r"\bclubs?\b|\bstudent org\w*\b|\bfraternit\w+\b|\bsororit\w+\b|\bgreek life\b|\bget involved\b|\bstudent government\b|\basosu\b",
          "student organizations clubs", _h("clubs", "see", "asosu"), []),
    Topic("safety", r"\bpolice\b|\bsafe ?ride\b|\blost (and|&) found\b|\bstolen\b|\btheft\b|\bcampus safety\b|\bwalk me home\b|\bescort\b",
          "public safety", _h("publicsafety"), [("Department of Public Safety", "https://publicsafety.oregonstate.edu/contact")]),
    Topic("access", r"\baccommodat\w+\b|\bdisabilit\w+\b|\bdas\b|\bextra time\b|\bnote ?takers?\b|\badhd\b|\bdyslexi\w+\b|\bservice animal\b",
          "disability access services accommodations", _h("ds"), [("Disability Access Services", "https://ds.oregonstate.edu/hours-and-contact-information")]),
    Topic("tech", r"\bwi-?fi\b|\beduroam\b|\bonid\b|\bpasswords?\b|\bduo\b|\bcanvas\b|\b(osu |school )?e-?mail\b|\bvpn\b|\bsoftware\b|\bprint\w*\b|"
                  r"\blaptops?\b|\bcomputer labs?\b|\bmicrosoft\b|\bzoom\b|\binternet\b|\b2fa\b|\btwo[- ](step|factor)\b",
          "technology service desk", _h("technology"), [("UIT Service Desk", "https://technology.oregonstate.edu/help")]),
    Topic("library", r"\blibrar\w+\b|\bstudy rooms?\b|\bcheck out (a )?(book|laptop)s?\b|\binterlibrary\b|\bvalley library\b",
          "library", _h("library"), [("OSU Libraries", "https://library.oregonstate.edu/contact")]),
    Topic("career", r"\bjobs?\b|\binternships?\b|\bresum[eé]s?\b|\bcareers?\b|\bhandshake\b|\binterviews?\b|\bcover letters?\b|\bcareer fair\b",
          "career development center", _h("career"), [("Career Development Center", "https://career.oregonstate.edu/about/contact")]),
    Topic("basic needs", r"\bfood pantry\b|\bfree food\b|\bhungry\b|\bsnap\b|\bfood stamps\b|\b(can'?t |cannot )?afford (food|rent|groceries|textbooks?)\b|"
                         r"\bemergency (funds?|money|housing|loan)\b|\btextbook lending\b|\bhomeless\b|\bbroke\b",
          "basic needs center food pantry", _h("basicneeds"), [("Basic Needs Center", "https://basicneeds.oregonstate.edu/lets-connect")]),
    Topic("conduct", r"\bcheat\w*\b|\bacademic (misconduct|integrity|dishonesty)\b|\bplagiar\w+\b|\bcode of conduct\b|\bconduct (hearing|violation|meeting)\b|"
                     r"\bgot (written up|in trouble)\b",
          "student conduct community standards academic misconduct", _h("scs", "sccs", "studentlife"),
          [("Student Community Standards", "https://scs.oregonstate.edu/contact-us")]),
    Topic("equity", r"\btitle ix\b|\bharass\w+\b|\bdiscriminat\w+\b|\bbias\b|\breport (an? )?(incident|assault)\b|\bsexual (assault|misconduct)\b",
          "equal opportunity and access report", _h("eoa"), [("Office of Equal Opportunity and Access (reporting)", "https://eoa.oregonstate.edu/report")]),
    Topic("admissions", r"\bappl(y|ying|ication)\b[^.?]{0,30}\b(osu|oregon state|admission|freshman|first[- ]year|transfer)\b|\badmissions?\b|\bget into osu\b|"
                        r"\btransfer (credits?|student|from)\b|\b(ap|ib) (credits?|scores?|exam)\b|\bcommunity college\b|\bacceptance\b|\bdual enroll\w*\b",
          "admissions apply transfer credit", _h("admissions", "transfer"),
          [("Office of Admissions", "https://admissions.oregonstate.edu/contact-information")]),
    Topic("international", r"\bvisas?\b|\bi-?20\b|\bopt\b|\bcpt\b|\bf-?1\b|\bj-?1\b|\binternational students?\b|\bsevis\b|\bwork authorization\b",
          "international services immigration", _h("internationalservices"),
          [("Office of International Services", "https://internationalservices.oregonstate.edu/international-osu/contact-ois")]),
    Topic("veterans", r"\bveterans?\b|\bgi bill\b|\bmilitary\b|\bva benefits?\b", "military veteran resources", _h("veterans"),
          [("Military & Veteran Resources", "https://veterans.oregonstate.edu/contact-us")]),
    Topic("ecampus", r"\becampus\b|\bonline (degree|program|student|students)\b|\bdistance (student|learner|education)\b|\bproctor\w*\b",
          "Ecampus online", _h("ecampus"), [("Oregon State Ecampus", "https://ecampus.oregonstate.edu/contact/")]),
    Topic("catalog", r"\bprereq\w*\b|\bbacc core\b|\bcore ed\w*\b|\bgen ?eds?\b|\bdegree requirements?\b|\bwhat classes (do i|are)\b|\bcourse description\b|"
                     r"\bacademic (standing|probation|regulations?)\b|\bdean'?s list\b|\bhonor roll\b|\bgpa (to|do i|needed|requirement)\b",
          "academic catalog requirements", _h("catalog", "coreeducation"), []),
    Topic("family", r"\bchild ?care\b|\bdaycare\b|\bstudent parents?\b|\blactation\b", "family resource center childcare", _h("familyresources"),
          [("Family Resource Center", "https://familyresources.oregonstate.edu/contact")]),
]
_COMPILED = [(t, re.compile(t.asks, re.I)) for t in TOPICS]


def topics_for(question: str) -> list[Topic]:
    return [t for t, rx in _COMPILED if rx.search(question or "")]


def expansion(question: str) -> str:
    """OSU's wording for the topics this question is about, to add to a keyword search."""
    return " ".join(t.words for t in topics_for(question))


def owns(topics: list[Topic], url: str) -> bool:
    parts = urlsplit(url)
    host, path = (parts.hostname or "").lower().removeprefix("www."), (parts.path or "/").lower()
    return any(host == h.removeprefix("www.") and (rx is None or re.search(rx, path)) for t in topics for h, rx in t.hosts)


def contacts_for(question: str, limit: int = 3) -> list[tuple[str, str]]:
    """The office or offices for this question's topic, most specific first. Empty when no topic matches."""
    out = []
    for t in topics_for(question):
        for c in t.contacts:
            if c not in out:
                out.append(c)
    return out[:limit]
