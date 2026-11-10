"""Spanish support that works with no model.

Offline, Beaver Bot can't translate. What it can do honestly:
- notice a question written in Spanish;
- turn its campus words into English search words with a small glossary, so the search still finds OSU's pages
  (which are in English);
- answer with Spanish wording around quotes that stay in English, exactly as OSU's page has them.

When a model is connected it receives the student's original Spanish question and is asked to answer in Spanish.
"""
import re
import unicodedata

SPANISH_HINTS = re.compile(
    r"[¿¡ñ]|\b(c[oó]mo|d[oó]nde|cu[aá]ndo|cu[aá]nto|cu[aá]l|qu[eé]|qui[eé]n|puedo|necesito|quiero|tengo|hay|para|una?|"
    r"los|las|del|mi|mis|es|est[aá]|son|clases?|matr[ií]cula|ayuda|pagar|pago|fecha|beca|tutor[ií]a|estudiantes?)\b",
    re.I)

# Longest phrases first. Left side is matched without accents, in lower case.
GLOSSARY = [
    ("fecha limite para agregar o dejar", "add/drop deadline"),
    ("fecha limite para dar de baja", "last day to drop"),
    ("fecha limite para agregar", "last day to add"),
    ("fecha limite", "deadline"), ("ultimo dia", "last day"),
    ("plan de pagos", "payment plan"), ("plan de pago", "payment plan"),
    ("dar de baja una clase", "drop a class"), ("darme de baja", "drop a class"), ("dar de baja", "drop"),
    ("dejar una clase", "drop a class"), ("retirarme de una clase", "withdraw from a class"),
    ("retirarme", "withdraw"), ("retirar", "withdraw"),
    ("agregar una clase", "add a class"), ("anadir una clase", "add a class"), ("agregar", "add"),
    ("inscribirme en clases", "register for classes"), ("inscribirme", "register"), ("inscripcion", "registration"),
    ("matricularme", "register"), ("registrarme", "register"),
    ("ayuda financiera", "financial aid"), ("asistencia financiera", "financial aid"),
    ("colegiatura", "tuition"), ("matricula", "tuition"), ("cuotas", "fees"),
    ("becas", "scholarships"), ("beca", "scholarship"),
    ("factura", "bill"), ("cuenta", "bill"), ("pagar", "pay"), ("pago", "payment"), ("reembolso", "refund"),
    ("tutorias", "tutoring"), ("tutoria", "tutoring"), ("tutor", "tutoring"),
    ("consejero academico", "academic advisor"), ("asesor academico", "academic advisor"),
    ("consejero", "counselor"), ("consejeria", "counseling"), ("asesor", "advisor"), ("asesoria", "advising"),
    ("salud mental", "mental health counseling"), ("centro de salud", "student health services"), ("salud", "health"),
    ("seguro medico", "health insurance"), ("vacunas", "immunizations"),
    ("vivienda", "housing"), ("residencia", "residence hall"), ("dormitorio", "residence hall"),
    ("plan de comidas", "meal plan"), ("comedor", "dining"), ("comida", "food"), ("despensa", "food pantry"),
    ("estacionamiento", "parking"), ("permiso de estacionamiento", "parking permit"), ("permiso", "permit"),
    ("autobus", "bus"), ("bicicleta", "bike"),
    ("biblioteca", "library"), ("centro de escritura", "writing center"), ("ensayo", "essay"),
    ("curriculum", "resume"), ("hoja de vida", "resume"), ("empleo", "job"), ("trabajo", "job"),
    ("pasantia", "internship"), ("practicas", "internship"),
    ("expediente academico", "transcript"), ("certificado de notas", "transcript"), ("calificaciones", "grades"),
    ("calificacion", "grade"), ("notas", "grades"), ("promedio", "gpa"),
    ("examenes finales", "finals week"), ("examen final", "final exam"), ("examenes", "exams"), ("examen", "exam"),
    ("requisitos previos", "prerequisites"), ("prerrequisitos", "prerequisites"), ("requisitos", "requirements"),
    ("especialidad", "major"), ("carrera", "major"), ("titulo", "degree"), ("creditos", "credits"),
    ("graduarme", "graduate"), ("graduacion", "graduation"),
    ("transferir creditos", "transfer credit"), ("transferencia", "transfer"), ("admision", "admission"),
    ("solicitud", "application"), ("solicitar", "apply"), ("estudiantes internacionales", "international students"),
    ("visa", "visa"), ("adaptaciones", "accommodations"), ("discapacidad", "disability"),
    ("contrasena", "password"), ("correo electronico", "email"), ("correo", "email"), ("wifi", "wifi"),
    ("en linea", "online"), ("a distancia", "online ecampus"),
    ("trimestre de invierno", "winter term"), ("trimestre de primavera", "spring term"),
    ("trimestre de otono", "fall term"), ("trimestre de verano", "summer term"), ("trimestre", "term"),
    ("invierno", "winter"), ("primavera", "spring"), ("otono", "fall"), ("verano", "summer"),
    ("empiezan las clases", "classes begin"), ("comienzan las clases", "classes begin"),
    ("empieza", "start"), ("comienza", "start"), ("termina", "end"),
    ("clases", "classes"), ("clase", "class"), ("curso", "course"), ("cursos", "courses"),
    ("retencion", "hold"), ("bloqueo", "hold"), ("conducta", "conduct"), ("integridad academica", "academic integrity"),
    ("privacidad", "privacy"), ("veteranos", "veterans"), ("emergencia", "emergency"),
    ("como configuro", "how do i set up"), ("como puedo", "how do i"), ("como", "how do i"),
    ("donde puedo", "where can i"), ("donde", "where"), ("cuando es", "when is"), ("cuando", "when"),
    ("cuanto cuesta", "how much does it cost"), ("cuanto", "how much"), ("que es", "what is"),
    ("quien", "who"), ("cual es", "what is"), ("cuales son", "what are"),
    ("obtener", "get"), ("conseguir", "get"), ("recibir", "get"), ("encuentro", "find"), ("encontrar", "find"),
    ("cambiar", "change"), ("restablecer", "reset"), ("pedir", "request"), ("hablar con", "talk to"),
    ("necesito", "i need"), ("quiero", "i want"), ("puedo", "can i"), ("tengo que", "do i have to"),
    ("mi saldo", "my balance"), ("saldo", "balance"), ("cuanto debo", "how much do i owe"),
    ("suicidarme", "suicide"), ("suicidio", "suicide"), ("matarme", "kill myself"), ("quiero morir", "want to die"),
    ("hacerme dano", "hurt myself"), ("lastimarme", "hurt myself"), ("no estoy a salvo", "not safe"),
]
_SMALL = {"el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "al", "a", "en", "para", "por", "con",
          "mi", "mis", "me", "se", "es", "son", "y", "o", "que", "lo", "le", "su", "sus", "hay", "esta", "estan"}


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def looks_spanish(text: str) -> bool:
    """Two Spanish signals, so one shared word ("visa", "para") doesn't flip an English question."""
    return len(SPANISH_HINTS.findall(text)) >= 2


# A whole message that is one Spanish word or phrase ("hola", "gracias"), which the two-signal rule above misses.
SHORT_SPANISH = re.compile(
    r"^[\s¡¿]*(hola|buenas|buenos d[ií]as|buenas (tardes|noches)|(muchas |mil )?gracias|de nada|por favor|adi[oó]s|"
    r"hasta luego|nos vemos|s[ií]|claro|vale|perd[oó]n|disculpa|ayuda|qu[eé] tal|no entiendo|no s[eé]|bueno|oye|listo)"
    r"\b[\s!.,?]*$", re.I)
ENGLISH_HINTS = re.compile(r"\b(the|is|are|what|how|when|where|why|who|i|my|me|you|yes|yeah|thanks|thank|please|"
                           r"english|can|do|does|that|this)\b", re.I)


def is_spanish(text: str, previous: str | None = None) -> bool:
    """Spanish by its own words, or a short reply ("ok", "y el otro?") in a conversation that is already in Spanish."""
    if looks_spanish(text) or SHORT_SPANISH.search(text):
        return True
    return (bool(previous) and (looks_spanish(previous) or bool(SHORT_SPANISH.search(previous)))
            and len(text.split()) <= 4 and not ENGLISH_HINTS.search(text))


def to_english(text: str) -> str:
    """Campus words in English, for search and for the safety checks. Unknown words are kept as they are."""
    low = strip_accents(text.lower())
    low = re.sub(r"[¿¡]", " ", low)
    for es, en in GLOSSARY:
        low = re.sub(rf"\b{re.escape(es)}\b", f" {en} ", low)
    words = [w for w in low.split() if w.strip("?,.;:!") not in _SMALL]
    return " ".join(words).strip()


# Fixed wording the pipeline produces, in Spanish. Keys are assistant.answer reasons.
MESSAGES = {
    "refusal": "No encontré eso en las páginas públicas de OSU y prefiero no adivinar. Esta oficina puede ayudarte:",
    "own_records": "Eso está en tu expediente personal, que este asistente no puede ver: solo lee las páginas "
                   "públicas de OSU y nunca te pedirá tu contraseña.",
    "individual_contact": "No comparto datos de contacto de personas. El programa de tu curso o su página en Canvas "
                          "tiene los datos de tu instructor, y la oficina del departamento también puede ayudarte.",
    "live_data": "Los cupos cambian minuto a minuto, así que no los tengo. Revisa el horario de clases en vivo.",
    "academic_integrity": "No puedo hacer por ti un trabajo con nota; eso rompería las reglas de integridad "
                          "académica de OSU. El Writing Center y el Academic Success Center te ayudan a hacerlo "
                          "por tu cuenta.",
    "crisis": "Si tú u otra persona está en peligro inmediato, llama al 911. No tienes que pasar por esto a solas; "
              "abajo están los recursos de crisis de OSU (en inglés).",
}
