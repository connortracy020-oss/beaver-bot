"""Crawler settings, data locations, and the scope rules every phase shares."""
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ["BEAVERBOT_DATA_DIR"]).resolve() if os.environ.get("BEAVERBOT_DATA_DIR") else ROOT / "data"
RAW_DIR = DATA / "raw"
LOG_DIR = DATA / "logs"
DISCOVERY_DIR = DATA / "discovery"
DB_PATH = DATA / "osu.sqlite"

BOT_NAME = "OSUStudentAssistantResearch"
BOT_VERSION = "0.1"


@dataclass
class Settings:
    contact_email: str = ""
    min_delay_s: float = 2.0
    min_global_delay_s: float = 3.0   # between any two requests to OSU, whichever site (shared rate limit)
    timeout_s: float = 30.0
    max_retries_5xx: int = 3
    max_html_bytes: int = 5_000_000
    max_pdf_bytes: int = 25_000_000

    @property
    def user_agent(self) -> str:
        contact = f"contact: {self.contact_email}" if self.contact_email else "contact email not yet set"
        return f"{BOT_NAME}/{BOT_VERSION} (independent student class project, not affiliated with OSU; {contact})"

    @property
    def user_agent_public(self) -> str:
        """The User-Agent as written into anything that may be committed: the contact address is a placeholder."""
        return self.user_agent.replace(self.contact_email, "<contact_email>") if self.contact_email else self.user_agent


def load_settings() -> Settings:
    """crawler.toml (gitignored) supplies the settings; OSU_CRAWLER_CONTACT overrides the contact address."""
    path = ROOT / "crawler.toml"
    values = {}
    if path.exists():
        with path.open("rb") as f:
            values = tomllib.load(f)
    settings = Settings(**{k: v for k, v in values.items() if k in Settings.__dataclass_fields__})
    if os.environ.get("OSU_CRAWLER_CONTACT"):
        settings.contact_email = os.environ["OSU_CRAWLER_CONTACT"].strip()
    return settings


# Anything that needs a login. A redirect into one of these marks the page login-required; we never follow it.
LOGIN_HOSTS = {
    "login.oregonstate.edu",
    "idp.oregonstate.edu",
    "sso.oregonstate.edu",
    "canvas.oregonstate.edu",
    "beaverhub.oregonstate.edu",
    "my.oregonstate.edu",
    "infosu.oregonstate.edu",
    "prodapps.isadm.oregonstate.edu",
    "oregonstate.instructure.com",
    "oregonstate.service-now.com",
    "login.microsoftonline.com",
    "accounts.google.com",
    "aims.parking.oregonstate.edu",      # parking permit portal
    "oregonstate.joinhandshake.com",     # Handshake (career jobs)
    "app.joinhandshake.com",
    "joinhandshake.com",
}
LOGIN_PATH_RE = re.compile(
    r"(/user/login|/user/register|/user/password|/saml|/shibboleth|/Shibboleth\.sso|/cas/login|/idp/|/sso/|/login\b|/signin\b|/oauth)",
    re.IGNORECASE,
)

# Data minimization: personal directories and profiles are skipped and logged, never fetched.
PII_HOSTS = {"directory.oregonstate.edu"}
# OSU's Drupal sites put one page per employee under /directory/<name>; the library uses /directory-profile/.
# "staff"/"faculty" only count as a listing when they end the path (/about/staff), since
# /faculty/... on Ecampus is resources for instructors, not a list of people.
# Listing pages whose last segment names a group of people (leadership, team, members, ambassadors,
# subject/scheduling contacts) are skipped too, as is any /staff/<name> profile.
PII_PATH_RE = re.compile(
    r"/(people|person|directory|directory-profile|profiles?|users?|bios?|human|our-people|our-staff"
    r"|meet-our-staff|meet-the-team|our-team|staff-directory|faculty-directory|faculty-staff|faculty-and-staff)(/|$)"
    r"|/(staff|faculty|student-care-staff|more-staff-info|leadership|team|members|ambassadors|student-ambassadors"
    r"|advisory-board|subject-contacts|scheduling-contacts)/?$"
    r"|/staff/[^/]+/?$",
    re.IGNORECASE,
)
# Listings that no pattern can separate from ordinary pages without over-blocking (found in the Tier 1 sitemaps).
PII_PATHS = {
    "/academics/programs/artificial-intelligence/ai-degree-program-faculty",
    "/academics/programs/materials-science/materials-science-faculty",
    "/mime/mymime/graduate-advising/mime-graduate-advisor",
    "/mime/mymime/undergraduate-advising/meet-mechanical-industrial-and-manufacturing-engineering-advisor",
}
