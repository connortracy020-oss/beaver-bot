"""Getting the site ready for a public host: the serving copy of the data, the private data archive, the port and
proxy handling, the health check, the per-visitor limit and the daily model budget. No network, no paid calls."""
import datetime
import hashlib
import io
import json
import os
import sqlite3
import tarfile
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from assistant import anthropic_provider as ap
from assistant import retrieve
from beaverbot import budget, config, slim, talk
from deploy import hostdata
from osu_crawl import db


def clean_env(**extra):
    names = ("PORT", "RENDER", "BEAVERBOT_HOST", "BEAVERBOT_PORT", "BEAVERBOT_PROXY_HOPS", "BEAVERBOT_ASK_LIMITS", "BEAVERBOT_HOSTS",
             "RENDER_EXTERNAL_HOSTNAME", "BEAVERBOT_DAILY_BUDGET_USD", "ASSISTANT_PROVIDER", "ASSISTANT_MODEL")
    env = {k: v for k, v in os.environ.items() if k not in names}
    env.update(extra)
    return mock.patch.dict(os.environ, env, clear=True)


def little_database(path: Path) -> None:
    con = db.connect(path)
    con.execute("INSERT INTO pages (id, url, domain, title, main_text, headings, retrieved_at, owning_office, raw_path, content_hash, http_status, first_seen_at) VALUES "
                "(1, 'https://example.edu/tuition', 'example.edu', 'Tuition', ?, 'Paying', '2026-10-01', 'Billing', 'raw/1.html', 'abc', 200, '2026-10-01')", ("long page text " * 400,))
    con.execute("INSERT INTO documents (id, url, title, kind, text, raw_path) VALUES (1, 'https://example.edu/a.pdf', 'A form', 'pdf', ?, 'raw/a.pdf')", ("pdf text " * 300,))
    con.execute("INSERT INTO documents (id, url, title, kind, text) VALUES (2, 'https://example.edu/b.pdf', 'A scan', 'pdf', NULL)")
    for i, text in enumerate(["Tuition is due on the first day of the term.", "A parking permit is sold online.", "Meet your advisor before you register."]):
        con.execute("INSERT INTO chunks (page_id, seq, heading_path, anchor, text, token_estimate) VALUES (1, ?, 'Paying', '', ?, 10)", (i, text))
    con.execute("INSERT INTO links (from_url, to_url, region) VALUES ('https://other.example.edu/x', 'https://example.edu/tuition', 'main')")
    con.execute("INSERT INTO dates (page_id, context, date_text, date_iso, authority) VALUES (1, 'Fall term begins', 'Sept 24', '2026-09-24', 'authoritative')")
    con.execute("CREATE TABLE IF NOT EXISTS page_categories (page_id INTEGER NOT NULL, category TEXT NOT NULL, is_primary INTEGER NOT NULL, PRIMARY KEY (page_id, category))")
    con.execute("INSERT INTO page_categories VALUES (1, 'paying', 1)")
    con.commit()
    retrieve.build_authority(con)
    con.close()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ServingCopy(unittest.TestCase):
    def test_slim_copy_keeps_what_the_site_reads_and_leaves_the_full_database_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, out = Path(tmp) / "full.sqlite", Path(tmp) / "serve" / "osu.sqlite"
            little_database(src)
            before = digest(src)
            report = slim.build(src, out)
            self.assertEqual(digest(src), before, "the full database must not change")
            self.assertEqual((report["pages"], report["chunks"], report["documents"]), (1, 3, 2))
            con = sqlite3.connect(f"file:{out.as_posix()}?mode=ro", uri=True)
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            for gone in ("links", "fetch_log", "frontier", "skips", "nav_menus", "crawl_runs"):
                self.assertNotIn(gone, tables)
            self.assertEqual(con.execute("SELECT url, title, owning_office, main_text, raw_path, content_hash FROM pages").fetchone(),
                             ("https://example.edu/tuition", "Tuition", "Billing", None, None, ""))
            # the site counts PDFs that had text, without ever reading the text
            self.assertEqual(con.execute("SELECT COUNT(*) FROM documents WHERE kind LIKE '%pdf%' AND gone_at IS NULL AND text IS NOT NULL").fetchone()[0], 1)
            self.assertEqual(con.execute("SELECT MAX(LENGTH(text)) FROM documents").fetchone()[0], 0)
            self.assertEqual([r[0] for r in con.execute("SELECT c.text FROM chunks_fts f JOIN chunks c ON c.id = f.rowid WHERE chunks_fts MATCH 'parking'")],
                             ["A parking permit is sold online."])
            self.assertEqual(con.execute("SELECT sites FROM page_authority").fetchone()[0], 1)
            self.assertEqual(con.execute("SELECT date_iso, source_title FROM deadlines").fetchone(), ("2026-09-24", "Tuition"))
            self.assertEqual(con.execute("SELECT category FROM page_categories").fetchone()[0], "paying")
            con.close()
            self.assertLess(out.stat().st_size, src.stat().st_size)

    def test_it_refuses_to_write_over_the_full_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "full.sqlite"
            little_database(src)
            with self.assertRaises(SystemExit):
                slim.build(src, src)


class DataArchive(unittest.TestCase):
    def archive(self, tmp: Path, extra: dict | None = None) -> Path:
        path = tmp / "a.tar.gz"
        with tarfile.open(path, "w:gz") as tar:
            for name in list(hostdata.FILES) + list(extra or {}):
                data = (extra or {}).get(name, name.encode())
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        return path

    def test_only_the_expected_files_are_unpacked(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            archive = self.archive(tmp, {"../escape.txt": b"x", "extra.sh": b"x"})
            self.assertEqual(sorted(hostdata.unpack(archive, tmp / "data")), sorted(hostdata.FILES))
            self.assertEqual(sorted(p.name for p in (tmp / "data").iterdir()), sorted(hostdata.FILES))
            self.assertFalse((tmp / "escape.txt").exists())

    def test_fetch_checks_the_sha_before_unpacking_and_never_runs_without_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            archive = self.archive(tmp)
            seen = {}

            def fake_download(url, token, dest):
                seen.update(url=url, token=token)
                dest.write_bytes(archive.read_bytes())

            with mock.patch.object(hostdata, "download", fake_download), mock.patch("assistant.semantic._model", lambda: None):
                with clean_env(DATA_URL="https://example.com/a.tar.gz", DATA_SHA256="0" * 64):
                    with self.assertRaises(SystemExit):
                        hostdata.fetch(tmp / "bad")
                self.assertEqual(list((tmp / "bad").iterdir()), [], "a download that fails the check leaves nothing behind")
                with clean_env(DATA_URL="https://example.com/a.tar.gz"):
                    with self.assertRaises(SystemExit):
                        hostdata.fetch(tmp / "none")
                with clean_env(DATA_URL="https://example.com/a.tar.gz", DATA_SHA256=digest(archive).upper(), DATA_TOKEN="t0ken"):
                    hostdata.fetch(tmp / "good")
            self.assertEqual(seen, {"url": "https://example.com/a.tar.gz", "token": "t0ken"})
            self.assertEqual(sorted(p.name for p in (tmp / "good").iterdir()), sorted(hostdata.FILES))

    def test_the_token_is_not_passed_on_to_another_host_and_plain_http_is_refused(self):
        req = urllib.request.Request("https://api.example.com/asset/1")
        req.add_unredirected_header("Authorization", "Bearer t0ken")
        handler = hostdata._KeepTokenHome()
        away = handler.redirect_request(req, None, 302, "Found", {}, "https://storage.example.net/blob?sig=1")
        self.assertIsNone(away.get_header("Authorization"))
        self.assertNotIn("Authorization", away.unredirected_hdrs)
        with self.assertRaises(SystemExit):
            hostdata.download("http://example.com/a.tar.gz", None, Path("unused"))

    def test_private_data_stays_out_of_the_repository(self):
        ignored = (config.ROOT / ".gitignore").read_text(encoding="utf-8")
        for line in ("data/", "*.sqlite", "*.db", "*.npy", "*.tar.gz", "beaverbot.local.toml", "crawler.toml"):
            self.assertIn(line, ignored.splitlines())
        host = (config.ROOT / "render.yaml").read_text(encoding="utf-8")
        for name in ("DATA_URL", "DATA_SHA256", "DATA_TOKEN", "ANTHROPIC_API_KEY"):
            self.assertRegex(host, rf"key: {name}\n\s+sync: false", f"{name} is filled in on the host, never written here")
        self.assertNotRegex(host, r"sk-ant|ghp_|github_pat_")
        self.assertIn("healthCheckPath: /healthz", host)


class HostSettings(unittest.TestCase):
    def test_a_laptop_stays_private_and_a_host_listens_on_its_port(self):
        with clean_env():
            self.assertEqual((config.host(), config.port(), config.hosted()), ("127.0.0.1", 8765, False))
            self.assertEqual(config.ask_limits(), [(40, 60.0)])
            self.assertEqual(config.proxy_hops(), 0)
        with clean_env(PORT="10000", RENDER="true", RENDER_EXTERNAL_HOSTNAME="beaver-bot.onrender.com"):
            self.assertEqual((config.host(), config.port(), config.hosted()), ("0.0.0.0", 10000, True))
            self.assertEqual(config.ask_limits(), [(20, 600.0), (6, 30.0)])
            self.assertIn("beaver-bot.onrender.com", config.allowed_hosts())
        with clean_env(BEAVERBOT_ASK_LIMITS="nonsense"):
            self.assertEqual(config.ask_limits(), [(20, 600.0), (6, 30.0)], "a typo falls back to the careful limit")

    def test_meaning_search_has_an_off_switch_and_a_low_memory_mode(self):
        from assistant import semantic
        with clean_env(BEAVERBOT_SEMANTIC="off"), mock.patch.object(semantic, "VECTORS", config.ROOT / "README.md"),                 mock.patch.object(semantic, "IDS", config.ROOT / "README.md"), mock.patch.dict(semantic._state, {}, clear=True):
            self.assertFalse(semantic.available())
            self.assertEqual(semantic.nearest("anything"), [])
        with clean_env():
            self.assertFalse(semantic.low_memory())
        with clean_env(PORT="10000"):
            self.assertTrue(semantic.low_memory())
        with clean_env(PORT="10000", BEAVERBOT_LOW_MEMORY="off"):
            self.assertFalse(semantic.low_memory())

    def test_forwarded_headers_are_believed_only_behind_a_declared_proxy(self):
        from beaverbot.server import Handler

        class Fake:
            client_address = ("10.0.0.9", 1234)
            server = type("S", (), {"chain_noted": True})()
            headers = {"X-Forwarded-For": "6.6.6.6, 203.0.113.5, 172.16.0.1", "X-Forwarded-Proto": "https"}

        with clean_env():
            self.assertEqual(Handler.client_key(Fake()), "10.0.0.9")
            self.assertFalse(Handler.is_https(Fake()))
        with clean_env(BEAVERBOT_PROXY_HOPS="1"):
            self.assertEqual(Handler.client_key(Fake()), "172.16.0.1")
            self.assertTrue(Handler.is_https(Fake()))
        with clean_env(BEAVERBOT_PROXY_HOPS="2"):
            self.assertEqual(Handler.client_key(Fake()), "203.0.113.5", "an address the visitor typed in front is ignored")
        with clean_env(BEAVERBOT_PROXY_HOPS="5"):
            self.assertEqual(Handler.client_key(Fake()), "10.0.0.9")


class HostedServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from beaverbot.server import make_server
        cls.server = make_server("127.0.0.1", 0, quiet=True)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_health_check_answers_under_any_name_and_says_nothing_else(self):
        req = urllib.request.Request(self.base + "/healthz", headers={"Host": "10.201.3.4:10000"})
        with urllib.request.urlopen(req, timeout=10) as r:
            self.assertEqual((r.status, json.loads(r.read())), (200, {"ok": True}))
        with self.assertRaises(urllib.error.HTTPError) as other:
            urllib.request.urlopen(urllib.request.Request(self.base + "/api/config", headers={"Host": "evil.example"}), timeout=10)
        self.assertEqual(other.exception.code, 403)

    def test_each_visitor_gets_their_own_allowance(self):
        def ask(address):
            req = urllib.request.Request(self.base + "/api/ask", data=json.dumps({"question": "hi", "stream": False}).encode(),
                                         headers={"Content-Type": "application/json", "X-Forwarded-For": address})
            body = urllib.request.urlopen(req, timeout=30).read().decode("utf-8")
            return next(json.loads(line[6:]) for line in body.split("\n") if line.startswith("data: {") and '"kind"' in line).get("reason")

        with clean_env(BEAVERBOT_PROXY_HOPS="1", BEAVERBOT_ASK_LIMITS="5/600,2/30", ASSISTANT_PROVIDER="guide"), \
                mock.patch.object(budget, "log", lambda what: None):
            self.assertEqual([ask("203.0.113.50") == "slow_down" for _ in range(3)], [False, False, True], "the burst limit")
            self.assertNotEqual(ask("203.0.113.51"), "slow_down", "another visitor is not held back")
            self.assertEqual(ask("203.0.113.50"), "slow_down")


class DailyBudget(unittest.TestCase):
    def setUp(self):
        self.usage = mock.patch.dict(ap.AnthropicProvider.usage, {"calls": 0, "input_tokens": 0, "output_tokens": 0})
        self.usage.start()
        self.state = mock.patch.dict(budget._state, {"day": None, "base": 0.0, "questions": 0, "slowed": 0, "capped": 0, "told": False})
        self.state.start()
        self.quiet = mock.patch.object(budget, "log", lambda what: None)
        self.quiet.start()

    def tearDown(self):
        for p in (self.quiet, self.state, self.usage):
            p.stop()

    def spend(self, dollars: float):
        price_in = ap.PRICES[ap.DEFAULT_MODEL][0]
        ap.AnthropicProvider.usage["input_tokens"] += int(dollars / price_in * 1_000_000)

    def test_over_the_daily_budget_the_site_answers_offline_until_the_next_day(self):
        day = datetime.datetime(2026, 11, 10, 12, tzinfo=datetime.timezone.utc)
        with clean_env(ASSISTANT_PROVIDER="anthropic"):
            self.assertEqual(budget.daily_budget(), 1.0)
            self.assertEqual(budget.provider_name(day), "anthropic")
            self.spend(0.6)
            self.assertFalse(budget.capped(day))
            self.spend(0.5)
            self.assertAlmostEqual(budget.spent_today(day), 1.1, places=2)
            self.assertTrue(budget.capped(day))
            self.assertEqual(budget.provider_name(day), "guide")
            tomorrow = day + datetime.timedelta(days=1)
            self.assertEqual(budget.provider_name(tomorrow), "anthropic", "a new day starts a new budget")
            self.assertAlmostEqual(budget.spent_today(tomorrow), 0.0)
        with clean_env(ASSISTANT_PROVIDER="anthropic", BEAVERBOT_DAILY_BUDGET_USD="0"):
            self.assertEqual(budget.provider_name(), "guide", "a budget of 0 turns paid calls off")
        with clean_env(ASSISTANT_PROVIDER="guide"):
            self.spend(50)
            self.assertFalse(budget.capped(), "offline answers cost nothing, so there is nothing to cap")

    def test_a_model_without_a_listed_price_is_counted_as_expensive(self):
        with clean_env(ASSISTANT_PROVIDER="anthropic", ASSISTANT_MODEL="some-new-model"):
            self.assertEqual(budget.spent_today(), 0.0)
            ap.AnthropicProvider.usage["output_tokens"] += 100_000
            self.assertAlmostEqual(budget.spent_today(), 100_000 * budget.UNKNOWN_PRICE[1] / 1_000_000)

    def test_the_capped_reply_is_a_friendly_answer_not_an_error(self):
        answered = {"kind": "answer", "text": "Tuition is due on the first day of the term. [1]", "pages": []}
        with clean_env(ASSISTANT_PROVIDER="anthropic", ASSISTANT_ALLOW_PAID_CALLS="yes"), \
                mock.patch.object(talk, "_by_rules", lambda *a, **k: dict(answered)), \
                mock.patch.object(talk, "_by_model", side_effect=AssertionError("no paid call once the budget is used")), \
                mock.patch.object(talk.store, "available", lambda: False):
            self.assertFalse(budget.capped())
            self.spend(2)
            con = sqlite3.connect(":memory:")
            for lang in ("en", "es"):
                out = talk.converse("when is tuition due", lang=lang, con=con)
                self.assertEqual(out["kind"], "answer")
                self.assertTrue(out["text"].startswith(budget.NOTE[lang]))
                self.assertTrue(out["text"].endswith(answered["text"]))
                self.assertNotRegex(out["text"], r"(?i)\b(error|guaranteed|official)\b")

    def test_only_counts_are_logged(self):
        self.quiet.stop()
        try:
            with clean_env(ASSISTANT_PROVIDER="guide"), mock.patch("sys.stderr", new_callable=io.StringIO) as err:
                for _ in range(budget.LOG_EVERY):
                    budget.count("questions")
                budget.count("slowed")
            line = err.getvalue()
            self.assertRegex(line, r"^\[budget\] counts: questions=20 slowed=0 answered_offline=0 estimated=\$0\.0000 of \$1\.00 today\n$")
        finally:
            self.quiet.start()


if __name__ == "__main__":
    unittest.main()
