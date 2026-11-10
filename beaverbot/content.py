"""What the pages other than the chat show: topics, deadlines, offices, and the questions the site suggests.

Everything here is read from the stored public pages or from assistant/categories.py. Nothing is written.
"""
import datetime
import re
import sqlite3
import threading

from assistant.categories import BY_ID, CATEGORIES

# The home page's popular questions. The team's top three come first.
POPULAR = [
    ("When is the add/drop deadline?", "¿Cuándo es la fecha límite para agregar o dejar una clase?"),
    ("How do I set up a payment plan?", "¿Cómo configuro un plan de pago?"),
    ("Where do I get tutoring?", "¿Dónde consigo tutoría?"),
    ("How do I drop a class?", "¿Cómo dejo una clase?"),
    ("How do I see a counselor?", "¿Cómo hablo con un consejero?"),
    ("How do I get a parking permit?", "¿Cómo consigo un permiso de estacionamiento?"),
]

# Questions shown per topic and offered as "ask next". Each was checked against the stored pages.
BANK: dict[str, list[tuple[str, str]]] = {
    "admissions": [
        ("Will my community college classes transfer to OSU?", "¿Se transfieren mis clases del colegio comunitario a OSU?"),
        ("What is the Degree Partnership Program?", "¿Qué es el Degree Partnership Program?"),
        ("How do I apply to the Honors College?", "¿Cómo solicito entrar al Honors College?"),
    ],
    "registration": [
        ("How do I drop a class?", "¿Cómo dejo una clase?"),
        ("How do I change a class to S/U grading?", "¿Cómo cambio una clase a calificación S/U?"),
        ("How do I order a transcript?", "¿Cómo pido mi expediente académico?"),
        ("What is priority registration?", "¿Qué es la inscripción prioritaria?"),
    ],
    "dates": [
        ("When is the add/drop deadline?", "¿Cuándo es la fecha límite para agregar o dejar una clase?"),
        ("When does winter term start?", "¿Cuándo empieza el trimestre de invierno?"),
        ("When is the last day to withdraw from a class?", "¿Cuándo es el último día para retirarme de una clase?"),
        ("When is finals week?", "¿Cuándo es la semana de exámenes finales?"),
    ],
    "courses": [
        ("What are the prerequisites for CS 261?", "¿Cuáles son los requisitos previos de CS 261?"),
        ("What is Core Education?", "¿Qué es Core Education?"),
        ("What is the Seeking Solutions requirement?", "¿Qué es el requisito Seeking Solutions?"),
    ],
    "paying": [
        ("How do I set up a payment plan?", "¿Cómo configuro un plan de pago?"),
        ("What happens if I pay my bill late?", "¿Qué pasa si pago mi factura tarde?"),
        ("How do I apply for scholarships?", "¿Cómo solicito becas?"),
        ("How do I apply for financial aid?", "¿Cómo solicito ayuda financiera?"),
    ],
    "living": [
        ("How do I get a parking permit?", "¿Cómo consigo un permiso de estacionamiento?"),
        ("How do I apply for housing?", "¿Cómo solicito vivienda?"),
        ("How does the Beaver Bus work?", "¿Cómo funciona el Beaver Bus?"),
    ],
    "health": [
        ("How do I see a counselor?", "¿Cómo hablo con un consejero?"),
        ("What does Student Health Services offer?", "¿Qué ofrece Student Health Services?"),
        ("Do I need health insurance?", "¿Necesito seguro médico?"),
    ],
    "accessibility": [
        ("How do I request accommodations?", "¿Cómo pido adaptaciones?"),
        ("How do testing accommodations work?", "¿Cómo funcionan las adaptaciones para exámenes?"),
    ],
    "support": [
        ("Where do I get tutoring?", "¿Dónde consigo tutoría?"),
        ("How do I get help with writing a paper?", "¿Dónde me ayudan a escribir un ensayo?"),
        ("Where can I get free food on campus?", "¿Dónde consigo comida gratis en el campus?"),
        ("How do I find an internship?", "¿Cómo encuentro una pasantía?"),
    ],
    "rights": [
        ("What is FERPA?", "¿Qué es FERPA?"),
        ("What counts as academic misconduct?", "¿Qué se considera mala conducta académica?"),
    ],
    "tech": [
        ("How do I connect to eduroam?", "¿Cómo me conecto a eduroam?"),
    ],
    "ecampus": [
        ("Is tutoring available for online students?", "¿Hay tutoría para estudiantes en línea?"),
        ("How do Ecampus exams work?", "¿Cómo funcionan los exámenes de Ecampus?"),
    ],
}

NAMES_ES = {
    "admissions": ("Entrar a OSU: admisión, transferencia e internacional", "solicitar admisión, crédito de transferencia, visas y estatus migratorio"),
    "registration": ("Inscripción y clases", "inscribirse, agregar o dejar clases, retenciones, calificaciones, expedientes"),
    "dates": ("Fechas y plazos", "el calendario académico"),
    "courses": ("Cursos y requisitos del título", "programas y cursos del catálogo, Core Education, reglamentos académicos"),
    "paying": ("Pagar la universidad", "matrícula y cuotas, facturación y planes de pago, ayuda financiera, becas"),
    "living": ("Vivienda, comida y vida en el campus", "vivienda, comedores, estacionamiento, transporte, recreación, clubes"),
    "health": ("Salud, consejería y crisis", "Student Health Services, consejería (CAPS), recursos de crisis 24/7"),
    "accessibility": ("Accesibilidad", "Disability Access Services: adaptaciones y exámenes"),
    "support": ("Apoyo, éxito y carreras", "asesoría, tutoría, Writing Center, biblioteca, necesidades básicas, carreras"),
    "rights": ("Derechos, conducta y políticas", "código de conducta, integridad académica, privacidad (FERPA), reportes"),
    "tech": ("Ayuda con tecnología", "cuentas y contraseñas, software, wifi, ayuda técnica"),
    "ecampus": ("Estudiantes en línea (Ecampus)", "todo lo anterior para estudiantes en línea"),
}
ICONS = {"admissions": "door", "registration": "list", "dates": "calendar", "courses": "cap", "paying": "wallet",
         "living": "home", "health": "heart", "accessibility": "access", "support": "hands", "rights": "scale",
         "tech": "laptop", "ecampus": "globe"}

_ES_TO_EN = {es.lower(): en for pairs in [POPULAR, *BANK.values()] for en, es in pairs}
_lock = threading.Lock()
_cache: dict = {}


def english_for(question: str) -> str | None:
    """The English twin of one of the site's own Spanish questions, so search is exact for those."""
    return _ES_TO_EN.get(" ".join(question.split()).lower())


def all_questions(lang: str = "en") -> list[str]:
    i = 1 if lang == "es" else 0
    return list(dict.fromkeys(pair[i] for pairs in [POPULAR, *BANK.values()] for pair in pairs))


def followups(category: str | None, question: str, lang: str = "en", n: int = 3) -> list[str]:
    i = 1 if lang == "es" else 0
    asked = {" ".join(question.split()).lower().rstrip("?"), (english_for(question) or "").lower().rstrip("?")}
    pool = [p for p in BANK.get(category or "", [])] + [p for p in POPULAR]
    out = []
    for pair in pool:
        if pair[0].lower().rstrip("?") in asked or pair[1].lower().rstrip("?") in asked or pair[i] in out:
            continue
        out.append(pair[i])
        if len(out) == n:
            break
    return out


def counts(con: sqlite3.Connection) -> dict:
    """How much is in the library, for the "searching N pages" line and the About page."""
    with _lock:
        if "counts" in _cache:
            return _cache["counts"]
    pages, sites = con.execute("SELECT COUNT(*), COUNT(DISTINCT domain) FROM pages WHERE gone_at IS NULL").fetchone()
    pdfs = con.execute("SELECT COUNT(*) FROM documents WHERE kind LIKE '%pdf%' AND gone_at IS NULL AND text IS NOT NULL").fetchone()[0]
    newest = con.execute("SELECT MAX(retrieved_at) FROM pages").fetchone()[0] or ""
    out = {"pages": pages, "sites": sites, "pdfs": pdfs, "checked": newest[:10]}
    with _lock:
        _cache["counts"] = out
    return out


def topics(con: sqlite3.Connection) -> list[dict]:
    """The 12 categories, each with its questions, the office to ask, and the OSU pages other sites link to most."""
    with _lock:
        if "topics" in _cache:
            return _cache["topics"]
    out = []
    for c in CATEGORIES:
        rows = con.execute("""
            SELECT p.url, p.title, p.owning_office, p.retrieved_at, COALESCE(a.sites, 0) AS sites
            FROM page_categories pc JOIN pages p ON p.id = pc.page_id
            LEFT JOIN page_authority a ON a.url = p.url
            WHERE pc.category = ? AND pc.is_primary = 1 AND p.archived = 0 AND p.gone_at IS NULL
              AND p.duplicate_of IS NULL AND p.url NOT LIKE '%?page=%' AND p.title IS NOT NULL
            ORDER BY sites DESC, LENGTH(p.url) LIMIT 6""", (c.id,)).fetchall()
        total = con.execute("SELECT COUNT(*) FROM page_categories WHERE category = ? AND is_primary = 1", (c.id,)).fetchone()[0]
        out.append({
            "id": c.id, "icon": ICONS.get(c.id, "list"),
            "name": {"en": c.name, "es": NAMES_ES[c.id][0]},
            "covers": {"en": c.covers, "es": NAMES_ES[c.id][1]},
            "questions": {"en": [q for q, _ in BANK.get(c.id, [])], "es": [q for _, q in BANK.get(c.id, [])]},
            "contacts": [{"name": n, "url": u} for n, u in c.contacts],
            "pages": [{"title": " ".join(r["title"].split()), "url": r["url"], "office": r["owning_office"],
                       "checked": (r["retrieved_at"] or "")[:10]} for r in rows],
            "count": total,
        })
    with _lock:
        _cache["topics"] = out
    return out


def offices() -> list[dict]:
    """Every office the assistant sends students to, grouped by topic. From assistant/categories.py."""
    out = []
    for c in CATEGORIES:
        for name, url in c.contacts:
            phone = re.search(r"\b\d{3}-\d{3}-\d{4}\b", name)
            out.append({"name": re.sub(r"\s*\((24/7[^)]*|billing|reporting|Office of Admissions|Academic Catalog)\)", "", name).strip(),
                        "note": (re.search(r"\(([^)]*)\)", name) or [None, None])[1],
                        "phone": phone.group(0) if phone else None, "url": url, "topic": c.id,
                        "topic_name": {"en": c.name, "es": NAMES_ES[c.id][0]}, "icon": ICONS.get(c.id, "list")})
    return out


# ---- deadlines -----------------------------------------------------------------------------------
KINDS = [  # (kind, words in the calendar row's name)
    ("add_drop", r"Last Day to (Add|Drop)"), ("withdraw", r"Withdraw"), ("grading", r"Grading Basis|Audit"),
    ("registration", r"Reg\.|Registration"), ("start", r"Classes Begin|Term Dates|Weeks Dates"),
    ("finals", r"Finals"), ("end", r"Classes End|Term Ends"), ("grades", r"Grades"),
    ("break", r"Break|Holiday|Day( Observed)?$|Juneteenth|Commencement"),
]
SUBSESSION_RE = re.compile(r"\b(5A|5B|Super Term|Extension|Session|Week [0-9]|\d+ Weeks?)\b")


def _iso(d: str) -> datetime.date | None:
    try:
        return datetime.date.fromisoformat(d)
    except ValueError:
        return None


def deadlines(con: sqlite3.Connection, today: datetime.date | None = None) -> dict:
    """Dates from the Registrar's current academic calendar: the only source this project treats as authoritative."""
    today = today or datetime.date.today()
    rows = con.execute("""SELECT date_iso, date_text, context, term, source_url FROM deadlines
                          WHERE date_iso IS NOT NULL ORDER BY date_iso""").fetchall()
    seen, items = set(), []
    for r in rows:
        start_text, _, end_text = r["date_iso"].partition("/")
        start, end = _iso(start_text), _iso(end_text) if end_text else None
        parts = [p.strip() for p in r["context"].split(" | ")]
        name = parts[-1] if len(parts) >= 3 else None
        if not start or not name or (start, name) in seen:
            continue
        if (end or start) < today - datetime.timedelta(days=14):
            continue
        seen.add((start, name))
        kind = next((k for k, rx in KINDS if re.search(rx, name)), "other")
        items.append({"date": start.isoformat(), "end": end.isoformat() if end else None, "name": name,
                      "term": r["term"], "kind": kind, "session": bool(SUBSESSION_RE.search(name)),
                      "past": (end or start) < today, "days": (start - today).days, "url": r["source_url"]})
    checked = con.execute("SELECT MAX(retrieved_at) FROM pages WHERE url LIKE 'https://registrar.oregonstate.edu/osu-academic-calendar%'").fetchone()[0]
    terms_seen = list(dict.fromkeys(i["term"] for i in items if i["term"]))
    return {"items": items, "terms": terms_seen, "checked": (checked or "")[:10],
            "source": {"title": "Academic Calendar", "office": "Office of the Registrar",
                       "url": "https://registrar.oregonstate.edu/osu-academic-calendar"},
            "today": today.isoformat()}


def category_name(cat_id: str | None, lang: str = "en") -> str | None:
    if cat_id not in BY_ID:
        return None
    return NAMES_ES[cat_id][0] if lang == "es" else BY_ID[cat_id].name
