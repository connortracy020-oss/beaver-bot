"""Raw extraction of deadlines and term dates, kept with their context for human review.

Two sources:
- tables, where a row has a date cell and a name cell (the registrar's academic calendar); the year comes
  from the table caption or the heading above it ("September 2026");
- running text, where a date sits near a cue word ("deadline", "last day", "due", "begins", ...).

Each date gets its own year: the one written with it, else the nearest year written before it in the same
block, else an academic-year label ("2026-27": July-December -> 2026, January-June -> 2027) in the block,
heading or page title, else a single year in the heading. Without any of those, `date_iso` stays empty.
Ranges ("Dec 14 - Jan 3, 2027", "November 1 through February 15") roll over the new year correctly.
"""
import re
from datetime import date

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
MONTH_RE = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sept?(?:ember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?"
DAY_DATE = rf"(?P<m>{MONTH_RE})\s+(?P<d>\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(?P<y>(?:19|20)\d{{2}}))?"
NUMERIC = r"(?P<nm>\d{1,2})/(?P<nd>\d{1,2})/(?P<ny>(?:20)?\d{2})"
DATE_RE = re.compile(rf"\b(?:{DAY_DATE}|{NUMERIC})\b", re.IGNORECASE)
RANGE_SEP = r"\s*(?:[-–—]+|\bthrough\b|\bthru\b|\bto\b|\buntil\b)\s*"
RANGE_RE = re.compile(rf"\b{DAY_DATE}{RANGE_SEP}(?:(?P<m2>{MONTH_RE})\s+)?(?P<d2>\d{{1,2}})(?:st|nd|rd|th)?"
                      rf"(?:,?\s+(?P<y2>(?:19|20)\d{{2}}))?\b(?![:.]\d)", re.IGNORECASE)  # "June 12 - 7:30" is a time
WEEK_RE = re.compile(r"\b(?:(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day\s+of\s+)?(?:week|wk\.?)\s+(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|eleven)\b|\bfinals week\b|\bdead week\b",
                     re.IGNORECASE)
TERM_RE = re.compile(r"\b(Fall|Winter|Spring|Summer)(?:\s+(?:term|quarter|session))?(?:\s+((?:19|20)\d{2}))?\b", re.IGNORECASE)
YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")
ACAD_RE = re.compile(r"\b((?:19|20)\d{2})\s*[-–/]\s*((?:19|20)?\d{2})\b")
CUE_RE = re.compile(r"\b(deadline|due|last day|first day|no later than|priority|closes?|opens?|begins?|starts?|ends?|until|by \w+ \d|"
                    r"drop|withdraw|add|register|registration|refund|apply|submit|finals?|commencement|holiday|break|"
                    r"ceremony|ceremonies|graduation|orientation)\b",
                    re.IGNORECASE)
LABEL_CUE_RE = re.compile(r"\b(date|dates|when|deadline)\s*:", re.IGNORECASE)  # "Date: Friday, June 11"
SKIP_CONTEXT_RE = re.compile(r"^(last updated|updated|posted|published|copyright|©)", re.IGNORECASE)
WEEKDAYS = re.compile(r"^(mon|tues|wednes|thurs|fri|satur|sun)day(\s*-\s*(mon|tues|wednes|thurs|fri|satur|sun)day)?$", re.I)


def _month(s: str) -> int:
    return MONTHS[s[:3].lower()]


def _iso(y, m, d) -> str | None:
    try:
        return date(int(y), int(m), int(d)).isoformat()
    except (TypeError, ValueError):
        return None


def academic_year(*texts: str) -> tuple[int, int] | None:
    for t in texts:
        m = ACAD_RE.search(t or "")
        if m:
            a, b = int(m.group(1)), m.group(2)
            b = int(b) if len(b) == 4 else (a // 100) * 100 + int(b)
            if b == a + 1:
                return a, b
    return None




WEEKDAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
WEEKDAY_RE = re.compile(r"\b(mon|tues?|wed(nes)?|thu(rs)?|fri|sat(ur)?|sun)(day)?\b\.?,?\s*$", re.IGNORECASE)
TIME_RE = re.compile(r"\b\d{1,2}(:\d{2})?\s*(a\.?m\.?|p\.?m\.?|noon)", re.IGNORECASE)
STAMP_BEFORE_RE = re.compile(r"(revised|rev\.?|\(rev|dated|effective|updated|published|posted|created|last modified)\s*:?\s*(on\s+)?$",
                             re.IGNORECASE)
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")
TERM_LABEL_RE = re.compile(r"\b(Fall|Winter|Spring|Summer)(?:\s+(?:term|quarter|session))?\s+((?:19|20)\d{2})\b", re.IGNORECASE)


def label_year(month: int, term: str | None, year: int) -> int:
    """The calendar year of `month` under a label like "Winter 2027": Winter/Spring registration happens in the
    autumn before (Nov 2026 for Winter 2027); Fall 2026's January-June items are in 2027."""
    term = (term or "").lower()
    if term in ("winter", "spring") and month >= 7:
        return year - 1
    if term == "fall" and month <= 6:
        return year + 1
    return year


def _label(*texts: str) -> tuple[str | None, int | None]:
    """The first "Term YYYY" label, else the first plain year, in the given texts."""
    for t in texts:
        m = TERM_LABEL_RE.search(t or "")
        if m:
            return m.group(1).lower(), int(m.group(2))
    for t in texts:
        if t and not ACAD_RE.search(t):
            m = YEAR_RE.search(t)
            if m:
                return None, int(m.group(1))
    return None, None


class YearContext:
    """Resolves the year for a month that was written without one.

    Order: a year written earlier in the same text; a "Term YYYY" label later in the same sentence ("November 30
    ... for winter 2027"); an academic-year label ("2026-27"); the heading's "Term YYYY" or plain year.
    """

    def __init__(self, text: str, acad: tuple[int, int] | None, label: tuple[str | None, int | None] = (None, None)):
        self.text, self.acad, (self.label_term, self.label_year) = text, acad, label
        self.acad_spans = [(m.start(), m.end()) for m in ACAD_RE.finditer(text)]
        self.last: tuple[int, int] | None = None  # (year, month) of the previous date resolved in this text

    def year_for(self, month: int, pos: int) -> int | None:
        before = [m for m in YEAR_RE.finditer(self.text[:pos])
                  if not any(a <= m.start() < b for a, b in self.acad_spans)]
        if before:
            year = int(before[-1].group(1))
            # A list running "Oct 1, 2026 ... Jan 15" has crossed into the next year.
            if self.last and self.last[0] == year and month < self.last[1] - 2:
                year += 1
            return year
        sentence_end = SENTENCE_RE.search(self.text, pos)
        after = TERM_LABEL_RE.search(self.text[pos: sentence_end.start() if sentence_end else len(self.text)])
        if after:
            return label_year(month, after.group(1), int(after.group(2)))
        if self.acad:
            return self.acad[0] if month >= 7 else self.acad[1]
        if self.label_year:
            return label_year(month, self.label_term, self.label_year)
        return None


def _weekday_fix(y: int | None, m: int, d: int, weekday: str | None) -> int | None:
    """If a weekday is written with the date, pick the neighbouring year that matches it."""
    if not weekday or y is None:
        return y
    want = next((i for i, n in enumerate(WEEKDAY_NAMES) if n.startswith(weekday.lower()[:3])), None)
    if want is None:
        return y
    for cand in (y, y - 1, y + 1):
        try:
            if date(cand, m, d).weekday() == want:
                return cand
        except ValueError:
            continue
    return y


def _parse(text: str, ctx: YearContext, offset: int = 0, weekday: str | None = None):
    """First date or date range in text -> (as written, iso or None, year, month)."""
    r = RANGE_RE.search(text)
    if r and not r.group("m2") and int(r.group("d2")) <= int(r.group("d")):
        r = None  # "June 12 - 9" would end before it starts: read it as the single date below
    if r:
        m1, d1 = _month(r.group("m")), int(r.group("d"))
        m2 = _month(r.group("m2")) if r.group("m2") else m1
        y1 = int(r.group("y")) if r.group("y") else None
        y2 = int(r.group("y2")) if r.group("y2") else None
        if y1 is None and y2 is not None:
            y1 = y2 - 1 if m1 > m2 else y2
        if y1 is None:
            y1 = _weekday_fix(ctx.year_for(m1, offset + r.start()), m1, d1, weekday)
        if y2 is None and y1 is not None:
            y2 = y1 + 1 if m2 < m1 else y1
        a, b = _iso(y1, m1, d1), _iso(y2, m2, int(r.group("d2")))
        if y2 is not None:
            ctx.last = (y2, m2)
        return r.group(0), (f"{a}/{b}" if a and b else None), y1, m1
    m = DATE_RE.search(text)
    if not m:
        return None
    if m.group("m"):
        month, day = _month(m.group("m")), int(m.group("d"))
        y = int(m.group("y")) if m.group("y") else _weekday_fix(ctx.year_for(month, offset + m.start()), month, day, weekday)
        if y is not None:
            ctx.last = (y, month)
        return m.group(0), (_iso(y, month, day) if y else None), y, month
    ny = int(m.group("ny"))
    ny = ny + 2000 if ny < 100 else ny
    return m.group(0), _iso(ny, m.group("nm"), m.group("nd")), ny, int(m.group("nm"))


def _term(text: str, year: int | None, month: int | None, near: int | None = None) -> str | None:
    """The term named closest to `near` in text. A Winter or Spring term mentioned in Sept-Dec is next year's."""
    matches = list(TERM_RE.finditer(text or ""))
    if not matches:
        return None
    t = min(matches, key=lambda x: abs(x.start() - near)) if near is not None else matches[0]
    name = t.group(1).title()
    if t.group(2):
        return f"{name} {t.group(2)}"
    if year is None:
        return name
    if name in ("Winter", "Spring") and month and month >= 9:
        year += 1
    return f"{name} {year}"


def _not_a_deadline(text: str, start: int, end: int) -> bool:
    """Revision/publication stamps ("revised: 08/04/2015", "dated April 28, 1969") and numbers like 'May 13,602'."""
    if STAMP_BEFORE_RE.search(text[max(0, start - 20):start]):
        return True
    return bool(re.match(r",\d{3}\b", text[end:end + 5]))


def from_tables(tables: list[dict]) -> list[dict]:
    """One row per date cell. The event is the row's label; with several date columns, each date also gets its
    column header ("Petition filing deadline"). Rows that are only dates with nothing naming them are skipped."""
    out = []
    for t in tables:
        header = [h for h in t.get("header") or []]
        titles = []  # single-cell rows such as "Reinstatement for winter term 2027 - classes begin: January 4, 2027"
        for row in t["rows"]:
            if len({c for c in row if c}) == 1 and row != header:
                titles.append(next(c for c in row if c))
        if not header or len(set(header)) == 1:
            # Header written with <td>: the first multi-cell row of labels directly above a row of dates.
            rows = t["rows"]
            for a, b in zip(rows, rows[1:]):
                if (len({c for c in a if c}) > 1 and not any(DATE_RE.search(c) for c in a)
                        and any(DATE_RE.search(c) for c in b)):
                    header = a
                    break
        context_text = " ".join([t["caption"], t["heading"]] + titles)
        acad = academic_year(context_text)
        for row in t["rows"]:
            if row == header or all(c.lower() in ("month/day", "day of week", "name", "date", "dates", "event", "")
                                    for c in row):
                continue
            cells = list(dict.fromkeys(c for c in row if c))  # colspan copies collapse
            ctx = YearContext("", acad, _label(t["caption"], t["heading"], *titles))
            max_len = 200 if len(cells) == 1 else 60  # a title row may carry its own date
            date_idx = [i for i, c in enumerate(row) if DATE_RE.search(c) and len(c) < max_len
                        and not _not_a_deadline(c, DATE_RE.search(c).start(), DATE_RE.search(c).end())]
            if not date_idx:
                continue
            weekday_cell = next((c for c in cells if WEEKDAYS.match(c.replace(" ", ""))), None)
            times = [c for c in cells if TIME_RE.fullmatch(c.strip()) or (TIME_RE.match(c) and len(c) < 12)]
            labels = [c for i, c in enumerate(row) if i not in date_idx and c and c != weekday_cell and c not in times]
            name = max(labels, key=len) if labels else ""
            if len(cells) == 1:
                name = DATE_RE.split(cells[0])[0].strip(" :–-") or cells[0]  # a title row that itself carries a date
            if not name and not header:
                continue  # an axis of dates with nothing saying what they are
            seen = set()
            for i in date_idx:
                cell = row[i]
                if cell in seen:
                    continue
                seen.add(cell)
                col = header[i] if i < len(header) and header[i] and not DATE_RE.search(header[i]) else ""
                cue = name if (name and len(date_idx) == 1) else " | ".join(filter(None, [name, col]))
                if times:
                    cue = f"{cue} ({', '.join(times)})" if cue else ", ".join(times)
                wd = re.match(r"\s*([A-Za-z]+day)\b", cell)
                parsed = _parse(cell, ctx, weekday=(wd.group(1) if wd else (weekday_cell or "").split(" ")[0] or None))
                if not parsed:
                    continue
                date_text, iso, y, month = parsed
                out.append({"context": " | ".join(cells), "date_text": date_text, "date_iso": iso,
                            "term": _term(name, y, month) or _term(context_text, y, month), "cue": cue[:200] or None,
                            "heading_path": " > ".join(filter(None, [t["heading"], t["caption"]]))})
    return out


def from_sections(sections, title: str = "") -> list[dict]:
    """Dates in running text, kept only when their own sentence has a cue word or names a term."""
    out, seen = [], set()
    for s in sections:
        heading = " > ".join(s.heading_path)
        label = _label(heading)
        for block in s.blocks:
            if " | " in block or SKIP_CONTEXT_RE.match(block):
                continue  # table rows are handled by from_tables
            ctx = YearContext(block, academic_year(block, heading, title), label)
            bounds = [0] + [m.end() for m in SENTENCE_RE.finditer(block)] + [len(block)]
            covered: list[tuple[int, int]] = []
            for m in list(RANGE_RE.finditer(block)) + list(DATE_RE.finditer(block)):
                if any(m.start() >= a and m.end() <= b for a, b in covered):
                    continue
                if _not_a_deadline(block, m.start(), m.end()):
                    covered.append((m.start(), m.end()))
                    continue
                a = max(b for b in bounds if b <= m.start())
                b = min(b for b in bounds if b >= m.end())
                sentence = block[a:b].strip()
                # The cue can be in the sentence or in the section's own heading ("Oregon State commencement ceremony").
                cue = (CUE_RE.search(sentence) or LABEL_CUE_RE.search(sentence)
                       or CUE_RE.search(s.heading_path[-1] if s.heading_path else ""))
                if not (cue or TERM_RE.search(sentence)):
                    continue
                wd = WEEKDAY_RE.search(block[max(0, m.start() - 12):m.start()])
                parsed = _parse(m.group(0), ctx, offset=m.start(), weekday=wd.group(1) if wd else None)
                if not parsed:
                    continue
                covered.append((m.start(), m.end()))
                date_text, iso, year, month = parsed
                context = sentence if len(sentence) >= 40 or a == 0 else block[max(b2 for b2 in bounds if b2 < a):b].strip()
                key = (date_text, context)
                if key in seen:
                    continue
                seen.add(key)
                out.append({"context": context[:1000], "date_text": date_text, "date_iso": iso,
                            "term": _term(sentence, year, month, near=m.start() - a) or _term(heading, year, month),
                            "cue": cue.group(0).lower() if cue else None, "heading_path": heading})
            for w in WEEK_RE.finditer(block):
                a = max(b for b in bounds if b <= w.start())
                b = min(b for b in bounds if b >= w.end())
                sentence = block[a:b].strip()
                cue = CUE_RE.search(sentence)
                if cue and (w.group(0), sentence) not in seen:
                    seen.add((w.group(0), sentence))
                    out.append({"context": sentence[:1000], "date_text": w.group(0), "date_iso": None,
                                "term": _term(sentence, None, None) or _term(heading, None, None),
                                "cue": cue.group(0).lower(), "heading_path": heading})
    return out
