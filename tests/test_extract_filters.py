"""Extraction drops lists of named people (club officers, "Meet the team") and placeholder text, keeps the rest."""
import unittest

from osu_crawl.extract import extract_html

PAGE = """<html><head><title>Korean Student Association | Student Organizations | Oregon State University</title></head>
<body><main><h1>Korean Student Association</h1>
<h2>About Us</h2><p>Welcome to the official homepage of the Korean Student Association at Oregon State.</p>
<h2>Officers</h2><p>President: Jane Example. Treasurer: Sam Sample. Event Coordinator: Alex Placeholder.</p>
<h2>Meet the Team</h2><h3>Jordan Doe</h3><p>Hi! I'm the club's media coordinator.</p>
<h2>Upcoming Events</h2><p>Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor.</p>
<h2>Professional Officer Course</h2><p>Cadets in the professional officer course enlist in the Air Force Reserve.</p>
<h2>Club Scholarship</h2><p>Awarded each spring to a member who mentors new students.</p><p>2025-2026 winners: Pat Example, Lee Sample</p>
</main></body></html>"""


class Filters(unittest.TestCase):
    def setUp(self):
        self.ex = extract_html(PAGE.encode(), "https://clubs.oregonstate.edu/korean-student-association")
        self.text = self.ex.main_text

    def test_officer_lists_and_their_subsections_are_dropped(self):
        for name in ("Jane Example", "Sam Sample", "Jordan Doe", "media coordinator", "Pat Example"):
            self.assertNotIn(name, self.text)

    def test_placeholder_text_is_dropped(self):
        self.assertNotIn("Lorem ipsum", self.text)

    def test_other_content_is_kept(self):
        self.assertIn("official homepage", self.text)
        self.assertIn("Air Force Reserve", self.text)  # "Officer Course" is not an officer list
        self.assertIn("mentors new students", self.text)  # an award's description stays, its winners go


if __name__ == "__main__":
    unittest.main()
