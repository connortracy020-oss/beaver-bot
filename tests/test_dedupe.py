"""Dedupe on a temporary database: identical pages and PDFs leave search once, boilerplate chunks are kept once,
text shared by a few pages stays on each, and a second run changes nothing. No network, no real data."""
import tempfile
import unittest
from pathlib import Path

from osu_crawl import db, dedupe


class Dedupe(unittest.TestCase):
    def setUp(self):
        self.con = db.connect(Path(tempfile.mkdtemp()) / "t.sqlite")

    def page(self, url, text_hash, chunks):
        pid = self.con.execute("INSERT INTO pages(url, domain, retrieved_at, first_seen_at, content_hash, http_status,"
                               " main_text, text_hash) VALUES (?, 'x.oregonstate.edu', 'now', 'now', 'c', 200, 'text', ?)",
                               (url, text_hash)).lastrowid
        for seq, text in enumerate(chunks):
            self.con.execute("INSERT INTO chunks(page_id, seq, text) VALUES (?, ?, ?)", (pid, seq, text))
        return pid

    def chunks_of(self, pid):
        return [r[0] for r in self.con.execute("SELECT text FROM chunks WHERE page_id=? ORDER BY seq", (pid,))]

    def test_identical_pages_keep_one_copy_in_search(self):
        keep = self.page("https://x.oregonstate.edu/students", "h1", ["Core education for students"])
        clone = self.page("https://x.oregonstate.edu/students-0", "h1", ["Core education for students"])
        dedupe.run(apply=True, con=self.con)
        self.assertEqual(self.chunks_of(keep), ["Core education for students"])
        self.assertEqual(self.chunks_of(clone), [])
        self.assertEqual(self.con.execute("SELECT duplicate_of FROM pages WHERE id=?", (clone,)).fetchone()[0],
                         "https://x.oregonstate.edu/students")

    def test_boilerplate_is_kept_once_and_shared_text_stays(self):
        legend = "An asterisk (*) means the course meets a Core Education requirement."
        shared = "Option requirements: BA 347, BA 348."
        pages = [self.page(f"https://x.oregonstate.edu/table-{i}", f"t{i}", [f"Table {i}", legend]
                           + ([shared] if i < 3 else [])) for i in range(6)]
        result = dedupe.run(apply=True, con=self.con)
        self.assertEqual(result["boilerplate_chunks"], 5)
        self.assertEqual(sum(legend in self.chunks_of(p) for p in pages), 1)
        self.assertEqual(sum(shared in self.chunks_of(p) for p in pages), 3)  # on 3 pages only: kept on each
        self.assertTrue(all(f"Table {i}" in self.chunks_of(p) for i, p in enumerate(pages)))

    def test_a_second_run_changes_nothing(self):
        self.page("https://x.oregonstate.edu/a", "h", ["same"])
        self.page("https://x.oregonstate.edu/a-0", "h", ["same"])
        dedupe.run(apply=True, con=self.con)
        before = self.con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        again = dedupe.run(apply=True, con=self.con)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0], before)
        self.assertEqual(again.get("pages_chunks", 0), 0)


if __name__ == "__main__":
    unittest.main()
