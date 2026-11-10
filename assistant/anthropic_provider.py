"""A provider for Claude through Anthropic's Messages API. PAID, and locked until the project owner approves.

Nothing here runs by default. To use it the owner must do all of this in their own environment:

    pip install -r requirements-model.txt          # the official SDK; not installed with the rest of the project
    set ANTHROPIC_API_KEY=...                      # never written to a file in this repo
    set ASSISTANT_ALLOW_PAID_CALLS=yes             # the lock in providers.get_provider
    set ASSISTANT_PROVIDER=anthropic               # the one-line switch

Optional: ASSISTANT_MODEL (default below: Claude Haiku 5.5, chosen by the owner) and ASSISTANT_EFFORT
(low | medium | high; unset = the model's default).

Before turning it on, the owner confirms the API's current terms say inputs are not used for training. OSU's
robots.txt sets `ai-train=no` (docs/crawl-policy.md section 7), so a provider is allowed only on those terms.

What is sent: exactly the `system` and `user` strings from assistant/answer.py: public page excerpts and the
student's question with contact details and ID numbers redacted. Whatever comes back still has to pass
verify.py before a student sees it.
"""
import json
import os

DEFAULT_MODEL = "claude-haiku-5-5"     # the project owner's choice (2026-11-09)
NOT_FOUND = json.dumps({"status": "not_found", "answer": "", "citations": []})
MAX_TOKENS = 16000      # room for the model's thinking plus a short JSON answer; non-streaming, so kept moderate


PRICES = {"claude-haiku-5-5": (0.10, 0.50)}     # dollars per million input / output tokens, for the cost estimate
# The answer format from assistant/answer.py, as a schema the API enforces.
ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["answered", "not_found"]},
        "answer": {"type": "string"},
        "citations": {"type": "array", "items": {
            "type": "object",
            "properties": {"chunk_id": {"type": "integer"}, "quote": {"type": "string"}},
            "required": ["chunk_id", "quote"], "additionalProperties": False}},
    },
    "required": ["status", "answer", "citations"], "additionalProperties": False,
}


class AnthropicProvider:
    name, paid = "anthropic", True
    usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0}     # running totals for this process

    @classmethod
    def cost(cls) -> float | None:
        """A rough dollar estimate for the calls made so far, when the model's price is known here."""
        model = os.environ.get("ASSISTANT_MODEL", "").strip() or DEFAULT_MODEL
        if model not in PRICES:
            return None
        return (cls.usage["input_tokens"] * PRICES[model][0] + cls.usage["output_tokens"] * PRICES[model][1]) / 1_000_000

    def __init__(self, client=None, model: str | None = None):
        self.model = model or os.environ.get("ASSISTANT_MODEL", "").strip() or DEFAULT_MODEL
        self._client = client       # tests pass a fake; the real client is made on first use, after the paid lock

    _shared = None      # one real client for the whole process, so requests reuse its open connection

    def _get_client(self):
        if self._client is None:
            if AnthropicProvider._shared is None:
                try:
                    import anthropic
                except ImportError as e:
                    raise RuntimeError("The Anthropic SDK isn't installed. Run: pip install -r requirements-model.txt") from e
                # Reads ANTHROPIC_API_KEY (or an `ant auth login` profile) from the environment. No key is passed in code.
                AnthropicProvider._shared = anthropic.Anthropic(timeout=60.0, max_retries=2)
            self._client = AnthropicProvider._shared
        return self._client

    @classmethod
    def warm(cls) -> None:
        """Load the SDK and build the client ahead of the first question. Makes no request and costs nothing."""
        try:
            cls()._get_client()
        except Exception:       # a missing SDK or key shows up, with its message, when a question is asked
            pass

    def complete(self, system: str, user: str, max_tokens: int = 2000, schema: dict | None = None) -> str:
        # Structured output: the API returns exactly the asked-for format, so a stray sentence can't break parsing.
        # The default is the answer format; the website's conversation step passes its own (beaverbot/talk.py).
        request = {"model": self.model, "max_tokens": max(max_tokens, MAX_TOKENS), "system": system,
                   "messages": [{"role": "user", "content": user}],
                   "output_config": {"format": {"type": "json_schema", "schema": schema or ANSWER_SCHEMA}}}
        effort = os.environ.get("ASSISTANT_EFFORT", "").strip().lower()
        if effort:
            request["output_config"]["effort"] = effort
        response = self._get_client().messages.create(**request)
        used = getattr(response, "usage", None)
        if used is not None:
            AnthropicProvider.usage["calls"] += 1
            AnthropicProvider.usage["input_tokens"] += getattr(used, "input_tokens", 0) or 0
            AnthropicProvider.usage["output_tokens"] += getattr(used, "output_tokens", 0) or 0
        if response.stop_reason == "refusal":
            # The model declined. The student gets the normal "couldn't find this" reply with the right office.
            return NOT_FOUND
        return json_only("".join(block.text for block in response.content if block.type == "text"))


def json_only(text: str) -> str:
    """The answer object alone, when a model wrote a sentence around it. Anything else is returned unchanged
    and left for the verifier to reject."""
    text = text.strip()
    if text.startswith("{") and text.endswith("}"):
        return text
    end = text.rfind("}")
    start = max(text.rfind('{"status"', 0, end), text.rfind('{"action"', 0, end))
    if start >= 0 and end > start:
        candidate = text[start:end + 1]
        try:
            if isinstance(json.loads(candidate), dict):
                return candidate
        except json.JSONDecodeError:
            pass
    return text
