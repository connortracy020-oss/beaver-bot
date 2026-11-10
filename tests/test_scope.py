"""Tier 2b scope rules (docs/tier2b-plan.md): what a college site keeps, what whole sites leave out, host aliases."""
import unittest

from osu_crawl.crawl import PHASES, START_URLS, skip_reason_for
from osu_crawl.scope import SCOPE, canonical_host, document_in_scope, in_scope


def keeps(url):
    return in_scope(url, (SCOPE,)) and not skip_reason_for(url)


class Colleges(unittest.TestCase):
    def test_student_facing_pages_are_kept(self):
        for url in ["https://business.oregonstate.edu/programs/undergraduate",
                    "https://liberalarts.oregonstate.edu/spp/econ/undergraduate-programs",
                    "https://science.oregonstate.edu/academics/majors",
                    "https://math.oregonstate.edu/undergraduate/math-placement-assessment",
                    "https://pharmacy.oregonstate.edu/programs-admissions/pharm-d",
                    "https://www.forestry.oregonstate.edu/students/scholarships"]:
            with self.subTest(url=url):
                self.assertTrue(keeps(url))

    def test_research_news_and_people_are_left_out(self):
        for url in ["https://business.oregonstate.edu/faculty-and-research/some-paper",
                    "https://science.oregonstate.edu/impact/2026/05/a-story",
                    "https://health.oregonstate.edu/research/labs/x",
                    "https://business.oregonstate.edu/blog/undergraduate-life",          # a blog post about students
                    "https://ib.oregonstate.edu/undergraduate/integrative-biology-news-events",
                    "https://business.oregonstate.edu/programs/continuing-and-professional-education/course-1",
                    "https://business.oregonstate.edu/online-mba-thank-you",
                    "https://vetmed.oregonstate.edu/pet-memorial/rex",
                    "https://health.oregonstate.edu/pac/class/yoga-1"]:
            with self.subTest(url=url):
                self.assertFalse(keeps(url))

    def test_a_college_home_page_is_not_student_facing_by_itself(self):
        self.assertFalse(keeps("https://agsci.oregonstate.edu/"))

    def test_extension_stations_are_left_out(self):
        self.assertFalse(keeps("https://agsci.oregonstate.edu/nwrec/programs/vegetables"))


class WholeSites(unittest.TestCase):
    def test_whole_sites_with_their_exclusions(self):
        self.assertTrue(keeps("https://veterans.oregonstate.edu/oregon-education-benefits"))
        self.assertTrue(keeps("https://cape.oregonstate.edu/survivor-advocacy"))
        self.assertFalse(keeps("https://eoa.oregonstate.edu/annual-report/2024"))
        self.assertFalse(keeps("https://publicsafety.oregonstate.edu/osu-jobs/dispatcher"))
        self.assertFalse(keeps("https://commencement.oregonstate.edu/class-2017"))

    def test_leadership_and_redirect_hosts_are_not_in_scope(self):
        for url in ["https://leadership.oregonstate.edu/trustees/meeting", "https://bee.oregonstate.edu/",
                    "https://eecs.oregonstate.edu/"]:
            with self.subTest(url=url):
                self.assertFalse(in_scope(url, (SCOPE,)))

    def test_people_directories_are_still_skipped(self):
        self.assertEqual(skip_reason_for("https://graduate.oregonstate.edu/directory/jane-doe"), "pii")


class NamedPeople(unittest.TestCase):
    """Full crawl (2026-10-29): rosters, profiles and records about named students are left out."""

    def test_roster_and_profile_pages_are_left_out(self):
        for url in ["https://asosu.oregonstate.edu/jane-example",  # a student-government member's profile
                    "https://asosu.oregonstate.edu/student-gov/senate/legislation",
                    "https://asosu.oregonstate.edu/outreach-committee",
                    "https://honors.oregonstate.edu/honors-college-fall-2025-undergraduate-research-showcases",
                    "https://honors.oregonstate.edu/2026-honors-college-thesis-fair",
                    "https://liberalarts.oregonstate.edu/spp/phd/students/current-phd-students",
                    "https://liberalarts.oregonstate.edu/current-students/cla-honors-student-profiles",
                    "https://liberalarts.oregonstate.edu/svpda/gd/students/horizons-2026",
                    "https://liberalarts.oregonstate.edu/spp/sociology/students/sociology-student-awards/past-recipients-x",
                    "https://business.oregonstate.edu/student-life/career-success/career-success-team",
                    "https://recsports.oregonstate.edu/sept-30-rec-sports-advisory-board-meeting-minutes",
                    "https://see.oregonstate.edu/ela/orange-media-network/omn-awards",
                    # resume, 2026-10-29
                    "https://honors.oregonstate.edu/envoy/jane-example",
                    "https://graduate.oregonstate.edu/story-page/jane-example-wins-3mt",
                    "https://graduate.oregonstate.edu/story/jane-example",
                    "https://graduate.oregonstate.edu/environmental-sciences-graduate-program-esgp/"
                    "stories-environmental-sciences-graduate-program-alumni",
                    "https://diversity.oregonstate.edu/state-inclusive-excellence/jane-example",
                    "https://commencement.oregonstate.edu/ceremony-2021/pharmacy",
                    "https://veterans.oregonstate.edu/gold-star-project-member/example-jane",
                    "https://veterans.oregonstate.edu/gold-star-project-database"]:
            with self.subTest(url=url):
                self.assertFalse(keeps(url))

    def test_student_facing_pages_on_those_sites_stay(self):
        for url in ["https://asosu.oregonstate.edu/", "https://asosu.oregonstate.edu/student-resources/basic-needs",
                    "https://asosu.oregonstate.edu/student-gov/elections",
                    "https://honors.oregonstate.edu/thesis-mentor-faqs",
                    "https://liberalarts.oregonstate.edu/current-students/advising",
                    "https://liberalarts.oregonstate.edu/spp/sociology/students/sociology-student-awards",
                    "https://liberalarts.oregonstate.edu/slcs/advising/meet-slcs-advisor",
                    "https://recsports.oregonstate.edu/about/recreational-sports-advisory-board",
                    "https://graduate.oregonstate.edu/awards/laurels-block-grant",
                    "https://graduate.oregonstate.edu/faq",
                    "https://commencement.oregonstate.edu/guests"]:
            with self.subTest(url=url):
                self.assertTrue(keeps(url))

    def test_pdfs_that_are_records_about_students_are_left_out(self):
        f = "https://asosu.oregonstate.edu/sites/asosu.oregonstate.edu/files/2024-10/"
        h = "https://honors.oregonstate.edu/sites/honors.oregonstate.edu/files/2025-05/"
        self.assertFalse(document_in_scope(f + "Senate%20Minutes%202023.01.24.pdf", "ASOSU Senate Meeting"))
        self.assertFalse(document_in_scope(f + "results.pdf", "2022 Preliminary Results"))
        self.assertFalse(document_in_scope(f + "SR-83.08%20Climate.pdf", "View Full Document"))  # not governing
        self.assertTrue(document_in_scope(f + "ASOSU%20Statutes.pdf", "View ASOSU Statutes"))
        self.assertFalse(document_in_scope(h + "researchshowcase202402.pdf", "View Presentation"))
        self.assertFalse(document_in_scope(h + "student_thesis.pdf", "Water Fluoridation Policies"))
        self.assertTrue(document_in_scope(h + "thesis_poster_1.pdf", "How can I find a thesis project?"))
        self.assertFalse(document_in_scope("https://diversity.oregonstate.edu/sites/x/files/pplc_agenda_1-13-23.pdf"))
        self.assertTrue(document_in_scope("https://registrar.oregonstate.edu/sites/x/files/transcript-request.pdf"))
        g = "https://graduate.oregonstate.edu/sites/graduate.oregonstate.edu/files/"
        self.assertFalse(document_in_scope(g + "mcdermott_executive_summary.pdf", "Assigning Value to Sustainability"))
        self.assertFalse(document_in_scope(g + "OSU%20Final%20Project%20Executive%20Summary.pdf", "Executive Summary"))
        self.assertFalse(document_in_scope(g + "Example%20PhD_dissertation_abstract.docx"))
        self.assertTrue(document_in_scope(g + "psm_executive_summary_guidelines.pdf", "PSM Executive Summary Guidelines"))
        self.assertTrue(document_in_scope(g + "mais_handbook.pdf", "MAIS Handbook"))


class Aliases(unittest.TestCase):
    def test_sitemap_aliases_are_rewritten(self):
        self.assertEqual(canonical_host("https://gradschool.oregonstate.edu/current-students"),
                         "https://graduate.oregonstate.edu/current-students")
        self.assertEqual(canonical_host("https://sccs.oregonstate.edu/code-student-conduct"),
                         "https://scs.oregonstate.edu/code-student-conduct")
        self.assertEqual(canonical_host("https://registrar.oregonstate.edu/"), "https://registrar.oregonstate.edu/")


class Phases(unittest.TestCase):
    def test_pilot_is_small_and_every_site_has_an_in_scope_start(self):
        pilot = PHASES["tier2b-pilot"]
        self.assertLessEqual(sum(p for p, _ in pilot.values()), 160)
        for host in pilot:
            with self.subTest(host=host):
                self.assertTrue(START_URLS[host])
                self.assertTrue(all(in_scope(u, (SCOPE,)) for u in START_URLS[host]))

    def test_tier2b_is_in_the_weekly_recrawl(self):
        self.assertIn("admissions.oregonstate.edu", PHASES["recrawl"])
        self.assertNotIn("gradschool.oregonstate.edu", PHASES["recrawl"])  # alias of graduate


if __name__ == "__main__":
    unittest.main()
