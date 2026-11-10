"""Site settings. Everything comes from environment variables, so no secret or machine detail lives in the repo.

| Variable | Default | What it does |
|---|---|---|
| `ASSISTANT_PROVIDER` | `guide` | Which answer provider to use. `guide` is offline. Switching to a model is this one line. |
| `ASSISTANT_ALLOW_PAID_CALLS` | unset | Must be `yes` before any paid provider will run (assistant/providers.py). |
| `BEAVERBOT_HOST` / `BEAVERBOT_PORT` | `127.0.0.1` / `8765` | Where the site listens. |
| `BEAVERBOT_PINNED` | `on` offline, `fallback` with a model | When the hand-checked answers in pinned.json are used: `on` (first), `fallback` (only when the provider can't answer) or `off`. |
| `ASSISTANT_MODEL` / `ASSISTANT_EFFORT` | Claude Haiku 5.5 / the model's default | For the `anthropic` provider. |

The same choices can be written in `beaverbot.local.toml` (gitignored; see `beaverbot.example.toml`). Keys are
never read from a file.
| `BEAVERBOT_STREAM_MS` | `28` | Pause between streamed pieces of an answer, in milliseconds. `0` sends it at once. |

For a public host (docs/deploy.md):

| Variable | Default | What it does |
|---|---|---|
| `PORT` | unset | Set by the host. When present the site listens on it, on every address (0.0.0.0). |
| `BEAVERBOT_DATA_DIR` | `data/` | Where the databases and the search index are. |
| `BEAVERBOT_HOSTS` | none | Extra names the site answers to, comma-separated. Render's own name is added automatically. |
| `BEAVERBOT_PROXY_HOPS` | `0` | How many proxies the host puts in front of the site. Above 0, the forwarded address and protocol headers are trusted. |
| `BEAVERBOT_ASK_LIMITS` | `40/60`, or `20/600,6/30` on a host | Questions allowed per visitor, as count/seconds pairs. |
| `BEAVERBOT_DAILY_BUDGET_USD` | `1` | Estimated model spend per day before the site answers offline (budget.py). |
| `BEAVERBOT_LIVE_SEARCH` | `off` | The web-search backup. Leave it off on a host. |
| `BEAVERBOT_LOW_MEMORY` | on where `PORT` is set | Keeps the search vectors at half size in memory (assistant/semantic.py). |
| `BEAVERBOT_SEMANTIC` | on | `off` turns meaning-based search off, which frees about 180 MB. |
"""
import os
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ["BEAVERBOT_DATA_DIR"]).resolve() if os.environ.get("BEAVERBOT_DATA_DIR") else ROOT / "data"
OSU_DB = DATA / "osu.sqlite"            # the crawled public pages (private, never served, never committed)
DEMO_DB = DATA / "demo.db"              # sample classes and made-up students (python -m beaverbot.demo.generate)
FEEDBACK_DB = DATA / "feedback.sqlite"  # ratings and "report a wrong answer"; nothing else is ever saved
STATIC = Path(__file__).resolve().parent / "static"

OFFLINE_PROVIDERS = {"guide", "extractive", "scripted"}
LOCAL_FILE = ROOT / "beaverbot.local.toml"      # this computer's settings; gitignored (see beaverbot.example.toml)
LOCAL_KEYS = {"provider": "ASSISTANT_PROVIDER", "allow_paid_calls": "ASSISTANT_ALLOW_PAID_CALLS",
              "model": "ASSISTANT_MODEL", "effort": "ASSISTANT_EFFORT", "pinned": "BEAVERBOT_PINNED",
              "host": "BEAVERBOT_HOST", "port": "BEAVERBOT_PORT",
              "live_search": "BEAVERBOT_LIVE_SEARCH", "brave_monthly_limit": "BEAVERBOT_BRAVE_MONTHLY_LIMIT"}
KEY_NAMES = ("ANTHROPIC_API_KEY", "BRAVE_SEARCH_API_KEY")              # read from the environment only, never from a file


def load_local(path: Path | None = None) -> dict:
    """Apply this computer's settings file, if there is one. Real environment variables always win.

    The file holds choices (which provider, which model), never a key. Keys stay in environment variables. On
    Windows a key saved as a user environment variable is also picked up when the program was started from a
    window that opened before the variable was set; it is read into memory and never written anywhere.
    """
    path = path or LOCAL_FILE
    applied = {}
    if path.exists():
        with path.open("rb") as f:
            values = tomllib.load(f)
        for key, env in LOCAL_KEYS.items():
            if key in values and not os.environ.get(env):
                os.environ[env] = str(values[key]).lower() if isinstance(values[key], bool) else str(values[key])
                applied[key] = os.environ[env]
        if os.environ.get("ASSISTANT_ALLOW_PAID_CALLS") == "true":
            os.environ["ASSISTANT_ALLOW_PAID_CALLS"] = "yes"
    if provider_name() not in OFFLINE_PROVIDERS and sys.platform == "win32":
        for name in KEY_NAMES:
            if not os.environ.get(name):
                value = _windows_user_env(name)
                if value:
                    os.environ[name] = value
    return applied


def _windows_user_env(name: str) -> str | None:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            return str(winreg.QueryValueEx(key, name)[0]) or None
    except (ImportError, OSError):
        return None


def provider_name() -> str:
    return os.environ.get("ASSISTANT_PROVIDER", "guide").strip() or "guide"


def hosted() -> bool:
    """Running on a public host rather than a laptop: the host sets PORT (and Render sets RENDER)."""
    return bool(os.environ.get("PORT") or os.environ.get("RENDER"))


def host() -> str:
    return os.environ.get("BEAVERBOT_HOST") or ("0.0.0.0" if hosted() else "127.0.0.1")


def port() -> int:
    return int(os.environ.get("BEAVERBOT_PORT") or os.environ.get("PORT") or "8765")


def proxy_hops() -> int:
    """How many proxies sit between the visitor and this server (BEAVERBOT_PROXY_HOPS, default 0: none, trust nothing).
    Each proxy adds the address it heard from to the end of X-Forwarded-For, so with N proxies the visitor is the Nth
    entry from the end. Anything further left was typed by the visitor and can be made up."""
    try:
        return max(0, min(5, int(os.environ.get("BEAVERBOT_PROXY_HOPS", "0"))))
    except ValueError:
        return 0


def ask_limits() -> list[tuple[int, float]]:
    """Questions allowed per visitor, as (count, seconds) pairs; all must hold. BEAVERBOT_ASK_LIMITS, e.g. "20/600,6/30"
    for 20 in ten minutes and no more than 6 in any half minute."""
    default = "20/600,6/30" if hosted() else "40/60"
    out = []
    for part in (os.environ.get("BEAVERBOT_ASK_LIMITS") or default).split(","):
        try:
            n, per = part.split("/")
            out.append((max(1, int(n)), max(1.0, float(per))))
        except ValueError:
            return [(20, 600.0), (6, 30.0)]
    return out


def pinned_mode() -> str:
    """When the hand-checked answers are used: "first", "fallback" (only when the provider can't answer) or "off".

    Offline they come first. With a model they are a fallback, so the team sees the model's own answers.
    BEAVERBOT_PINNED (or `pinned` in the local file) overrides: on, fallback or off."""
    setting = os.environ.get("BEAVERBOT_PINNED", "").strip().lower()
    if setting in ("on", "first"):
        return "first"
    if setting in ("off", "fallback"):
        return setting
    return "first" if provider_name() in OFFLINE_PROVIDERS else "fallback"


def pinned_enabled() -> bool:
    return pinned_mode() == "first"


def brave_monthly_limit() -> int:
    """Live searches allowed per calendar month (BEAVERBOT_BRAVE_MONTHLY_LIMIT). The backup stops at 90% of this.
    Brave's pricing page (read 2026-11-09) lists $5 per 1,000 requests against a monthly free credit, and no
    2,000-search free tier, so the default stays inside $5 of credit."""
    try:
        return max(0, int(os.environ.get("BEAVERBOT_BRAVE_MONTHLY_LIMIT", "1000")))
    except ValueError:
        return 1000


def allowed_hosts() -> set[str]:
    """The names this server answers to: this computer, plus any listed in BEAVERBOT_HOSTS (comma-separated) for a
    real deployment, such as the site's own domain."""
    names = os.environ.get("BEAVERBOT_HOSTS", "") + "," + os.environ.get("RENDER_EXTERNAL_HOSTNAME", "")
    extra = {h.strip().lower() for h in names.split(",") if h.strip()}
    return {"localhost", "127.0.0.1", "::1"} | extra


def cookie_secure() -> bool:
    """Whether the session cookie is marked Secure (BEAVERBOT_COOKIE_SECURE, default on). Browsers accept a Secure
    cookie from http://localhost in Chrome, Edge and Firefox. Safari does not, so turn this off to try the demo
    sign-in in Safari over plain http. A real deployment is https, where it must stay on."""
    return os.environ.get("BEAVERBOT_COOKIE_SECURE", "on").strip().lower() not in ("off", "no", "0", "false")


def stream_ms() -> int:
    try:
        return max(0, min(200, int(os.environ.get("BEAVERBOT_STREAM_MS", "28"))))
    except ValueError:
        return 28
