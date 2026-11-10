"""How each OSU site organizes its information, computed from the crawl database. Structure only, no page text.

    python -m osu_crawl.structure    # writes docs/structure-map.json and docs/structure-map.generated.md

Per host:
- navigation: the site's own main menu (two levels)
- sections: first path segment, with page counts and page types
- page types and templates
- most-linked pages: links from the *content* of other pages on the same site (menus and footers would make
  every menu item look important)
- hubs vs leaves: a hub mostly points elsewhere (many content links, little text per link); a leaf is
  a page with real text and few content links
- forms: documents by kind, and the pages that list the most forms
- outbound: other OSU sites this one links to from its content
"""
import json
import sys
from collections import Counter, defaultdict
from urllib.parse import urlsplit

from . import db
from .config import ROOT

HUB_MIN_LINKS = 15
HUB_MAX_WORDS_PER_LINK = 40
LEAF_MAX_LINKS = 3


def section_of(url: str) -> str:
    segs = [s for s in urlsplit(url).path.split("/") if s]
    return "/" + segs[0] if segs else "/"


def menu_outline(tree: list[dict], depth: int = 2) -> list[dict]:
    return [{"text": i["text"], "url": i["url"],
             "children": menu_outline(i["children"], depth - 1) if depth > 1 else [],
             "descendants": _count(i["children"])} for i in tree]


def _count(tree: list[dict]) -> int:
    return sum(1 + _count(i["children"]) for i in tree)


def build() -> dict:
    con = db.connect()
    pages = [dict(r) for r in con.execute(
        "SELECT id, url, canonical_url, domain, title, page_type, template, owning_office, archived,"
        " LENGTH(main_text) AS chars, main_text FROM pages")]
    by_url = {p["url"]: p for p in pages}
    for p in pages:
        if p["canonical_url"]:
            by_url.setdefault(p["canonical_url"], p)
        p["words"] = len((p.pop("main_text") or "").split())

    out_main = defaultdict(set)   # page url -> same-host stored pages it links to from its content
    outbound = defaultdict(Counter)
    for frm, to, region, internal in con.execute("SELECT from_url, to_url, region, is_internal FROM links"):
        if region != "main" or frm not in by_url:
            continue
        src = by_url[frm]
        target = by_url.get(to)
        if internal and target and target["url"] != src["url"]:
            out_main[src["url"]].add(target["url"])
        elif not internal:
            host = urlsplit(to).hostname or ""
            if host.endswith("oregonstate.edu"):
                outbound[src["domain"]][host] += 1

    def is_hub(p) -> bool:
        n_out = len(out_main[p["url"]])
        return n_out >= HUB_MIN_LINKS and p["words"] / max(1, n_out) <= HUB_MAX_WORDS_PER_LINK

    # "Most linked" counts links from ordinary content pages only: an A-Z index or a hub links to everything,
    # which says nothing about what the site's own writers point readers to.
    in_main = Counter()           # stored page url -> distinct same-host content pages linking to it
    for src_url, targets in out_main.items():
        if not is_hub(by_url[src_url]):
            for t in targets:
                in_main[t] += 1

    docs = [dict(r) for r in con.execute(
        "SELECT d.url, d.kind, d.title, d.purpose, d.owning_office, d.form_host, p.domain, p.url AS page_url,"
        " p.title AS page_title FROM documents d LEFT JOIN pages p ON p.id = d.found_on_page_id")]
    menus = {r["host"]: json.loads(r["menu"]) for r in con.execute("SELECT host, menu FROM nav_menus")}

    result = {"generated_from": str(db.DB_PATH.relative_to(ROOT)), "hosts": {}}
    for host in sorted({p["domain"] for p in pages}):
        hp = [p for p in pages if p["domain"] == host]
        hp_urls = {p["url"] for p in hp}
        sections = defaultdict(list)
        for p in hp:
            sections[section_of(p["url"])].append(p)
        hubs, leaves = [], []
        for p in hp:
            n_out = len(out_main[p["url"]])
            if is_hub(p):
                hubs.append((n_out, p))
            elif n_out <= LEAF_MAX_LINKS and p["words"] >= 80:
                leaves.append(p)
        host_docs = [d for d in docs if d["domain"] == host]
        form_pages = Counter((d["page_url"], d["page_title"]) for d in host_docs if d["kind"] != "pdf" or d["title"])
        result["hosts"][host] = {
            "pages": len(hp),
            "archived_pages": sum(p["archived"] for p in hp),
            "offices": dict(Counter(p["owning_office"] for p in hp).most_common()),
            "navigation": menu_outline(menus.get(host, [])),
            "sections": [{"section": s, "pages": len(ps), "page_types": dict(Counter(p["page_type"] for p in ps).most_common()),
                          "examples": [p["title"] for p in sorted(ps, key=lambda p: -in_main[p["url"]])[:3]]}
                         for s, ps in sorted(sections.items(), key=lambda kv: -len(kv[1]))],
            "page_types": dict(Counter(p["page_type"] for p in hp).most_common()),
            "templates": [{"template": t, "pages": n, "example": next(p["url"] for p in hp if p["template"] == t)}
                          for t, n in Counter(p["template"] for p in hp).most_common()],
            "most_linked": [{"url": u, "title": by_url[u]["title"], "linked_from": n, "page_type": by_url[u]["page_type"]}
                            for u, n in in_main.most_common() if u in hp_urls][:12],
            "hubs": [{"url": p["url"], "title": p["title"], "content_links": n, "words": p["words"]}
                     for n, p in sorted(hubs, key=lambda x: -x[0])][:12],
            "hub_count": len(hubs),
            "leaf_count": len(leaves),
            "forms": {
                "by_kind": dict(Counter(d["kind"] for d in host_docs).most_common()),
                "listed_on": [{"url": u, "title": t, "documents": n} for (u, t), n in form_pages.most_common(8) if u],
                "external_hosts": dict(Counter(d["form_host"] for d in host_docs
                                               if d["kind"] in ("external_form", "login_required")).most_common()),
            },
            "links_to_other_osu_sites": dict(outbound[host].most_common(10)),
        }
    totals = Counter(p["page_type"] for p in pages)
    result["totals"] = {"pages": len(pages), "documents": len(docs), "page_types": dict(totals.most_common()),
                        "documents_by_kind": dict(Counter(d["kind"] for d in docs).most_common())}
    return result


def to_markdown(m: dict) -> str:
    md = ["# Structure map: generated tables",
          "", "Built by `python -m osu_crawl.structure` from the crawl database. Structure only: URLs, titles and counts.",
          "Read [structure-map.md](structure-map.md) first; this file is the per-site detail.", ""]
    for host, h in m["hosts"].items():
        md += [f"## {host}", "",
               f"{h['pages']} pages ({h['archived_pages']} archived) · {h['hub_count']} hubs · {h['leaf_count']} leaf pages · "
               f"page types: {', '.join(f'{k} {v}' for k, v in h['page_types'].items())}", ""]
        if h["navigation"]:
            md += ["**Main menu**", ""]
            for item in h["navigation"]:
                kids = ", ".join(c["text"] for c in item["children"][:8])
                more = f" (+{len(item['children']) - 8} more)" if len(item["children"]) > 8 else ""
                md.append(f"- **{item['text']}**" + (f": {kids}{more}" if kids else ""))
            md.append("")
        md += ["**Sections** (first path segment)", "", "| section | pages | types | most-linked examples |", "|---|---|---|---|"]
        md += [f"| `{s['section']}` | {s['pages']} | {', '.join(f'{k} {v}' for k, v in s['page_types'].items())} | "
               f"{'; '.join(s['examples'])} |" for s in h["sections"][:12]]
        if len(h["sections"]) > 12:
            md.append(f"| … | {sum(s['pages'] for s in h['sections'][12:])} more pages in {len(h['sections']) - 12} sections | | |")
        md += ["", "**Most linked from other pages' content**", ""]
        md += [f"- {p['title']} ({p['linked_from']}) — {p['url']}" for p in h["most_linked"][:8]] or ["- none"]
        md += ["", "**Hubs** (many content links, little text of their own)", ""]
        md += [f"- {p['title']} — {p['content_links']} links, {p['words']} words — {p['url']}" for p in h["hubs"][:6]] or ["- none"]
        f = h["forms"]
        md += ["", "**Forms and documents**: " + (", ".join(f"{k} {v}" for k, v in f["by_kind"].items()) or "none"), ""]
        md += [f"- listed on {p['title']} ({p['documents']}) — {p['url']}" for p in f["listed_on"][:5]]
        if f["external_hosts"]:
            md.append("- form systems: " + ", ".join(f"{k} ({v})" for k, v in f["external_hosts"].items()))
        md += ["", "**Templates**: " + ", ".join(f"{t['template']} ({t['pages']})" for t in h["templates"]), ""]
        if h["links_to_other_osu_sites"]:
            md += ["**Links out to other OSU sites**: " + ", ".join(f"{k} ({v})" for k, v in h["links_to_other_osu_sites"].items()), ""]
    return "\n".join(md)


if __name__ == "__main__":
    m = build()
    (ROOT / "docs" / "structure-map.json").write_text(json.dumps(m, indent=1, ensure_ascii=False), encoding="utf-8")
    (ROOT / "docs" / "structure-map.generated.md").write_text(to_markdown(m), encoding="utf-8")
    print(f"{m['totals']['pages']} pages, {len(m['hosts'])} hosts -> docs/structure-map.json, docs/structure-map.generated.md",
          file=sys.stderr)
