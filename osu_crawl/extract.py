"""Turn one HTML page into structure: title, breadcrumb, headings, sections, links, forms and the office contact block.

The main content is found with per-platform selectors (OSU's Drupal "Madrone" theme, CourseLeaf for the catalog,
Ecampus's own templates), then walked in document order so every block of text keeps its heading path.
trafilatura runs on every page too, as a fallback and as a cross-check on how much text we kept.
"""
import json
import re
from dataclasses import dataclass, field
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

import trafilatura
from lxml import html as lxml_html
from lxml.html import HtmlElement

from .privacy import scrub_text

HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
BLOCKY = HEADINGS | {"p", "div", "section", "article", "ul", "ol", "li", "table", "tr", "dl", "dt", "dd", "pre",
                     "blockquote", "figure", "figcaption", "details", "summary", "address", "header", "footer",
                     "aside", "nav", "main", "form", "fieldset"}
DROP = "script|style|noscript|template|svg|iframe|form|nav|button[not(ancestor::h1 or ancestor::h2 or ancestor::h3 or ancestor::h4)]|select|input|textarea"
CONTACT_HEADING_RE = re.compile(r"^(contact( info(rmation)?| us)?|get in touch)$", re.IGNORECASE)
# Sections that list named people: club officers, "Meet the team", staff directories. Not stored (data minimization).
PEOPLE_HEADING_RE = re.compile(r"\b((club |executive |student )?officers|executive (board|team|council)|e-?board|"
                               r"(committee|board|council) members|meet (the|our|your) (team|staff|officers|board)|our (team|staff|officers)|"
                               r"staff directory|leadership team|"
                               # full Tier 2b crawl: award winners, showcase presenters, student senators
                               r"(past |previous )?(award )?(recipients|winners)|presenters|senators|"
                               r"student profiles)\b", re.IGNORECASE)
LOREM_RE = re.compile(r"lorem ipsum dolor", re.IGNORECASE)  # unfinished template pages
# "2025-2026 winners: <names>" under an award's description: the description stays, the names go.
RECIPIENT_LINE_RE = re.compile(r"^\W*((19|20)\d\d(\s*[-–/]\s*(19|20)?\d\d)?\s+)?"
                               r"(winners?|recipients?|awardees?|honorees?|honorable mentions?)\s*:", re.IGNORECASE)
CONTACT_FOOTER_STOP_RE = re.compile(r"^(copyright|©|disclaimer|land acknowledgment|privacy)", re.IGNORECASE)
HIDDEN_EMAIL = "[email hidden on page]"

# Main-content selectors, most specific first.
MAIN_SELECTORS = {
    "drupal": ["//main[@role='main']", "//main"],
    "courseleaf": ["//div[@id='content'][@role='main']", "//div[@id='textcontainer']", "//div[@id='content']"],
    # div[@role='main'] is the content column; 'maincontent' also wraps a promo sidebar ("Ecampus fact").
    "ecampus": ["//div[@role='main']", "//div[contains(@class,'maincontent')]", "//main",
                "//div[contains(@class,'infomain')]", "//div[@id='main-wrapper']", "//div[@id='content']"],
    "generic": ["//main", "//*[@role='main']", "//article", "//div[@id='content']"],
}
BOILERPLATE_IN_MAIN = [
    "//*[@id='dialog-title']/..",                       # CourseLeaf "Print Options" dialog
    "//*[contains(@class,'visually-hidden')]",
    "//*[contains(@class,'sr-only')]",
    "//*[contains(@class,'printonly')]",
    "//*[contains(@class,'breadcrumb')]",
    "//*[contains(@class,'pager')]",
    "//*[contains(@class,'promo-box')]",                # Ecampus "Ecampus fact" / "Student resources" promos
    "//*[@id='efact']",
    "//*[contains(@class,'hNavTable')]",                # Ecampus tab menus
    "//*[contains(@class,'dNav')]",
]

EXTERNAL_FORM_HOSTS = {
    "qualtrics.com": "qualtrics", "na2.documents.adobe.com": "adobe sign", "secure.adobesign.com": "adobe sign",
    "echosign.com": "adobe sign", "forms.office.com": "microsoft forms", "forms.microsoft.com": "microsoft forms",
    "docs.google.com": "google forms", "forms.gle": "google forms", "maxient.com": "maxient",
    "jotform.com": "jotform", "dynamicforms.ngwebsolutions.com": "dynamic forms", "docusign.net": "docusign",
    "app.smartsheet.com": "smartsheet", "formstack.com": "formstack",
}
FORMISH_RE = re.compile(r"\b(form|petition|request|application|apply|submit|report|appeal|waiver|authorization)\b", re.I)


@dataclass
class Section:
    heading_path: list[str]
    anchor: str | None
    level: int
    blocks: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(self.blocks)


@dataclass
class PageExtract:
    platform: str
    title: str
    html_title: str
    site_name: str | None
    canonical_url: str | None
    language: str | None
    meta_robots: str
    breadcrumb: list[dict]
    headings: list[dict]
    sections: list[Section]
    main_text: str
    contact_block: str | None
    links: list[dict]
    forms: list[dict]
    tables: list[dict]
    template: str
    main_found: bool
    trafilatura_text: str
    nav_menu: list[dict] | None = None

    def heading_tree(self) -> list[dict]:
        root: list[dict] = []
        stack: list[tuple[int, list]] = [(0, root)]
        for h in self.headings:
            node = {**h, "children": []}
            while stack and stack[-1][0] >= h["level"]:
                stack.pop()
            stack[-1][1].append(node)
            stack.append((h["level"], node["children"]))
        return root


SR_ONLY_RE = re.compile(r"\((link is external|link downloads document|opens in (a )?new (window|tab))\)", re.IGNORECASE)


ZERO_WIDTH_RE = re.compile("[\u200b\u200c\u200d\u2060\ufeff\u00ad]")  # zero-width characters and soft hyphens


def norm_ws(s: str) -> str:
    return " ".join(SR_ONLY_RE.sub(" ", ZERO_WIDTH_RE.sub("", s or "")).split())


def table_rows(table: HtmlElement) -> list[list[str]]:
    """Rows of cell texts with rowspan/colspan expanded, so every row carries the date cell it shares."""
    rows: list[list[str]] = []
    carry: dict[int, tuple[str, int]] = {}  # column -> (text, rows still to fill)
    for tr in table.iter("tr"):
        cells = [c for c in tr if isinstance(c.tag, str) and c.tag in ("td", "th")]
        row: list[str] = []
        col = 0
        for c in cells:
            while col in carry:
                text, left = carry[col]
                row.append(text)
                carry[col] = (text, left - 1)
                if left - 1 <= 0:
                    del carry[col]
                col += 1
            text = norm_ws(c.text_content())
            span = int(c.get("colspan") or 1) if (c.get("colspan") or "1").isdigit() else 1
            down = int(c.get("rowspan") or 1) if (c.get("rowspan") or "1").isdigit() else 1
            for _ in range(span):
                row.append(text)
                if down > 1:
                    carry[col] = (text, down - 1)
                col += 1
        while col in carry:
            text, left = carry[col]
            row.append(text)
            carry[col] = (text, left - 1)
            if left - 1 <= 0:
                del carry[col]
            col += 1
        if any(row):
            rows.append(row)
    return rows


def normalize_url(url: str) -> str:
    """Lowercase host, drop fragment, keep query (pagers like ?page=2 matter), strip default index files."""
    p = urlsplit(url)
    path = p.path or "/"
    path = re.sub(r"/index\.(html?|php)$", "/", path)
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), path, p.query, ""))


def detect_platform(doc: HtmlElement, url: str) -> str:
    host = urlsplit(url).hostname or ""
    gen = " ".join(doc.xpath("//meta[@name='Generator' or @name='generator']/@content"))
    if "Drupal" in gen:
        return "drupal"
    if host == "catalog.oregonstate.edu" or doc.xpath("//div[@id='textcontainer']"):
        return "courseleaf"
    if host == "ecampus.oregonstate.edu":
        return "ecampus"
    return "generic"


def find_main(doc: HtmlElement, platform: str) -> HtmlElement | None:
    for xp in MAIN_SELECTORS.get(platform, []) + MAIN_SELECTORS["generic"]:
        found = doc.xpath(xp)
        if found:
            return found[0]
    return None


def region_of(a: HtmlElement, main: HtmlElement | None) -> str:
    el = a
    while el is not None:
        tag, cls, ident, role = el.tag, (el.get("class") or ""), (el.get("id") or ""), (el.get("role") or "")
        if "breadcrumb" in cls or ident == "breadcrumb":
            return "breadcrumb"
        if el is main:
            return "main"
        if tag == "footer" or role == "contentinfo" or "footer" in ident:
            return "footer"
        if tag == "aside" or "sidebar" in cls or ident in ("right-col", "left-col"):
            return "sidebar"
        if tag in ("nav", "header") or role in ("navigation", "banner"):
            return "nav"
        el = el.getparent()
    return "other"


def _block_has_blocks(el: HtmlElement) -> bool:
    return any(isinstance(d.tag, str) and d.tag in BLOCKY for d in el.iterdescendants())


class _Walker:
    """Walk the main region in order, emitting text blocks under the current heading path."""

    def __init__(self, page_title: str, tab_labels: dict[str, str] | None = None):
        self.sections = [Section([page_title] if page_title else [], None, 1)]
        self.stack: list[tuple[int, str, str | None]] = []  # (level, text, anchor)
        self.headings: list[dict] = []
        self.page_title = page_title
        self.tab_labels = tab_labels or {}

    def heading(self, el: HtmlElement):
        anchor = el.get("id") or next((d.get("id") for d in el.iterdescendants() if d.get("id")), None)
        self.add_heading(int(el.tag[1]), norm_ws(el.text_content()), anchor)

    def add_heading(self, level: int, text: str, anchor: str | None):
        """`anchor` "__caption__" marks a table caption: kept on the stack to recognise sibling tables, never stored."""
        if not text:
            return
        real_anchor = None if anchor == "__caption__" else anchor
        self.headings.append({"level": level, "text": text, "anchor": real_anchor})
        if level == 1:
            self.stack = []
            if text == self.page_title:
                return
        while self.stack and self.stack[-1][0] >= level:
            self.stack.pop()
        self.stack.append((level, text, anchor))
        path = ([self.page_title] if self.page_title else []) + [t for _, t, _ in self.stack if t != self.page_title]
        self.sections.append(Section(path, real_anchor, level))

    def emit(self, text: str, prefix: str = ""):
        text = norm_ws(text)
        if text and text not in (":", ".", ",", "|"):
            self.sections[-1].blocks.append(prefix + text)

    def walk(self, el: HtmlElement, prefix: str = "", depth: int = 0):
        """Inline runs (text, <a>, <strong>, tails) join into one block until a block element appears.
        `prefix` ("- " for a list item) goes on the first block only; nested lists indent by `depth`."""
        run: list[str] = [el.text or ""]
        first = [True]

        def flush():
            text = norm_ws(" ".join(run))
            if text:
                self.emit(text, prefix if first[0] else "")
                first[0] = False
            run.clear()

        for child in el:
            if not isinstance(child.tag, str):
                run.append(child.tail or "")
                continue
            if child.tag not in BLOCKY and not _block_has_blocks(child):
                run.append(child.text_content())
                run.append(child.tail or "")
                continue
            flush()
            label = self.tab_labels.get(child.get("aria-labelledby") or "") if child.get("role") == "tabpanel" else None
            if label:
                # CourseLeaf puts Overview / Requirements / Majors ... in tab panels; the tab name heads the section.
                self.add_heading(2, label, child.get("id"))
                self.walk(child, depth=depth)
            elif child.tag in HEADINGS:
                self.heading(child)
            elif child.tag == "table":
                self.table(child)
            elif child.tag in ("ul", "ol"):
                for n, li in enumerate(child.iterchildren("li"), start=1):
                    bullet = "  " * depth + (f"{n}. " if child.tag == "ol" else "- ")
                    if _block_has_blocks(li):
                        self.walk(li, bullet, depth + 1)
                    else:
                        self.emit(li.text_content(), bullet)
            elif child.tag == "dl":
                for item in child:
                    if isinstance(item.tag, str):
                        self.emit(item.text_content(), "" if item.tag == "dt" else "  ")
            elif _block_has_blocks(child):
                self.walk(child, depth=depth)
            else:
                self.emit(child.text_content())
            run.append(child.tail or "")
        flush()

    def table(self, table: HtmlElement):
        # A captioned table (each month of the academic calendar) is its own section, so the caption
        # ("September 2026") travels with its rows into every chunk.
        caption = norm_ws(" ".join(table.xpath("./caption//text()")))
        if caption:
            level = min(6, (self.stack[-1][0] if self.stack else 1) + 1)
            if self.stack and self.stack[-1][2] == "__caption__":
                level = self.stack[-1][0]  # consecutive tables are siblings
            self.add_heading(level, caption, "__caption__")
        for row in table_rows(table):
            self.emit(" | ".join(row))


def _tables(main: HtmlElement) -> list[dict]:
    """Tables with caption, header row and nearest preceding heading, for the date extractor."""
    out = []
    for t in main.iter("table"):
        caption = norm_ws(" ".join(t.xpath("./caption//text()")))
        prev = t.xpath("preceding::*[self::h1 or self::h2 or self::h3 or self::h4 or self::h5][1]")
        header = []
        for tr in t.iter("tr"):
            cells = [c for c in tr if isinstance(c.tag, str) and c.tag in ("td", "th")]
            if cells and all(c.tag == "th" for c in cells):
                header = [norm_ws(c.text_content()) for c in cells]
                break
        out.append({"caption": caption, "heading": norm_ws(prev[0].text_content()) if prev else "",
                    "header": header, "rows": table_rows(t)})
    return out


def _nav_menu(doc: HtmlElement, base: str) -> list[dict] | None:
    """The site's main menu as a tree (Drupal "Main menu", CourseLeaf left menu, Ecampus #nav)."""
    navs = [n for n in doc.xpath("//nav[.//ul]")
            if not re.search(r"pager|breadcrumb|pagination", " ".join(filter(None, [
                n.get("class"), n.get("id"), n.get("aria-label"), n.get("aria-labelledby")])), re.I)]
    if not navs:
        return None

    def label(n):
        ref = n.get("aria-labelledby")
        return (n.get("aria-label") or "") + " " + (" ".join(doc.xpath(f"//*[@id='{ref}']//text()")) if ref else "")

    preferred = doc.xpath("//nav[@id='cl-menu']") or [n for n in navs if re.search(r"\bmain\b", label(n), re.I)]
    menu = preferred[0] if preferred else max(navs, key=lambda n: len(n.xpath(".//a")))
    top = menu.xpath(".//ul[1]")
    if not top:
        return None

    def build(ul):
        items = []
        for li in ul.iterchildren("li"):
            a = li.find(".//a")
            sub = li.find("ul")
            label = norm_ws(a.text_content()) if a is not None else norm_ws(li.text or "")
            href = normalize_url(urljoin(base, a.get("href"))) if a is not None and a.get("href") else None
            items.append({"text": label, "url": href, "children": build(sub) if sub is not None else []})
        return items

    return build(top[0])


def _template(platform: str, main: HtmlElement | None, url: str) -> str:
    if main is None:
        return f"{platform}:no-main"
    if platform == "drupal":
        kinds = set()
        for cls in main.xpath(".//@class"):
            for c in cls.split():
                m = re.match(r"(paragraph--type--|view-id-|node--type-|block-views-block-)([\w-]+)", c)
                if m:
                    kinds.add(m.group(2).replace("_", "-"))
        return "drupal:" + ("+".join(sorted(kinds)[:4]) or "basic")
    if platform == "courseleaf":
        if main.xpath(".//div[contains(@class,'courseblock')]"):
            return "courseleaf:course-list"
        if main.xpath(".//*[@id='requirementstextcontainer' or @id='degreerequirementstextcontainer']"):
            return "courseleaf:program"
        if main.xpath(".//*[@id='textcontainer']//table[contains(@class,'sc_courselist')]"):
            return "courseleaf:courselist-page"
        return "courseleaf:page"
    if platform == "ecampus":
        path = urlsplit(url).path
        if path.startswith("/ask-ecampus/") and path.count("/") > 2:
            return "ecampus:ask-answer" if "/category/" not in path else "ecampus:ask-category"
        return "ecampus:" + ("htm-page" if path.endswith(".htm") else "page")
    return f"{platform}:page"


def extract_html(content: bytes, url: str) -> PageExtract:
    doc = lxml_html.fromstring(content)
    platform = detect_platform(doc, url)
    html_title = norm_ws(doc.findtext(".//title") or "")
    canonical = doc.xpath("//link[@rel='canonical']/@href")
    lang = doc.get("lang") or (doc.xpath("//meta[@http-equiv='Content-Language']/@content") or [None])[0]
    meta_robots = ",".join(doc.xpath("//meta[translate(@name,'ROBOTS','robots')='robots']/@content")).lower()

    # Cloudflare replaces emails with "[email protected]"; we leave them hidden (see crawl-policy.md).
    for el in doc.xpath("//*[contains(@class,'__cf_email__')]"):
        el.text, el.tail = HIDDEN_EMAIL, el.tail
        for c in list(el):
            el.remove(c)

    # Drupal's site-name block lists [parent unit, this site]; the last link is the site itself.
    parts = [p.strip() for p in re.split(r"\s+[|<]\s+", html_title) if p.strip()]
    names = [norm_ws(a.text_content()) for a in doc.xpath("//*[contains(@class,'block__content__site-name')]//a")]
    site_name = names[-1] if names else (parts[-2] if len(parts) >= 3 else None)

    main = find_main(doc, platform)
    links = []
    for a in doc.iter("a"):
        href = (a.get("href") or "").strip()
        if not href or href.startswith(("#", "javascript:")):
            continue
        absolute = urljoin(url, href)
        if absolute.lower().startswith(("mailto:", "tel:")):
            continue  # personal contact details aren't part of the link graph
        if not absolute.lower().startswith(("http://", "https://")):
            continue  # sms:, skype:, data: and the like are not web pages
        links.append({"url": normalize_url(absolute), "text": norm_ws(a.text_content())[:300],
                      "region": region_of(a, main), "nofollow": "nofollow" in (a.get("rel") or "").lower()})

    breadcrumb = []
    for a in doc.xpath("//*[contains(@class,'breadcrumb') or @id='breadcrumb']//a"):
        if a.get("href"):
            breadcrumb.append({"text": norm_ws(a.text_content()), "url": normalize_url(urljoin(url, a.get("href")))})
    crumb_tail = doc.xpath("//*[contains(@class,'breadcrumb') or @id='breadcrumb']//*[@aria-current='page' or contains(@class,'active')]")
    if crumb_tail:
        breadcrumb.append({"text": norm_ws(crumb_tail[-1].text_content()), "url": None})

    forms = _forms(doc, url)
    nav_menu = _nav_menu(doc, url)
    contact_block = _contact_block(doc)

    # Some headings carry an inline <style> ("Cost of Attendance .accordion-toggle {font-size:25px}").
    for el in doc.xpath("//h1//style | //h1//script"):
        el.drop_tree()
    title = ""
    if main is not None:
        h1s = [norm_ws(h.text_content()) for h in main.iter("h1")]
        title = next((h for h in h1s if h and h != "Oregon State University"), "")
    if not title:
        h1s = [norm_ws(h.text_content()) for h in doc.iter("h1")]
        title = next((h for h in h1s if h and h != "Oregon State University"), "") or (parts[0] if parts else html_title)
    if not title or title.startswith("|"):
        # Pages with an empty <h1> (e.g. a Drupal A-Z listing) give "<title>| Office | OSU</title>": name them from
        # the URL instead, e.g. registrar /site-index/c -> "Site index C".
        segs = [unquote(s).strip() for s in urlsplit(url).path.split("/") if unquote(s).strip()]
        title = " ".join(segs).replace("-", " ").strip().capitalize() or site_name or html_title.strip("| ")

    if platform == "ecampus" and "/ask-ecampus/category/" in urlsplit(url).path:
        # Every Ask Ecampus category page has the h1 "Ask Ecampus"; the category is only in the URL.
        slug = [s for s in urlsplit(url).path.split("/") if s][-1]
        title = f"{title}: {slug.replace('-', ' ').capitalize()}"

    sections, headings, tables = [], [], []
    if main is not None:
        tab_labels = {a.get("id"): norm_ws(a.text_content()) for a in doc.xpath("//*[@role='tab' or ancestor::nav[@id='tabs']]")
                      if a.get("id")}
        for xp in BOILERPLATE_IN_MAIN:
            for el in main.xpath("." + xp if xp.startswith("//") else xp):
                if el is not main and el.getparent() is not None:
                    el.drop_tree()
        for el in main.xpath(".//" + " | .//".join(DROP.split("|"))):
            if el.getparent() is not None:
                el.drop_tree()
        # lxml joins text with no separator: give <br> and block boundaries a space so words don't run together.
        for el in main.iter():
            if isinstance(el.tag, str) and (el.tag == "br" or el.tag in BLOCKY or el.tag in ("td", "th")):
                el.tail = " " + (el.tail or "")
                if el.tag != "br":
                    el.text = " " + (el.text or "")
        # <time datetime="2025-07-16T..">Jul 16</time>: write the year into the text, so a row read on its
        # own (or split from its table caption) still says which year it is.
        for t in main.iter("time"):
            dt = t.get("datetime") or ""
            if re.match(r"\d{4}-\d{2}-\d{2}", dt) and not re.search(r"\b(19|20)\d{2}\b", t.text_content()):
                if len(t):
                    t[-1].tail = (t[-1].tail or "") + f", {dt[:4]}"
                else:
                    t.text = (t.text or "").rstrip() + f", {dt[:4]}"
        tables = _tables(main)
        walker = _Walker(title, tab_labels)
        walker.walk(main)
        sections, headings = walker.sections, walker.headings
        # A heading with nothing under it is often the content itself (a notice, an announcement): keep its text.
        for i, s in enumerate(sections):
            if not s.blocks and len(s.heading_path) > 1 and (i == len(sections) - 1 or sections[i + 1].level <= s.level):
                s.blocks.append(s.heading_path[-1])
        # The contact box is stored once in `contact_block`; keep it out of the page's own sections. A page that
        # is itself titled "Contact Us" keeps its body: that is the real contact content.
        sections = [s for s in sections
                    if s.blocks and not (len(s.heading_path) > 1 and CONTACT_HEADING_RE.match(s.heading_path[-1]))]
        for s in sections:
            s.blocks = [b for b in s.blocks if not LOREM_RE.search(b) and not RECIPIENT_LINE_RE.match(b)]
        sections = [s for s in sections
                    if s.blocks and not any(PEOPLE_HEADING_RE.search(h) for h in s.heading_path[1:])]

    if title == "Ask Ecampus" and _template(platform, main, url) == "ecampus:ask-answer":
        # Every answer page has the h1 "Ask Ecampus"; the question is the first heading under it.
        question = next((s.heading_path[1] for s in sections if len(s.heading_path) > 1), None)
        title = f"Ask Ecampus: {question}" if question else title

    traf = trafilatura.extract(content, url=url, include_tables=True, favor_recall=True) or ""
    if main is None and traf:
        sections = [Section([title] if title else [], None, 1, [b for b in traf.split("\n") if b.strip()])]

    # Individuals' emails and direct phones never reach storage (privacy.py); office and role contacts stay.
    # Everything stored or derived (main_text, chunks, dates, links, forms) is built from these scrubbed values.
    for s in sections:
        s.blocks = [scrub_text(b)[0] for b in s.blocks]
    tables = [{**t, "header": [scrub_text(c)[0] for c in t["header"]],
               "rows": [[scrub_text(c)[0] for c in row] for row in t["rows"]]} for t in tables]
    contact_block = scrub_text(contact_block)[0]
    for l in links:
        l["text"] = scrub_text(l["text"])[0]
    for f in forms:
        f["purpose"] = scrub_text(f["purpose"])[0]

    main_text = "\n\n".join(
        (("#" * min(len(s.heading_path), 6) + " " + s.heading_path[-1] + "\n") if s.heading_path else "") + s.text
        for s in sections)

    return PageExtract(
        platform=platform, title=title, html_title=html_title, site_name=site_name,
        canonical_url=normalize_url(urljoin(url, canonical[0])) if canonical else None,
        language=(lang or "").split("-")[0].lower() or None, meta_robots=meta_robots, breadcrumb=breadcrumb,
        headings=headings, sections=sections, main_text=main_text, contact_block=contact_block, links=links,
        forms=forms, tables=tables, template=_template(platform, main, url), main_found=main is not None,
        trafilatura_text=traf, nav_menu=nav_menu)


def _contact_block(doc: HtmlElement) -> str | None:
    """The office's own contact box (address, main phone, hours link). Shared by every page of a site."""
    for h in doc.xpath("//h2|//h3|//h4"):
        heading = norm_ws(h.text_content())
        if not CONTACT_HEADING_RE.match(heading):
            continue
        block = h.getparent()
        for _ in range(2):  # the heading's own wrapper is sometimes empty (Ecampus footer)
            if len(norm_ws(block.text_content())) > len(heading) + 20 or block.getparent() is None:
                break
            block = block.getparent()
        lines = []
        for t in block.itertext():
            t = norm_ws(t)
            if CONTACT_FOOTER_STOP_RE.match(t):
                break
            if t and t != "|" and not CONTACT_HEADING_RE.match(t):
                lines.append(t)
        if lines:
            return "\n".join(lines)[:800]
    return None


def _forms(doc: HtmlElement, url: str) -> list[dict]:
    """On-page forms (never submitted) and links that lead to forms elsewhere."""
    out = []
    for f in doc.iter("form"):
        inputs = f.xpath(".//input[not(@type='hidden') and not(@type='submit') and not(@type='button')] | .//textarea")
        ident = " ".join(filter(None, [f.get("id"), f.get("class"), f.get("role"), f.get("action"), f.get("onsubmit"),
                                       f.get("aria-label")] + f.xpath(".//input/@id | .//input/@type | .//input/@placeholder"
                                                                       " | .//select/@id | .//label//text()"))).lower()
        single_query = len(inputs) == 1 and (inputs[0].get("name") or "") in ("q", "query", "search", "keys", "s", "")
        if "search" in ident or single_query:
            continue  # site or knowledge-base search box, not a form a student fills in
        kind = "filter" if "views-exposed-form" in ident else "web_form"
        legend = f.xpath(".//legend//text() | preceding::*[self::h1 or self::h2 or self::h3][1]//text()")
        out.append({"source": "on_page", "kind": kind, "url": normalize_url(urljoin(url, f.get("action") or url)),
                    "method": (f.get("method") or "get").lower(), "purpose": norm_ws(" ".join(legend))[:200],
                    "form_host": "drupal webform" if "webform" in ident else None,
                    "fields": len(f.xpath(".//input[not(@type='hidden')] | .//select | .//textarea"))})
    for a in doc.iter("a"):
        href = a.get("href") or ""
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        absolute = normalize_url(urljoin(url, href))
        host = urlsplit(absolute).hostname or ""
        text = norm_ws(a.text_content())
        ext = next((name for dom, name in EXTERNAL_FORM_HOSTS.items() if host == dom or host.endswith("." + dom)), None)
        if ext:
            out.append({"source": "link", "kind": "external_form", "url": absolute, "purpose": text[:200], "form_host": ext})
        elif urlsplit(absolute).path.lower().endswith(".pdf"):
            out.append({"source": "link", "kind": "pdf", "url": absolute, "purpose": text[:200], "form_host": None})
        elif re.search(r"/form/[\w-]+", urlsplit(absolute).path) and host.endswith("oregonstate.edu"):
            out.append({"source": "link", "kind": "web_form", "url": absolute, "purpose": text[:200],
                        "form_host": "drupal webform"})
    return out


def to_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)
