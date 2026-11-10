"""The Beaver Bot web server: a small standard-library HTTP server. No framework, no new dependencies.

- Serves the front end from beaverbot/static/ (plain HTML, CSS and JavaScript modules; no build step, no CDN).
- Answers questions over /api/ask as a stream of server-sent events.
- Serves the topic, deadline and office pages from the stored public pages.
- Serves the demo layer (made-up students, sample classes) from data/demo.db.

Privacy rules this file enforces:
- The databases are opened read-only and never sent to the browser. Only answers, short quotes and links leave.
- Questions arrive in the request body, never in a URL, and the access log prints no address and no query string.
- Nothing is saved except a rating or a "report a wrong answer" the student chose to send (feedback.py).
"""
import datetime
import json
import mimetypes
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from assistant import answer as A
from assistant.providers import PaidCallNotApproved

from . import answers, budget, config, content, feedback, talk
from .demo import actions, audit, draft, es, finder, hub as H, intents, store, systems

PAGES = {"/", "/topics", "/deadlines", "/offices", "/saved", "/about", "/auth/callback"}
# What a model tool may ask for, as a change the student must still review and confirm (demo/systems.py).
TOOL_CHANGES = {"plan_add": lambda c: ("registration", {"type": "add", "term": store.REG_TERM, "crn": c["crn"], "linked": c.get("linked")}),
                "plan_add_many": lambda c: ("registration", {"type": "add_many", "term": store.REG_TERM, "items": c.get("items", [])}),
                "plan_drop": lambda c: ("registration", {"type": "remove", "term": store.REG_TERM, "crn": c["crn"]}),
                "book": lambda c: ("advising", {"type": "book", "slot": c["slot"]}),
                "cancel_appointment": lambda c: ("advising", {"type": "cancel"})}
MAX_BODY = 32_000
MAX_STREAMS = 24
_streams = threading.Semaphore(MAX_STREAMS)
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                               "script-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; "
                               "frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("application/manifest+json", ".webmanifest")


def ctype_of(path) -> str:
    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if ctype.startswith("text/") or ctype in ("application/json", "image/svg+xml", "application/manifest+json"):
        ctype += "; charset=utf-8"
    return ctype


def library_ready() -> bool:
    return config.OSU_DB.exists()


def site_config() -> dict:
    provider = config.provider_name()
    out = {
        "name": "Beaver Bot", "tagline": "Find the right campus page in seconds.",
        "provider": provider, "offline": provider in config.OFFLINE_PROVIDERS,
        "library": None, "demo": store.available(),
        "popular": {"en": [q for q, _ in content.POPULAR], "es": [q for _, q in content.POPULAR]},
        "questions": {"en": content.all_questions("en"), "es": content.all_questions("es")},
    }
    if library_ready():
        out["library"] = content.counts(answers.connect())
    return out


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "BeaverBot"
    sys_version = ""

    # -- plumbing ----------------------------------------------------------------------------------
    def finish(self):
        """Each connection gets its own thread, and each thread its own database connections. Close them with it."""
        try:
            super().finish()
        finally:
            answers.release()
            store.release()

    def log_message(self, fmt, *args):
        if getattr(self.server, "quiet", False):
            return
        # Method, path without its query string, and status. No address, no query, no body.
        path = urlsplit(self.path).path
        status = args[1] if len(args) > 1 else ""
        sys.stderr.write(f"{time.strftime('%H:%M:%S')} {self.command} {path} {status}\n")

    def _headers(self, status: int, ctype: str, length: int | None, extra: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        if length is not None:
            self.send_header("Content-Length", str(length))
        for k, v in {**SECURITY_HEADERS, **(extra or {})}.items():
            self.send_header(k, v)
        if self.is_https():
            self.send_header("Strict-Transport-Security", "max-age=31536000")
        self.end_headers()

    def host_ok(self) -> bool:
        """Only answer to the names this server is meant to be reached by (config.allowed_hosts). This stops another
        site from pointing its own name at this computer to get around the same-origin checks."""
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
        return host in config.allowed_hosts()

    def send_hub(self, data):
        """A signed-in demo response, in Spanish when the page is (the X-Lang header). Stored data stays English."""
        self.send_json(es.localize(data) if self.headers.get("X-Lang") == "es" else data)

    def send_json(self, data, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self._headers(status, "application/json; charset=utf-8", len(body), {"Cache-Control": "no-store"})
        self.wfile.write(body)

    def read_json(self) -> dict | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None
        if length <= 0 or length > MAX_BODY:
            return None
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def send_file(self, path, status: int = 200):
        try:
            stat = path.stat()
            body = path.read_bytes()
        except OSError:
            return self.send_json({"error": "not found"}, 404)
        etag = f'"{int(stat.st_mtime)}-{stat.st_size}"'
        if self.headers.get("If-None-Match") == etag and status == 200:
            return self._headers(304, ctype_of(path), 0, {"ETag": etag, "Cache-Control": "no-cache"})
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/json", "image/svg+xml", "application/manifest+json"):
            ctype += "; charset=utf-8"
        self._headers(status, ctype, len(body), {"ETag": etag, "Cache-Control": "no-cache"})
        if self.command != "HEAD":
            self.wfile.write(body)

    # -- GET ---------------------------------------------------------------------------------------
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        url = urlsplit(self.path)
        path, query = url.path, {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            if path == "/healthz":                      # the host's "is it up" check; it says nothing else
                return self.send_json({"ok": True})
            if not self.host_ok():                      # a request that reached us under some other site's name
                return self.send_json({"error": "host"}, 403)
            if path.startswith("/static/"):
                target = (config.STATIC / path[len("/static/"):]).resolve()
                if config.STATIC.resolve() not in target.parents or not target.is_file():
                    return self.send_json({"error": "not found"}, 404)
                return self.send_file(target)
            if path in ("/favicon.ico", "/favicon.svg"):
                return self.send_file(config.STATIC / "icon.svg")
            if path == "/api/config":
                return self.send_json(site_config())
            if path in ("/api/topics", "/api/deadlines", "/api/offices"):
                if path == "/api/offices":
                    return self.send_json({"offices": content.offices()})
                if not library_ready():
                    return self.send_json({"error": "library"}, 503)
                con = answers.connect()
                if path == "/api/topics":
                    return self.send_json({"topics": content.topics(con), "library": content.counts(con)})
                return self.send_json(content.deadlines(con))
            if path == "/auth/start":
                return self.auth_start(query)
            if path == "/signin":
                return self.send_file(config.STATIC / "signin.html")
            if path == "/api/session":
                return self.session_get(query)
            if path == "/api/idp/accounts":
                return self.send_json({"accounts": store.students(store.connect()) if store.available() else []})
            if path.startswith("/api/hub/"):
                return self.hub_get(path[len("/api/hub/"):], query)
            if path.startswith("/api/demo/"):
                return self.demo_get(path[len("/api/demo/"):], query)
            if path.startswith("/api/"):
                return self.send_json({"error": "not found"}, 404)
            if path in PAGES:
                return self.send_file(config.STATIC / "index.html")
            return self.send_file(config.STATIC / "index.html", 404)
        except (BrokenPipeError, ConnectionError):
            pass
        except H.Refused as e:
            self.send_json({"error": e.code, "detail": e.detail}, e.status)
        except Exception:
            traceback.print_exc()
            self.send_json({"error": "server"}, 500)

    def demo_get(self, name: str, query: dict):
        if not store.available():
            return self.send_json({"error": "demo"}, 503)
        con = store.connect()
        if name == "students":
            return self.send_json({"students": store.students(con)})
        if name == "courses":
            return self.send_json({"courses": store.search_courses(con, query.get("q", "")[:60])})
        if name == "course":
            found = finder.details(con, query.get("code", "")[:12])
            return self.send_json(found or {"error": "not found"}, 200 if found else 404)
        if name == "programs":
            return self.send_json({"programs": audit.programs(con, query.get("q", "")[:60], limit=14)})
        if name == "forms":
            return self.send_json({"forms": store.forms(con, query.get("q", "")[:80])})
        if name == "resources":
            return self.send_json({"resources": store.resources(con, query.get("q", "")[:80], query.get("category", "")[:30])})
        return self.send_json({"error": "not found"}, 404)

    # -- POST --------------------------------------------------------------------------------------
    def do_POST(self):
        path = urlsplit(self.path).path
        try:
            origin = self.headers.get("Origin")
            if not self.host_ok():
                self.close_connection = True
                return self.send_json({"error": "host"}, 403)
            if origin and urlsplit(origin).netloc != self.headers.get("Host"):      # a form or script on another site
                self.close_connection = True                # its body was never read, so this connection isn't reused
                return self.send_json({"error": "origin"}, 403)
            body = self.read_json()
            if body is None:
                self.close_connection = True
                return self.send_json({"error": "bad request"}, 400)
            if path == "/api/ask":
                return self.ask(body)
            if path == "/api/feedback":
                return self.send_json({"ok": feedback.rate(body)})
            if path == "/api/report":
                return self.send_json({"ok": feedback.report(body)})
            if path.startswith(("/api/session/", "/api/hub/", "/api/idp/")):
                return self.hub_post(path, body)
            self.send_json({"error": "not found"}, 404)
        except (BrokenPipeError, ConnectionError):
            pass
        except H.Refused as e:
            self.send_json({"error": e.code, "detail": es.say(e.detail) if self.headers.get("X-Lang") == "es" else e.detail}, e.status)
        except Exception:
            traceback.print_exc()
            try:
                self.send_json({"error": "server"}, 500)
            except Exception:
                pass

    # -- the signed-in demo: sessions and changes (beaverbot/demo/hub.py, systems.py) --------------------
    @property
    def hub(self) -> H.Hub:
        return self.server.hub

    def client_key(self) -> str:
        """Who to count a request against for rate limiting. Kept in memory only, never logged.

        Behind a host's proxy every request arrives from the proxy, so the visitor's address is read from
        X-Forwarded-For, but only when the owner has said how many proxies there are (config.proxy_hops)."""
        hops = config.proxy_hops()
        if hops:
            chain = [p.strip() for p in (self.headers.get("X-Forwarded-For") or "").split(",") if p.strip()]
            if not getattr(self.server, "chain_noted", True):       # once, a count only: helps the owner set the number right
                self.server.chain_noted = True
                sys.stderr.write(f"[proxy] X-Forwarded-For carries {len(chain)} address(es); BEAVERBOT_PROXY_HOPS is {hops}\n")
            if len(chain) >= hops:
                return chain[-hops][:64]
        return self.client_address[0]

    def is_https(self) -> bool:
        """The visitor reached the site over https. Only a proxy the owner told us about is believed."""
        return bool(config.proxy_hops()) and self.headers.get("X-Forwarded-Proto") == "https"

    def session(self, touch: bool = True) -> H.Session | None:
        for value in H.read_cookies(self.headers.get("Cookie")):
            found = self.hub.get(value, touch)
            if found:
                return found
        return None

    def need_session(self, body: dict | None = None) -> H.Session:
        """The signed-in session, or a refusal. With a body, the request must also carry the session's CSRF token."""
        session = self.session()
        if session is None:
            raise H.Refused("signed_out", 401)
        if body is not None:
            self.hub.check_csrf(session, self.headers.get("X-CSRF-Token") or body.get("csrf"))
        return session

    def auth_start(self, query: dict):
        """The app sends the browser here to begin signing in. We answer with a redirect to the sign-in page, the
        way an identity provider would be reached. No student is named yet."""
        if not store.available():
            return self.send_json({"error": "demo"}, 503)
        if not self.hub.allow("signin-start:" + self.client_key(), 20, 60):
            return self.send_json({"error": "slow_down"}, 429)
        rid = self.hub.start_sign_in(query.get("challenge", ""), query.get("state", ""))
        self._headers(302, "text/plain; charset=utf-8", 0, {"Location": f"/signin?request={rid}", "Cache-Control": "no-store"})

    def session_get(self, query: dict):
        session = self.session(touch="peek" not in query)       # checking the countdown doesn't keep a session alive
        if session is None:
            return self.send_json({"signed_in": False})
        ctx = systems.context(store.connect(), session)
        self.send_json({"signed_in": True, **session.public(), "profile": store.profile(ctx.con, ctx.row)})

    def hub_get(self, name: str, query: dict):
        session = self.need_session()
        ctx = systems.context(store.connect(), session)
        if name == "history":
            return self.send_hub({"history": systems.history(self.hub, ctx)})
        if name == "sections":                      # every section of one course in one term, for picking or swapping
            term = query.get("term", store.REG_TERM)[:8]
            found = finder.details(ctx.con, query.get("code", "")[:12], term) if term in ctx.state["terms"] else None
            if not found:
                raise H.Refused("not_found", 404)
            return self.send_hub({**systems.stamp(ctx, "Class search", "the class schedule"), **found})
        options = {}
        if "term" in query:
            options["term"] = query["term"][:8]
        if "view" in query:
            options["view"] = query["view"][:12]
        if query.get("program", "").isdigit():
            options["program"] = int(query["program"])
        self.send_hub(systems.read(ctx, name[:20], **options))

    def hub_post(self, path: str, body: dict):
        hub = self.hub
        if path == "/api/idp/approve":                  # the simulated sign-in page: which locked demo account was approved
            if not hub.allow("signin-approve:" + self.client_key(), 20, 60):
                raise H.Refused("slow_down", 429)
            known = {s["slug"] for s in store.students(store.connect())} if store.available() else set()
            out = hub.approve_sign_in(str(body.get("request", ""))[:80], str(body.get("account", ""))[:30], known)
            return self.send_json({"redirect": f"/auth/callback?code={out['code']}&state={out['state']}"})
        if path == "/api/session/token":                # the app swaps the one-time code for a session
            if not hub.allow("signin-token:" + self.client_key(), 20, 60):
                raise H.Refused("slow_down", 429)
            old = self.session(touch=False)
            session = hub.finish_sign_in(body.get("code"), body.get("verifier"), old.sid if old else None)
            ctx = systems.context(store.connect(), session)
            data = json.dumps({"signed_in": True, **session.public(), "profile": store.profile(ctx.con, ctx.row)}).encode("utf-8")
            self._headers(200, "application/json; charset=utf-8", len(data),
                          {"Cache-Control": "no-store", "Set-Cookie": H.cookie_header(session.sid, config.cookie_secure(), https=self.is_https())})
            return self.wfile.write(data)

        session = self.need_session(body)               # everything below needs the session and its CSRF token
        if path == "/api/session/signout":
            hub.sign_out(session.sid)
            data = b'{"ok": true}'
            self._headers(200, "application/json; charset=utf-8", len(data),
                          {"Cache-Control": "no-store", "Set-Cookie": H.cookie_header("", config.cookie_secure(), clear=True, https=self.is_https())})
            return self.wfile.write(data)
        if path == "/api/session/keepalive":
            return self.send_json(session.public())
        if path == "/api/session/verify":               # the fresh "it's really me" step, simulated as an Approve button
            if not hub.allow("verify:" + session.sid, 10, 60):
                raise H.Refused("slow_down", 429)
            hub.verify(session)
            return self.send_json(session.public())
        if not hub.allow("change:" + session.sid, 60, 60):      # a person clicks a few times a minute; a script does not
            raise H.Refused("slow_down", 429)
        ctx = systems.context(store.connect(), session)
        if path == "/api/hub/propose":
            return self.send_hub(systems.propose(hub, ctx, str(body.get("system", ""))[:20], body.get("change"), by="student"))
        if path == "/api/hub/confirm":
            return self.send_hub(systems.confirm(hub, ctx, body.get("id"), body.get("token")))
        if path == "/api/hub/undo":
            return self.send_hub(systems.undo(hub, ctx, body.get("id")))
        if path == "/api/hub/reset":
            with session.lock:
                systems.reset(ctx, everyone=bool(body.get("everyone")))
            return self.send_json({"ok": True})
        if path == "/api/hub/clock":                    # demo control: pretend it is some days later (registration day)
            days = body.get("days")
            session.clock_days = days if isinstance(days, int) and 0 <= days <= 60 else 0
            return self.send_json(session.public())
        if path == "/api/hub/reveal":                   # sensitive details stay hidden until a fresh check
            return self.send_hub(systems.read(ctx, str(body.get("system", ""))[:20], reveal=True))
        if path == "/api/hub/draft":                    # the plan being worked out in the chat. It changes only the draft, never the classes.
            with session.lock:
                return self.send_hub(draft.edit(ctx, body) if body.get("op") else draft.evaluate(ctx, body.get("term"), body.get("items")))
        if path == "/api/hub/draft/sections":           # the other sections of one of its classes
            return self.send_hub(draft.sections(ctx, body.get("term"), body.get("items"), body.get("crn")))
        if path == "/api/hub/draft/options":            # classes that could go into it
            return self.send_hub(draft.options(ctx, body.get("term"), body.get("items"), body.get("replace"), body.get("query")))
        if path == "/api/hub/find":                     # the class finder, for any term
            code, term = str(body.get("course", ""))[:12], str(body.get("term", store.REG_TERM))[:8]
            if not store.course(ctx.con, code) or term not in ctx.state["terms"]:
                raise H.Refused("not_found", 404)
            found = finder.find(ctx.con, session.slug, code, body.get("prefs"), systems.legacy(ctx), term)
            found["sample"] = True
            return self.send_json(found)
        raise H.Refused("not_found", 404)

    # -- the question stream -----------------------------------------------------------------------
    def ask(self, body: dict):
        question = body.get("question")
        if not isinstance(question, str) or not question.strip():
            return self.send_json({"error": "bad request"}, 400)
        if not _streams.acquire(blocking=False):
            return self.send_json({"error": "busy"}, 503)
        try:
            self._headers(200, "text/event-stream; charset=utf-8", None,
                          {"Cache-Control": "no-store", "Connection": "close", "X-Accel-Buffering": "no"})
            self.close_connection = True

            def emit(event: str, data: dict):
                self.wfile.write(f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8"))
                self.wfile.flush()

            try:
                payload = self.answer(body, question, emit)
            except PaidCallNotApproved:
                payload = None
                emit("error", {"message": "locked"})
            except Exception:
                traceback.print_exc()
                payload = None
                emit("error", {"message": "server"})
            if payload:
                text = payload.pop("text")
                emit("meta", payload)
                delay = 0 if body.get("stream") is False or payload["kind"] == "crisis" else config.stream_ms() / 1000
                for piece in answers.pieces(text):
                    emit("delta", {"t": piece})
                    if delay:
                        time.sleep(delay)
                emit("done", {"text": text})
        except (BrokenPipeError, ConnectionError):
            pass
        finally:
            _streams.release()

    def answer(self, body: dict, question: str, emit) -> dict:
        lang = body.get("lang") if body.get("lang") in ("en", "es") else "en"
        history = body.get("history") if isinstance(body.get("history"), list) else None
        if history is None and isinstance(body.get("previous"), str):
            history = [{"role": "user", "text": body["previous"]}]
        session = self.session()
        # Counted per address as well as per session, so signing in again doesn't buy a fresh allowance.
        budget.count("questions")
        who = self.client_key()
        if not all([self.hub.allow(f"ask{i}:{who}", n, per) for i, (n, per) in enumerate(config.ask_limits())]) \
                or (session and not self.hub.allow("ask:" + session.sid, 30, 60)):
            budget.count("slowed")
            return {"kind": "chat", "reason": "slow_down", "text": "That's a lot of messages in a minute. Give me a few seconds and ask again.",
                    "lang": lang, "pages": [], "cites": {}, "contacts": [], "followups": [], "category": None, "checked": None, "mode": "rules"}
        demo = ctx = None
        if session and store.available():           # who is asking comes from the session, never from the request body
            ctx = systems.context(store.connect(), session)
            flow = body["demo"].get("flow") if isinstance(body.get("demo"), dict) else None
            demo = {"student": session.slug, "state": systems.legacy(ctx), "flow": flow, "site_facts": {tool: draft.site_facts(ctx, tool) for tool in intents.SITES}}
        if not library_ready():
            return {"kind": "setup", "reason": "library", "text": "The library of OSU pages isn't loaded on this computer yet, "
                    "so I can't look anything up. See the README for how to build it.", "lang": lang, "pages": [],
                    "cites": {}, "contacts": [], "followups": [], "category": None, "checked": None, "mode": "none"}
        payload = talk.converse(question, lang=lang, history=history, demo=demo, emit=emit)
        change = payload.pop("apply", None) if isinstance(payload, dict) else None
        if ctx and change and change.get("type") == "site_action":
            # A change on a connected site, asked for in words. Work out the exact change, then treat it like a button press:
            # the student gets the same review to confirm. If the request can't be pinned down, ask, and show the site.
            try:
                system, wanted, problem = actions.resolve(ctx, change.get("tool"), change.get("query"), change.get("number"))
            except H.Refused:
                system, wanted, problem = None, None, "I couldn't set that up. Open the panel and try it there."
            if wanted:
                change = {"type": "site_change", "system": system, "change": wanted}
            else:
                payload["text"] = payload["said"] = es.say(problem) if lang == "es" else problem
                change = None
        if ctx and change and change.get("type") in ("draft_put", "draft_drop"):
            # A follow-up in the chat edited the plan being worked on. Only the draft changes; adding it still needs the review.
            try:
                with session.lock:
                    card = draft.edit(ctx, {"op": change["type"][6:], "crn": change.get("crn"), "linked": change.get("linked")})
                payload["card"] = es.localize(card) if lang == "es" else card
            except H.Refused:
                pass
            change = None
        elif ctx and isinstance(payload, dict) and payload.get("kind") == "demo" and not change:
            try:                                    # the card under the reply, written by the server from the sandbox
                card = draft.chat_card(ctx, payload)
            except H.Refused:
                card = None
            if card:
                payload["card"] = es.localize(card) if lang == "es" else card
        if isinstance(payload, dict) and payload.get("kind") == "demo" and not change and not payload.get("card"):
            payload["text"] = talk.without_card_talk(payload.get("text", ""))      # nothing is drawn under it, so it may not say so
        if lang == "es" and isinstance(payload, dict) and payload.get("chips"):
            payload["chips"] = [es.chip(c) for c in payload["chips"]]
        if change and ctx and (change.get("type") in TOOL_CHANGES or change.get("type") == "site_change"):
            # The assistant may only propose. The student reviews this exact change and confirms it themselves.
            edited = (draft.saved(ctx) or {}).get("items") or (body["demo"].get("draft") if isinstance(body.get("demo"), dict) else None)
            if change["type"] == "plan_add_many" and isinstance(edited, list) and edited:
                change = {**change, "items": edited[:8]}     # "add them all" means the list as the student edited it in the chat
            system, wanted = (change["system"], change["change"]) if change["type"] == "site_change" else TOOL_CHANGES[change["type"]](change)
            try:
                proposal = systems.propose(self.hub, ctx, system, wanted, by="assistant")
            except H.Refused:
                proposal = None
            if proposal:
                spanish = lang == "es"
                proposal = es.localize(proposal) if spanish else proposal
                payload["proposal"] = proposal
                blocked = " ".join(x for x in (proposal["blocks"][0]["reason"], proposal["blocks"][0].get("next")) if x) if proposal["blocks"] else None     # why, and what to do instead
                title = proposal["title"][0].lower() + proposal["title"][1:]
                if spanish:
                    payload["text"] = (f"Todavía no puedo hacer eso. {blocked}" if blocked else
                                       f"Te lo dejé listo: {title}. Aún no ha cambiado nada. Revísalo abajo y confirma si está bien.")
                else:
                    payload["text"] = (f"I can't do that yet. {blocked}" if blocked else
                                       f"I've set this up for you: {title}. Nothing has changed yet. "
                                       "Look it over below and confirm if it's right.")
                payload["said"] = payload["text"]
        return payload


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    quiet = False
    chain_noted = False
    hub: H.Hub = None


def make_server(host: str | None = None, port: int | None = None, quiet: bool = False) -> Server:
    server = Server((host or config.host(), config.port() if port is None else port), Handler)
    server.quiet = quiet
    server.hub = H.Hub()
    return server
