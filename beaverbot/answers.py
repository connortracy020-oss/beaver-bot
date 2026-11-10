"""A student's question in, an answer (or the right office) out, with progress events along the way.

This wraps the existing pipeline in assistant/answer.py and changes none of its rules:

1. **Crisis** first, always, and never a model.
2. **Guard** for questions the assistant must not answer.
3. **Hand-checked answers** (pinned.json), when enabled. They are verified against the stored pages like any other.
4. **Retrieve**, with two additions made here: calendar rows for date questions, and a stricter relevance check so
   an off-topic question gets "I don't know" instead of a loosely related quote.
5. **Provider**, then the **quote verifier**. Anything that fails is discarded.

Nothing is saved. The question is used for this one answer and then dropped.
"""
import datetime
import json
import math
import re
import sqlite3
import threading
from typing import Callable
from urllib.parse import urlsplit

from assistant import answer as A
from assistant import owners
from assistant.categories import BY_ID
from assistant.guide import SPANISH_RULE, GuideProvider, calendar_query, calendar_rows
from assistant.providers import Provider, get_provider
from assistant.retrieve import PAST_RE, Hit, search, terms
from assistant.verify import verify

from . import config, content, pinned, spanish

MAX_QUESTION = 400
RELEVANCE_MIN = 0.6        # share of the question's weighted search words the best page must contain
CALENDAR_URL = "https://registrar.oregonstate.edu/osu-academic-calendar"
FOLLOWUP_RE = re.compile(r"^\s*(and|but|what about|how about|what if|y |pero |y qu[eé])\b", re.I)
PRONOUN_RE = re.compile(r"\b(it|that|this|those|them|they|there|one|eso|esa|ese|esto)\b", re.I)
BANNED_RE = re.compile(r"\bguaranteed\b|\byou should definitely\b|\bofficial\b", re.I)
DONT_KNOW = {"weak retrieval", "model found no answer", "failed verification", "style check"}
ES_CRISIS = re.compile(r"suicid|matarme|quiero morir|hacerme da[nñ]o|lastimarme|no estoy a salvo", re.I)

Emit = Callable[[str, dict], None]
_local = threading.local()


def connect() -> sqlite3.Connection:
    """A read-only connection to the crawled pages, one per thread. The site never writes to this database."""
    con = getattr(_local, "con", None)
    if con is None:
        con = sqlite3.connect(f"file:{config.OSU_DB.as_posix()}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        _local.con = con
    return con


def release() -> None:
    """Close this thread's connection. The server calls it as each request ends, so a finished request holds no memory."""
    con = getattr(_local, "con", None)
    if con is not None:
        _local.con = None
        con.close()


# ---- relevance: is the best page really about this question? ------------------------------------
class Relevance:
    """Weights each search word by how rare it is in the stored pages. "pizza" says more than "best"."""
    _lock = threading.Lock()
    _df: dict[str, int] = {}
    _total = 0

    def __init__(self, con: sqlite3.Connection):
        self.con = con
        if not Relevance._total:
            Relevance._total = con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] or 1

    def _count(self, word: str) -> int:
        with Relevance._lock:
            if word in Relevance._df:
                return Relevance._df[word]
        try:
            n = self.con.execute("SELECT COUNT(*) FROM chunks_fts WHERE chunks_fts MATCH ?", (f'"{word}"',)).fetchone()[0]
        except sqlite3.Error:
            n = 0
        with Relevance._lock:
            Relevance._df[word] = n
        return n

    def weights(self, question: str) -> dict[str, float]:
        out = {}
        for t in terms(question):
            for piece in re.split(r"[/-]", t):
                if len(piece) > 2 or piece.isdigit():
                    out[piece] = max(0.15, math.log((Relevance._total + 1) / (self._count(piece) + 1)))
        return out

    def coverage(self, question: str, hit: Hit, weights: dict[str, float] | None = None) -> float:
        weights = weights if weights is not None else self.weights(question)
        total = sum(weights.values())
        if not total:
            return 0.0
        low = f"{hit.title} {hit.heading_path} {hit.text}".lower()
        return sum(w for t, w in weights.items() if t[: max(4, len(t) - 3)] in low) / total


# ---- calendar rows for date questions -----------------------------------------------------------
def calendar_hits(con: sqlite3.Connection, question: str, today: datetime.date, limit: int = 3) -> list[Hit]:
    """Chunks of the Registrar's current academic calendar that hold the dates this question asks about."""
    want = calendar_query(question)
    if not want or PAST_RE.search(question):
        return []
    rows = con.execute("""SELECT c.id, c.heading_path, c.anchor, c.text, p.url, p.title, p.retrieved_at, p.owning_office
                          FROM chunks c JOIN pages p ON p.id = c.page_id
                          WHERE p.url LIKE ? AND p.archived = 0 AND p.gone_at IS NULL ORDER BY p.url, c.seq""",
                       (CALENDAR_URL + "%",)).fetchall()
    found = []
    for r in rows:
        if "Past Academic Calendar" in (r["heading_path"] or ""):
            continue
        matches = calendar_rows(r["text"], want, today)
        if matches:
            found.append((min(m["date"] for m in matches), r))
    found.sort(key=lambda f: f[0])
    return [Hit(chunk_id=r["id"], score=99.0, coverage=1.0, title=r["title"] or "Academic Calendar",
                heading_path=r["heading_path"] or "", url=r["url"], page_url=r["url"],
                retrieved_at=(r["retrieved_at"] or "")[:10], office=r["owning_office"], excerpt="", text=r["text"])
            for _, r in found[:limit]]


# ---- providers ----------------------------------------------------------------------------------
class Fixed:
    """Returns one prepared output: a hand-checked answer on its way to the verifier."""
    name, paid = "pinned", False

    def __init__(self, output: str):
        self.output = output

    def complete(self, system: str, user: str, max_tokens: int = 2000) -> str:
        return self.output


class SiteProvider:
    """The configured provider, plus what the site knows: the language, and the words used for search."""
    paid = False

    def __init__(self, inner: Provider, lang: str, original: str, search_question: str, emit: Emit,
                 today: datetime.date):
        self.inner, self.lang, self.original, self.search_question = inner, lang, original, search_question
        self.emit, self.today, self.name = emit, today, inner.name

    def complete(self, system: str, user: str, max_tokens: int = 2000) -> str:
        self.emit("status", {"step": "writing"})
        if isinstance(self.inner, GuideProvider):
            chunks = [{"id": int(cid), "title": title, "section": section, "url": url, "text": text.strip()}
                      for cid, title, section, url, _, text in
                      re.findall(r'<chunk id="(\d+)" title="([^"]*)" section="([^"]*)" url="([^"]*)" '
                                 r'retrieved="([^"]*)">\n(.*?)\n</chunk>', user, re.S)]
            guide = GuideProvider(today=self.today)
            out = json.dumps(guide.compose(self.search_question, chunks, self.lang))
        else:
            # A model can't know today's date, and "when is the deadline" depends on it.
            system = (f"{system}\n- Today is {self.today:%A, %B} {self.today.day}, {self.today.year}. For a question "
                      "about a date, give the next upcoming one and name its term; mention a past one only if asked."
                      "\n- Talk to the student directly and start with the answer itself. The student can't see "
                      "what you were given, so never write the words \"excerpt\", \"excerpts\", \"chunk\" or \"prompt\". "
                      "Say \"OSU's page\" for where something came from, and \"I couldn't find\" for what is missing."
                      "\n- Keep it short: a direct first sentence, then steps or a few list items only when they help. "
                      "Aim for under 120 words.")
            if self.lang == "es":
                # A model gets the student's own words (redacted), and is asked to answer in Spanish.
                system = (f"{system}\n- {SPANISH_RULE} Quotes stay exactly as written on the page. In Spanish write "
                          "\"la página de OSU\", never the English words \"OSU's page\".")
                user = re.sub(r"<question>\n.*?\n</question>",
                              lambda _: f"<question>\n{A.redact(self.original)}\n</question>", user, count=1, flags=re.S)
            out = self.inner.complete(system, user, max_tokens)
            self.emit("status", {"step": "checking"})
            problems = self._problems(out, user)
            if problems:
                # One more try, told exactly which checks failed. If it isn't better, the first attempt stands
                # and the verifier discards it as usual.
                again = self.inner.complete(
                    system, f"{user}\n\n<previous_attempt>\n{out[:3000]}\n</previous_attempt>\n<problems>\n"
                    + "\n".join(f"- {p}" for p in problems) + "\n</problems>\nYour previous attempt failed these "
                    "automatic checks. Answer again and fix them. Copy each quote character for character from one "
                    "excerpt, and number the [n] markers by position in your citations list.", max_tokens)
                if len(self._problems(again, user)) < len(problems):
                    out = again
            return out
        self.emit("status", {"step": "checking"})
        return out

    @staticmethod
    def _problems(raw: str, user: str) -> list[str]:
        """Why this output would be discarded: the verifier's reasons, plus the site's wording rule."""
        chunks = {int(cid): text.strip() for cid, text in re.findall(r'<chunk id="(\d+)"[^>]*>\n(.*?)\n</chunk>', user, re.S)}
        verdict = verify(raw, chunks)
        if verdict.status == "not_found":
            return []
        problems = list(verdict.problems)
        if verdict.answer and BANNED_RE.search(_own_words(_soften(verdict.answer), quoted_lists=False)):
            problems.append('the answer uses a word this site never uses in its own sentences ("guaranteed", '
                            '"official", "you should definitely"); say it another way')
        return problems


# ---- the pipeline -------------------------------------------------------------------------------
def is_followup(question: str) -> bool:
    words = [t for t in terms(question) if len(t) > 2]
    return bool(FOLLOWUP_RE.search(question)) or len(words) <= 1 or (len(words) <= 3 and bool(PRONOUN_RE.search(question)))


def site_label(url: str) -> str:
    host = (urlsplit(url).hostname or "").removeprefix("www.")
    return host


def _payload(res: A.Result, lang: str, hits: list[Hit], question: str, provider_name: str, extra: dict | None = None) -> dict:
    by_url = {}
    office = {h.url: h.office for h in hits} | {h.page_url: h.office for h in hits}
    cites = {}
    for s in res.sources:
        page_url = s["url"].split("#")[0]
        page = by_url.setdefault(page_url, {"p": len(by_url) + 1, "title": s["title"] or site_label(s["url"]),
                                            "url": s["url"], "site": site_label(s["url"]),
                                            "office": office.get(s["url"]) or office.get(page_url),
                                            "checked": s["retrieved_at"][:10], "quotes": []})
        quote = " ".join(s["quote"].split())
        if res.kind != "crisis" and quote not in page["quotes"]:
            page["quotes"].append(quote)
        cites[str(s["n"])] = page["p"]
    category = None
    if res.kind == "answer":
        category = A.category_for(question, hits)
    elif [tuple(c) for c in res.contacts] != A.GENERAL_CONTACT:      # the general fallback office belongs to no topic
        category = next((c.id for c in BY_ID.values() if any(tuple(x) in c.contacts for x in res.contacts)), None) \
            or A.category_for(question, hits, trust_hits=False)
    checked = min((p["checked"] for p in by_url.values() if p["checked"]), default=None)
    contacts = res.contacts
    if res.kind == "refusal" and res.reason in DONT_KNOW:
        # The office for this question's own topic, not every office in its topic group (a dining question used
        # to show Recreational Sports and Public Safety, which share the "campus life" group).
        contacts = owners.contacts_for(question) or contacts
    text = res.text
    if res.kind == "refusal" and res.reason in DONT_KNOW:
        text = "I couldn't find that on OSU's public pages, and I'd rather not guess. This office can help:"
    if lang == "es" and res.kind != "answer":
        text = spanish.MESSAGES.get("crisis" if res.kind == "crisis" else
                                    res.reason if res.reason in spanish.MESSAGES else "refusal", text)
        if res.kind == "crisis" and res.sources:
            text += "\n\n" + res.sources[0]["quote"]
    out = {
        "kind": res.kind, "reason": res.reason, "text": text, "lang": lang,
        "pages": list(by_url.values()), "cites": cites,
        "contacts": [{"name": n, "url": u} for n, u in contacts],
        "category": {"id": category, "name": BY_ID[category].name} if category in BY_ID else None,
        "checked": checked, "mode": provider_name,
        "followups": content.followups(category, question, lang) if res.kind != "crisis" else [],
    }
    out.update(extra or {})
    return out


def retrieve(con: sqlite3.Connection, search_question: str, today: datetime.date, k: int = 5,
             emit: Emit | None = None, gate: bool = True) -> list[Hit]:
    """The page excerpts for a question: calendar rows first for a date question, then keyword search, with the
    relevance check that returns nothing rather than a loosely related page."""
    emit = emit or (lambda event, data: None)
    emit("status", {"step": "searching", "pages": content.counts(con)["pages"]})
    dated = calendar_hits(con, search_question, today)
    hits = search(con, expand(search_question), k)
    if not dated and gate:      # a model judges relevance itself and can search again; the offline composer can't
        relevance = Relevance(con)
        weights = relevance.weights(search_question)
        best = max((relevance.coverage(search_question, h, weights) for h in hits[:3]), default=0.0)
        if best < RELEVANCE_MIN:
            hits = []
    hits = (dated + [h for h in hits if h.chunk_id not in {d.chunk_id for d in dated}])[:max(k, len(dated))]
    if hits:
        emit("status", {"step": "found", "count": len({h.page_url for h in hits}),
                        "titles": list(dict.fromkeys(h.title for h in hits))[:3]})
    else:
        emit("status", {"step": "none"})
    return hits


def neighbors(con: sqlite3.Connection, hit: Hit) -> list[Hit]:
    """The excerpts just before and after this one on the same page. A rule often starts one paragraph earlier than
    the part a keyword search lands on, and reading only the middle of it is how a model gets it wrong."""
    rows = con.execute("""SELECT c.id, c.heading_path, c.anchor, c.text, p.url, p.title, p.retrieved_at, p.owning_office
                          FROM chunks t JOIN chunks c ON c.page_id = t.page_id AND c.seq IN (t.seq - 1, t.seq + 1)
                          JOIN pages p ON p.id = c.page_id
                          WHERE t.id = ? AND p.gone_at IS NULL ORDER BY c.seq""", (hit.chunk_id,)).fetchall()
    return [Hit(chunk_id=r["id"], score=0.0, coverage=0.0, title=r["title"] or "", heading_path=r["heading_path"] or "",
                url=r["url"] + (f"#{r['anchor']}" if r["anchor"] else ""), page_url=r["url"],
                retrieved_at=(r["retrieved_at"] or "")[:10], office=r["owning_office"], excerpt="", text=r["text"])
            for r in rows]


def pinned_answer(con: sqlite3.Connection, english: str, search_question: str, lang: str,
                  emit: Emit | None = None) -> dict | None:
    """A hand-checked answer for this question, verified against the stored page right now, or None."""
    entry = pinned.find(search_question)
    prepared = pinned.prepare(con, entry, lang) if entry else None
    if not prepared:
        return None
    hits, output = prepared
    if emit:
        emit("status", {"step": "searching", "pages": content.counts(con)["pages"]})
        emit("status", {"step": "found", "count": len({h.page_url for h in hits}),
                        "titles": list(dict.fromkeys(h.title for h in hits))[:3]})
    found = A.answer(english, provider=Fixed(output), search_fn=lambda q, k: hits)
    if found.kind != "answer":
        return None
    nxt = entry.get("followups", {}).get(lang) or entry.get("followups", {}).get("en")
    return _payload(found, lang, hits, english, "pinned", {"followups": nxt} if nxt else None)


def ask(question: str, lang: str = "en", previous: str | None = None, emit: Emit | None = None,
        con: sqlite3.Connection | None = None, provider: Provider | None = None,
        today: datetime.date | None = None, use_pinned: bool | None = None) -> dict:
    """Answer one question. Returns the payload the browser renders; `emit` receives progress events."""
    emit = emit or (lambda event, data: None)
    today = today or datetime.date.today()
    question = " ".join((question or "").split())[:MAX_QUESTION]
    if lang not in ("en", "es"):
        lang = "en"
    if lang == "en" and spanish.looks_spanish(question):
        lang = "es"
    english = (content.english_for(question) or spanish.to_english(question)) if lang == "es" else question
    emit("status", {"step": "reading"})
    con = con or connect()

    # 1. Crisis: OSU's own resources, quoted from the stored page. No search, no model, no playful anything.
    if A.CRISIS_RE.search(english) or A.CRISIS_RE.search(question) or ES_CRISIS.search(question):
        return _payload(A.crisis(con), lang, [], english, "none")

    # 2. Guard.
    blocked = A.guard(english)
    if blocked:
        return _payload(blocked, lang, [], english, "none",
                        {"offer_demo": blocked.reason in ("own_records", "live_data")})

    search_question = english
    if previous and is_followup(english):
        prev = " ".join(previous.split())[:MAX_QUESTION]
        search_question = f"{spanish.to_english(prev) if spanish.looks_spanish(prev) else prev} {english}"

    # 3. Hand-checked answers. The verifier still runs: if OSU's page no longer has the quote, this is skipped.
    #    Offline they come first. With a model they are only a fallback for when the model can't answer.
    mode = config.pinned_mode() if use_pinned is None else ("first" if use_pinned else "off")

    def hand_checked(announce: bool) -> dict | None:
        return pinned_answer(con, english, search_question, lang, emit if announce else None)

    if mode == "first":
        ready = hand_checked(announce=True)
        if ready:
            return ready

    # 4-5. Retrieve, compose, verify.
    seen: list[Hit] = []

    def find(q: str, k: int) -> list[Hit]:
        seen[:] = retrieve(con, search_question, today, k, emit)
        return seen

    inner = provider or get_provider(config.provider_name())
    site = SiteProvider(inner, lang, question, search_question, emit, today)
    res = A.answer(english, provider=site, search_fn=find)
    offline = isinstance(inner, GuideProvider)
    if res.kind == "answer":
        if not offline:
            res.text = _soften(res.text)
        if BANNED_RE.search(_own_words(res.text, quoted_lists=offline)):
            # Our own wording must never use these words. A quote from OSU's page may; a model's sentence may not.
            res = A.refusal("style check", A.category_for(english, seen), problems=["answer used a word the site avoids"])
    if res.kind != "answer" and not offline:
        # The model couldn't answer, or its answer failed a check. Before saying "I don't know":
        # a hand-checked answer if there is one, then the offline composer when only the checks failed.
        ready = hand_checked(announce=False) if mode == "fallback" else None
        if ready:
            return ready
        if res.reason in ("failed verification", "style check") and seen:
            backup = SiteProvider(GuideProvider(today=today), lang, question, search_question, lambda e, d: None, today)
            second = A.answer(english, provider=backup, search_fn=lambda q, k: seen)
            if second.kind == "answer":
                return _payload(second, lang, seen, english, "guide")
    return _payload(res, lang, seen, english, inner.name)


# Words students use that OSU's pages don't, added to the search (not to the question the provider sees).
EXPAND = [
    (re.compile(r"\bcounsel(or|ors|lor|lors)\b|\btherapist\b|\btherapy\b", re.I), "counseling psychological services CAPS"),
    (re.compile(r"\bcredits?\b.{0,25}\bgraduat", re.I), "minimum credits baccalaureate degree institutional requirements"),
    (re.compile(r"\bfood pantry\b|\bfree food\b", re.I), "basic needs center food pantry"),
    (re.compile(r"\bduo\b.{0,40}\b(phone|code)\b|\b(phone|code)\b.{0,40}\bduo\b", re.I), "duo bypass code service desk"),
]


def expand(question: str) -> str:
    extra = [words for rx, words in EXPAND if rx.search(question)]
    return f"{question} {' '.join(extra)}" if extra else question


def _soften(text: str) -> str:
    """Take "official" out of a model's own sentences ("an official transcript" -> "a transcript").

    Lines that quote OSU's page ("> "), text inside double quotes, and a capitalized name such as "Order Official
    Transcript" are left exactly as they are."""
    def fix(segment: str) -> str:
        segment = re.sub(r"\b([Aa])n official(ly)?\s+", lambda m: m.group(1) + " ", segment)
        return re.sub(r"\bofficial(ly)?\s+", "", segment)

    out = []
    for line in text.split("\n"):
        if line.lstrip().startswith(">"):
            out.append(line)
            continue
        parts = re.split(r'("[^"\n]*")', line)
        out.append("".join(p if p.startswith('"') else fix(p) for p in parts))
    return "\n".join(out)


def _own_words(text: str, quoted_lists: bool) -> str:
    """The answer without what is quoted from OSU's page (a quote may use any word OSU used).

    Quote lines ("> ") and text inside double quotes are always OSU's words, and "Official" inside a capitalized
    name is OSU's label. The offline guide's steps and list items are exact quotes too; a model's are its own
    wording, so they are checked."""
    skip = (">", "+", "-") if quoted_lists else (">",)
    kept = [l for l in text.splitlines() if not l.lstrip().startswith(skip)]
    return re.sub(r"\bOfficial(?= [A-Z])", " ", re.sub(r'"[^"\n]{8,}"', " ", "\n".join(kept)))


def pieces(text: str, size: int = 4) -> list[str]:
    """The answer cut into small pieces for streaming, a few words at a time, never splitting a [n] marker."""
    tokens = re.findall(r"\s+|\[\d+\]|[^\s\[]+|\[", text)
    out, buf, words = [], "", 0
    for t in tokens:
        buf += t
        if not t.isspace():
            words += 1
        if words >= size or "\n" in t:
            out.append(buf)
            buf, words = "", 0
    if buf:
        out.append(buf)
    return out
