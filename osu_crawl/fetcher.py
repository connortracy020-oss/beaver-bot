"""Polite HTTP fetching.

Rules this module enforces for every request, in every phase:
- Only one crawler process at a time (a lock file in data/logs), so pacing is never shared or doubled.
- robots.txt is read first for each host and obeyed (Allow/Disallow with wildcards, Crawl-delay, Request-rate).
  Its own redirects are followed by hand and paced too. If it can't be read after retries, the host is
  left alone for the rest of the run.
- One request at a time; at least `min_delay_s` (or the robots crawl-delay, if larger) between the end of
  one response and the next request to the same host.
- Redirects are followed by hand so every hop is checked against robots.txt, login/PII rules, the host
  allow-list and the caller's scope check.
- 5xx: exponential backoff honoring Retry-After, then give up on that URL. Five 5xx or five network
  errors in a row stop the host for the rest of the run (not permanently).
- 202, 429, or any 4xx/5xx carrying a captcha/challenge page: the host is marked blocked, the block is
  written to disk at once and sticks across runs. We do not retry, rotate anything, or work around it.
- 403: OSU's own themed "Access denied" page (an unpublished page) skips that URL only, any number of times,
  whatever its size, and even when its cookie banner names reCAPTCHA. Any other full-page 403 skips the URL once
  per host; a second one blocks the host. A 403 on robots.txt or the home page, or a short/non-HTML body, blocks
  the host as above.
  Every refusal's body is saved to data/logs/refused/ for review.
- Redirects into a login/SSO system are recorded as login-required and not followed.
"""
import hashlib
import json
import os
import random
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlsplit

import httpx
from protego import Protego

from .config import (
    BOT_NAME, DISCOVERY_DIR, LOG_DIR, LOGIN_HOSTS, LOGIN_PATH_RE, PII_HOSTS, PII_PATH_RE, PII_PATHS, RAW_DIR,
    Settings,
)

CHALLENGE_MARKERS = (b"cf-chl", b"challenge-platform", b"g-recaptcha", b"h-captcha", b"hcaptcha",
                     b"Attention Required!", b"Just a moment...", b"captcha",
                     b"awsWafCookieDomainList", b"gokuProps", b"AwsWafIntegration")
MAX_REDIRECTS = 5
MAX_CONSECUTIVE_FAILURES = 5
MAX_RETRY_AFTER_S = 600
# OSU's sites share one Cloudflare rate limit: a 429 or challenge on any of them pauses all of them.
ZONE = "oregonstate.edu"
ZONE_COOLDOWN_H = 24
GLOBAL = "*"  # key for the last request to any host, in last_request
MIN_FULL_PAGE_BYTES = 20_000  # an unexplained 403 shorter than this is a firewall/rate-limit page
# OSU's own Drupal "Access denied" page: "<title>Access denied | <Office> | Oregon State University</title>", or
# "| OSU College of Pharmacy". Small sites' themes make it as short as 16 KB (Family Resource Center, 2026-10-29).
ACCESS_DENIED_TITLE_RE = re.compile(rb"<title>\s*Access denied\s*\|[^<]*(Oregon State University|OSU)\b[^<]*</title>",
                                    re.IGNORECASE)
CDN_BLOCK_RE = re.compile(rb"cf-error|ray id|used cloudflare to restrict|attention required|request blocked", re.IGNORECASE)
# Markers only a CDN/WAF challenge carries. A themed page can mention reCAPTCHA (its cookie banner lists it).
INTERSTITIAL_MARKERS = (b"cf-chl", b"challenge-platform", b"Just a moment...", b"Attention Required!",
                        b"awsWafCookieDomainList", b"gokuProps", b"AwsWafIntegration")


def is_themed_access_denied(content: bytes) -> bool:
    """The site's own themed page (Drupal, OSU title), not a CDN or firewall page."""
    head = content[:20000]
    return (bool(ACCESS_DENIED_TITLE_RE.search(head)) and b"Drupal" in head and b"<html" in head[:5000].lower()
            and not CDN_BLOCK_RE.search(content) and not any(m in content for m in INTERSTITIAL_MARKERS))
ROBOTS_CACHE = DISCOVERY_DIR / "robots"
ROBOTS_TTL_S = 24 * 3600
DISALLOW_ALL = "User-agent: *\nDisallow: /"


class DomainBlocked(Exception):
    """The host refused us (403/429/202/challenge). Stop crawling it, for good, and tell the user."""


class HostUnavailable(Exception):
    """The host is failing (robots.txt unreachable, repeated 5xx or network errors). Leave it for this run."""


class CrawlerLocked(Exception):
    """Another crawler or discovery process is running."""


class Skipped(Exception):
    """A URL we chose not to fetch. `reason` is one of: robots, login, pii, out_of_scope, too_large, ..."""

    def __init__(self, url: str, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {url} {detail}".strip())
        self.url, self.reason, self.detail = url, reason, detail


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int
    headers: dict
    content: bytes
    retrieved_at: str
    content_hash: str
    raw_path: str | None
    redirects: list[str] = field(default_factory=list)
    elapsed: float | None = None  # time spent on the final request only, not on politeness waits

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "").split(";")[0].strip().lower()

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def classify_url(url: str) -> str | None:
    """Return a skip reason for URLs we never fetch, regardless of robots.txt."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if host in LOGIN_HOSTS or LOGIN_PATH_RE.search(parts.path):
        return "login"
    if host in PII_HOSTS or PII_PATH_RE.search(parts.path) or parts.path.lower().rstrip("/") in PII_PATHS:
        return "pii"
    if parts.scheme not in ("http", "https"):
        return "out_of_scope"
    return None


def _retry_after_s(value: str | None) -> float | None:
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        return max(0.0, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError):
        return None


def _write_json_atomic(path: Path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    os.replace(tmp, path)


class PoliteFetcher:
    def __init__(self, settings: Settings, allowed_hosts: set[str] | None = None,
                 log_name: str = "requests.jsonl", save_raw: bool = True):
        self.settings = settings
        self.allowed_hosts = allowed_hosts  # None = any *.oregonstate.edu host
        self.save_raw = save_raw
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        self.lock_path = LOG_DIR / "crawler.lock"
        try:
            fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, f"pid {os.getpid()} since {now_iso()}\n".encode())
            os.close(fd)
        except FileExistsError:
            raise CrawlerLocked(
                f"{self.lock_path} exists: another crawler/discovery process is running. If none is "
                f"(e.g. the last run was killed), delete that file and start again.") from None
        self.client = httpx.Client(
            headers={"User-Agent": settings.user_agent, "Accept-Language": "en-US,en;q=0.8"},
            timeout=settings.timeout_s,
            follow_redirects=False,
            http2=False,
        )
        self.robots: dict[str, Protego | None] = {}
        self.robots_raw: dict[str, dict] = {}
        self.last_request: dict[str, float] = {}
        self.not_before: dict[str, float] = {}
        self.blocked: dict[str, str] = {}
        self.unavailable: dict[str, str] = {}
        self.failures: dict[str, int] = {}
        self.log_path = LOG_DIR / log_name
        self.skips: list[dict] = []
        # Pacing survives across processes, so back-to-back runs still respect the per-host delay.
        self.pacing_path = LOG_DIR / "pacing.json"
        if self.pacing_path.exists():
            self.last_request.update(json.loads(self.pacing_path.read_text()))
        # A block is sticky across runs: only a person clears data/logs/blocked.json.
        self.blocked_path = LOG_DIR / "blocked.json"
        self.blocked.update(self._blocked_on_disk())
        # A zone-wide pause after a 429/challenge, sticky across runs until it expires or a person clears it.
        self.cooldown_path = LOG_DIR / "cooldown.json"
        self.cooldown: dict[str, dict] = (json.loads(self.cooldown_path.read_text())
                                          if self.cooldown_path.exists() else {})
        # Single-page 403s per host, also sticky: a host gets one, a second stops it (crawl-policy.md).
        self.forbidden_path = LOG_DIR / "forbidden.json"
        self.forbidden: dict[str, list[str]] = self._forbidden_on_disk()

    # ---- logging and state -----------------------------------------------------------------
    def _log(self, **entry):
        # Millisecond timestamps, so the 2 s pacing rule can be checked from the log.
        entry.setdefault("ts", datetime.now(timezone.utc).isoformat(timespec="milliseconds"))
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def _skip(self, url: str, reason: str, detail: str = ""):
        self.skips.append({"url": url, "reason": reason, "detail": detail, "ts": now_iso()})
        self._log(event="skip", url=url, reason=reason, detail=detail)
        raise Skipped(url, reason, detail)

    def _blocked_on_disk(self) -> dict:
        if self.blocked_path.exists():
            return json.loads(self.blocked_path.read_text())
        return {}

    def _forbidden_on_disk(self) -> dict:
        if self.forbidden_path.exists():
            return json.loads(self.forbidden_path.read_text())
        return {}

    def _save_refusal(self, host: str, url: str, status: int, content: bytes) -> Path:
        """Keep what the server sent with a 202/403/429 or challenge, so a person can see what it was."""
        refused_dir = LOG_DIR / "refused"
        refused_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        path = refused_dir / f"{stamp}-{host}-{status}-{hashlib.sha256(url.encode()).hexdigest()[:10]}.html"
        path.write_bytes(content)
        self._log(event="refusal_saved", url=url, status=status, path=str(path.name), bytes=len(content))
        return path

    def _forbidden(self, host: str, url: str, content: bytes):
        """HTTP 403 (rules approved by the owner, 2026-10-22). Nothing is retried.

        - The site's own themed "Access denied" page (a full HTML page, how OSU's Drupal answers for an unpublished
          page): skip that URL only, with no limit per host.
        - Any other full-page 403 on an ordinary page: skip that URL; a second one stops the host.
        - A 403 on the home page, or with a short or non-HTML body: stop the host for good.
        """
        saved = self._save_refusal(host, url, 403, content)
        earlier = self.forbidden.get(host, [])
        if urlsplit(url).path in ("", "/"):
            self._block(host, f"HTTP 403 on the home page {url}")
        themed_denied = is_themed_access_denied(content)
        if not themed_denied:
            if CDN_BLOCK_RE.search(content):
                self._block(host, f"HTTP 403 CDN/firewall block page on {url}")
            if len(content) < MIN_FULL_PAGE_BYTES or b"<html" not in content[:5000].lower():
                self._block(host, f"HTTP 403 with a {len(content)}-byte body on {url}")
            if earlier:
                self._block(host, f"second HTTP 403 on {url} (earlier: {', '.join(earlier)})")
            # Only unexplained 403s count toward the one-per-host allowance.
            self.forbidden[host] = earlier + [url]
            _write_json_atomic(self.forbidden_path, {**self._forbidden_on_disk(), **self.forbidden})
        kind = "access-denied page" if themed_denied else "full page"
        self._skip(url, "forbidden", f"HTTP 403 ({kind}, {len(content)} bytes), body in data/logs/refused/{saved.name}")

    @staticmethod
    def _zone_of(host: str) -> str:
        return ZONE if host == ZONE or host.endswith("." + ZONE) else host

    def _start_cooldown(self, host: str, why: str):
        """Pause every host in the zone: no further request to any OSU site until the cooldown ends."""
        zone = self._zone_of(host)
        until = datetime.now(timezone.utc).timestamp() + ZONE_COOLDOWN_H * 3600
        self.cooldown[zone] = {"until": datetime.fromtimestamp(until, timezone.utc).isoformat(timespec="seconds"),
                               "reason": f"{host}: {why}", "set_at": now_iso()}
        on_disk = json.loads(self.cooldown_path.read_text()) if self.cooldown_path.exists() else {}
        _write_json_atomic(self.cooldown_path, {**on_disk, **self.cooldown})
        self._log(event="zone_cooldown", zone=zone, until=self.cooldown[zone]["until"], reason=why)

    def _check_cooldown(self, host: str):
        c = self.cooldown.get(self._zone_of(host))
        if c and datetime.now(timezone.utc) < datetime.fromisoformat(c["until"]):
            self._unavailable(host, f"zone {self._zone_of(host)} cooling down until {c['until']} ({c['reason']})")

    def _block(self, host: str, why: str):
        """Record a block immediately, merged with what is on disk, so no crash or second process can lose it."""
        self.blocked[host] = why
        merged = {**self._blocked_on_disk(), **self.blocked}
        _write_json_atomic(self.blocked_path, merged)
        self._log(event="blocked", host=host, reason=why)
        raise DomainBlocked(f"{host}: {why}")

    def _unavailable(self, host: str, why: str):
        self.unavailable[host] = why
        self._log(event="host_unavailable", host=host, reason=why)
        raise HostUnavailable(f"{host}: {why}")

    def _failure(self, host: str, why: str):
        self.failures[host] = self.failures.get(host, 0) + 1
        if self.failures[host] >= MAX_CONSECUTIVE_FAILURES:
            self._unavailable(host, f"{MAX_CONSECUTIVE_FAILURES} failures in a row (last: {why})")

    # ---- pacing --------------------------------------------------------------------------
    def delay_for(self, host: str) -> float:
        delay = self.settings.min_delay_s
        rp = self.robots.get(host)
        if rp is not None:
            crawl_delay = rp.crawl_delay(BOT_NAME)
            if crawl_delay:
                delay = max(delay, float(crawl_delay))
            rate = rp.request_rate(BOT_NAME)
            if rate and rate.requests:
                delay = max(delay, rate.seconds / rate.requests)
        return delay

    def ready_at(self, host: str) -> float:
        """Earliest time a request to `host` is allowed."""
        last = self.last_request.get(host)
        earliest = last + self.delay_for(host) if last is not None else 0.0
        last_any = self.last_request.get(GLOBAL)
        any_ok = last_any + self.settings.min_global_delay_s if last_any is not None else 0.0
        return max(earliest, any_ok, self.not_before.get(host, 0.0))

    def _wait_turn(self, host: str):
        remaining = self.ready_at(host) - time.time()
        if remaining > 0:
            time.sleep(remaining + random.uniform(0, 0.3))
        self.last_request[host] = self.last_request[GLOBAL] = time.time()

    def _mark_done(self, host: str):
        # The delay counts from the end of the previous response, not its start, per host and across hosts.
        self.last_request[host] = self.last_request[GLOBAL] = time.time()

    # ---- robots.txt ----------------------------------------------------------------------
    def _get_robots_once(self, url: str):
        """GET robots.txt, following redirects by hand: each hop is paced and checked like any request."""
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            host = urlsplit(current).hostname.lower()
            if host in self.blocked or classify_url(current) == "login":
                return None, current
            self._wait_turn(host)
            try:
                resp = self.client.get(current)
            finally:
                self._mark_done(host)
            if resp.is_redirect and "location" in resp.headers:
                current = urljoin(current, resp.headers["location"])
                continue
            return resp, current
        return None, current

    def robots_for(self, scheme: str, host: str) -> Protego | None:
        if host in self.blocked:
            raise DomainBlocked(f"{host}: already blocked ({self.blocked[host]})")
        self._check_cooldown(host)
        if host in self.unavailable:
            raise HostUnavailable(f"{host}: {self.unavailable[host]}")
        if host in self.robots:
            return self.robots[host]
        url = f"{scheme}://{host}/robots.txt"
        cache = ROBOTS_CACHE / f"{host}.json"
        if cache.exists():
            cached = json.loads(cache.read_text(encoding="utf-8"))
            age = time.time() - datetime.fromisoformat(cached["retrieved_at"]).timestamp()
            if age < ROBOTS_TTL_S and cached.get("status") == 200:
                self.robots_raw[host] = cached
                self.robots[host] = Protego.parse(cached["body"])
                return self.robots[host]

        resp, final, last_error = None, url, ""
        for attempt in range(self.settings.max_retries_5xx + 1):
            try:
                resp, final = self._get_robots_once(url)
            except httpx.HTTPError as e:
                resp, last_error = None, repr(e)
                self._log(event="robots", url=url, error=last_error, attempt=attempt)
            else:
                if resp is None:
                    break  # redirected into a login system or a blocked host
                self._log(event="robots", url=url, status=resp.status_code, final_url=final, attempt=attempt)
                if resp.status_code < 500:
                    break
                last_error = f"HTTP {resp.status_code}"
            if attempt < self.settings.max_retries_5xx:
                time.sleep(5 * 2 ** attempt + random.uniform(0, 1))

        if resp is None and final == url:
            # Unreachable after retries (network/TLS failure): leave the host alone this run.
            self.robots_raw[host] = {"url": url, "status": None, "error": last_error, "body": ""}
            self._unavailable(host, f"robots.txt unreachable ({last_error})")
        if resp is None:
            # Redirected somewhere we won't go: treat as disallow-all, never as permission.
            self.robots_raw[host] = {"url": url, "status": None, "final_url": final, "body": ""}
            self.robots[host] = Protego.parse(DISALLOW_ALL)
            return self.robots[host]

        body = resp.text if resp.status_code == 200 else ""
        self.robots_raw[host] = {"url": url, "status": resp.status_code, "final_url": final,
                                 "body": body, "retrieved_at": now_iso()}
        ROBOTS_CACHE.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(self.robots_raw[host], indent=1), encoding="utf-8")
        # 403/429, a challenge page, or an odd 2xx such as 202 (how bot-protection services answer
        # before a JavaScript check) all mean the host does not want automated clients.
        if (resp.status_code in (403, 429) or 200 < resp.status_code < 300
                or self._is_challenge(resp.status_code, resp.content)):
            self.robots[host] = None
            self._block(host, f"robots.txt returned {resp.status_code} (bot protection)")
        if resp.status_code >= 500:
            self._unavailable(host, f"robots.txt returned {resp.status_code} after retries")
        if resp.status_code == 200:
            self.robots[host] = Protego.parse(body)
        else:
            # 404 and other 4xx without a challenge: no robots.txt, so nothing is disallowed (RFC 9309).
            self.robots[host] = Protego.parse("")
        return self.robots[host]

    def allowed_by_robots(self, url: str) -> bool:
        parts = urlsplit(url)
        rp = self.robots_for(parts.scheme, parts.hostname.lower())
        return rp is not None and rp.can_fetch(url, BOT_NAME)

    # ---- fetching ------------------------------------------------------------------------
    def _check(self, url: str):
        host = (urlsplit(url).hostname or "").lower()
        if host in self.blocked:
            raise DomainBlocked(f"{host}: already blocked ({self.blocked[host]})")
        self._check_cooldown(host)
        if host in self.unavailable:
            raise HostUnavailable(f"{host}: {self.unavailable[host]}")
        reason = classify_url(url)
        if reason:
            self._skip(url, reason)
        if self.allowed_hosts is not None and host not in self.allowed_hosts:
            self._skip(url, "out_of_scope", host)
        if self.allowed_hosts is None and not (host == "oregonstate.edu" or host.endswith(".oregonstate.edu")):
            self._skip(url, "out_of_scope", host)
        if not self.allowed_by_robots(url):
            self._skip(url, "robots")

    def fetch(self, url: str, extra_headers: dict | None = None, max_bytes: int | None = None,
              hop_check: Callable[[str], str | None] | None = None) -> FetchResult:
        """GET `url`. `hop_check(u)` returns a skip reason for any URL (first or redirect target) we must not fetch."""
        redirects: list[str] = []
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            if current != url and classify_url(current) == "login":
                self._log(event="login_redirect", url=url, to=current)
                self._skip(url, "login", f"redirects to {current}")
            if hop_check:
                reason = hop_check(current)
                if reason:
                    self._skip(url, reason, f"redirect target {current}" if current != url else "")
            try:
                self._check(current)
            except Skipped as e:
                if current == url:
                    raise
                self._skip(url, e.reason, f"redirect target {current}")
            resp, content, elapsed = self._get_with_backoff(current, extra_headers, max_bytes)
            if resp.status_code in (301, 302, 303, 307, 308) and "location" in resp.headers:
                redirects.append(current)
                current = urljoin(current, resp.headers["location"])
                continue
            return self._finish(url, current, resp, content, redirects, elapsed)
        self._log(event="error", url=url, error="too many redirects")
        raise httpx.TooManyRedirects(f"too many redirects: {url}", request=None)

    def _get_with_backoff(self, url: str, extra_headers: dict | None, max_bytes: int | None):
        host = urlsplit(url).hostname.lower()
        limit = max_bytes or self.settings.max_pdf_bytes
        for attempt in range(self.settings.max_retries_5xx + 1):
            self._wait_turn(host)
            started = time.monotonic()
            started_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")  # logged as-is: exact
            try:
                with self.client.stream("GET", url, headers=extra_headers or {}) as resp:
                    declared = int(resp.headers.get("content-length") or 0)
                    if declared > limit:
                        self._log(event="fetch", url=url, status=resp.status_code, note="too_large", bytes=declared)
                        self._skip(url, "too_large", f"{declared} bytes")
                    chunks, size = [], 0
                    for chunk in resp.iter_bytes():
                        size += len(chunk)
                        if size > limit:
                            self._skip(url, "too_large", f">{limit} bytes")
                        chunks.append(chunk)
                    content = b"".join(chunks)
            except httpx.HTTPError as e:
                self._mark_done(host)
                self._log(event="fetch", url=url, error=repr(e), attempt=attempt)
                self._failure(host, repr(e))
                if attempt == self.settings.max_retries_5xx:
                    raise
                time.sleep(5 * 2 ** attempt + random.uniform(0, 1))
                continue
            finally:
                self._mark_done(host)
            elapsed = round(time.monotonic() - started, 2)
            self._log(event="fetch", url=url, status=resp.status_code, bytes=len(content), elapsed=elapsed,
                      attempt=attempt, started=started_at)

            challenge = self._is_challenge(resp.status_code, content)
            if resp.status_code in (202, 429) or challenge:
                self._save_refusal(host, url, resp.status_code, content)
                why = f"{'challenge page' if challenge else 'HTTP ' + str(resp.status_code)} (HTTP {resp.status_code}) on {url}"
                self._start_cooldown(host, why)
                self._block(host, why)
            if resp.status_code == 403:
                self._forbidden(host, url, content)
            if resp.status_code >= 500:
                retry_after = _retry_after_s(resp.headers.get("retry-after"))
                if retry_after and retry_after > MAX_RETRY_AFTER_S:
                    self._unavailable(host, f"HTTP {resp.status_code} with Retry-After {int(retry_after)} s")
                if retry_after:
                    self.not_before[host] = time.time() + retry_after
                self._failure(host, f"HTTP {resp.status_code}")
                if attempt < self.settings.max_retries_5xx:
                    time.sleep(max(5 * 2 ** attempt + random.uniform(0, 1), retry_after or 0))
                    continue
            else:
                self.failures[host] = 0
            return resp, content, elapsed
        return resp, content, elapsed

    @staticmethod
    def _is_challenge(status: int, content: bytes) -> bool:
        # Ordinary pages can embed a reCAPTCHA on a contact form, so the markers only count when the
        # server also refused or deferred the request (202 or any 4xx/5xx, e.g. AWS WAF's 405 CAPTCHA).
        if status == 403 and is_themed_access_denied(content):
            return False  # the site's own page; its cookie banner lists reCAPTCHA (pharmacy, 2026-10-29)
        if status == 202 or status >= 400:
            head = content[:20000]
            return any(m in head for m in CHALLENGE_MARKERS)
        return b"<title>Just a moment...</title>" in content[:5000]

    def _finish(self, url, final_url, resp, content, redirects, elapsed) -> FetchResult:
        digest = hashlib.sha256(content).hexdigest()
        raw_path = None
        if self.save_raw and resp.status_code == 200 and content:
            # Keyed by the URL we asked for, so two URLs redirecting to one page never overwrite each other.
            raw_path = str(self._store_raw(url, resp.headers.get("content-type", ""), content))
        return FetchResult(url=url, final_url=final_url, status=resp.status_code,
                           headers={k.lower(): v for k, v in resp.headers.items()}, content=content,
                           retrieved_at=now_iso(), content_hash=digest, raw_path=raw_path, redirects=redirects,
                           elapsed=elapsed)

    @staticmethod
    def _store_raw(url: str, content_type: str, content: bytes) -> Path:
        ct = content_type.lower()
        ext = ".pdf" if "pdf" in ct else ".xml" if "xml" in ct else ".txt" if "text/plain" in ct else ".html"
        host = urlsplit(url).hostname
        path = RAW_DIR / host / (hashlib.sha256(url.encode()).hexdigest()[:24] + ext)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path.relative_to(RAW_DIR.parent.parent)

    def close(self):
        self.pacing_path.write_text(json.dumps(self.last_request))
        _write_json_atomic(self.blocked_path, {**self._blocked_on_disk(), **self.blocked})
        self.client.close()
        self.lock_path.unlink(missing_ok=True)
