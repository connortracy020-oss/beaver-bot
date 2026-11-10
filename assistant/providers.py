"""The model interface. Any model can be plugged in by adding a Provider; nothing in the app depends on a vendor.

A provider takes a system prompt and a user prompt and returns the model's raw text, which must be the JSON answer
format in answer.py. Two providers ship, and neither calls an external service:

- `extractive`: no model at all. It quotes the retrieved sentences that best match the question. Free, offline,
  and always verifiable; useful for demos and for testing the pipeline end to end.
- `scripted`: returns canned outputs, for tests.

Rules for adding a real model (see docs/answer-layer.md):
- **Keys:** read from environment variables inside the provider, never from a file in the repo or a CLI argument.
- **Paid calls need approval:** set `paid = True`. `get_provider` refuses a paid provider unless the owner has set
  ASSISTANT_ALLOW_PAID_CALLS=yes in their own environment.
- **Payload:** only `system` and `user` from build_prompt() are sent: public page text and the student's question
  with contact details and ID numbers redacted.
"""
import json
import os
import re
from typing import Callable, Protocol


class PaidCallNotApproved(RuntimeError):
    pass


class Provider(Protocol):
    name: str
    paid: bool

    def complete(self, system: str, user: str, max_tokens: int = 2000) -> str: ...


class ExtractiveProvider:
    """Answers with the retrieved text itself: the best-matching sentences from the top chunks, quoted exactly."""
    name, paid = "extractive", False

    def __init__(self, max_quotes: int = 2):
        self.max_quotes = max_quotes

    def complete(self, system: str, user: str, max_tokens: int = 2000) -> str:
        question, chunks = _parse_prompt(user)
        words = set(re.findall(r"[a-z0-9]{3,}", question.lower()))
        scored = []
        for rank, (cid, text) in enumerate(chunks):
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            for i, line in enumerate(lines):
                sentences = re.split(r"(?<=[.!?])\s+", line)
                for j, quote in enumerate(sentences):
                    # A label ("Annual Commuter Parking Permit Prices:") is only useful with the lines under it.
                    # Only a line's last sentence can run on into the next line and stay a contiguous quote.
                    for nxt in (lines[i + 1:] if j == len(sentences) - 1 else []):
                        if len(quote) >= 120 or not (quote.endswith(":") or len(quote) < 60):
                            break
                        quote = f"{quote} {nxt}"
                    overlap = len(words & set(re.findall(r"[a-z0-9]{3,}", quote.lower())))
                    if overlap and 25 <= len(quote) <= 400:
                        scored.append((overlap, -rank, cid, quote))
        scored.sort(reverse=True)
        picked = []
        for _, _, cid, quote in scored:
            if not any(quote in q or q in quote for _, q in picked):  # skip overlapping quotes
                picked.append((cid, quote))
            if len(picked) == self.max_quotes:
                break
        if not picked:
            return json.dumps({"status": "not_found", "answer": "", "citations": []})
        cites = [{"chunk_id": cid, "quote": quote} for cid, quote in picked]
        answer = " ".join(f'"{c["quote"]}" [{i}]' for i, c in enumerate(cites, 1))
        return json.dumps({"status": "answered", "answer": answer, "citations": cites})


class ScriptedProvider:
    """Returns the given outputs in order (or a function of the prompt). For tests: no network."""
    name, paid = "scripted", False

    def __init__(self, outputs: list[str] | Callable[[str, str], str]):
        self.outputs, self.calls = outputs, []

    def complete(self, system: str, user: str, max_tokens: int = 2000) -> str:
        self.calls.append((system, user))
        if callable(self.outputs):
            return self.outputs(system, user)
        return self.outputs[len(self.calls) - 1]


def _guide() -> Provider:
    from .guide import GuideProvider          # imported late: guide.py imports retrieve.py, which needs the database module
    return GuideProvider()


def _anthropic() -> Provider:
    from .anthropic_provider import AnthropicProvider
    return AnthropicProvider()


# name -> factory. A real model's adapter registers here; its factory reads its key from the environment.
REGISTRY: dict[str, Callable[[], Provider]] = {
    "extractive": ExtractiveProvider,
    "guide": _guide,            # offline: dates, steps and quotes copied from the excerpts (guide.py)
    "anthropic": _anthropic,    # paid, locked until the owner approves (anthropic_provider.py)
}


def get_provider(name: str | None = None) -> Provider:
    name = name or os.environ.get("ASSISTANT_PROVIDER", "extractive")
    if name not in REGISTRY:
        raise KeyError(f"unknown provider {name!r}; available: {', '.join(sorted(REGISTRY))}")
    provider = REGISTRY[name]()
    if provider.paid and os.environ.get("ASSISTANT_ALLOW_PAID_CALLS", "").lower() != "yes":
        raise PaidCallNotApproved(
            f"{name} is a paid API. The project owner must approve paid calls and set ASSISTANT_ALLOW_PAID_CALLS=yes.")
    return provider


def _parse_prompt(user: str) -> tuple[str, list[tuple[int, str]]]:
    """Pull the question and the chunks back out of build_prompt()'s text (used by the extractive provider)."""
    q = re.search(r"<question>\n?(.*?)\n?</question>", user, re.S)
    chunks = [(int(cid), text.strip()) for cid, text in
              re.findall(r'<chunk id="(\d+)"[^>]*>\n(.*?)\n</chunk>', user, re.S)]
    return (q.group(1).strip() if q else ""), chunks
