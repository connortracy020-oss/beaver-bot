"""Category mapping (owner-approved 2026-10-29): the new "Getting in" category, the campus-life rename, and every
Tier 2b site gets a primary category."""
import unittest

from assistant.categories import BY_ID, CATEGORIES, categorize
from osu_crawl.crawl import PHASES, START_URLS


class Mapping(unittest.TestCase):
    def test_twelve_categories_with_the_new_one_and_the_rename(self):
        self.assertEqual(len(CATEGORIES), 12)
        self.assertEqual(BY_ID["admissions"].name, "Getting in: admissions, transfer & international")
        self.assertEqual(BY_ID["living"].name, "Housing, dining & campus life")
        self.assertTrue(all(c.contacts for c in CATEGORIES))

    def test_every_tier2b_site_has_a_primary_category(self):
        for host in PHASES["tier2b"]:
            for url in START_URLS[host]:
                with self.subTest(url=url):
                    self.assertTrue(categorize(url))

    def test_sections_win_over_the_whole_site(self):
        cases = {
            "https://transfer.oregonstate.edu/transfer-credit": "admissions",
            "https://internationalservices.oregonstate.edu/f-1-students": "admissions",
            "https://graduate.oregonstate.edu/future-students": "admissions",
            "https://graduate.oregonstate.edu/finance/graduate-fellowships-and-scholarships": "paying",
            "https://graduate.oregonstate.edu/current-students/doctoral-students": "courses",
            "https://veterans.oregonstate.edu/chapter-33-post-911-gi-bill": "paying",
            "https://veterans.oregonstate.edu/nmfa-military-spouse-scholarships": "paying",
            "https://veterans.oregonstate.edu/contact-us": "support",
            "https://science.oregonstate.edu/academics/majors": "courses",
            "https://science.oregonstate.edu/admissions/transfer": "admissions",
            "https://liberalarts.oregonstate.edu/advising": "support",
            "https://recsports.oregonstate.edu/sports/intramurals": "living",
            "https://cape.oregonstate.edu/survivor-advocacy": "health",
            "https://eoa.oregonstate.edu/report": "rights",
            "https://summer.oregonstate.edu/": "registration",
            # Tier 1 and 2 pages keep their categories
            "https://registrar.oregonstate.edu/osu-academic-calendar": "dates",
            "https://uhds.oregonstate.edu/apply": "living",
        }
        for url, cat in cases.items():
            with self.subTest(url=url):
                self.assertEqual(categorize(url)[0], cat)


if __name__ == "__main__":
    unittest.main()
