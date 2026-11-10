"""Phase 1/2 crawler: resumable, polite, one request in flight at a time across all of OSU.

    python -m osu_crawl.crawl pilot     # ~200 pages from registrar, catalog, ecampus (Phase 1)
    python -m osu_crawl.crawl tier1     # every Tier 1 host (Phase 2, after the pilot is approved)
    python -m osu_crawl.crawl status    # frontier and run counts

Stopping (Ctrl+C) is safe: each URL is committed all-or-nothing, the frontier lives in SQLite, and the next run
of the same phase resumes it.
"""
import hashlib
import json
import re
import sys
import time
import traceback
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, urlsplit, urlunsplit

import httpx

from . import db
from .config import DISCOVERY_DIR, LOG_DIR, LOGIN_HOSTS, RAW_DIR, ROOT, load_settings
from .dates import from_sections, from_tables
from .extract import FORMISH_RE, extract_html, normalize_url
from .fetcher import DomainBlocked, FetchResult, HostUnavailable, PoliteFetcher, Skipped, classify_url, now_iso
from .process import chunk_sections, classify_page, good_title, pdf_sections, read_pdf
from .scope import (ALIASES, NEWS, SCOPE, TIER2B, canonical_host, document_in_scope, in_scope, is_asset, office_for,
                    under)

GLOBAL_GAP_S = 0.5
# A re-crawl skips pages whose sitemap date says unchanged, but only if we fetched them within this many days.
SITEMAP_TRUST_DAYS = 28
# Links into OSU's sign-in systems whose path names a form, whatever the link text says.
SSO_FORM_PATH_RE = re.compile(r"/genDocusignForm|/BannerExtensibility/customPage/|/BanPages/|/esp\?id=sc_cat_item", re.I)
SHORTENER_HOSTS = {"bit.ly", "tinyurl.com", "ow.ly", "go.osu.edu", "beav.es", "t.co"}
# Tier 3 sections anywhere in a path (/students/going-online-podcast/, /x/news/...), not only at the root.
TIER3_SEGMENT_RE = re.compile(r"/(news|podcasts?|[\w-]*-podcast|stories|all-stories|feature-story|announcements?|events)(/|$)", re.I)
MAX_DEPTH = 4
MAX_PAGER = 20

START_URLS = {
    "registrar.oregonstate.edu": ["https://registrar.oregonstate.edu/",
                                  "https://registrar.oregonstate.edu/osu-academic-calendar",
                                  "https://registrar.oregonstate.edu/forms"],
    "catalog.oregonstate.edu": ["https://catalog.oregonstate.edu/", "https://catalog.oregonstate.edu/courses/",
                                "https://catalog.oregonstate.edu/regulations/"],
    "ecampus.oregonstate.edu": ["https://ecampus.oregonstate.edu/students/current/",
                                "https://ecampus.oregonstate.edu/ask-ecampus/"],
    "advising.oregonstate.edu": ["https://advising.oregonstate.edu/"],
    "financialaid.oregonstate.edu": ["https://financialaid.oregonstate.edu/"],
    "finance.oregonstate.edu": ["https://finance.oregonstate.edu/student-accounts"],
    "ds.oregonstate.edu": ["https://ds.oregonstate.edu/"],
    "studentlife.oregonstate.edu": ["https://studentlife.oregonstate.edu/"],
    "scs.oregonstate.edu": ["https://scs.oregonstate.edu/"],
    "studenthealth.oregonstate.edu": ["https://studenthealth.oregonstate.edu/"],
    "counseling.oregonstate.edu": ["https://counseling.oregonstate.edu/"],
    "uhds.oregonstate.edu": ["https://uhds.oregonstate.edu/"],
    "library.oregonstate.edu": ["https://library.oregonstate.edu/"],
    "technology.oregonstate.edu": ["https://technology.oregonstate.edu/", "https://technology.oregonstate.edu/help-desks"],
    "engineering.oregonstate.edu": ["https://engineering.oregonstate.edu/academics",
                                    "https://engineering.oregonstate.edu/student-life/student-experience/support"],
    "map.oregonstate.edu": ["https://map.oregonstate.edu/"],
    "success.oregonstate.edu": ["https://success.oregonstate.edu/"],
    "holds.oregonstate.edu": ["https://holds.oregonstate.edu/"],
    "care.oregonstate.edu": ["https://care.oregonstate.edu/"],
    "basicneeds.oregonstate.edu": ["https://basicneeds.oregonstate.edu/"],
    # Tier 2
    "scholarships.oregonstate.edu": ["https://scholarships.oregonstate.edu/"],
    "food.oregonstate.edu": ["https://food.oregonstate.edu/", "https://food.oregonstate.edu/menus-and-nutrition"],
    "transportation.oregonstate.edu": ["https://transportation.oregonstate.edu/", "https://transportation.oregonstate.edu/parking"],
    "writingcenter.oregonstate.edu": ["https://writingcenter.oregonstate.edu/"],
    "career.oregonstate.edu": ["https://career.oregonstate.edu/", "https://career.oregonstate.edu/students"],
    "experience.oregonstate.edu": ["https://experience.oregonstate.edu/career"],
}
# Tier 2b: a whole-site rule starts at the home page; a college's home page is not student-facing, so colleges start
# at their student-facing pages.
START_URLS.update({h: [f"https://{h}/"] for h in TIER2B
                   if in_scope(f"https://{h}/", (TIER2B,)) and h != "gradschool.oregonstate.edu"})
START_URLS.update({
    "business.oregonstate.edu": ["https://business.oregonstate.edu/programs",
                                 "https://business.oregonstate.edu/programs/undergraduate"],
    "liberalarts.oregonstate.edu": ["https://liberalarts.oregonstate.edu/academics",
                                    "https://liberalarts.oregonstate.edu/advising"],
    "health.oregonstate.edu": ["https://health.oregonstate.edu/academics", "https://health.oregonstate.edu/advising"],
    "agsci.oregonstate.edu": ["https://agsci.oregonstate.edu/internships"],
    "education.oregonstate.edu": ["https://education.oregonstate.edu/advising"],
    "ceoas.oregonstate.edu": ["https://ceoas.oregonstate.edu/academics"],
    "www.forestry.oregonstate.edu": ["https://www.forestry.oregonstate.edu/students",
                                     "https://www.forestry.oregonstate.edu/academics"],
    "science.oregonstate.edu": ["https://science.oregonstate.edu/academics"],
    "vetmed.oregonstate.edu": ["https://vetmed.oregonstate.edu/academics"],
    "pharmacy.oregonstate.edu": ["https://pharmacy.oregonstate.edu/programs-admissions"],
    "math.oregonstate.edu": ["https://math.oregonstate.edu/undergraduate"],
    "ib.oregonstate.edu": ["https://ib.oregonstate.edu/undergraduate"],
})

# Phase name -> {host: (page cap, document cap)}; None = no cap.
PHASES = {
    "pilot": {"registrar.oregonstate.edu": (80, 15), "catalog.oregonstate.edu": (60, 5),
              "ecampus.oregonstate.edu": (60, 10)},
    "tier1": {h: (None, None) for h in [
        "registrar.oregonstate.edu", "financialaid.oregonstate.edu", "finance.oregonstate.edu", "ds.oregonstate.edu",
        "studentlife.oregonstate.edu", "scs.oregonstate.edu", "studenthealth.oregonstate.edu",
        "counseling.oregonstate.edu", "uhds.oregonstate.edu", "advising.oregonstate.edu", "success.oregonstate.edu",
        "holds.oregonstate.edu", "care.oregonstate.edu", "basicneeds.oregonstate.edu", "technology.oregonstate.edu",
        "library.oregonstate.edu", "ecampus.oregonstate.edu", "engineering.oregonstate.edu",
        "catalog.oregonstate.edu", "map.oregonstate.edu"]},
}
# Tier 2 (docs/tier2-plan.md): a ~150-page pilot, then the rest. Run only after the owner approves each.
PHASES["tier2-pilot"] = {"scholarships.oregonstate.edu": (13, 3), "writingcenter.oregonstate.edu": (28, 3),
                         "career.oregonstate.edu": (45, 4), "transportation.oregonstate.edu": (40, 4),
                         "food.oregonstate.edu": (23, 1), "experience.oregonstate.edu": (1, 0)}
PHASES["tier2"] = {h: (None, None) for h in PHASES["tier2-pilot"]}
# Tier 2b (docs/tier2b-plan.md): a ~150-page pilot across all three groups (pages, PDFs per site), then the rest.
PHASES["tier2b-pilot"] = {
    "admissions.oregonstate.edu": (12, 1), "graduate.oregonstate.edu": (8, 1),
    "internationalservices.oregonstate.edu": (6, 1), "intoosu.oregonstate.edu": (4, 0), "transfer.oregonstate.edu": (4, 1),
    "summer.oregonstate.edu": (3, 0), "commencement.oregonstate.edu": (3, 0), "honors.oregonstate.edu": (5, 1),
    "clubs.oregonstate.edu": (10, 0), "asosu.oregonstate.edu": (6, 1), "recsports.oregonstate.edu": (5, 1),
    "mu.oregonstate.edu": (3, 0), "familyresources.oregonstate.edu": (4, 1), "diversity.oregonstate.edu": (4, 0),
    "cape.oregonstate.edu": (4, 1), "eoa.oregonstate.edu": (4, 1), "publicsafety.oregonstate.edu": (4, 1),
    "veterans.oregonstate.edu": (5, 1), "undergradresearch.oregonstate.edu": (3, 0),
    "coreeducation.oregonstate.edu": (3, 1), "see.oregonstate.edu": (6, 0), "policy.oregonstate.edu": (5, 1),
    "business.oregonstate.edu": (5, 1), "liberalarts.oregonstate.edu": (6, 1), "health.oregonstate.edu": (6, 1),
    "agsci.oregonstate.edu": (4, 0), "education.oregonstate.edu": (3, 1), "ceoas.oregonstate.edu": (3, 0),
    "www.forestry.oregonstate.edu": (3, 1), "science.oregonstate.edu": (4, 1), "vetmed.oregonstate.edu": (2, 0),
    "pharmacy.oregonstate.edu": (3, 1), "math.oregonstate.edu": (3, 0), "ib.oregonstate.edu": (3, 0),
}
PHASES["tier2b"] = {h: (None, None) for h in PHASES["tier2b-pilot"]}
# A re-crawl revisits everything already fetched on the approved hosts (see Crawler._start_run). Tier 2b joined it
# after its full crawl finished (2026-10-29).
PHASES["recrawl"] = {**PHASES["tier1"], **PHASES["tier2"], **PHASES["tier2b"]}


def canonical_form(url: str) -> str:
    """https, lowercase host, no fragment; only a Drupal-style ?page=N survives (anything else is a filter)."""
    p = urlsplit(normalize_url(url))
    scheme = "https" if (p.hostname or "").endswith("oregonstate.edu") else p.scheme
    query = ""
    q = parse_qs(p.query)
    if list(q) == ["page"] and q["page"][0].isdigit() and 0 < int(q["page"][0]) <= MAX_PAGER:
        query = f"page={int(q['page'][0])}"
    return urlunsplit((scheme, p.netloc, p.path, query, ""))


def is_pdf(url: str) -> bool:
    return urlsplit(url).path.lower().endswith(".pdf")


def skip_reason_for(url: str) -> str | None:
    reason = classify_url(url)
    if reason:
        return reason
    path = urlsplit(url).path.lower()
    if any(under(path, p) for p in NEWS) or TIER3_SEGMENT_RE.search(path):
        return "tier3"
    if is_asset(url):
        return "asset"
    if "@" in path:
        return "not_page"  # an email address written as a relative link ("student.orgs@oregonstate.edu")
    if path.startswith("/cdn-cgi/"):
        return "not_page"  # Cloudflare's email-protection and other service endpoints
    if re.search(r"\.(xml|txt|rss|ics|json)$|/feed/?$|/rss/?$", path):
        return "not_page"  # sitemaps, feeds and calendar exports
    return None


def iso_date(value: str | None) -> str | None:
    """Sitemap lastmod ("2026-09-04T16:34Z") or an HTTP date ("Thu, 22 Oct 2026 16:35:38 GMT") -> ISO 8601 UTC."""
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).astimezone(timezone.utc).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        pass
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)  # a bare sitemap date is a UTC date, not local time
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def menu_size(tree: list[dict]) -> int:
    return sum(1 + menu_size(i["children"]) for i in tree)


def nav_path(tree: list[dict] | None, *urls: str) -> list[str] | None:
    """Labels from the menu's top level down to the item that links to this page, if the menu has it."""
    wanted = {canonical_form(u) for u in urls if u}
    for item in tree or []:
        if item["url"] and canonical_form(item["url"]) in wanted:
            return [item["text"]]
        below = nav_path(item["children"], *urls)
        if below:
            return [item["text"]] + below
    return None


def page_hop_check(url: str) -> str | None:
    """Applied to a page URL and to every redirect target: skip rules plus path scope."""
    return skip_reason_for(url) or (None if in_scope(url, (SCOPE,)) else "out_of_scope")


def robots_tokens(directives: str) -> set[str]:
    return {t for t in re.split(r"[,\s]+", directives.lower()) if t}


class Crawler:
    def __init__(self, phase: str):
        self.settings = load_settings()
        if not self.settings.contact_email:
            sys.exit("Set contact_email in crawler.toml first (see crawler.example.toml). The User-Agent must name a contact.")
        self.phase = phase
        self.caps = PHASES[phase]
        self.hosts = list(self.caps)
        self.con = db.connect()
        allowed = set(self.hosts) | {a for h in self.hosts for a in ALIASES.get(h, [])}
        self.fetcher = PoliteFetcher(self.settings, allowed_hosts=allowed, log_name=f"crawl-{phase}.jsonl")
        self.last_global = 0.0
        self.counts = defaultdict(int)
        self.run_id = self._start_run()

    # ---- run bookkeeping -------------------------------------------------------------------
    def _start_run(self) -> int:
        row = self.con.execute("SELECT id FROM crawl_runs WHERE phase=? AND finished_at IS NULL ORDER BY id DESC",
                               (self.phase,)).fetchone()
        if row:
            print(f"Resuming run {row['id']} ({self.phase})")
            run_id = row["id"]
        else:
            cur = self.con.execute("INSERT INTO crawl_runs(phase, started_at, user_agent, hosts) VALUES (?,?,?,?)",
                                   (self.phase, now_iso(), self.settings.user_agent, json.dumps(self.hosts)))
            run_id = cur.lastrowid
            if self.phase == "recrawl":
                # Put every stored page and PDF back in the queue. handle() then skips what the sitemap says is
                # unchanged without a request, and asks the server conditionally (ETag / Last-Modified) for the rest.
                marks = ",".join("?" * len(self.hosts))
                # Errors (a 404, a timeout) get one more try each run: a page that comes back is picked up again.
                n = self.con.execute(f"UPDATE frontier SET state='queued' WHERE state IN ('fetched','not_modified','error')"
                                     f" AND domain IN ({marks})", self.hosts).rowcount
                print(f"Re-crawl: {n} URLs queued again")
            self.con.commit()
        self.seed()  # idempotent, so an interrupted seed is completed on resume
        return run_id

    def seed(self):
        """Start URLs first, then each host's in-scope sitemap URLs in round-robin order across sections."""
        for host in self.hosts:
            for u in START_URLS.get(host, []):
                db.enqueue(self.con, canonical_form(u), host, "seed", priority=0)
            listing = DISCOVERY_DIR / f"sitemap-urls-{host}.txt"
            if not listing.exists():
                continue
            by_section = defaultdict(list)
            for line in listing.read_text(encoding="utf-8").splitlines():
                loc, _, lastmod = line.partition("\t")
                url = canonical_form(canonical_host(loc))
                reason = skip_reason_for(url)
                if reason:
                    db.log_skip(self.con, url, reason, "listed in sitemap; not fetched", None)
                    continue
                if not in_scope(url, (SCOPE,)):
                    continue
                segs = [s for s in urlsplit(url).path.split("/") if s]
                by_section["/".join(segs[:2])].append((url, lastmod or None))
            groups = list(by_section.values())
            while any(groups):
                for g in groups:
                    if g:
                        url, lastmod = g.pop(0)
                        if not db.enqueue(self.con, url, host, "sitemap", priority=2, sitemap_lastmod=lastmod) and lastmod:
                            # Known URL: keep its sitemap date current, so a re-crawl can tell what changed.
                            self.con.execute("UPDATE frontier SET sitemap_lastmod=? WHERE url=?", (lastmod, url))
        self.con.commit()

    # ---- scheduling ------------------------------------------------------------------------
    def _under_cap(self, host: str, kind: str) -> bool:
        page_cap, doc_cap = self.caps[host]
        cap = page_cap if kind == "page" else doc_cap
        if cap is None:
            return True
        done = self.con.execute(
            "SELECT COUNT(*) FROM frontier WHERE domain=? AND kind=? AND state NOT IN ('queued','skipped')",
            (host, kind)).fetchone()[0]
        return done < cap

    def _next(self):
        """The queued URL on whichever usable, under-cap host can be contacted soonest."""
        best = None
        for order, host in enumerate(self.hosts):
            if host in self.fetcher.blocked or host in self.fetcher.unavailable:
                continue
            for kind in ("page", "document"):
                if not self._under_cap(host, kind):
                    continue
                row = self.con.execute(
                    "SELECT * FROM frontier WHERE domain=? AND kind=? AND state='queued' ORDER BY priority, seq LIMIT 1",
                    (host, kind)).fetchone()
                if row is None:
                    continue
                key = (self.fetcher.ready_at(host), row["priority"], order)
                if best is None or key < best[0]:
                    best = (key, row)
        return best[1] if best else None

    def run(self):
        started = time.time()
        try:
            while (row := self._next()) is not None:
                wait = self.last_global + GLOBAL_GAP_S - time.time()
                if wait > 0:
                    time.sleep(wait)
                try:
                    self.handle(row)
                except (KeyboardInterrupt, SystemExit):
                    self.con.rollback()  # never keep half a page
                    raise
                except Exception:
                    # One bad page must not stop or wedge the crawl: undo its partial writes, record it, move on.
                    self.con.rollback()
                    with (LOG_DIR / "errors.log").open("a", encoding="utf-8") as f:
                        f.write(f"{now_iso()} {row['url']}\n{traceback.format_exc()}\n")
                    db.set_state(self.con, row["url"], "error", self.run_id, "processing_error")
                    self.counts["processing_error"] += 1
                    print(f"  processing error {row['url']} (see data/logs/errors.log)")
                self.last_global = time.time()
                self.con.commit()
            if not self.fetcher.unavailable:
                self.con.execute("UPDATE crawl_runs SET finished_at=? WHERE id=?", (now_iso(), self.run_id))
                self.con.commit()
        except KeyboardInterrupt:
            print("\nStopped. Run the same command again to resume.")
        finally:
            self.fetcher.close()
            for host, why in self.fetcher.blocked.items():
                self.con.execute("INSERT OR IGNORE INTO blocked_hosts(host, reason, ts) VALUES (?,?,?)",
                                 (host, why, now_iso()))
            self.con.commit()
            mins = (time.time() - started) / 60
            print(f"\n{dict(self.counts)} in {mins:.1f} min")
            if self.fetcher.blocked:
                print("BLOCKED HOSTS (stopped for good, not retried):", self.fetcher.blocked)
            if self.fetcher.unavailable:
                print("UNAVAILABLE THIS RUN (URLs left queued; rerun later to resume):", self.fetcher.unavailable)

    # ---- one URL ---------------------------------------------------------------------------
    def handle(self, row):
        url, host, kind = row["url"], row["domain"], row["kind"]
        reason = skip_reason_for(url)
        if reason:
            return self._skipped(url, reason, "matched skip rules")
        if kind == "document":
            doc = self.con.execute("SELECT purpose FROM documents WHERE url=?", (url,)).fetchone()
            if not document_in_scope(url, doc["purpose"] if doc else None):
                return self._skipped(url, "student_records", "a record about named students")
        cond = {}
        if kind == "page":
            stored = self.con.execute("SELECT retrieved_at FROM pages WHERE url=?", (url,)).fetchone()
            lastmod = iso_date(row["sitemap_lastmod"])
            fresh = stored and iso_date(stored["retrieved_at"]) >= iso_date(
                (datetime.now(timezone.utc) - timedelta(days=SITEMAP_TRUST_DAYS)).isoformat())
            if fresh and lastmod and lastmod <= iso_date(stored["retrieved_at"]):
                # The sitemap says it hasn't changed since we fetched it: no request at all. Sitemap dates aren't
                # trusted forever: after SITEMAP_TRUST_DAYS the page gets a conditional request anyway.
                db.set_state(self.con, url, "not_modified", self.run_id, "sitemap_lastmod")
                self.counts["unchanged_by_sitemap"] += 1
                return
        # Ask the server whether pages and PDFs changed since our copy (ETag / Last-Modified): a 304 has no body.
        prev = self.con.execute("SELECT etag, last_modified FROM fetch_log WHERE url=? AND http_status=200"
                                " ORDER BY id DESC LIMIT 1", (url,)).fetchone()
        if prev and prev["etag"]:
            cond["If-None-Match"] = prev["etag"]
        if prev and prev["last_modified"]:
            cond["If-Modified-Since"] = prev["last_modified"]
        try:
            res = self.fetcher.fetch(url, extra_headers=cond,
                                     max_bytes=self.settings.max_pdf_bytes if kind == "document"
                                     else self.settings.max_html_bytes,
                                     hop_check=page_hop_check if kind == "page" else skip_reason_for)
        except Skipped as e:
            if kind == "document" and e.reason == "login":
                self._login_document(url)
            return self._skipped(url, e.reason, e.detail)
        except DomainBlocked as e:
            db.set_state(self.con, url, "blocked", self.run_id)
            db.log_fetch(self.con, self.run_id, url=url, error=str(e))
            self.counts["blocked"] += 1
            print(f"  BLOCKED {host}: {e} -- stopping this host for good")
            return
        except HostUnavailable as e:
            db.log_fetch(self.con, self.run_id, url=url, error=str(e))  # the URL stays queued for a later run
            self.counts["host_unavailable"] += 1
            print(f"  UNAVAILABLE {host}: {e} -- leaving it for this run")
            return
        except httpx.HTTPError as e:
            db.set_state(self.con, url, "error", self.run_id, "network")
            db.log_fetch(self.con, self.run_id, url=url, error=repr(e))
            self.counts["error"] += 1
            print(f"  error {url}: {e!r}")
            return
        db.log_fetch(self.con, self.run_id, res, elapsed=res.elapsed)

        if res.status == 304:
            db.set_state(self.con, url, "not_modified", self.run_id)
            self.counts["not_modified"] += 1
            return
        if res.status == 401:
            if kind == "document":
                self._login_document(url)
            return self._skipped(url, "login", "HTTP 401")
        if res.status in (404, 410) and self._mark_gone(url, res.status):
            db.set_state(self.con, url, "error", self.run_id, f"http_{res.status}")
            self.counts["gone"] += 1
            print(f"  {res.status} {url} -- removed from search (page no longer published)")
            return
        if res.status != 200:
            db.set_state(self.con, url, "error", self.run_id, f"http_{res.status}")
            self.counts[f"http_{res.status}"] += 1
            print(f"  {res.status} {url}")
            return

        final_host = urlsplit(res.final_url).hostname
        if res.content_type == "application/pdf" or res.content[:5] == b"%PDF-":
            self.handle_pdf(row, res)
        elif "html" in res.content_type and kind == "page":
            self.handle_html(row, res, final_host)
        else:
            if res.raw_path:
                (ROOT / res.raw_path).unlink(missing_ok=True)
            self.con.execute("UPDATE documents SET http_status=?, retrieved_at=?, content_hash=? WHERE url=?",
                             (res.status, res.retrieved_at, res.content_hash, url))
            self._skipped(url, "unsupported_type", res.content_type)

    def _mark_gone(self, url: str, status: int) -> bool:
        """A stored page or PDF that OSU took down: drop its chunks and dates so it can't be cited, keep the record."""
        gone = False
        for table, key in (("pages", "page_id"), ("documents", "document_id")):
            row = self.con.execute(f"SELECT id FROM {table} WHERE url=? AND gone_at IS NULL", (url,)).fetchone()
            if row:
                self.con.execute(f"DELETE FROM chunks WHERE {key}=?", (row["id"],))
                self.con.execute(f"DELETE FROM dates WHERE {key}=?", (row["id"],))
                self.con.execute(f"UPDATE {table} SET gone_at=?, http_status=? WHERE id=?", (now_iso(), status, row["id"]))
                gone = True
        return gone

    def _skipped(self, url: str, reason: str, detail: str = ""):
        db.set_state(self.con, url, "skipped", self.run_id, reason)
        db.log_skip(self.con, url, reason, detail, self.run_id)
        self.counts[f"skip_{reason}"] += 1

    def _login_document(self, url: str):
        db.upsert_document(self.con, {"url": url, "kind": "login_required"}, authoritative=True)

    def handle_html(self, row, res, final_host: str):
        url = row["url"]
        ex = extract_html(res.content, res.final_url)
        tokens = robots_tokens(ex.meta_robots + "," + res.headers.get("x-robots-tag", ""))
        noindex, nofollow = bool(tokens & {"noindex", "none"}), bool(tokens & {"nofollow", "none"})
        page_id = None
        if noindex:
            if res.raw_path:
                (ROOT / res.raw_path).unlink(missing_ok=True)
            self._skipped(url, "noindex", ",".join(sorted(tokens)))
        else:
            canonical = canonical_form(ex.canonical_url or res.final_url)
            if urlsplit(url).query.startswith("page="):
                # Drupal pager pages (?page=N) name page 1 as canonical but hold different rows (later calendar
                # months), so each is its own page.
                canonical = url
            twin = self.con.execute("SELECT url FROM pages WHERE canonical_url=? AND url<>?", (canonical, url)).fetchone()
            if twin:
                db.set_state(self.con, url, "duplicate", self.run_id)
                db.log_skip(self.con, url, "duplicate", f"same canonical as {twin['url']}", self.run_id)
                self.counts["duplicate"] += 1
            else:
                page_id = self._store_page(row, res, ex, canonical, final_host)
        if page_id is not None:
            self._record_forms(ex, page_id, self._office(ex, row, final_host), follow=not nofollow, page_host=final_host)
        if not nofollow:
            self._follow(row, ex)

    @staticmethod
    def _office(ex, row, final_host: str) -> str | None:
        return office_for(final_host if final_host in SCOPE else row["domain"], ex.site_name)

    def _store_page(self, row, res, ex, canonical: str, final_host: str) -> int:
        url = row["url"]
        table_dates = [{**d, "source": "table"} for d in from_tables(ex.tables)]
        text_dates = [{**d, "source": "text"} for d in from_sections(ex.sections, ex.title)]
        page_type, signals = classify_page(res.final_url, ex, len(table_dates))
        course_list = ex.template == "courseleaf:course-list"
        chunks = chunk_sections(ex.sections, merge_tiny=not course_list)
        if course_list:
            # One chunk per course; put "AAE 210, INTRODUCTION TO AEROSPACE ENGINEERING, 4 Credits" in the text too.
            for c in chunks:
                if " > " in c["heading_path"]:
                    c["text"] = c["heading_path"].split(" > ")[-1] + "\n" + c["text"]
        title = ex.title
        archive = re.search(r"/archive/([\w-]+)", urlsplit(url).path)
        if archive:
            # Past calendars are all titled "Past Academic Calendar"; say which period, and flag them.
            title = f"{title} ({archive.group(1).replace('--', ' to ')})"
        # Old draft calendars ("[DRAFT] Fall Term 2022") and past term tabs ("Fall 2019") are still published;
        # treat them as archived too.
        archived = bool(archive) or bool(re.match(r"/(academic-calendar/draft-|simple-tabs/(fall|winter|spring|summer)-)",
                                                  urlsplit(url).path))
        stats = {"main_chars": len(ex.main_text), "trafilatura_chars": len(ex.trafilatura_text),
                 "sections": len(ex.sections), "chunks": len(chunks), "links": len(ex.links),
                 "main_found": ex.main_found, "canonical_tag": bool(ex.canonical_url),
                 "headings": len(ex.headings), "table_dates": len(table_dates),
                 "text_dates": len(text_dates), "redirects": res.redirects}
        rec = {
            "url": url, "canonical_url": canonical, "domain": row["domain"], "title": title,
            "archived": int(archived), "nav_path": db.to_json(nav_path(ex.nav_menu, url, canonical)),
            "breadcrumb": db.to_json(ex.breadcrumb), "headings": db.to_json(ex.heading_tree()),
            "main_text": ex.main_text, "language": ex.language,
            # OSU's Drupal sends the cache time as Last-Modified (every page "changed" today); the sitemap's
            # lastmod is the real edit date, so it wins. The raw header stays in fetch_log for conditional GETs.
            "last_modified": iso_date(row["sitemap_lastmod"] or res.headers.get("last-modified")),
            "etag": res.headers.get("etag"),
            "retrieved_at": res.retrieved_at, "content_hash": res.content_hash, "text_hash": db.sha256(ex.main_text),
            "http_status": res.status, "page_type": page_type, "page_type_signals": db.to_json(signals),
            "owning_office": self._office(ex, row, final_host), "site_name": ex.site_name,
            "platform": ex.platform, "template": ex.template, "contact_block": ex.contact_block,
            "extract_stats": db.to_json(stats), "meta_robots": ex.meta_robots, "raw_path": res.raw_path,
        }
        page_id, changed = db.upsert_page(self.con, rec)
        if changed or getattr(self, "force_children", False):
            db.replace_children(self.con, page_id=page_id, chunks=chunks, dates=table_dates + text_dates,
                                source_url=url, date_authority_value=db.date_authority(url, archived))
        db.replace_links(self.con, url, ex.links, final_host)
        if ex.nav_menu:
            # Keep the fullest menu seen on the host (a home page can carry only a secondary menu).
            prev = self.con.execute("SELECT menu FROM nav_menus WHERE host=?", (final_host,)).fetchone()
            if prev is None or menu_size(ex.nav_menu) > menu_size(json.loads(prev["menu"])):
                self.con.execute("INSERT OR REPLACE INTO nav_menus(host, from_url, menu, retrieved_at) VALUES (?,?,?,?)",
                                 (final_host, url, db.to_json(ex.nav_menu), res.retrieved_at))
        db.set_state(self.con, url, "fetched", self.run_id)
        self.counts["pages"] += 1
        print(f"  [{self.counts['pages']:>3}] {row['domain'].split('.')[0]:<10} {page_type:<9} {ex.template:<28} "
              f"{len(chunks):>2} chunks {len(table_dates) + len(text_dates):>3} dates  {url}")
        return page_id

    def _record_forms(self, ex, page_id: int, office: str | None, follow: bool, page_host: str = ""):
        nofollow_urls = {l["url"] for l in ex.links if l["nofollow"]}
        for f in ex.forms:
            if f["kind"] == "filter":
                continue
            kind = f["kind"]
            host = urlsplit(f["url"]).hostname or ""
            doc_url = canonical_form(f["url"]) if kind == "pdf" and host.endswith("oregonstate.edu") else f["url"]
            if kind == "pdf" and not document_in_scope(doc_url, f["purpose"]):
                continue  # a record about named students (minutes, election results, ...): not even its link
            # A PDF hosted by someone else (another OSU unit, another state) is not the linking office's document.
            doc_office = office if (kind != "pdf" or host == page_host) else SCOPE.get(host, {}).get("office")
            db.upsert_document(self.con, {
                "url": doc_url, "purpose": f["purpose"] or None, "kind": kind,
                "form_host": f.get("form_host"), "owning_office": doc_office, "found_on_page_id": page_id})
            # CourseLeaf offers every catalog page as "Download Page (PDF)": a copy of the HTML we already have.
            page_copy = host == "catalog.oregonstate.edu" and (f["purpose"] or "").lower().startswith("download page")
            if kind == "pdf" and host in self.hosts and follow and f["url"] not in nofollow_urls and not page_copy:
                db.enqueue(self.con, doc_url, host, "link", kind="document", priority=1)
        for l in ex.links:
            host = urlsplit(l["url"]).hostname or ""
            behind_login = host in LOGIN_HOSTS or classify_url(l["url"]) == "login"
            if behind_login and (FORMISH_RE.search(l["text"]) or SSO_FORM_PATH_RE.search(l["url"])):
                db.upsert_document(self.con, {
                    "url": l["url"], "title": l["text"][:200], "purpose": l["text"][:200], "kind": "login_required",
                    "form_host": host, "owning_office": office, "found_on_page_id": page_id})
            elif host in SHORTENER_HOSTS and re.search(r"\bforms?\b", l["text"], re.I):
                # A form behind a short link (bit.ly/...): recorded, never followed.
                db.upsert_document(self.con, {
                    "url": l["url"], "title": l["text"][:200], "purpose": l["text"][:200], "kind": "external_form",
                    "form_host": host, "owning_office": office, "found_on_page_id": page_id})

    def _follow(self, row, ex):
        depth = row["depth"] + 1
        if depth > MAX_DEPTH:
            return
        base_path = urlsplit(row["url"]).path
        for l in ex.links:
            if l["nofollow"] or is_pdf(l["url"]):
                continue
            url = canonical_form(l["url"])
            host = urlsplit(url).hostname or ""
            if host not in self.hosts:
                continue
            reason = skip_reason_for(url)
            if reason:
                db.log_skip(self.con, url, reason, f"linked from {row['url']}", self.run_id)
                continue
            if not in_scope(url, (SCOPE,)):
                continue
            pager = urlsplit(url).path == base_path and urlsplit(url).query.startswith("page=")
            priority = 0 if pager else (1 if row["priority"] == 0 and l["region"] == "main" else 3)
            db.enqueue(self.con, url, host, "link", discovered_from=row["url"], depth=depth, priority=priority)

    def handle_pdf(self, row, res):
        url = row["url"]
        tokens = robots_tokens(res.headers.get("x-robots-tag", ""))
        if tokens & {"noindex", "none"}:
            if res.raw_path:
                (ROOT / res.raw_path).unlink(missing_ok=True)
            return self._skipped(url, "noindex", "X-Robots-Tag " + ",".join(sorted(tokens)))
        linked = self.con.execute(
            "SELECT d.id, d.purpose, d.owning_office FROM documents d WHERE d.url=?", (url,)).fetchone()
        if (urlsplit(url).hostname == "catalog.oregonstate.edu" and linked
                and (linked["purpose"] or "").lower().startswith("download page")):
            # A print copy of a catalog page we store as HTML: keep the row, not a second copy of the text.
            self.con.execute("DELETE FROM chunks WHERE document_id=?", (linked["id"],))
            self.con.execute("DELETE FROM dates WHERE document_id=?", (linked["id"],))
            self.con.execute("UPDATE documents SET text=NULL WHERE id=?", (linked["id"],))
            return self._skipped(url, "catalog_page_pdf", "print copy of an HTML catalog page")
        info = read_pdf(res.content)
        # The linking page's words ("Examination for Credit or Waiver") name a form better than PDF metadata.
        purpose = linked["purpose"] if linked else None
        title = purpose if good_title(purpose) else (info["title"] or purpose)
        rec = {
            "url": url, "title": title or None, "kind": "fillable_pdf" if info["fillable"] else "pdf",
            "owning_office": (linked["owning_office"] if linked else None) or SCOPE.get(row["domain"], {}).get("office"),
            "http_status": res.status, "retrieved_at": res.retrieved_at,
            "last_modified": res.headers.get("last-modified"), "content_hash": res.content_hash,
            "page_count": info["page_count"], "needed_ocr": int(info["needs_ocr"]), "text": info["text"],
            "raw_path": res.raw_path,
        }
        doc_id = db.upsert_document(self.con, rec, authoritative=True)
        if info["needs_ocr"]:
            # A scanned PDF: no OCR (owner's decision). Students get a link, not searchable text.
            db.add_link_only(self.con, url, title, "scanned PDF, OCR skipped", rec["owning_office"])
            db.replace_children(self.con, document_id=doc_id, chunks=[], dates=[], source_url=url)
            db.set_state(self.con, url, "fetched", self.run_id)
            self.counts["documents_link_only"] += 1
            return
        sections = pdf_sections(title, info["pages"], info["items"])
        chunks = chunk_sections(sections)
        dates = [{**d, "source": "text"} for d in from_sections(sections, title or "")]
        db.replace_children(self.con, document_id=doc_id, chunks=chunks, dates=dates, source_url=url)
        db.set_state(self.con, url, "fetched", self.run_id)
        self.counts["documents"] += 1
        flag = " NEEDS-OCR" if info["needs_ocr"] else ""
        print(f"  [pdf] {info['page_count']:>3}p {rec['kind']:<12}{flag} {url}")


def reprocess(phase: str, state: str, like: str, kind: str = "%"):
    """Re-run extraction for already-downloaded URLs from their raw files in data/raw. Makes no requests."""
    c = Crawler.__new__(Crawler)
    c.settings, c.phase, c.caps = load_settings(), phase, PHASES[phase]
    c.hosts, c.con, c.counts, c.fetcher = list(c.caps), db.connect(), defaultdict(int), None
    c.force_children = True  # rebuild chunks and dates even when the page text is unchanged
    c.run_id = c.con.execute("SELECT id FROM crawl_runs WHERE phase=? ORDER BY id DESC", (phase,)).fetchone()["id"]
    rows = c.con.execute("SELECT * FROM frontier WHERE state=? AND url LIKE ? AND kind LIKE ?",
                         (state, like, kind)).fetchall()
    for row in rows:
        url, kind = row["url"], row["kind"]
        # Rules may have tightened since the fetch: drop what is now out of scope instead of re-storing it.
        if kind == "document" and drop_document(c.con, url, c.run_id):
            print(f"  removed (now student_records): {url}")
            continue
        reason = page_hop_check(url) if kind == "page" else skip_reason_for(url)
        if reason:
            c.con.execute("UPDATE documents SET found_on_page_id=NULL WHERE found_on_page_id IN"
                          " (SELECT id FROM pages WHERE url=?)", (url,))
            c.con.execute("DELETE FROM pages WHERE url=?", (url,))  # chunks and dates cascade
            c.con.execute("DELETE FROM links WHERE from_url=?", (url,))
            db.set_state(c.con, url, "skipped", c.run_id, reason)
            db.log_skip(c.con, url, reason, "removed on reprocess: now excluded", c.run_id)
            c.con.commit()
            print(f"  removed (now {reason}): {url}")
            continue
        ext = ".pdf" if kind == "document" else ".html"
        raw = RAW_DIR / urlsplit(url).hostname / (hashlib.sha256(url.encode()).hexdigest()[:24] + ext)
        log = c.con.execute("SELECT * FROM fetch_log WHERE url=? AND http_status=200 ORDER BY id DESC", (url,)).fetchone()
        if not raw.exists() or log is None:
            print(f"  no raw copy for {url}; leaving it")
            continue
        content = raw.read_bytes()
        res = FetchResult(url, log["final_url"] or url, 200,
                          {"content-type": "application/pdf" if kind == "document" else "text/html",
                           "last-modified": log["last_modified"], "etag": log["etag"]},
                          content, log["fetched_at"], hashlib.sha256(content).hexdigest(),
                          str(raw.relative_to(ROOT)), elapsed=log["elapsed_s"])
        if kind == "document":
            c.handle_pdf(row, res)
        else:
            c.handle_html(row, res, urlsplit(res.final_url).hostname)
        c.con.commit()
    print(dict(c.counts))


def drop_document(con, url: str, run_id: int | None) -> bool:
    """Take a stored PDF that the document rules now exclude out of the database (text, chunks, dates). Its saved copy
    in data/raw stays (owner's rule, 2026-10-29). Makes no requests."""
    row = con.execute("SELECT id, purpose, raw_path FROM documents WHERE url=?", (url,)).fetchone()
    if document_in_scope(url, row["purpose"] if row else None):
        return False
    if row:
        con.execute("DELETE FROM documents WHERE id=?", (row["id"],))  # chunks and dates cascade; data/raw is kept
    if con.execute("SELECT 1 FROM frontier WHERE url=?", (url,)).fetchone():
        db.set_state(con, url, "skipped", run_id, "student_records")
        db.log_skip(con, url, "student_records", "removed: a record about named students", run_id)
    con.commit()
    return True


def prune_documents() -> dict:
    """Apply the document rules to everything stored so far (PDFs and link-only records). Offline."""
    con = db.connect()
    run = con.execute("SELECT id FROM crawl_runs ORDER BY id DESC").fetchone()
    urls = {r["url"] for r in con.execute("SELECT url FROM documents WHERE kind IN ('pdf', 'fillable_pdf')")}
    urls |= {r["url"] for r in con.execute("SELECT url FROM frontier WHERE kind='document' AND state != 'skipped'")}
    removed = defaultdict(int)
    for url in sorted(urls):
        if drop_document(con, url, run["id"] if run else None):
            removed[urlsplit(url).hostname] += 1
    return dict(removed)


TIER2_ENDED = LOG_DIR / "tier2-ended.json"


def resume_tier2(now: datetime | None = None) -> int:
    """Finish Tier 2 after the rate-limit pause (owner's decision, 2026-10-23):

    - nothing is sent before the all-of-OSU pause in data/logs/cooldown.json has ended;
    - the global pace must be at least 3 s between any two requests to OSU;
    - only the five Tier 2 sites blocked by the 2026-10-23 429s are unblocked;
    - if any 429 or challenge recurs, the crawler pauses all of OSU at once and Tier 2 ends for good
      (data/logs/tier2-ended.json; this command then refuses to run again).
    Returns a process exit code.
    """
    from .scope import TIER2
    now = now or datetime.now(timezone.utc)
    if TIER2_ENDED.exists():
        print(f"Tier 2 has ended and will not resume: {TIER2_ENDED.read_text()}")
        return 2
    cooldown_path = LOG_DIR / "cooldown.json"
    cooldown = json.loads(cooldown_path.read_text()) if cooldown_path.exists() else {}
    pause = cooldown.get("oregonstate.edu")
    if pause and now < datetime.fromisoformat(pause["until"]):
        left = datetime.fromisoformat(pause["until"]) - now
        print(f"OSU is paused until {pause['until']} ({left.total_seconds() / 3600:.1f} h left). Nothing was sent.")
        return 3
    settings = load_settings()
    if settings.min_global_delay_s < 3.0:
        print(f"min_global_delay_s is {settings.min_global_delay_s}; it must be at least 3 s. Nothing was sent.")
        return 4

    # Unblock exactly the sites the 2026-10-23 rate limit blocked, and say so in the log.
    blocked_path = LOG_DIR / "blocked.json"
    blocked = json.loads(blocked_path.read_text()) if blocked_path.exists() else {}
    rate_limited = [h for h in TIER2 if "HTTP 429" in blocked.get(h, "") or "challenge" in blocked.get(h, "")]
    for h in rate_limited:
        why = blocked.pop(h)
        with (LOG_DIR / "crawl-tier2.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"event": "unblocked", "host": h, "ts": now_iso(), "previous_block": why,
                                "by": "project owner, 2026-10-23: resume after the pause at a 3 s global pace"}) + "\n")
    blocked_path.write_text(json.dumps(blocked, indent=1))
    con = db.connect()
    marks = ",".join("?" * len(rate_limited)) or "''"
    con.execute(f"DELETE FROM blocked_hosts WHERE host IN ({marks})", rate_limited)
    # The five URLs that got the 429 were never fetched; put them back in the queue.
    con.execute(f"UPDATE frontier SET state='queued' WHERE state='blocked' AND domain IN ({marks})", rate_limited)
    # The pilot (run 3) is superseded by the full Tier 2 run.
    con.execute("UPDATE crawl_runs SET finished_at=? WHERE phase='tier2-pilot' AND finished_at IS NULL", (now_iso(),))
    con.commit()
    print(f"Unblocked {len(rate_limited)} Tier 2 sites: {', '.join(rate_limited)}")

    crawler = Crawler("tier2")
    crawler.run()
    after = json.loads(cooldown_path.read_text()) if cooldown_path.exists() else {}
    new_pause = after.get("oregonstate.edu")
    if new_pause and new_pause.get("set_at", "") > now.isoformat(timespec="seconds"):
        TIER2_ENDED.write_text(json.dumps({"ended_at": now_iso(), "reason": new_pause["reason"]}, indent=1))
        print(f"\nA 429/challenge recurred: all of OSU is paused until {new_pause['until']} and Tier 2 has ENDED.")
        return 5
    return 0


# 2026-10-29: OSU's own "Access denied" pages that the old 403 check misread as blocks (crawl-policy.md §8).
TIER2B_FALSE_STOPS = {
    "commencement.oregonstate.edu": "https://commencement.oregonstate.edu/2021-commencement",
    "familyresources.oregonstate.edu": "https://familyresources.oregonstate.edu/about-us",
    "pharmacy.oregonstate.edu": "https://pharmacy.oregonstate.edu/student-experience/our-campuses",
}


def _keep_awake(on: bool):
    """Ask Windows not to idle-sleep while this process crawls (no setting changes; ends with the process)."""
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | (0x00000001 if on else 0))


def resume_tier2b(now: datetime | None = None) -> int:
    """Finish Tier 2b after the 2026-10-29 false-alarm pause (owner's decision, 2026-10-29):

    - nothing is sent before the all-of-OSU pause ends, below a 3 s global pace, or while another crawl runs;
    - only the three false stops are cleared, and only while their recorded block is that day's 403;
      their three unpublished pages are marked skipped, never retried;
    - a new pause or block during the run returns 5, so Tier 2b is not added to the weekly re-crawl.
    Returns a process exit code.
    """
    now = now or datetime.now(timezone.utc)
    cooldown_path = LOG_DIR / "cooldown.json"
    cooldown = json.loads(cooldown_path.read_text()) if cooldown_path.exists() else {}
    pause = cooldown.get("oregonstate.edu")
    if pause and now < datetime.fromisoformat(pause["until"]):
        left = datetime.fromisoformat(pause["until"]) - now
        print(f"OSU is paused until {pause['until']} ({left.total_seconds() / 3600:.1f} h left). Nothing was sent.")
        return 3
    settings = load_settings()
    if settings.min_global_delay_s < 3.0:
        print(f"min_global_delay_s is {settings.min_global_delay_s}; it must be at least 3 s. Nothing was sent.")
        return 4
    if (LOG_DIR / "crawler.lock").exists():
        print(f"{LOG_DIR / 'crawler.lock'} exists: another crawl is running. Nothing was sent.")
        return 6

    blocked_path = LOG_DIR / "blocked.json"
    blocked = json.loads(blocked_path.read_text()) if blocked_path.exists() else {}
    cleared = [h for h, url in TIER2B_FALSE_STOPS.items() if blocked.get(h, "").endswith(f" on {url}")]
    con = db.connect()
    run = con.execute("SELECT id FROM crawl_runs WHERE phase='tier2b' ORDER BY id DESC").fetchone()
    for h in cleared:
        why = blocked.pop(h)
        with (LOG_DIR / "crawl-tier2b.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"event": "unblocked", "host": h, "ts": now_iso(), "previous_block": why,
                                "by": "project owner, 2026-10-29: OSU's own Access denied page, not a block"}) + "\n")
        con.execute("DELETE FROM blocked_hosts WHERE host=?", (h,))
        url = TIER2B_FALSE_STOPS[h]
        db.set_state(con, url, "skipped", run["id"] if run else None, "forbidden")
        db.log_skip(con, url, "forbidden", "HTTP 403: OSU's Access denied page (unpublished)", run["id"] if run else None)
    blocked_path.write_text(json.dumps(blocked, indent=1))
    con.commit()
    print(f"Cleared {len(cleared)} false stops: {', '.join(cleared) or 'none'}")

    _keep_awake(True)
    try:
        Crawler("tier2b").run()
    finally:
        _keep_awake(False)
    after_pause = (json.loads(cooldown_path.read_text()) if cooldown_path.exists() else {}).get("oregonstate.edu")
    after_blocked = json.loads(blocked_path.read_text()) if blocked_path.exists() else {}
    if after_pause and after_pause.get("set_at", "") > now.isoformat(timespec="seconds"):
        print(f"\nA 429/challenge came back: all of OSU is paused until {after_pause['until']}. Stop and tell the owner.")
        return 5
    if set(after_blocked) - set(blocked):
        print(f"\nNew blocks: {sorted(set(after_blocked) - set(blocked))}. Stop and tell the owner.")
        return 5
    return 0


def status():
    con = db.connect()
    for r in con.execute("SELECT id, phase, started_at, finished_at FROM crawl_runs ORDER BY id"):
        print(dict(r))
    for r in con.execute("SELECT domain, kind, state, COUNT(*) n FROM frontier GROUP BY 1,2,3 ORDER BY 1,2,3"):
        print(f"  {r['domain']:<32} {r['kind']:<9} {r['state']:<13} {r['n']}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "status":
        status()
    elif cmd == "reprocess":  # python -m osu_crawl.crawl reprocess <phase> <state> <url LIKE> [page|document]
        reprocess(*sys.argv[2:6])
    elif cmd == "prune-documents":  # offline: drop stored PDFs the document rules now exclude
        print(prune_documents())
    elif cmd == "resume-tier2":  # owner-approved 2026-10-23; refuses to send anything before the pause ends
        sys.exit(resume_tier2())
    elif cmd == "resume-tier2b":  # owner-approved 2026-10-29; refuses to send anything before the pause ends
        sys.exit(resume_tier2b())
    else:
        Crawler(cmd).run()
