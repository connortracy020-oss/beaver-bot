"""Cost safety for a public site: a daily ceiling on paid model calls, and counts for the log.

The site is open to anyone, and every model reply costs a little. This keeps a running estimate of today's spend
from the tokens each reply used. Once it passes the daily budget (BEAVERBOT_DAILY_BUDGET_USD, default $1), the site
answers from its offline rules for the rest of the day (exact quotes from the stored pages) and says so in one
friendly line. It never shows an error.

Two limits to know about:
- The estimate lives in memory. A restart, or a free host putting the site to sleep, starts it again from zero.
  The real backstop is the monthly spend limit set in the model provider's own console (docs/deploy.md).
- The day rolls over at midnight UTC.

Only counts are logged: how many questions, how many were slowed down, the estimated spend. Never a question,
never an address.
"""
import datetime
import os
import sys
import threading

from . import config

UNKNOWN_PRICE = (5.0, 25.0)        # dollars per million tokens, assumed for a model whose price isn't listed here
LOG_EVERY = 20
NOTE = {"en": "I've done a lot of answering today, so for the rest of the day I'm keeping it simple: this is quoted straight from the page.",
        "es": "Hoy he respondido mucho, así que por el resto del día lo hago sencillo: esto viene citado directamente de la página."}
_lock = threading.Lock()
_state = {"day": None, "base": 0.0, "questions": 0, "slowed": 0, "capped": 0, "told": False}


def daily_budget() -> float:
    """Dollars of model calls allowed per day. 0 turns paid calls off entirely."""
    try:
        return max(0.0, float(os.environ.get("BEAVERBOT_DAILY_BUDGET_USD", "1")))
    except ValueError:
        return 1.0


def total_cost() -> float:
    """Estimated dollars spent on model calls since this process started."""
    from assistant import anthropic_provider as ap
    model = os.environ.get("ASSISTANT_MODEL", "").strip() or ap.DEFAULT_MODEL
    price_in, price_out = ap.PRICES.get(model, UNKNOWN_PRICE)
    used = ap.AnthropicProvider.usage
    return (used["input_tokens"] * price_in + used["output_tokens"] * price_out) / 1_000_000


def _roll(now: datetime.datetime | None = None) -> None:
    day = (now or datetime.datetime.now(datetime.timezone.utc)).date()
    if _state["day"] != day:
        _state.update(day=day, base=total_cost(), questions=0, slowed=0, capped=0, told=False)


def spent_today(now=None) -> float:
    with _lock:
        _roll(now)
        return max(0.0, total_cost() - _state["base"])


def over(now=None) -> bool:
    return spent_today(now) >= daily_budget()


def provider_name(now=None) -> str:
    """The provider to answer with right now: the configured one, or the offline rules once today's budget is used."""
    name = config.provider_name()
    if name in config.OFFLINE_PROVIDERS or not over(now):
        return name
    with _lock:
        _state["capped"] += 1
        first, _state["told"] = not _state["told"], True
    if first:
        log("daily budget reached; answering offline until midnight UTC")
    return "guide"


def capped(now=None) -> bool:
    return config.provider_name() not in config.OFFLINE_PROVIDERS and over(now)


def count(what: str) -> None:
    """Note one question, or one request that was slowed down. Every so often, write the totals to the log."""
    with _lock:
        _roll()
        _state[what] += 1
        due = what == "questions" and _state["questions"] % LOG_EVERY == 0
    if due:
        log("counts")


def summary() -> dict:
    spent = spent_today()
    with _lock:
        return {"questions": _state["questions"], "slowed": _state["slowed"], "answered_offline": _state["capped"],
                "estimated_usd": round(spent, 4), "budget_usd": daily_budget()}


def log(what: str) -> None:
    s = summary()
    sys.stderr.write(f"[budget] {what}: questions={s['questions']} slowed={s['slowed']} answered_offline={s['answered_offline']} "
                     f"estimated=${s['estimated_usd']:.4f} of ${s['budget_usd']:.2f} today\n")
    sys.stderr.flush()
