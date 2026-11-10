"""Chunking, page-type rules and PDF reading: everything that turns an extracted page into stored records."""
import re
import unicodedata
from collections import Counter

import pymupdf

from .extract import PageExtract, Section
from .privacy import scrub_text

TARGET_WORDS, MAX_WORDS, TINY_WORDS = 350, 450, 25
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")


# ---- chunks ----------------------------------------------------------------------------------

def _words(text: str) -> int:
    return len(text.split())


def _split_long(text: str) -> list[str]:
    """Split one oversized block at sentence boundaries, carrying one sentence of overlap."""
    sentences = SENTENCE_RE.split(text)
    out, cur = [], []
    for s in sentences:
        if cur and _words(" ".join(cur + [s])) > MAX_WORDS:
            out.append(" ".join(cur))
            cur = [cur[-1]]
        cur.append(s)
    if cur:
        out.append(" ".join(cur))
    return out


def _common_prefix(a: list[str], b: list[str]) -> list[str]:
    out = []
    for x, y in zip(a, b):
        if x != y:
            break
        out.append(x)
    return out


def _labelled(path: list[str], base: list[str], blocks: list[str]) -> list[str]:
    """Blocks prefixed with the headings below `base`, so a merged chunk keeps every subsection's name."""
    extra = path[len(base):]
    return ([" > ".join(extra) + ":"] if extra else []) + blocks


def chunk_sections(sections: list[Section], merge_tiny: bool = True) -> list[dict]:
    """Chunks of ~200-450 words that never cross a top-level (h2) heading unless both sides are tiny.

    Sibling subsections under one h2 are packed together until the next would pass MAX_WORDS. Each keeps its
    own heading as a line in the text ("Artificial Intelligence Club:"), and the chunk's heading_path is the
    deepest path all its pieces share. A section too long for one chunk is split on its own.
    `merge_tiny=False` keeps small h2 sections apart (course lists: one chunk per course).
    """
    pieces: list[dict] = []  # {path, anchor, blocks}
    for sec in sections:
        key = sec.heading_path[:2]
        last = pieces[-1] if pieces else None
        lines = _labelled(sec.heading_path, key, list(sec.blocks))
        if _words(" ".join(sec.blocks)) > MAX_WORDS:
            pieces.extend({"path": sec.heading_path, "anchor": sec.anchor, "blocks": [t]}
                          for t in (c["text"] for c in _pack(sec.heading_path, sec.blocks, sec.anchor)))
            continue
        if (last and last["path"][:2] == key and last.get("open")
                and _words(" ".join(last["blocks"] + lines)) <= MAX_WORDS):
            base = _common_prefix(last["path"], sec.heading_path)
            if len(base) < len(last["path"]):
                last["blocks"] = _labelled(last["path"], base, last["blocks"])
                lines = _labelled(sec.heading_path, base, list(sec.blocks))
                last["path"] = base
            else:
                lines = _labelled(sec.heading_path, base, list(sec.blocks))
            last["blocks"] += lines
            last["anchor"] = last["anchor"] or sec.anchor
        else:
            pieces.append({"path": list(sec.heading_path), "anchor": sec.anchor, "blocks": list(sec.blocks),
                           "open": True})

    # Neighbouring tiny pieces (different h2s, e.g. a run of one-line notices) are merged the same way.
    merged: list[dict] = []
    for p in pieces:
        prev = merged[-1] if merged else None
        if (merge_tiny and prev and _words(" ".join(prev["blocks"])) < TINY_WORDS * 3 and _words(" ".join(p["blocks"])) < TINY_WORDS * 3
                and _words(" ".join(prev["blocks"] + p["blocks"])) <= TARGET_WORDS):
            base = _common_prefix(prev["path"], p["path"])
            prev["blocks"] = _labelled(prev["path"], base, prev["blocks"]) + _labelled(p["path"], base, p["blocks"])
            prev["path"] = base
            prev["anchor"] = prev["anchor"] or p["anchor"]
        else:
            merged.append(p)

    chunks = [{"heading_path": " > ".join(p["path"]), "anchor": p["anchor"], "text": "\n".join(p["blocks"]),
               "token_estimate": round(_words(" ".join(p["blocks"])) * 1.33)} for p in merged if p["blocks"]]
    for i, c in enumerate(chunks):
        c["seq"] = i
    return chunks


def _pack(path: list[str], blocks: list[str], anchor: str | None) -> list[dict]:
    out, cur = [], []
    for block in blocks:
        pieces = _split_long(block) if _words(block) > MAX_WORDS else [block]
        for piece in pieces:
            if cur and _words("\n".join(cur + [piece])) > MAX_WORDS:
                out.append("\n".join(cur))
                cur = []
            cur.append(piece)
            if _words("\n".join(cur)) >= TARGET_WORDS:
                out.append("\n".join(cur))
                cur = []
    if cur:
        out.append("\n".join(cur))
    return [{"heading_path": " > ".join(path), "anchor": anchor, "text": t,
             "token_estimate": round(_words(t) * 1.33)} for t in out if t.strip()]


# ---- page type -------------------------------------------------------------------------------

RULES = [
    ("news", r"/(news|stories|all-stories|feature-story|announcement)(/|$)", None),
    ("deadline", r"calendar|deadline|important-dates|/dates|finals?-(week|exam)|exam-schedule|refund-schedule",
     r"\b(calendar|deadlines?|important dates|key dates|final exam schedule|dates and deadlines)\b"),
    ("faq", r"faq|/ask-ecampus/(?!category)[\w-]+", r"\b(faqs?|frequently asked)\b"),
    # A forms hub (/forms), a petition, or a "...-form" page; not every tool that lives under Ecampus's /forms/.
    ("form", r"/forms?/?$|petition|-forms?([-./]|$)", r"\b(forms?|petitions?)\b"),
    ("contact", r"contact|hours|location|directions|visit-us|find-us", r"\b(contact( us| info)?|hours|locations?|directions)\b"),
    ("policy", r"polic(y|ies)|regulations?|code-of|conduct|rights|standards|guidelines|procedures|ferpa",
     r"\b(polic(y|ies)|regulations?|code of|student conduct|rights and responsibilities|guidelines|procedures|ferpa)\b"),
    ("how-to", r"how-(to|do)|getting-?started|steps|apply|request|register|adding|changing|change-",
     r"^(how (to|do i)|getting started|steps|apply|request|register|adding|changing|change)\b"),
]


def classify_page(url: str, ex: PageExtract, n_table_dates: int) -> tuple[str, dict]:
    path = url.split("//", 1)[-1].split("/", 1)[-1].lower()
    title = ex.title.lower()
    heads = [h["text"] for h in ex.headings]
    signals: dict[str, list[str]] = {}
    for kind, url_re, title_re in RULES:
        if re.search(url_re, "/" + path):
            signals.setdefault(kind, []).append("url")
        if title_re and re.search(title_re, title):
            signals.setdefault(kind, []).append("title")
    if re.search(r"/site-index(/|\?|$)", "/" + path):
        return "other", {"other": ["site A-Z index (a list of links)"]}
    if n_table_dates >= 5:
        signals.setdefault("deadline", []).append(f"{n_table_dates} dated table rows")
    # Short calls to action ("Ready to apply?", "Questions?") are not FAQ entries; real questions have 4+ words.
    questions = len({h.strip().lower() for h in heads if h.strip().endswith("?") and len(h.split()) >= 4})
    if questions >= 3 or (ex.template == "ecampus:ask-answer"):
        signals.setdefault("faq", []).append(f"{questions} question headings" if questions >= 3 else "template")
    howto_heads = [h for h in heads if re.match(r"(how (to|do i|can i)|steps?\b|to (add|drop|withdraw|request|apply))", h, re.I)]
    if howto_heads:
        signals.setdefault("how-to", []).append(f"{len(howto_heads)} how-to heading(s)")
    real_forms = [f for f in ex.forms if f["source"] == "on_page" and f["kind"] == "web_form"]
    if real_forms:
        signals.setdefault("form", []).append(f"{len(real_forms)} on-page form(s)")
    form_links = [f for f in ex.forms if f["source"] == "link"]
    if len(form_links) >= 5 and len(ex.main_text) < 4000:
        signals.setdefault("form", []).append(f"{len(form_links)} form/PDF links on a short page")
    # "Step 1: Log into Beaver Hub." and numbered list items ("1. ...", from <ol>).
    ordered_steps = len(re.findall(r"(?im)^\s*(step \d+\s*[:.)\-]|\d+[.)]\s)", ex.main_text))
    if ordered_steps >= 3:
        signals.setdefault("how-to", []).append(f"{ordered_steps} numbered steps")
    # A process page that ends with a few FAQ questions is still a how-to.
    if ("how-to" in signals and "faq" in signals and ordered_steps >= 3
            and all(s.endswith("question headings") for s in signals["faq"])):
        return "how-to", signals
    for kind, _, _ in RULES:  # RULES is in priority order
        if kind in signals:
            return kind, signals
    return "other", signals


# ---- PDFs ------------------------------------------------------------------------------------

JUNK_TITLE_RE = re.compile(
    r"^(document title|untitled|microsoft (word|powerpoint|excel) -|return to\b|created |page \d|draft\b)"
    r"|\.(docx?|pptx?|xlsx?|pdf)$|_formatted|\[\d+\]|^[A-Za-z]+\s*,?\s*\d{4}$|^[A-Z]+$|-$",
    re.IGNORECASE)


def good_title(title: str | None) -> bool:
    t = " ".join((title or "").split())
    return len(t) >= 6 and not JUNK_TITLE_RE.search(t)


SOFT_HYPHEN_RE = re.compile("\u00ad\\s*")


def read_pdf(content: bytes) -> dict:
    doc = pymupdf.open(stream=content, filetype="pdf")
    # NFKC folds ligatures (the "fi" in "certificate" is often one glyph) so full-text search finds the words.
    # Individuals' emails and direct phones are removed before anything is stored (privacy.py).
    pages = [scrub_text(SOFT_HYPHEN_RE.sub("", unicodedata.normalize("NFKC", p.get_text("text"))))[0] for p in doc]
    text_chars = sum(len(t.strip()) for t in pages)
    has_images = any(p.get_images() for p in doc)
    fillable = any(True for p in doc for _ in p.widgets())
    title = (doc.metadata or {}).get("title") or ""
    if not good_title(title):
        lines = (" ".join(l.split()) for t in pages[:1] for l in t.splitlines())
        title = next((l for l in lines if good_title(l) and len(l) > 8), "")[:200]
    return {
        "page_count": len(pages),
        "title": title.strip(),
        "fillable": fillable,
        "needs_ocr": text_chars < 40 * max(1, len(pages)) and has_images,
        "pages": pages,
        "items": pdf_items(doc),
        "text": "\n\n".join(pages),
    }


def pdf_items(doc) -> list[tuple[str, int, str, int]]:
    """The PDF as a reading-order list of ("h", level, text, page) headings and ("p", 0, text, page) paragraphs.

    A heading is a short line set in a larger font than the body text, or a short all-bold line at body size.
    Lines repeated on most pages (running headers/footers) and form labels ending in ":" are never headings.
    """
    lines = []  # (page, block_no, text, size, bold)
    for pno, page in enumerate(doc, start=1):
        for bno, block in enumerate(page.get_text("dict")["blocks"]):
            for line in block.get("lines", []):
                spans = [s for s in line["spans"] if s["text"].strip()]
                if not spans:
                    continue
                text = unicodedata.normalize("NFKC", " ".join(" ".join(s["text"].split()) for s in spans)).strip()
                size = round(max(s["size"] for s in spans), 1)
                bold = all(s["flags"] & 16 or "bold" in s["font"].lower() for s in spans)
                lines.append((pno, bno, text, size, bold))
    if not lines:
        return []
    by_size = Counter()
    for _, _, text, size, _ in lines:
        by_size[size] += len(text)
    body = by_size.most_common(1)[0][0]
    pages_with = Counter()
    for pno, _, text, _, _ in {(l[0], 0, l[2], 0, 0) for l in lines}:
        pages_with[text] += 1
    n_pages = max(l[0] for l in lines)

    def is_heading(text, size, bold):
        words = text.split()
        if not (1 <= len(words) <= 14) or not re.search(r"[A-Za-z]{2}", text) or text.endswith((":", ",", ";")):
            return False
        if n_pages >= 3 and pages_with[text] >= max(3, n_pages // 2):
            return False  # running header or footer
        if re.fullmatch(r"(page\s*)?\d+(\s*(of|/)\s*\d+)?", text, re.I):
            return False
        if "___" in text or "@" in text or "http" in text.lower() or re.search(r"\b\d{5}(-\d{4})?\b", text):
            return False  # form fields, contact lines and addresses

        return size >= body + 1.0 or (bold and size >= body - 0.2 and not text.endswith("."))

    sizes = sorted({size for _, _, text, size, bold in lines if is_heading(text, size, bold) and size >= body + 1.0},
                   reverse=True)
    level_of = {s: min(2 + i, 4) for i, s in enumerate(sizes)}
    items, para, para_key = [], [], None
    for pno, bno, text, size, bold in lines:
        if is_heading(text, size, bold):
            if para:
                items.append(("p", 0, " ".join(para), para_key[0]))
                para = []
            items.append(("h", level_of.get(size, min(2 + len(sizes), 4)), text, pno))
            continue
        if para and (pno, bno) != para_key:
            items.append(("p", 0, " ".join(para), para_key[0]))
            para = []
        para.append(text)
        para_key = (pno, bno)
    if para:
        items.append(("p", 0, " ".join(para), para_key[0]))
    # A soft hyphen at a line break splits a word ("Supple- mental"): join it back.
    return [(kind, level, SOFT_HYPHEN_RE.sub("", text), pno) for kind, level, text, pno in items]


def pdf_sections(title: str, pages: list[str], items: list | None = None) -> list[Section]:
    """Sections for a PDF's chunks. With detected headings: 'Title > Heading > Subheading', anchored to the page
    the section starts on (#page=N). Without: one section per page ('Title > Page N')."""
    root = title or "PDF"
    words = lambda s: set(re.findall(r"[a-z0-9]+", (s or "").lower()))
    # Drop a heading that only repeats the document title, in any word order (usually the cover line).
    items = [i for i in (items or []) if not (i[0] == "h" and words(i[2]) and
                                              (words(i[2]) <= words(root) or words(root) <= words(i[2])))]
    n_heads = sum(1 for k, *_ in items if k == "h")
    n_paras = sum(1 for k, *_ in items if k == "p")
    # Tables and forms (bold cells everywhere) have more "headings" than paragraphs: page sections suit them better.
    if n_heads >= 2 and n_heads <= n_paras:
        out = [Section([root], "page=1", 1)]
        stack: list[tuple[int, str]] = []
        for kind, level, text, pno in items:
            if kind == "h":
                while stack and stack[-1][0] >= level:
                    stack.pop()
                stack.append((level, text))
                out.append(Section([root] + [t for _, t in stack], f"page={pno}", level))
            else:
                block = scrub_text(" ".join(text.split()))[0]
                if block:
                    out[-1].blocks.append(block)
        # A heading with nothing under it (a title page line, a form caption) is kept as content, like on web pages.
        for i, s in enumerate(out):
            if not s.blocks and len(s.heading_path) > 1 and (i == len(out) - 1 or out[i + 1].level <= s.level):
                s.blocks.append(s.heading_path[-1])
        return [s for s in out if s.blocks]
    out = []
    for i, page in enumerate(pages, start=1):
        paras = [" ".join(p.split()) for p in re.split(r"\n\s*\n", page) if p.strip()]
        if paras:
            out.append(Section([root, f"Page {i}"], f"page={i}", 2, paras))
    return out
