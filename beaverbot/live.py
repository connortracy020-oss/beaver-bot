"""The live web backup: a Brave search of OSU's own sites, used only when our stored pages can't answer.

This is the one module in beaverbot/ that can make a web request, and it makes two kinds:

1. One search request to Brave's API, carrying only the student's redacted question plus "site:oregonstate.edu".
   The key is read from the BRAVE_SEARCH_API_KEY environment variable each time; it is never written to a file,
   logged, or sent to the browser.
2. At most MAX_FETCHES page requests to OSU, for a result we don't already store. These go through the crawler's
   own PoliteFetcher, so every rule in docs/crawl-policy.md holds: our User-Agent, robots.txt, at least 3 seconds
   between any two requests to OSU, blocked.json and cooldown.json honoured, and a full stop on any 429 or
   challenge. The page's text goes through the same privacy scrub as crawled pages. Nothing fetched this way is
   stored: it is cut down to the parts that match the question, used for one answer and dropped. Links on the
   page are never followed, so this cannot crawl.

Limits: results are cached for a week, searches are counted per calendar month in data/logs/brave-usage.json, and
the backup switches itself off at 90% of the monthly limit (config.brave_monthly_limit()). Automated test runs
set BEAVERBOT_LIVE_SEARCH=off and never reach this module's network code.
"""
import datetime
import json
import os
import re
import threading
import time
from urllib.parse import urlsplit

from assistant import answer as A
from assistant.retrieve import Hit, terms

from . import config

API = "https://api.search.brave.com/res/v1/web/search"
MAX_RESULTS, MAX_FETCHES, MAX_CHUNKS, CHUNK_CHARS, CACHE_DAYS = 10, 1, 4, 1800, 7
USAGE_PATH = config.DATA / "logs" / "brave-usage.json"
CACHE_PATH = config.DATA / "logs" / "brave-cache.json"
_lock = threading.Lock()

# Never opened and never cited, whatever a search returns.
SKIP_HOSTS = re.compile(r"^(canvas|beaverhub|beav|my|mysupport|login|sso|cas|idp|onid|prodapps\.isadm|apps\.isadm|directory\b.*|people|"
                        r"classes|guides\.library|search|mybill|mydegrees|scheduler|secure|webmail|mail)\.oregonstate\.edu$|"
                        r"(^|\.)directory\.", re.I)
SKIP_PATHS = re.compile(r"/(people|person|directory|profiles?|staff|faculty-staff|our-team|team|roster|rosters|minutes|agendas?|users?|"
                        r"bios?|login|signin|sign-in|cas|sso|student-emails|award-winners|obituar\w*)(/|$)|\.(docx?|xlsx?|pptx?|zip)$", re.I)


def month() -> str:
    return datetime.date.today().strftime("%Y-%m")


def _read(path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write(path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def used() -> int:
    return int(_read(USAGE_PATH).get(month(), 0))


def status() -> dict:
    limit = config.brave_monthly_limit()
    n = used()
    return {"month": month(), "used": n, "limit": limit, "stop_at": int(limit * 0.9),
            "key": bool(os.environ.get("BRAVE_SEARCH_API_KEY", "").strip()), "switch": os.environ.get("BEAVERBOT_LIVE_SEARCH", "off")}


def enabled() -> bool:
    """Switched on by the owner (live_search = "on" in beaverbot.local.toml), a key in the environment, and under
    90% of this month's limit. Off by default, so tests and fresh clones never search the web."""
    s = status()
    return s["key"] and s["switch"].strip().lower() in ("on", "yes", "1", "true") and s["used"] < s["stop_at"]


def allowed(url: str) -> bool:
    """An OSU page this project would be willing to read: public, not a login or people page, not excluded by scope."""
    from osu_crawl import scope
    from osu_crawl.fetcher import classify_url
    parts = urlsplit(url)
    host, path = (parts.hostname or "").lower(), parts.path or "/"
    if parts.scheme != "https" or not (host == "oregonstate.edu" or host.endswith(".oregonstate.edu")):
        return False
    if host in scope.EXCLUDED_HOSTS or SKIP_HOSTS.search(host) or SKIP_PATHS.search(path) or classify_url(url):
        return False
    if scope.rule_for(host, (scope.SCOPE,)) is not None:        # a site we crawl: its own exclusions apply (profiles, minutes...)
        rule = scope.rule_for(host, (scope.SCOPE,))
        low = path.lower()
        if any(low.startswith(p.lower()) for p in rule["exclude"]) or (rule.get("exclude_re") and re.search(rule["exclude_re"], low)):
            return False
        if any(scope.under(low, p) for p in scope.NEWS):
            return False
    return True


def brave(question: str) -> list[dict]:
    """Search results as [{title, url, description}], OSU sites only, filtered. Cached; counted when a request is made."""
    import httpx
    query = " ".join(A.redact(question).split())[:300]
    key = query.lower()
    with _lock:
        cache = _read(CACHE_PATH)
        hit = cache.get(key)
        if hit and time.time() - hit["at"] < CACHE_DAYS * 86400:
            return hit["results"]
        if not enabled():
            return []
        usage = _read(USAGE_PATH)
        usage[month()] = int(usage.get(month(), 0)) + 1           # counted before the call, so a failure can't hide a request
        _write(USAGE_PATH, usage)
        try:
            resp = httpx.get(API, params={"q": f"{query} site:oregonstate.edu", "count": MAX_RESULTS, "country": "us", "search_lang": "en",
                                          "safesearch": "strict"},
                             headers={"X-Subscription-Token": os.environ["BRAVE_SEARCH_API_KEY"].strip(), "Accept": "application/json"},
                             timeout=10.0)
        except httpx.HTTPError as e:
            print(f"Live search failed: {type(e).__name__}", flush=True)       # never the request itself: it holds the key
            return []
        if resp.status_code != 200:
            print(f"Live search answered HTTP {resp.status_code}", flush=True)
            return []
        results = [{"title": " ".join(str(r.get("title", "")).split())[:200], "url": str(r.get("url", "")),
                    "description": re.sub(r"<[^>]+>", "", str(r.get("description", "")))[:400]}
                   for r in (resp.json().get("web") or {}).get("results", [])]
        results = [r for r in results if allowed(r["url"])]
        cache = {k: v for k, v in cache.items() if time.time() - v["at"] < CACHE_DAYS * 86400}
        cache[key] = {"at": time.time(), "results": results}
        _write(CACHE_PATH, cache)
        return results


def _score(question: str, text: str) -> float:
    words = [t for t in terms(question) if len(t) > 2]
    low = text.lower()
    return sum(1 for w in words if w[: max(4, len(w) - 3)] in low) / (len(words) or 1)


def stored(con, url: str, question: str) -> list[Hit]:
    """Our own stored copy of a page, as excerpts: the parts that match the question best."""
    page = url.split("#")[0].split("?")[0]
    rows = con.execute("""SELECT c.id, c.heading_path, c.anchor, c.text, p.url, p.title, p.retrieved_at, p.owning_office
                          FROM pages p JOIN chunks c ON c.page_id = p.id
                          WHERE p.url IN (?, ?) AND p.gone_at IS NULL ORDER BY c.seq""", (page, page.rstrip("/"))).fetchall()
    rows = sorted(rows, key=lambda r: -_score(question, f"{r['heading_path']} {r['text']}"))[:MAX_CHUNKS]
    return [Hit(chunk_id=r["id"], score=0.0, coverage=0.0, title=r["title"] or "", heading_path=r["heading_path"] or "",
                url=r["url"] + (f"#{r['anchor']}" if r["anchor"] else ""), page_url=r["url"],
                retrieved_at=(r["retrieved_at"] or "")[:10], office=r["owning_office"], excerpt="", text=r["text"]) for r in rows]


def fetch(url: str, question: str, first_id: int = -1) -> list[Hit]:
    """Open one OSU page now, politely, and return the parts that match the question. Nothing is saved."""
    from osu_crawl.config import load_settings
    from osu_crawl.extract import extract_html
    from osu_crawl.fetcher import CrawlerLocked, DomainBlocked, HostUnavailable, PoliteFetcher, Skipped
    from osu_crawl.privacy import scrub_text
    if not allowed(url):
        return []
    try:
        fetcher = PoliteFetcher(load_settings(), log_name="live-requests.jsonl", save_raw=False)
    except CrawlerLocked:
        return []                               # a crawl is running; it owns the line to OSU
    try:
        res = fetcher.fetch(url, max_bytes=2_000_000, hop_check=lambda u: None if allowed(u) else "out_of_scope")
        if res.status != 200 or "html" not in res.content_type:
            return []
        page = extract_html(res.content, res.final_url)
        if "noindex" in (page.meta_robots or "") or not page.main_found:
            return []
        parts = []
        for section in page.sections:
            text, _ = scrub_text(section.text or "")
            heading = " > ".join(section.heading_path or []) or page.title
            for start in range(0, len(text or ""), CHUNK_CHARS):
                piece = text[start:start + CHUNK_CHARS].strip()
                if len(piece) > 40:
                    parts.append((heading, piece))
        if not parts and page.main_text:
            text, _ = scrub_text(page.main_text)
            parts = [(page.title, text[i:i + CHUNK_CHARS]) for i in range(0, len(text or ""), CHUNK_CHARS)]
        parts = sorted(parts, key=lambda p: -_score(question, f"{p[0]} {p[1]}"))[:MAX_CHUNKS]
        today = datetime.date.today().isoformat()
        final = res.final_url.split("#")[0]
        return [Hit(chunk_id=first_id - i, score=0.0, coverage=0.0, title=page.title or "", heading_path=h, url=final, page_url=final,
                    retrieved_at=today, office=None, excerpt="", text=t) for i, (h, t) in enumerate(parts)]
    except (Skipped, DomainBlocked, HostUnavailable):
        return []                               # robots, a block, a pause after a 429 or challenge: stop, don't retry
    except Exception as e:
        print(f"Live page read failed: {type(e).__name__}", flush=True)
        return []
    finally:
        fetcher.close()


def search(con, question: str) -> tuple[list[Hit], set[str]]:
    """Excerpts for a question from a live search: our stored copy where we have the page, otherwise the page
    read now. Returns (hits, the page URLs that were read live)."""
    hits, live_pages, fetched = [], set(), 0
    for r in brave(question)[:5]:
        have = stored(con, r["url"], question)
        if have:
            hits += have
        elif fetched < MAX_FETCHES:
            fetched += 1
            got = fetch(r["url"], question, first_id=-1 - 10 * fetched)
            hits += got
            live_pages |= {h.page_url for h in got}
        if len(hits) >= 8:
            break
    return hits, live_pages
