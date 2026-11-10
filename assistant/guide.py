"""The offline "guide" provider: a readable answer built only from exact quotes, with no model and no network.

It reads the same prompt a model would get (answer.build_prompt) and returns the same JSON, so its output goes
through verify.py like any model's. It can do three things, all by copying text from the excerpts:

- **Dates:** when the question asks "when" and an excerpt holds rows from the Registrar's academic calendar
  ("Jan 10, 2027 | Sunday, 2027 | Last Day to Add a Winter Course ..."), it lists the matching rows.
- **Steps:** for a how-to question, it finds a run of steps or list items on the best page and lists them in order.
- **Quotes:** otherwise it quotes the two or three sentences that best match the question.

It cannot paraphrase or judge meaning. When nothing matches well it returns "not_found", and the student gets the
office to contact instead.

Answer text uses the site's small markup (docs/answer-layer.md): "+ " starts a step, "- " a list item, "> " a
quote from the page, and [n] cites a source. List numbers are left to the page so they are not mistaken for facts.
"""
import datetime
import json
import re

from .retrieve import terms

CHUNK_RE = re.compile(r'<chunk id="(\d+)" title="([^"]*)" section="([^"]*)" url="([^"]*)" retrieved="([^"]*)">\n'
                      r'(.*?)\n</chunk>', re.S)
QUESTION_RE = re.compile(r"<question>\n?(.*?)\n?</question>", re.S)
SPANISH_RULE = "Write the answer in Spanish."     # the site adds this line to the system prompt for Spanish

# ---- the academic calendar -----------------------------------------------------------------------
ROW_RE = re.compile(r"^([A-Z][a-z]{2} \d{1,2}, \d{4})(?: - [A-Z][a-z]{2} \d{1,2}, \d{4})? \| ([A-Za-z]+)[^|]*\| (.+)$",
                    re.M)
DATE_Q = re.compile(r"\b(when|what (day|date)|deadline|last day|how long do i have|until when|cu[aá]ndo|fecha)\b", re.I)
# (key, words in the question, words in the calendar row's name)
EVENTS = [
    ("add", r"\badd(ing)?\b", r"Last Day to Add\b"),
    ("drop", r"\bdrop", r"Last Day to Drop\b"),
    ("withdraw", r"\bwithdraw", r"Last Day to Withdraw\b"),
    ("grading", r"grading basis|\bs/u\b|pass.?/?no.?pass", r"Grading Basis"),
    ("audit", r"\baudit", r"\bAudit\b"),
    ("finals", r"\bfinals?\b|exam week", r"Finals Week"),
    ("grades", r"\bgrades?\b.{0,20}\b(available|posted|out|released)|when.{0,20}\bgrades\b", r"Grades Available"),
    ("register", r"\bregist(er|ration)\b|\bpriority\b", r"(Priority Reg|Registration)"),
    ("start", r"\b(starts?|begins?|first day)\b", r"(Term )?Classes Begin"),
    ("end", r"\b(ends?|over|last day of (class|classes|the term|term))\b", r"(Classes End|Term Ends)"),
    ("break", r"\b(break|holiday|thanksgiving|veterans|mlk|memorial day|juneteenth|labor day)\b",
     r"(Break|Holiday|Day( Observed)?$)"),
]
SEASON_RE = re.compile(r"\b(fall|winter|spring|summer)\b", re.I)
SUBSESSION_RE = re.compile(r"\b(5A|5B|Super Term|Extension|Session|Week [0-9])\b")
MONTHS = {m: i for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)}
MAX_ROWS = 6


def calendar_query(question: str) -> dict | None:
    """What a date question is asking the calendar for: {"events": [row-name regexes], "season": "winter" | None}."""
    if not DATE_Q.search(question):
        return None
    events = [(key, row) for key, words, row in EVENTS if re.search(words, question, re.I)]
    if not events:
        return None
    season = SEASON_RE.search(question)
    return {"keys": [k for k, _ in events], "rows": [r for _, r in events],
            "season": season.group(1).lower() if season else None,
            "subsessions": bool(SUBSESSION_RE.search(question))}


def _row_date(text: str) -> datetime.date | None:
    m = re.match(r"([A-Z][a-z]{2}) (\d{1,2}), (\d{4})", text)
    if not m or m.group(1) not in MONTHS:
        return None
    try:
        return datetime.date(int(m.group(3)), MONTHS[m.group(1)], int(m.group(2)))
    except ValueError:
        return None


def calendar_rows(text: str, want: dict, today: datetime.date) -> list[dict]:
    """Calendar rows in a chunk that match the question: [{"line", "date", "date_text", "weekday", "name"}]."""
    out = []
    for m in ROW_RE.finditer(text):
        date_text, weekday, row_name = m.group(1), m.group(2), m.group(3).strip()
        when = _row_date(date_text)
        if when is None or not any(re.search(rx, row_name) for rx in want["rows"]):
            continue
        if SUBSESSION_RE.search(row_name) and not want["subsessions"]:
            continue
        if want["season"] and not re.search(rf"\b{want['season']}\b", row_name, re.I) and SEASON_RE.search(row_name):
            continue
        if not want["season"] and when < today:
            continue
        out.append({"line": m.group(0).strip(), "date": when, "date_text": date_text, "weekday": weekday,
                    "name": row_name})
    return out


# ---- wording ---------------------------------------------------------------------------------------
TEXT = {
    "en": {
        "dates_one": "Here's what OSU's Academic Calendar lists:",
        "dates_next": "Here are the next dates on OSU's Academic Calendar:",
        "dates_tail": "Shorter sessions have their own dates, so check the calendar if your class isn't a full-term class.",
        "steps": "Here's how, from OSU's {title} page:",
        "steps_plain": "Here's how, from OSU's page:",
        "quotes_one": "Here's what OSU's {title} page says:",
        "quotes": "Here's what I found:",
    },
    "es": {
        "dates_one": "Esto aparece en el Calendario Académico de OSU (en inglés):",
        "dates_next": "Estas son las próximas fechas en el Calendario Académico de OSU (en inglés):",
        "dates_tail": "Las sesiones cortas tienen sus propias fechas; revisa el calendario si tu clase no dura todo el trimestre.",
        "steps": "Así se hace, según la página {title} de OSU (en inglés):",
        "steps_plain": "Así se hace, según la página de OSU (en inglés):",
        "quotes_one": "Esto dice la página {title} de OSU (en inglés):",
        "quotes": "Esto es lo que encontré (en inglés):",
    },
}

HOWTO_RE = re.compile(r"\bhow (do|can|would|should|to)\b|\bsteps?\b|\bprocess\b|\bc[oó]mo\b", re.I)
STEP_RE = re.compile(r"^(?:Step \d+\s*[:.)-]\s*|\d{1,2}[.)]\s+|[-•]\s+)(.+)$")
AVOID_RE = re.compile(r"\b(official|guaranteed)\b", re.I)     # words the site avoids; quotes carrying them rank lower
MIN_UNIT, MAX_UNIT, MAX_STEPS, MAX_QUOTES = 30, 340, 8, 3
# Words that show up in questions but say little about the topic ("How do I see a counselor?" is about counselors).
WEAK_WORDS = set("see use help work works make take student students osu campus one find look looking apply "
                 "available offer offers thing things".split())


def _stem(term: str) -> str:
    return term[: max(4, len(term) - 3)]


def _sentences(line: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z\"'(\[])", line) if s.strip()]


def _clean_title(title: str) -> str | None:
    """A page title that is safe to print in our own sentence: no digits (the verifier would read them as facts)."""
    title = " ".join((title or "").split())
    return title if title and not re.search(r"\d", title) and len(title) <= 70 else None


class GuideProvider:
    """Composes an answer from the excerpts' own words. Free, offline, always checkable by the verifier."""
    name, paid = "guide", False

    def __init__(self, today: datetime.date | None = None):
        self.today = today

    def complete(self, system: str, user: str, max_tokens: int = 2000) -> str:
        q = QUESTION_RE.search(user)
        chunks = [{"id": int(cid), "title": title, "section": section, "url": url, "text": text.strip()}
                  for cid, title, section, url, _, text in CHUNK_RE.findall(user)]
        lang = "es" if SPANISH_RULE in system else "en"
        return json.dumps(self.compose(q.group(1).strip() if q else "", chunks, lang))

    # -- the three kinds of answer --------------------------------------------------------------------
    def compose(self, question: str, chunks: list[dict], lang: str = "en") -> dict:
        say = TEXT.get(lang, TEXT["en"])
        found = self._dates(question, chunks, say) or self._steps(question, chunks, say) \
            or self._quotes(question, chunks, say)
        return found or {"status": "not_found", "answer": "", "citations": []}

    def _dates(self, question: str, chunks: list[dict], say: dict) -> dict | None:
        want = calendar_query(question)
        if not want:
            return None
        today = self.today or datetime.date.today()
        rows, seen = [], set()
        for c in chunks:
            for row in calendar_rows(c["text"], want, today):
                if row["line"] not in seen:
                    seen.add(row["line"])
                    rows.append({**row, "chunk_id": c["id"]})
        if not rows:
            return None
        rows.sort(key=lambda r: r["date"])
        if not want["season"]:
            # No term named: show the next term that has these dates, not every future term at once.
            first = SEASON_RE.search(rows[0]["name"])
            if first:
                rows = [r for r in rows if re.search(first.group(1), r["name"], re.I)
                        and (r["date"] - rows[0]["date"]).days < 150] or rows
        rows = rows[:MAX_ROWS]
        lines = [say["dates_one"] if want["season"] else say["dates_next"]]
        cites = []
        for n, r in enumerate(rows, 1):
            lines.append(f"- **{r['weekday']}, {r['date_text']}**: {r['name']} [{n}]")
            cites.append({"chunk_id": r["chunk_id"], "quote": r["line"]})
        lines += ["", say["dates_tail"]]
        return {"status": "answered", "answer": "\n".join(lines), "citations": cites}

    def _weights(self, question: str, chunks: list[dict]) -> dict[str, float]:
        """Search words with a weight: a word found in few of the excerpts says more than one found in all."""
        words = [t for t in terms(question) if len(t) > 2 or t.isdigit()]
        lows = [(c["title"] + " " + c["section"] + " " + c["text"]).lower() for c in chunks]
        out = {}
        for word in words:
            stem = _stem(word)
            rare = sum(stem in low for low in lows) <= max(2, len(lows) // 2)
            out[stem] = 0.4 if word in WEAK_WORDS else (2.0 if rare else 1.0)
        return out

    @staticmethod
    def _cover(text: str, weights: dict[str, float]) -> float:
        total = sum(weights.values())
        low = text.lower()
        return sum(w for s, w in weights.items() if s in low) / total if total else 0.0

    def _steps(self, question: str, chunks: list[dict], say: dict) -> dict | None:
        if not HOWTO_RE.search(question):
            return None
        weights = self._weights(question, chunks)
        best = None
        for rank, c in enumerate(chunks):
            lines = [l.strip() for l in c["text"].splitlines() if l.strip()]
            i = 0
            while i < len(lines):
                run = []
                while i + len(run) < len(lines) and (m := STEP_RE.match(lines[i + len(run)])):
                    run.append(m.group(1).strip())
                if len(run) >= 3:
                    label = lines[i - 1] if i and lines[i - 1].endswith(":") and len(lines[i - 1]) <= 200 else None
                    after = lines[i + len(run)] if i + len(run) < len(lines) else None
                    context = " ".join([c["title"], c["section"], label or "", *run])
                    score = self._cover(context, weights) + 0.1 * (1 - rank / max(1, len(chunks)))
                    if label and self._cover(label, weights) >= 0.5:
                        score += 0.25
                    if best is None or score > best[0]:
                        best = (score, c, label, run, after)
                i += max(1, len(run))
        if not best or best[0] < 0.75:
            return None
        _, c, label, run, after = best
        title = _clean_title(c["title"])
        lines = [say["steps"].format(title=title) if title else say["steps_plain"]]
        cites = []

        def cite(quote: str) -> int:
            cites.append({"chunk_id": c["id"], "quote": quote})
            return len(cites)

        if label and len(label) >= 12:
            lines.append(f"{label} [{cite(label)}]")
        for step in run[:MAX_STEPS]:
            if len(step) >= 8:
                lines.append(f"+ {step} [{cite(step)}]")
        if after and MIN_UNIT <= len(after) <= MAX_UNIT and not STEP_RE.match(after) and after.endswith("."):
            lines += ["", f"> {after} [{cite(after)}]"]
        if len(cites) < 3:
            return None
        return {"status": "answered", "answer": "\n".join(lines), "citations": cites}

    def _quotes(self, question: str, chunks: list[dict], say: dict) -> dict | None:
        weights = self._weights(question, chunks)
        if not weights:
            return None
        scored = []
        for rank, c in enumerate(chunks):
            heading = self._cover(c["title"] + " " + c["section"], weights)
            lines = [l.strip() for l in c["text"].splitlines() if l.strip()]
            for pos, line in enumerate(lines):
                if " | " in line and (len(line) > MAX_UNIT or not re.search(r"\d", line)):
                    continue        # a long table row, or a header row with no figures in it
                m = STEP_RE.match(line)
                for unit in _sentences(m.group(1) if m else line):
                    # A short label ("Annual permit prices:") is only useful with the line under it.
                    if (unit.endswith(":") and len(unit) < 80 and pos + 1 < len(lines) and not m
                            and unit == _sentences(line)[-1] and not STEP_RE.match(lines[pos + 1])):
                        unit = f"{unit} {lines[pos + 1]}"
                    if not MIN_UNIT <= len(unit) <= MAX_UNIT or unit.endswith("?") or len(unit.split()) < 5:
                        continue
                    cover = self._cover(unit, weights)
                    if cover < 0.34:
                        continue
                    score = cover + 0.2 * heading + 0.12 * (1 - rank / max(1, len(chunks)))
                    if AVOID_RE.search(unit):
                        score -= 0.3
                    scored.append((score, -rank, -pos, c, unit))
        scored.sort(key=lambda s: s[:3], reverse=True)
        if not scored or scored[0][0] < 0.62:
            return None
        picked, per_chunk = [], {}
        for score, _, pos, c, unit in scored:
            if score < scored[0][0] - 0.35 or per_chunk.get(c["id"], 0) >= 2:
                continue
            if any(unit in u or u in unit for _, _, u in picked):
                continue
            picked.append((c, -pos, unit))
            per_chunk[c["id"]] = per_chunk.get(c["id"], 0) + 1
            if len(picked) == MAX_QUOTES:
                break
        order = {c["id"]: i for i, c in enumerate(chunks)}
        picked.sort(key=lambda p: (order[p[0]["id"]], p[1]))      # page order reads better than score order
        titles = {p[0]["title"] for p in picked}
        title = _clean_title(next(iter(titles))) if len(titles) == 1 else None
        lines = [say["quotes_one"].format(title=title) if title else say["quotes"]]
        cites = []
        for n, (c, _, unit) in enumerate(picked, 1):
            lines.append(f"> {unit} [{n}]")
            cites.append({"chunk_id": c["id"], "quote": unit})
        return {"status": "answered", "answer": "\n".join(lines), "citations": cites}
