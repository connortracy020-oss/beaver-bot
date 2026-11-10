"""Remove individuals' contact details from stored text, keeping office and role contacts.

Applied in the storage pipeline (extract.py and process.read_pdf call scrub_text before anything is stored) and,
for data stored earlier, by `python -m osu_crawl.privacy scrub`.

What counts as personal:
- an email whose local part names a person ("first.last@", "first.m.last@") and has no role word in it
  ("financial.aid@", "cbee.advising@", "accounts.receivable@" are role mailboxes and stay), or any address at a
  consumer mail provider (gmail, yahoo, ...);
- a phone number or extension that sits in a person's contact entry: right after a person's name and/or job title
  ("Jane Doe, Associate Dean, 541-737-1234"), after "contact/call <Name>", or next to that person's own email.
Office lines ("Phone: 541-737-4331" in an office's contact box, "Main office 541-...", "Front desk ...", 800
numbers) and role mailboxes stay. Names themselves stay: page text is kept as published (owner's decision
2026-10-22); only the contact details attached to a person are removed.

    python -m osu_crawl.privacy audit    # count affected records, change nothing
    python -m osu_crawl.privacy scrub    # rewrite stored fields, log counts to data/logs/scrub-<time>.json
"""
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone

EMAIL_TOKEN = "[personal email removed]"
PHONE_TOKEN = "[direct phone removed]"

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(r"(?<![\d-])(?:\+?1[\s.-]?)?(?:\(\d{3}\)\s?|\d{3}[\s.-])\d{3}[\s.-]\d{4}(?:\s*(?:x|ext\.?)\s*\d{2,5})?(?!\d)"
                      r"|(?<![\d-])\b7-\d{4}\b(?!-)", re.IGNORECASE)
CONSUMER_MAIL = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com", "aol.com", "comcast.net",
                 "live.com", "msn.com", "protonmail.com", "me.com"}
# Words that make a mailbox a role/office address rather than a person's.
ROLE_WORDS = set("""
office offices help info information admin admins administration admissions aid financial accounts receivable
payable cashiers cashier school dept department departments undergrad undergraduate grad graduate gradinfo
gradstudies rotc gsa advocacy economics program programs studentsuccess success scholarships scholarship career
careers center centre services service support testing transfer club clubs team desk registrar registrars
registration records transcripts transcript housing dining health counseling library libraries ref reference hr
payroll billing conduct care deans dean deanofstudents diversity familyresources exemptions questions complaints
claims reporting www web webmaster news events media marketing communications osu studentlife involvement
advising advisor advisors ask contact contacts general main front reception enroll enrollment orientation
students student staff faculty alumni research lab labs institute initiative network outreach engagement
operations ops it techhelp servicedesk security safety police parking transportation recsports recreation
sports athletics veterans military international global ecampus online summer commencement honors writing
tutoring learning accessibility disability das caps uhds hsrc bnc asosu sccs scs eecs mime cce cbee nse ceoas
cel dce ecs csc abm apcc brr cccc cvm coe cos cla cas cfsl esl intl isp gradschool fes ferm fws hort cropsoil
coes coeadvising bee bb applied army navy air force afrotc nrotc civil mechanical chemical industrial nuclear
electrical bioengineering engr engineering forestry pharmacy vetmed business education liberalarts science
agsci public policy committee council senate board foundation fund grants grant procurement purchasing
inventory surplus mail receiving facilities maintenance custodial printing copy store bookstore cafe food
pantry meals mealbux snap fyeexemptions exemption appeals appeal petitions petition forms form apply
applications application inquiries inquiry questions feedback suggestions webteam it-help noreply no-reply
gradingquestions craftcenter gamedev speakingclub
""".split())

TITLE_WORDS = (r"Dean|Associate Dean|Assistant Dean|Vice Provost|Provost|President|Vice President|Director|"
               r"Associate Director|Assistant Director|Executive Director|Coordinator|Manager|Program Manager|"
               r"Advisor|Adviser|Academic Advisor|Counselor|Specialist|Professor|Associate Professor|"
               r"Assistant Professor|Instructor|Lecturer|Chair|Head|Officer|Librarian|Administrator|"
               r"Assistant|Associate|Supervisor|Lead|Registrar|Analyst|Representative|Navigator|Coach|"
               r"Strategist|Liaison|Consultant|Technician|Engineer|Developer|Designer|Ombuds(?:person)?")
# Words that mark an organization, not a person ("Student Health Services: 541-737-9355" is an office line).
ORG_WORDS = set("""
office student students services service center centre department dept university college school program
programs health library libraries oregon state academic financial aid housing dining career writing disability
access counseling registrar admissions ecampus engineering science sciences main front desk help line phone fax
hours hall building campus corvallis cascades portland bend newport toll free international graduate
undergraduate business human resources resource community standards basic needs care dean deans operations
information technology support network recreation sports police public safety emergency crisis transportation
parking accounts billing payroll controller cashier cashiers testing records transcripts veterans military
pharmacy veterinary medicine forestry agricultural liberal arts education hatfield marine valley memorial union
reser stadium kerr administration learning success advising math lab labs room suite floor annex the of and for
osu uhds caps das hsrc asosu scs sccs eecs mime cbee cce nse coe oregonian state's university's apartments
global online summer honors tutoring desk assistance appointment appointments clinic pharmacy lgbtq
""".split())
NAME = r"(?:Dr\.\s+)?[A-Z][a-z]+(?:[-'’][A-Z][a-z]+)?(?:\s+[A-Z]\.)?(?:\s+(?:van|von|de|del|la|le|da|di|du)\s+|\s+)[A-Z][a-zA-Z'’-]+(?:\s+[A-Z][a-zA-Z'’-]+)?"
PERSON_RES = [
    re.compile(rf"(?P<name>{NAME}),?\s*(?:\((?:she|he|they)[^)]*\)\s*,?\s*)?(?:(?:Ph\.?\s?D\.?|M\.?S\.?|M\.?A\.?|Ed\.?D\.?|MBA|LPC|LCSW|PsyD)\s*,?\s*)*(?:{TITLE_WORDS})\b"),
    re.compile(rf"\b(?i:contact|call|email|e-mail|reach|text)\s+(?P<name>{NAME})\b"),  # the name stays case-sensitive
    # A staff listing line: "Jane Doe 104 Some Hall Phone: 541-..." (name, then room/building, then a phone label)
    re.compile(rf"(?:^|(?<=/ )|(?<=\n)|(?<=: ))(?P<name>{NAME})\s+[^\n/|]{{0,40}}?\b(?:Phone|Tel|Office)\s*:"),
    # "Matt Smith—541-737-0000" / "Matt Smith, 541-737-0000" (a colon is left out: "Lebanon: (541) ..." is a town)
    re.compile(rf"(?P<name>{NAME})\s*(?:,|—|–)\s*(?=\(?\d{{3}}\)?[\s.-]?\d{{3}}[\s.-]\d{{4}}|7-\d{{4}}\b)"),
]
# Labels that mark an office line even inside a person's entry. Plain "Office:" is not one: faculty listings use
# it for the person's own desk phone.
OFFICE_LABEL_RE = re.compile(r"(main office|main line|main|front desk|fax|toll[- ]free|general|reception|"
                             r"help ?desk|hotline|service desk|crisis|24/7|after hours?|call us|contact us|reach us|"
                             r"us at|our office)\b[^0-9\n]{0,25}$", re.IGNORECASE)
WINDOW = 70  # a phone this close after a person's name/title, in the same entry, is that person's
# An entry ends at a sentence end, a line break, a list separator or a table cell.
SEGMENT_END_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\[])|\n|\s\|\s|•|;\s|\s-\s(?=[A-Z])")


def _is_person_name(name: str) -> bool:
    words = re.findall(r"[A-Za-z'’-]+", name.replace("Dr.", ""))
    return len(words) >= 2 and not any(w.lower().strip("'’") in ORG_WORDS for w in words)


def is_personal_email(email: str) -> bool:
    local, _, domain = email.lower().partition("@")
    if domain in CONSUMER_MAIL:
        return True
    tokens = [t for t in re.split(r"[._+-]", local) if t]
    if any(t in ROLE_WORDS or t.rstrip("s") in ROLE_WORDS for t in tokens):
        return False
    if all(len(t) <= 3 or not re.search(r"[aeiouy]", t) for t in tokens):
        return False  # acronyms ("lbh.bcc@" is a cultural center's mailbox), not a name
    # first.last, first.m.last, first.last2 -- OSU's format for people's addresses
    return len(tokens) >= 2 and all(re.fullmatch(r"[a-z]+\d*", t) for t in tokens) and len(tokens[0]) >= 2


def _person_anchors(text: str) -> list[tuple[int, int]]:
    spans = []
    for rx in PERSON_RES:
        for m in rx.finditer(text):
            if _is_person_name(m.group("name")):
                spans.append((m.start(), m.end()))
    return spans


def scrub_text(text: str | None) -> tuple[str | None, Counter]:
    """Return (text with individuals' emails and direct phones replaced, counts of what was replaced)."""
    counts: Counter = Counter()
    if not text or ("@" not in text and not PHONE_RE.search(text)):
        return text, counts
    personal_emails = [(m.start(), m.end()) for m in EMAIL_RE.finditer(text) if is_personal_email(m.group(0))]
    anchors = _person_anchors(text) + personal_emails
    remove: list[tuple[int, int, str]] = [(a, b, EMAIL_TOKEN) for a, b in personal_emails]
    bounds = [0] + [m.end() for m in SEGMENT_END_RE.finditer(text)] + [len(text) + 1]

    def segment(pos: int) -> int:
        return max(i for i, b in enumerate(bounds) if b <= pos)

    for m in PHONE_RE.finditer(text):
        s, e = m.start(), m.end()
        if m.group(0).lstrip("+1 .-(").startswith(("800", "888", "877", "866", "855", "844", "833")):
            continue  # toll-free numbers are always office lines
        if OFFICE_LABEL_RE.search(text[max(0, s - 40):s]):
            continue
        seg = segment(s)
        # A person's name/title shortly before, or the person's own email shortly after, in the same entry.
        before = [a for a in anchors if a[1] <= s and s - a[1] <= WINDOW and segment(a[0]) == seg]
        after = [a for a in personal_emails if a[0] >= e and a[0] - e <= 50 and segment(a[0]) == seg]
        if before or after:
            remove.append((s, e, PHONE_TOKEN))
    if not remove:
        return text, counts
    out, pos = [], 0
    for s, e, token in sorted(remove):
        if s < pos:
            continue
        out.append(text[pos:s])
        out.append(token)
        counts["email" if token == EMAIL_TOKEN else "phone"] += 1
        pos = e
    out.append(text[pos:])
    return "".join(out), counts


def find_personal(text: str | None) -> Counter:
    """What scrub_text would remove, without changing anything."""
    return scrub_text(text)[1]


# ---- the stored database ---------------------------------------------------------------------

# (table, key column, text columns) checked and scrubbed. JSON columns are scrubbed as text: the tokens contain no
# quotes or backslashes, so the JSON stays valid.
FIELDS = [
    ("pages", "id", ["title", "main_text", "contact_block", "headings", "breadcrumb"]),
    ("chunks", "id", ["text", "heading_path"]),
    ("documents", "id", ["title", "purpose", "text"]),
    ("dates", "id", ["context", "cue"]),
    ("links", "rowid", ["anchor_text"]),
]


def run(apply: bool) -> dict:
    from . import db
    from .config import LOG_DIR
    con = db.connect()
    report = {"applied": apply, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "fields": {}}
    for table, key, cols in FIELDS:
        for col in cols:
            rows_changed, c_total = 0, Counter()
            updates = []
            for k, value in con.execute(f"SELECT {key}, {col} FROM {table} WHERE {col} IS NOT NULL"):
                new, c = scrub_text(value)
                if c:
                    rows_changed += 1
                    c_total.update(c)
                    updates.append((new, k))
            if apply and updates:
                con.executemany(f"UPDATE {table} SET {col}=? WHERE {key}=?", updates)
            report["fields"][f"{table}.{col}"] = {"records": rows_changed, "emails": c_total["email"],
                                                  "phones": c_total["phone"]}
    if apply:
        con.commit()
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        path = LOG_DIR / f"scrub-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}.json"
        path.write_text(json.dumps(report, indent=1), encoding="utf-8")
        report["log"] = str(path)
    return report


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "audit"
    r = run(apply=(mode == "scrub"))
    total = Counter()
    for f, v in r["fields"].items():
        if v["records"]:
            print(f"  {f:<24} {v['records']:>6} records  {v['emails']:>5} emails  {v['phones']:>5} phones")
        total.update({"records": v["records"], "emails": v["emails"], "phones": v["phones"]})
    print(("scrubbed" if r["applied"] else "would scrub"), dict(total), r.get("log", ""))
