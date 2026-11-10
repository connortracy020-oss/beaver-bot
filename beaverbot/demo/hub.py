"""The signed-in demo's server side: sign-in, sessions, one store of sample-student state, and how it changes.

SAMPLE DATA ONLY. No real account, password or student record is involved anywhere in this file.

It is built the way a real version would have to work, so the demo can be shown to OSU as a design:

Sign-in     A redirect flow shaped like OpenID Connect (authorization code with PKCE). The browser is sent to a
            separate sign-in page, comes back with a one-time code, and swaps it (with its PKCE verifier) for a
            session. Beaver Bot never sees a password, because the demo has none: the sign-in page only offers
            locked, made-up accounts.
Sessions    Kept on the server. The browser holds only an unguessable id in an HttpOnly, Secure, SameSite cookie.
            A new id is issued at sign-in, sessions end after IDLE seconds without use or HARD seconds in all,
            and signing out deletes the session here.
Identity    Which student a request is about comes from the session and nothing else. Endpoints ignore any
            student id sent by the browser.
Sandbox     Every visitor gets their own copy of the sample students' state, so two people trying the demo never
            see each other's changes.
Changes     Nothing changes without three things: the session's CSRF token, a proposal the server itself wrote
            out (what will change, what won't, what is blocked and why), and that proposal's single-use
            confirmation token, which the student's own click sends back. The model can create proposals. It is
            never given a token, so it cannot confirm one. High-impact changes also need a fresh "it's really me"
            step (simulated here as an Approve button).
History     Every confirmed change is recorded with how to reverse it, so it can be undone where the real system
            would allow that.
"""
import base64
import datetime
import hashlib
import hmac
import re
import secrets
import threading
import time
from dataclasses import dataclass, field

IDLE, HARD = 20 * 60, 8 * 60 * 60               # seconds: no activity; in total
WARN = 2 * 60                                   # the browser warns this long before the idle limit
PROPOSAL_TTL, AUTH_TTL, VERIFY_TTL = 5 * 60, 5 * 60, 5 * 60
MAX_SESSIONS, MAX_HISTORY, MAX_PROPOSALS = 500, 60, 20
COOKIE = "bb_session"
SECURE_COOKIE = "__Host-bb_session"       # the prefix makes a browser refuse it unless Secure, Path=/ and no Domain
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class Refused(Exception):
    """A request the server won't carry out. `code` is shown to the browser; `status` is the HTTP status."""

    def __init__(self, code: str, status: int = 400, detail: str = ""):
        super().__init__(code)
        self.code, self.status, self.detail = code, status, detail


@dataclass
class Proposal:
    id: str
    token: str
    system: str
    change: dict
    plan: dict                  # what the student is shown: title, effects, unchanged, warnings, blocks, verify
    created: float
    by: str                     # "student" (a button) or "assistant" (a model tool call)
    used: bool = False


@dataclass
class Session:
    sid: str
    csrf: str
    slug: str
    created: float
    seen: float
    sandboxes: dict = field(default_factory=dict)       # slug -> that sample student's state, for this visitor only
    proposals: dict = field(default_factory=dict)
    history: list = field(default_factory=list)
    verified_until: float = 0.0
    clock_days: int = 0                                 # demo control: pretend it is this many days later
    counter: int = 0
    clock: object = time.time                           # the hub's clock, so tests can move time
    lock: object = field(default_factory=threading.RLock)      # one change at a time per session

    def state(self) -> dict:
        return self.sandboxes.setdefault(self.slug, {})

    def today(self) -> datetime.date:
        return datetime.date.today() + datetime.timedelta(days=self.clock_days)

    def public(self, now: float | None = None) -> dict:
        now = now or self.clock()
        return {"student": self.slug, "csrf": self.csrf, "idle_seconds": IDLE, "warn_seconds": WARN,
                "expires_in": int(min(self.seen + IDLE, self.created + HARD) - now),
                "verified": self.verified_until > now, "clock_days": self.clock_days}


class Hub:
    """All sessions and pending sign-ins for one running server. Everything is in memory and gone at restart."""

    def __init__(self, clock=time.time):
        self.clock = clock
        self.lock = threading.RLock()
        self.sessions: dict[str, Session] = {}
        self.pending: dict[str, dict] = {}              # sign-in requests waiting at the sign-in page
        self.codes: dict[str, dict] = {}                # one-time codes waiting to be swapped for a session
        self.hits: dict[str, list[float]] = {}          # rate limiting, by a short key

    # -- rate limiting ---------------------------------------------------------------------------------
    def allow(self, key: str, limit: int, per: float) -> bool:
        now = self.clock()
        with self.lock:
            recent = [t for t in self.hits.get(key, []) if now - t < per]
            if len(recent) >= limit:
                self.hits[key] = recent
                return False
            recent.append(now)
            self.hits[key] = recent
            if len(self.hits) > 5000:
                self.hits = {k: v for k, v in self.hits.items() if v and now - v[-1] < 3600}
            return True

    # -- sign-in: an authorization-code flow with PKCE ----------------------------------------------------
    def start_sign_in(self, challenge: str, state: str) -> str:
        """Step 1. The app asks to sign someone in. Returns the request id the sign-in page will show."""
        if not (isinstance(challenge, str) and 43 <= len(challenge) <= 128 and isinstance(state, str) and 8 <= len(state) <= 128
                and TOKEN_RE.match(challenge) and TOKEN_RE.match(state)):
            raise Refused("bad_request")
        now = self.clock()
        with self.lock:
            self.pending = {k: v for k, v in self.pending.items() if now - v["at"] < AUTH_TTL}
            if len(self.pending) > 2000:
                raise Refused("busy", 503)
            rid = secrets.token_urlsafe(24)
            self.pending[rid] = {"challenge": challenge, "state": state, "at": now}
            return rid

    def approve_sign_in(self, rid: str, slug: str, known: set[str]) -> dict:
        """Step 2. The sign-in page reports which locked demo account was chosen and approved. Returns the
        one-time code and the app's own `state` value to send the browser back with."""
        now = self.clock()
        with self.lock:
            req = self.pending.pop(rid, None)
            if not req or now - req["at"] > AUTH_TTL:
                raise Refused("sign_in_expired", 400)
            if slug not in known:
                raise Refused("unknown_account", 400)
            code = secrets.token_urlsafe(32)
            self.codes = {k: v for k, v in self.codes.items() if now - v["at"] < 60}
            self.codes[code] = {"slug": slug, "challenge": req["challenge"], "at": now}
            return {"code": code, "state": req["state"]}

    def finish_sign_in(self, code: str, verifier: str, old_sid: str | None = None) -> Session:
        """Step 3. The app swaps the code and its PKCE verifier for a session. The code works once, for a
        minute, and only with the verifier whose hash started the flow. Any earlier session is ended, so the
        session id always changes at sign-in."""
        now = self.clock()
        with self.lock:
            entry = self.codes.pop(code, None) if isinstance(code, str) else None
            if not entry or now - entry["at"] > 60 or not isinstance(verifier, str) or not TOKEN_RE.match(verifier):
                raise Refused("bad_code", 400)
            digest = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii", "ignore")).digest()).rstrip(b"=").decode()
            if not hmac.compare_digest(digest, entry["challenge"]):
                raise Refused("bad_code", 400)
            previous = self.sessions.pop(old_sid, None) if old_sid else None
            self._sweep(now)
            if len(self.sessions) >= MAX_SESSIONS:
                oldest = min(self.sessions.values(), key=lambda s: s.seen)
                del self.sessions[oldest.sid]
            session = Session(secrets.token_urlsafe(32), secrets.token_urlsafe(32), entry["slug"], now, now, clock=self.clock)
            if previous:                                # the same visitor signing in as another sample student keeps their sandbox
                session.sandboxes, session.clock_days = previous.sandboxes, previous.clock_days
            self.sessions[session.sid] = session
            return session

    # -- sessions --------------------------------------------------------------------------------------
    def _sweep(self, now: float) -> None:
        dead = [sid for sid, s in self.sessions.items() if now - s.seen > IDLE or now - s.created > HARD]
        for sid in dead:
            del self.sessions[sid]

    def get(self, sid: str | None, touch: bool = True) -> Session | None:
        """The live session for a cookie value, or None. Using a session keeps it alive (unless touch is False)."""
        if not sid:
            return None
        now = self.clock()
        with self.lock:
            s = self.sessions.get(sid)
            if not s:
                return None
            if now - s.seen > IDLE or now - s.created > HARD:
                del self.sessions[sid]
                return None
            if touch:
                s.seen = now
            return s

    def sign_out(self, sid: str | None) -> None:
        with self.lock:
            self.sessions.pop(sid or "", None)

    def check_csrf(self, session: Session, token) -> None:
        if not isinstance(token, str) or not hmac.compare_digest(token, session.csrf):
            raise Refused("csrf", 403)

    def verify(self, session: Session) -> float:
        """The fresh "it's really me" step. In the demo this is an Approve button; a real version would send the
        student back through OSU's sign-in for a new two-step check."""
        with self.lock:
            session.verified_until = self.clock() + VERIFY_TTL
            return session.verified_until

    # -- proposals: the only way anything changes -----------------------------------------------------------
    def propose(self, session: Session, system: str, change: dict, plan: dict, by: str = "student") -> dict:
        now = self.clock()
        with self.lock:
            session.proposals = {k: p for k, p in session.proposals.items() if not p.used and now - p.created < PROPOSAL_TTL}
            while len(session.proposals) >= MAX_PROPOSALS:
                del session.proposals[min(session.proposals, key=lambda k: session.proposals[k].created)]
            p = Proposal(secrets.token_urlsafe(9), secrets.token_urlsafe(24), system, change, plan, now, by)
            session.proposals[p.id] = p
            return self.describe(p)

    def describe(self, p: Proposal) -> dict:
        """What the browser gets. The token goes to the student's own review screen, over the session's own
        connection. It is never put in anything sent to the model."""
        return {"id": p.id, "token": p.token, "system": p.system, "by": p.by, "expires_in": int(p.created + PROPOSAL_TTL - self.clock()), **p.plan}

    def take(self, session: Session, pid, token) -> Proposal:
        """Claim a proposal for carrying out. Raises unless it exists, is unused, is fresh, and the token matches.
        A proposal is marked used here, before anything is changed, so it can never run twice."""
        now = self.clock()
        with self.lock:
            p = session.proposals.get(pid) if isinstance(pid, str) else None
            if not p or p.used:
                raise Refused("proposal_gone", 409)
            if now - p.created > PROPOSAL_TTL:
                del session.proposals[p.id]
                raise Refused("proposal_expired", 409)
            if not isinstance(token, str) or not hmac.compare_digest(token, p.token):
                raise Refused("bad_token", 403)
            if p.plan.get("blocks"):
                raise Refused("blocked", 409)
            p.used = True
            return p

    def record(self, session: Session, system: str, summary: str, undo: dict | None, details: list[str] | None = None) -> dict:
        with self.lock:
            session.counter += 1
            entry = {"id": session.counter, "at": datetime.datetime.now().strftime("%H:%M"), "system": system, "summary": summary,
                     "details": details or [], "undo": undo, "undone": False, "student": session.slug}
            session.history.append(entry)
            session.history = session.history[-MAX_HISTORY:]
            return entry

    def history(self, session: Session) -> list[dict]:
        return [{k: v for k, v in e.items() if k != "undo"} | {"can_undo": bool(e["undo"]) and not e["undone"]}
                for e in reversed(session.history) if e["student"] == session.slug]


def cookie_header(sid: str, secure: bool = True, clear: bool = False, https: bool = False) -> str:
    # Over https the name carries the __Host- prefix. Browsers refuse that prefix on plain http, even on localhost,
    # so the laptop demo uses the plain name with the same flags.
    parts = [f"{SECURE_COOKIE if secure and https else COOKIE}={'' if clear else sid}", "Path=/", "HttpOnly", "SameSite=Strict"]
    if secure:
        parts.append("Secure")
    if clear:
        parts.append("Max-Age=0")
    return "; ".join(parts)


def read_cookies(header: str | None) -> list[str]:
    """Every session cookie value in the header. A browser can hold one under each name (plain http and https),
    and an old, dead one must not hide the live one."""
    out = []
    for part in (header or "").split(";"):
        name, _, value = part.strip().partition("=")
        if name in (SECURE_COOKIE, COOKIE) and value:
            out.append(value)
    return out


def read_cookie(header: str | None) -> str | None:
    for part in (header or "").split(";"):
        name, _, value = part.strip().partition("=")
        if name in (SECURE_COOKIE, COOKIE) and value:
            return value
    return None
