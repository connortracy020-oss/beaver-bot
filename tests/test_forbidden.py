"""403 rules (owner's decision, 2026-10-22): OSU's own themed "Access denied" page skips one URL; anything that
looks like a CDN/firewall answer stops the host. Synthetic pages, no network, nothing written to data/logs.

The Tier 2b crawl (2026-10-29) stopped three sites on their own access-denied pages: two were smaller than the old
20 KB floor, and pharmacy's cookie banner lists reCAPTCHA, which read as a challenge.
"""
import tempfile
import unittest
from pathlib import Path

from osu_crawl.fetcher import DomainBlocked, PoliteFetcher, Skipped, is_themed_access_denied


def themed(title_tail: str, size: int, extra: str = "") -> bytes:
    head = (f'<!DOCTYPE html><html lang="en"><head><meta name="Generator" content="Drupal 10 (https://www.drupal.org)">'
            f"<title>Access denied | {title_tail}</title></head><body><main><h1>Access denied</h1>"
            f"<p>You are not authorized to access this page.</p>{extra}</main>")
    return (head + "<footer>" + "x" * max(0, size - len(head) - 30) + "</footer></body></html>").encode()


COOKIE_BANNER = ('<script type="application/json" data-drupal-selector="drupal-settings-json">{"cookies":{"services":'
                 '{"recaptcha":{"label":"reCAPTCHA","placeholderMainText":"This content is blocked because reCAPTCHA '
                 'cookies have not been accepted."}}}}</script>')
CF_CHALLENGE = (b'<!DOCTYPE html><html><head><title>Just a moment...</title></head><body>'
                b'<script src="/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page/v1"></script></body></html>')
CF_BLOCK = (b"<!DOCTYPE html><html><head><title>Attention Required! | Cloudflare</title></head><body>"
            b"<h1>Sorry, you have been blocked</h1><p>Cloudflare Ray ID: 1234</p></body></html>") + b" " * 25000


class Forbidden(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        f = PoliteFetcher.__new__(PoliteFetcher)
        f.forbidden, f.blocked, f.skips = {}, {}, []
        f.forbidden_path, f.blocked_path = tmp / "forbidden.json", tmp / "blocked.json"
        f._save_refusal = lambda host, url, status, content: tmp / "refused.html"
        f._log = lambda **kw: None
        self.f = f

    def outcome(self, url: str, content: bytes) -> str:
        host = url.split("/")[2]
        try:
            self.f._forbidden(host, url, content)
        except Skipped:
            return "skip"
        except DomainBlocked:
            return "block"
        return "none"

    def test_small_themed_pages_skip_the_url_only(self):
        for tail, size in (("Commencement | Oregon State University", 19_640),
                           ("Family Resource Center | Oregon State University", 16_276)):
            page = themed(tail, size)
            self.assertTrue(is_themed_access_denied(page), tail)
            self.assertEqual(self.outcome("https://familyresources.oregonstate.edu/about-us", page), "skip")
            self.assertEqual(self.outcome("https://familyresources.oregonstate.edu/other", page), "skip")  # any number

    def test_cookie_banner_naming_recaptcha_is_not_a_challenge(self):
        page = themed("OSU College of Pharmacy", 39_951, COOKIE_BANNER)
        self.assertTrue(is_themed_access_denied(page))
        self.assertFalse(PoliteFetcher._is_challenge(403, page))
        self.assertEqual(self.outcome("https://pharmacy.oregonstate.edu/student-experience/our-campuses", page), "skip")

    def test_real_challenges_and_cdn_blocks_still_stop(self):
        self.assertTrue(PoliteFetcher._is_challenge(403, CF_CHALLENGE))
        self.assertTrue(PoliteFetcher._is_challenge(429, b"<html><body>captcha</body></html>"))
        self.assertFalse(is_themed_access_denied(CF_BLOCK))
        self.assertEqual(self.outcome("https://mu.oregonstate.edu/a", CF_BLOCK), "block")
        # A themed-looking title on a challenge interstitial is still a challenge.
        fake = themed("Memorial Union | Oregon State University", 30_000, '<script src="/cdn-cgi/challenge-platform/x"></script>')
        self.assertFalse(is_themed_access_denied(fake))
        self.assertTrue(PoliteFetcher._is_challenge(403, fake))

    def test_unexplained_403s(self):
        self.assertEqual(self.outcome("https://mu.oregonstate.edu/", themed("Memorial Union | Oregon State University", 30_000)),
                         "block")  # the home page
        self.assertEqual(self.outcome("https://mu.oregonstate.edu/a", b"Forbidden"), "block")  # short, not HTML
        other = b"<html><head><title>Forbidden</title></head><body>" + b"x" * 25_000 + b"</body></html>"
        self.assertEqual(self.outcome("https://mu.oregonstate.edu/b", other), "skip")  # first unexplained one
        self.assertEqual(self.outcome("https://mu.oregonstate.edu/c", other), "block")  # second


if __name__ == "__main__":
    unittest.main()
