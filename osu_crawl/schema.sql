-- SQLite schema for the OSU public-page dataset (approved in Phase 0; created by osu_crawl/db.py).
-- The database lives at data/osu.sqlite, which is gitignored along with everything else under data/.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- One row per crawl run, for reporting and for resuming an interrupted run.
CREATE TABLE IF NOT EXISTS crawl_runs (
    id           INTEGER PRIMARY KEY,
    phase        TEXT NOT NULL,              -- pilot | tier1 | recrawl
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    user_agent   TEXT NOT NULL,
    hosts        TEXT NOT NULL,              -- JSON list of hosts in scope for this run
    notes        TEXT
);

-- Every URL we know about and what happened to it. A run resumes by picking up state='queued'.
CREATE TABLE IF NOT EXISTS frontier (
    url              TEXT PRIMARY KEY,       -- normalized: lowercase host, no fragment
    domain           TEXT NOT NULL,
    source           TEXT NOT NULL,          -- seed | sitemap | link
    discovered_from  TEXT,
    depth            INTEGER NOT NULL DEFAULT 0,
    sitemap_lastmod  TEXT,
    priority         INTEGER NOT NULL DEFAULT 5,       -- lower is fetched first
    seq              INTEGER,                          -- discovery order within a priority
    kind             TEXT NOT NULL DEFAULT 'page',     -- page | document
    state            TEXT NOT NULL DEFAULT 'queued',  -- queued | fetched | not_modified | duplicate | skipped | error | blocked
    skip_reason      TEXT,                   -- robots | noindex | login | pii | out_of_scope | tier3 | too_large | pilot_cap
    attempts         INTEGER NOT NULL DEFAULT 0,
    last_attempt_at  TEXT,
    run_id           INTEGER REFERENCES crawl_runs(id)
);
CREATE INDEX IF NOT EXISTS frontier_state ON frontier(state, domain, priority, seq);

-- Append-only HTTP log (mirrored to data/logs/*.jsonl).
CREATE TABLE IF NOT EXISTS fetch_log (
    id             INTEGER PRIMARY KEY,
    run_id         INTEGER REFERENCES crawl_runs(id),
    url            TEXT NOT NULL,
    final_url      TEXT,
    http_status    INTEGER,
    bytes          INTEGER,
    elapsed_s      REAL,
    etag           TEXT,
    last_modified  TEXT,
    content_hash   TEXT,
    error          TEXT,
    fetched_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pages (
    id                 INTEGER PRIMARY KEY,
    url                TEXT NOT NULL UNIQUE,
    canonical_url      TEXT,                 -- <link rel=canonical>, else final URL after redirects
    domain             TEXT NOT NULL,
    title              TEXT,
    breadcrumb         TEXT,                 -- JSON [{text, url}]
    headings           TEXT,                 -- JSON tree [{level, text, anchor, children}]
    nav_path           TEXT,                 -- JSON: this page's position in the site's own menu
    main_text          TEXT,
    language           TEXT,
    last_modified      TEXT,                 -- HTTP Last-Modified, else the page's own "last updated"
    etag               TEXT,
    retrieved_at       TEXT NOT NULL,
    content_hash       TEXT NOT NULL,        -- sha256 of the raw bytes
    text_hash          TEXT,                 -- sha256 of main_text: a real content change, not a nav tweak
    http_status        INTEGER NOT NULL,
    page_type          TEXT,                 -- policy | how-to | form | contact | deadline | news | faq | other
    page_type_signals  TEXT,                 -- JSON: which rules fired, for review
    owning_office      TEXT,
    site_name          TEXT,                 -- from the <title> suffix, e.g. "Office of the Registrar"
    platform           TEXT,                 -- drupal | courseleaf | ecampus | generic
    template           TEXT,                 -- layout fingerprint (e.g. drupal:basic_page, courseleaf:program)
    contact_block      TEXT,                 -- the office's contact box (address, main phone); no personal details
    extract_stats      TEXT,                 -- JSON: main_text chars, trafilatura chars, sections, links, ...
    meta_robots        TEXT,
    raw_path           TEXT,                 -- data/raw/<host>/<hash>.html, for re-parsing without re-crawling
    first_seen_at      TEXT NOT NULL,
    changed_at         TEXT,                 -- last time text_hash changed
    archived           INTEGER NOT NULL DEFAULT 0  -- a past-term page (e.g. a past academic calendar)
);
CREATE INDEX IF NOT EXISTS pages_domain ON pages(domain, page_type);

-- PDFs and forms. A web form is recorded, never submitted.
CREATE TABLE IF NOT EXISTS documents (
    id                INTEGER PRIMARY KEY,
    url               TEXT NOT NULL UNIQUE,
    title             TEXT,
    purpose           TEXT,                  -- what it is for: link text + nearby heading/sentence
    kind              TEXT NOT NULL,         -- pdf | fillable_pdf | web_form | external_form | login_required
    form_host         TEXT,                  -- e.g. qualtrics, adobe sign, dynamicforms, drupal webform
    owning_office     TEXT,
    found_on_page_id  INTEGER REFERENCES pages(id),
    http_status       INTEGER,
    retrieved_at      TEXT,
    last_modified     TEXT,
    content_hash      TEXT,
    page_count        INTEGER,
    needed_ocr        INTEGER NOT NULL DEFAULT 0,
    text              TEXT,
    raw_path          TEXT
);

-- Retrieval units. Each chunk belongs to a page or a document and keeps its heading path for citations.
CREATE TABLE IF NOT EXISTS chunks (
    id              INTEGER PRIMARY KEY,
    page_id         INTEGER REFERENCES pages(id) ON DELETE CASCADE,
    document_id     INTEGER REFERENCES documents(id) ON DELETE CASCADE,
    seq             INTEGER NOT NULL,
    heading_path    TEXT,                    -- "Financial Aid > Apply > FAFSA deadlines"
    anchor          TEXT,                    -- id of the nearest heading, for #deep-links
    text            TEXT NOT NULL,
    token_estimate  INTEGER,
    CHECK ((page_id IS NULL) <> (document_id IS NULL))
);
CREATE INDEX IF NOT EXISTS chunks_page ON chunks(page_id, seq);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text, heading_path, content = 'chunks', content_rowid = 'id', tokenize = 'porter unicode61'
);
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, text, heading_path) VALUES (new.id, new.text, new.heading_path);
END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text, heading_path) VALUES ('delete', old.id, old.text, old.heading_path);
END;
CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text, heading_path) VALUES ('delete', old.id, old.text, old.heading_path);
    INSERT INTO chunks_fts(rowid, text, heading_path) VALUES (new.id, new.text, new.heading_path);
END;

-- The link graph. `region` separates menu/footer links from links inside the content.
CREATE TABLE IF NOT EXISTS links (
    from_url     TEXT NOT NULL,
    to_url       TEXT NOT NULL,
    anchor_text  TEXT NOT NULL DEFAULT '',
    region       TEXT,                       -- main | nav | breadcrumb | sidebar | footer
    is_internal  INTEGER,                    -- same host
    nofollow     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (from_url, to_url, anchor_text)
);
CREATE INDEX IF NOT EXISTS links_to ON links(to_url);

-- Deadlines and term dates exactly as written, for later human review.
CREATE TABLE IF NOT EXISTS dates (
    id            INTEGER PRIMARY KEY,
    page_id       INTEGER REFERENCES pages(id) ON DELETE CASCADE,
    document_id   INTEGER REFERENCES documents(id) ON DELETE CASCADE,
    context       TEXT NOT NULL,             -- sentence or table row it came from
    date_text     TEXT NOT NULL,             -- as written: "Friday of week 2", "Jan. 5, 2027"
    date_iso      TEXT,                      -- only when unambiguous
    term          TEXT,                      -- "Winter 2027" when stated nearby
    heading_path  TEXT,
    cue           TEXT,                      -- event name (tables) or cue word ("deadline", "last day")
    source        TEXT,                      -- table | text
    reviewed      INTEGER NOT NULL DEFAULT 0,
    authority     TEXT NOT NULL DEFAULT 'mention',  -- authoritative (Registrar academic calendar) |
                                                     -- authoritative_archived (its past terms) | mention
    source_url    TEXT                       -- page or PDF the date was found on
);

-- Resources the assistant can link to but not read or search.
CREATE TABLE IF NOT EXISTS link_only (
    url            TEXT PRIMARY KEY,
    title          TEXT,
    reason         TEXT NOT NULL,            -- scanned PDF, OCR skipped | JavaScript app | bot protection
    owning_office  TEXT,
    added_at       TEXT NOT NULL
);

-- Each host's main menu as published, for the structure map.
CREATE TABLE IF NOT EXISTS nav_menus (
    host          TEXT PRIMARY KEY,
    from_url      TEXT NOT NULL,
    menu          TEXT NOT NULL,             -- JSON tree [{text, url, children}]
    retrieved_at  TEXT NOT NULL
);

-- Everything we chose not to fetch, and every host that refused us.
CREATE TABLE IF NOT EXISTS skips (
    url     TEXT NOT NULL,
    reason  TEXT NOT NULL,
    detail  TEXT,
    run_id  INTEGER REFERENCES crawl_runs(id),
    ts      TEXT NOT NULL,
    PRIMARY KEY (url, reason)
);
CREATE TABLE IF NOT EXISTS blocked_hosts (
    host    TEXT PRIMARY KEY,
    reason  TEXT NOT NULL,
    ts      TEXT NOT NULL
);
