"""Phase 0 discovery: robots.txt, sitemaps, link lists and start-URL checks. No page content is crawled.

    python -m osu_crawl.discover robots HOST [HOST ...]
    python -m osu_crawl.discover links URL [URL ...]       # outgoing links of one page (e.g. the A-Z index)
    python -m osu_crawl.discover sitemaps HOST [HOST ...]  # count URLs listed in each host's sitemaps
    python -m osu_crawl.discover verify URL [URL ...]      # does each start URL resolve, and where to?

Results go to data/discovery/ as JSON.
"""
import gzip
import json
import sys
from collections import Counter
from urllib.parse import urljoin, urlsplit, urlunsplit

from lxml import etree, html as lxml_html

from .config import DISCOVERY_DIR, load_settings
from .fetcher import DomainBlocked, HostUnavailable, PoliteFetcher, Skipped, classify_url

MAX_SITEMAP_FILES = 40  # per host; beyond this we extrapolate instead of fetching more


def save(name: str, data) -> None:
    DISCOVERY_DIR.mkdir(parents=True, exist_ok=True)
    (DISCOVERY_DIR / name).write_text(json.dumps(data, indent=2), encoding="utf-8")


def normalize(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path or "/", parts.query, ""))


def extract_links(page_html: bytes, base: str) -> list[dict]:
    doc = lxml_html.fromstring(page_html)
    out = []
    for a in doc.iter("a"):
        href = (a.get("href") or "").strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        out.append({"url": normalize(urljoin(base, href)), "text": " ".join(a.text_content().split()),
                    "rel": a.get("rel") or ""})
    return out


def parse_sitemap(content: bytes) -> tuple[str, list[dict]]:
    if content[:2] == b"\x1f\x8b":
        content = gzip.decompress(content)
    if not content.lstrip().startswith(b"<"):
        # Plain-text sitemap: one URL per line.
        lines = content.decode("utf-8", errors="replace").split()
        return "urlset", [{"loc": u} for u in lines if u.startswith("http")]
    root = etree.fromstring(content, parser=etree.XMLParser(resolve_entities=False, no_network=True, recover=True))
    if root is None:
        raise etree.XMLSyntaxError("unparseable sitemap", None, 0, 0)
    kind = etree.QName(root).localname  # "sitemapindex" or "urlset"
    entries = []
    for node in root:
        fields = {etree.QName(c).localname: (c.text or "").strip() for c in node}
        if fields.get("loc"):
            entries.append(fields)
    return kind, entries


def cmd_robots(fetcher: PoliteFetcher, hosts: list[str]):
    results = {}
    for host in hosts:
        try:
            rp = fetcher.robots_for("https", host)
            raw = fetcher.robots_raw.get(host, {})
            results[host] = {
                "status": raw.get("status"), "final_url": raw.get("final_url"),
                "crawl_delay": rp.crawl_delay("OSUStudentAssistantResearch") if rp else None,
                "sitemaps": list(rp.sitemaps) if rp else [],
                "effective_delay_s": fetcher.delay_for(host),
                "body": raw.get("body", ""),
            }
        except (DomainBlocked, HostUnavailable) as e:
            results[host] = {"blocked": str(e)}
        print(f"{host}: status={results[host].get('status')} delay={results[host].get('effective_delay_s')} "
              f"sitemaps={results[host].get('sitemaps')} {results[host].get('blocked', '')}")
    existing = {}
    path = DISCOVERY_DIR / "robots.json"
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
    existing.update(results)
    save("robots.json", existing)


def cmd_links(fetcher: PoliteFetcher, urls: list[str]):
    for url in urls:
        try:
            res = fetcher.fetch(url, max_bytes=load_settings().max_html_bytes)
        except (Skipped, DomainBlocked, HostUnavailable) as e:
            print(f"{url}: {e}")
            continue
        links = extract_links(res.content, res.final_url) if res.status == 200 else []
        name = "links-" + urlsplit(res.final_url).hostname + urlsplit(res.final_url).path.replace("/", "_") + ".json"
        save(name, {"url": url, "final_url": res.final_url, "status": res.status, "retrieved_at": res.retrieved_at,
                    "links": links})
        print(f"{url} -> {res.final_url} [{res.status}] {len(links)} links -> {name}")


def cmd_sitemaps(fetcher: PoliteFetcher, hosts: list[str]):
    summary = {}
    path = DISCOVERY_DIR / "sitemaps.json"
    if path.exists():
        summary = json.loads(path.read_text(encoding="utf-8"))
    for host in hosts:
        try:
            rp = fetcher.robots_for("https", host)
        except (DomainBlocked, HostUnavailable) as e:
            summary[host] = {"blocked": str(e)}
            continue
        queue = list(rp.sitemaps) if rp and list(rp.sitemaps) else [f"https://{host}/sitemap.xml"]
        seen, urls, files, errors, child_total = set(), [], [], [], 0
        while queue and len(files) < MAX_SITEMAP_FILES:
            sm = queue.pop(0)
            if sm in seen:
                continue
            seen.add(sm)
            try:
                res = fetcher.fetch(sm, max_bytes=50_000_000)
            except Skipped as e:
                errors.append({"sitemap": sm, "skipped": e.reason})
                continue
            except (DomainBlocked, HostUnavailable) as e:
                errors.append({"sitemap": sm, "blocked": str(e)})
                break
            if res.status != 200:
                errors.append({"sitemap": sm, "status": res.status})
                continue
            try:
                kind, entries = parse_sitemap(res.content)
            except etree.XMLSyntaxError as e:
                errors.append({"sitemap": sm, "parse_error": str(e)})
                continue
            files.append({"url": sm, "final_url": res.final_url, "kind": kind, "entries": len(entries)})
            if kind == "sitemapindex":
                children = [e["loc"] for e in entries]
                child_total += len(children)
                queue.extend(children)
            else:
                urls.extend(entries)
        unfetched = len(queue)
        by_host = Counter(urlsplit(u["loc"]).hostname for u in urls)
        by_section = Counter(_section(u["loc"]) for u in urls if urlsplit(u["loc"]).hostname == host)
        flagged = Counter(classify_url(u["loc"]) for u in urls)
        flagged.pop(None, None)
        per_file = (len(urls) / max(1, sum(1 for f in files if f["kind"] == "urlset")))
        summary[host] = {
            "sitemap_files_fetched": files, "errors": errors,
            "urls_listed": len(urls), "unfetched_child_sitemaps": unfetched,
            "estimated_total": round(len(urls) + unfetched * per_file),
            "urls_by_host": dict(by_host.most_common()),
            "top_sections": dict(by_section.most_common(40)),
            "would_skip": dict(flagged),
            "pdf_urls": sum(1 for u in urls if u["loc"].lower().endswith(".pdf")),
            "with_lastmod": sum(1 for u in urls if u.get("lastmod")),
        }
        DISCOVERY_DIR.mkdir(parents=True, exist_ok=True)
        (DISCOVERY_DIR / f"sitemap-urls-{host}.txt").write_text(
            "\n".join(f"{u['loc']}\t{u.get('lastmod', '')}" for u in urls), encoding="utf-8")
        save("sitemaps.json", summary)
        print(f"{host}: {len(files)} sitemap files, {len(urls)} URLs (est. {summary[host]['estimated_total']}), "
              f"skip-flagged {dict(flagged)}, errors {len(errors)}")


def _section(url: str) -> str:
    segs = [s for s in urlsplit(url).path.split("/") if s]
    return "/" + segs[0] if segs else "/"


def cmd_verify(fetcher: PoliteFetcher, urls: list[str]):
    results = {}
    path = DISCOVERY_DIR / "start-urls.json"
    if path.exists():
        results = json.loads(path.read_text(encoding="utf-8"))
    for url in urls:
        try:
            res = fetcher.fetch(url, max_bytes=load_settings().max_html_bytes)
            title = ""
            if res.status == 200 and "html" in res.content_type:
                t = lxml_html.fromstring(res.content).findtext(".//title")
                title = " ".join((t or "").split())
            robots_meta = ""
            if res.status == 200 and "html" in res.content_type:
                metas = lxml_html.fromstring(res.content).xpath("//meta[@name='robots']/@content")
                robots_meta = ",".join(metas)
            results[url] = {"status": res.status, "final_url": res.final_url, "redirects": res.redirects,
                            "title": title, "meta_robots": robots_meta,
                            "x_robots_tag": res.headers.get("x-robots-tag", ""),
                            "last_modified": res.headers.get("last-modified", ""),
                            "etag": bool(res.headers.get("etag")), "retrieved_at": res.retrieved_at}
        except Skipped as e:
            results[url] = {"skipped": e.reason, "detail": e.detail}
        except (DomainBlocked, HostUnavailable) as e:
            results[url] = {"blocked": str(e)}
        except Exception as e:  # network errors: record and move on
            results[url] = {"error": repr(e)}
        r = results[url]
        print(f"{url}: {r.get('status', r.get('skipped') or r.get('blocked') or r.get('error'))} "
              f"-> {r.get('final_url', '')} | {r.get('title', '')}")
        save("start-urls.json", results)


def cmd_text(fetcher: PoliteFetcher, urls: list[str]):
    """Main text of policy/terms pages, so they can be read and summarized in docs/crawl-policy.md."""
    import trafilatura
    out_dir = DISCOVERY_DIR / "text"
    out_dir.mkdir(parents=True, exist_ok=True)
    for url in urls:
        try:
            res = fetcher.fetch(url, max_bytes=load_settings().max_html_bytes)
        except (Skipped, DomainBlocked, HostUnavailable) as e:
            print(f"{url}: {e}")
            continue
        text = trafilatura.extract(res.content, url=res.final_url, include_tables=True, favor_recall=True) or ""
        name = (urlsplit(res.final_url).hostname + urlsplit(res.final_url).path).strip("/").replace("/", "_") + ".txt"
        (out_dir / name).write_text(f"URL: {res.final_url}\nStatus: {res.status}\nRetrieved: {res.retrieved_at}\n\n{text}",
                                    encoding="utf-8")
        print(f"{url} -> [{res.status}] {len(text)} chars -> text/{name}")


def main(argv: list[str]):
    cmd, args = argv[0], argv[1:]
    fetcher = PoliteFetcher(load_settings(), log_name="discovery.jsonl")
    try:
        {"robots": cmd_robots, "links": cmd_links, "sitemaps": cmd_sitemaps, "verify": cmd_verify,
         "text": cmd_text}[cmd](fetcher, args)
    finally:
        fetcher.close()
        if fetcher.skips:
            print(f"skipped {len(fetcher.skips)}: " + ", ".join(f"{s['reason']}:{s['url']}" for s in fetcher.skips[:10]))
        if fetcher.blocked:
            print("BLOCKED:", fetcher.blocked)


if __name__ == "__main__":
    main(sys.argv[1:])
