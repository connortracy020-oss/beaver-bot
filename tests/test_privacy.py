"""Privacy guard: individuals' emails and direct phone numbers must never be stored; office contacts must survive.

    .venv\\Scripts\\python -m unittest discover tests

The examples use made-up names. The database check scans data/osu.sqlite when it exists (it is gitignored, so a
fresh checkout skips that part) and fails on any personal email or direct phone in any stored text field.
"""
import re
import sqlite3
import unittest
from pathlib import Path

from osu_crawl.privacy import EMAIL_TOKEN, FIELDS, PHONE_TOKEN, find_personal, is_personal_email, scrub_text

DB = Path(__file__).resolve().parent.parent / "data" / "osu.sqlite"


class ScrubText(unittest.TestCase):
    def test_person_entry_loses_phone_and_email(self):
        text = "Jordan Example, Associate Dean, 541-737-1111, jordan.example@oregonstate.edu"
        out, counts = scrub_text(text)
        self.assertNotIn("541-737-1111", out)
        self.assertNotIn("jordan.example@", out)
        self.assertIn("Jordan Example, Associate Dean", out)  # the name and title stay; only contacts go
        self.assertEqual(counts, {"email": 1, "phone": 1})

    def test_contact_name_at_number(self):
        out, _ = scrub_text("For details, contact Casey Sample at 541-737-2222 or casey.sample@oregonstate.edu.")
        self.assertIn(PHONE_TOKEN, out)
        self.assertIn(EMAIL_TOKEN, out)

    def test_staff_listing_line(self):
        out, _ = scrub_text("Education: / Robin Placeholder 104 Furman Hall Phone: 541-737-3333 Email: askcoed@oregonstate.edu")
        self.assertNotIn("541-737-3333", out)
        self.assertIn("askcoed@oregonstate.edu", out)  # a role mailbox stays

    def test_office_and_role_contacts_stay(self):
        kept = [
            "Office of the Registrar B102 Kerr Administration Phone: (541)737-4331 Fax: (541)737-8123",
            "Student Health Services: 541-737-9355. Email financial.aid@oregonstate.edu or registrars@oregonstate.edu.",
            "Please call us during our on-call hours at 541-737-2131. For urgent concerns, help is available 24/7.",
            "Contact the Bloss Hall Resident Director via email or at 541-713-5555",
            "Questions? Contact Ecampus Student Services at 800-667-1465 (option 1).",
            "Send it to cbee.advising@oregonstate.edu or accounts.receivable@oregonstate.edu.",
        ]
        for text in kept:
            with self.subTest(text=text):
                self.assertEqual(scrub_text(text)[0], text)

    def test_mailbox_classification(self):
        self.assertTrue(is_personal_email("jordan.example@oregonstate.edu"))
        self.assertTrue(is_personal_email("someone@gmail.com"))
        for role in ["financial.aid@oregonstate.edu", "cbee.advising@oregonstate.edu", "caps@oregonstate.edu",
                     "lbh.bcc@oregonstate.edu", "registrars@oregonstate.edu"]:
            self.assertFalse(is_personal_email(role), role)

    def test_scrub_is_idempotent(self):
        once, _ = scrub_text("Jordan Example, Director, 541-737-1111, jordan.example@oregonstate.edu")
        twice, counts = scrub_text(once)
        self.assertEqual(once, twice)
        self.assertFalse(counts)


@unittest.skipUnless(DB.exists(), "no local database (data/ is gitignored)")
class StoredData(unittest.TestCase):
    def test_no_personal_contacts_in_stored_text(self):
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        failures = []
        for table, key, cols in FIELDS:
            for col in cols:
                for k, value in con.execute(f"SELECT {key}, {col} FROM {table} WHERE {col} IS NOT NULL"):
                    if find_personal(value):
                        failures.append(f"{table}.{col} {key}={k}")
        self.assertEqual(failures[:20], [], f"{len(failures)} stored fields still hold individuals' contact details;"
                                            " run: python -m osu_crawl.privacy scrub")

    def test_no_first_last_osu_addresses(self):
        """An independent, blunter check: no non-role first.last@oregonstate.edu address anywhere in stored text."""
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        rx = re.compile(r"\b[a-z]+(?:\.[a-z]+)+\d*@oregonstate\.edu\b", re.IGNORECASE)
        hits = set()
        for (text,) in con.execute("SELECT text FROM chunks UNION ALL SELECT main_text FROM pages"
                                   " UNION ALL SELECT text FROM documents WHERE text IS NOT NULL"):
            hits.update(e.lower() for e in rx.findall(text or "") if is_personal_email(e))
        self.assertEqual(sorted(hits)[:10], [], f"{len(hits)} personal OSU addresses found")


if __name__ == "__main__":
    unittest.main()
