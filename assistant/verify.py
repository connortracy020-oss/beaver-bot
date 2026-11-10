"""Checks a model's answer against the chunks it was shown, before a student sees it.

The model must return JSON (see answer.SYSTEM):

    {"status": "answered" | "not_found",
     "answer": "Text citing sources as [1], [2] ...",
     "citations": [{"chunk_id": 123, "quote": "text copied exactly from chunk 123"}, ...]}

An answer is **discarded** (the student gets the refusal message instead) when:
- the output isn't that JSON, or the status is anything but "answered";
- it has no citations, or the answer text has no [n] markers, or a marker points to no citation;
- a citation names a chunk the model wasn't given;
- a quote is shorter than MIN_QUOTE_CHARS or doesn't appear in its chunk (after normalizing whitespace, quote
  marks and dashes; a quote may skip text with "..." if each piece appears in order);
- a number in the answer (an amount, date or phone number) appears in none of the cited chunks.

It is **flagged** (shown, with the flag logged) when a citation is never referenced in the answer text.
"""
import json
import re
import unicodedata
from dataclasses import dataclass, field

MIN_QUOTE_CHARS = 8    # a table cell like "C | $167" is short but checkable; "Permits" is not
ELLIPSIS_RE = re.compile(r"\s*(?:\.\.\.|…)\s*")
MARKER_RE = re.compile(r"\[(\d+)\]")
NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
_FOLD = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", "‑": "-",
                       " ": " ", "­": None})


@dataclass
class Verdict:
    ok: bool
    status: str                      # "answered", "not_found" or "invalid"
    answer: str = ""
    citations: list[dict] = field(default_factory=list)   # [{"n", "chunk_id", "quote"}], all verified
    problems: list[str] = field(default_factory=list)     # reasons the answer was discarded
    flags: list[str] = field(default_factory=list)        # shown anyway, but worth a look


def normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text or "").translate(_FOLD).split())


def quote_in(quote: str, chunk: str) -> bool:
    """True when the quote appears in the chunk; "..." may stand for skipped text between pieces in order."""
    hay, pos = normalize(chunk), 0
    pieces = [p for p in ELLIPSIS_RE.split(normalize(quote)) if p]
    if not pieces:
        return False
    for p in pieces:
        i = hay.find(p, pos)
        if i < 0:
            return False
        pos = i + len(p)
    return True


def parse(raw: str) -> dict | None:
    """The JSON object in the model's output; tolerates a ```json fence around it, nothing else."""
    text = (raw or "").strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _numbers(text: str) -> set[str]:
    """Numbers as plain digits: "1,000" -> "1000", "$15.00" -> "15", "2.50" -> "2.5"."""
    out = set()
    for n in NUMBER_RE.findall(MARKER_RE.sub(" ", text)):
        n = n.replace(",", "")
        out.add(n.rstrip("0").rstrip(".") if "." in n else n)
    return out


def verify(raw: str, chunks: dict[int, str]) -> Verdict:
    data = parse(raw)
    if data is None:
        return Verdict(False, "invalid", problems=["output is not the JSON answer format"])
    status = data.get("status")
    if status == "not_found":
        return Verdict(False, "not_found", problems=["the model found no answer in the excerpts"])
    if status != "answered":
        return Verdict(False, "invalid", problems=[f"unknown status {status!r}"])
    answer, cites = data.get("answer"), data.get("citations")
    if not isinstance(answer, str) or not answer.strip():
        return Verdict(False, "invalid", problems=["empty answer"])
    if not isinstance(cites, list) or not cites:
        return Verdict(False, "invalid", answer=answer, problems=["no citations"])

    v = Verdict(True, "answered", answer=answer)
    for n, c in enumerate(cites, 1):
        cid, quote = (c.get("chunk_id"), c.get("quote")) if isinstance(c, dict) else (None, None)
        if isinstance(cid, str) and cid.isdigit():
            cid = int(cid)
        if not isinstance(cid, int) or not isinstance(quote, str):
            v.problems.append(f"citation [{n}] needs an integer chunk_id and a quote string")
        elif cid not in chunks:
            v.problems.append(f"citation [{n}] names chunk {cid}, which the model wasn't given")
        elif len(normalize(ELLIPSIS_RE.sub(" ", quote))) < MIN_QUOTE_CHARS:
            v.problems.append(f"citation [{n}] quote is too short to check: {quote!r}")
        elif not quote_in(quote, chunks[cid]):
            v.problems.append(f"citation [{n}] quote is not in chunk {cid}: {quote!r}")
        else:
            v.citations.append({"n": n, "chunk_id": cid, "quote": quote})

    markers = {int(m) for m in MARKER_RE.findall(answer)}
    if not markers:
        v.problems.append("the answer text cites no source ([n] markers)")
    for m in sorted(markers - set(range(1, len(cites) + 1))):
        v.problems.append(f"marker [{m}] has no matching citation")
    for c in v.citations:
        if c["n"] not in markers:
            v.flags.append(f"citation [{c['n']}] is never referenced in the answer")

    cited_text = " ".join(normalize(chunks[c["chunk_id"]]) for c in v.citations)
    cited_numbers = _numbers(cited_text)
    for num in sorted(_numbers(normalize(answer)) - cited_numbers):
        v.problems.append(f"the number {num} is in the answer but in none of the cited chunks")

    v.ok = not v.problems
    return v
