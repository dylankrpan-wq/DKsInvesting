"""Shared Claude API helper — key-gated, lazy import, never raises.

Used by dk/thesis/generator.py (narrative) and dk/briefing/desk_brief.py
(daily desk brief). Callers always fall back to their deterministic template
when a call can't be made.
"""
from __future__ import annotations
from dk.config import get_key

DEFAULT_MODEL = "claude-opus-4-8"

# Models that accept thinking={"type": "adaptive"}. Older models and Haiku 4.5
# return a 400 if it's sent, so callers gate on this.
_ADAPTIVE_MODELS = ("opus-4-6", "opus-4-7", "opus-4-8", "sonnet-4-6", "fable")


def supports_adaptive_thinking(model: str) -> bool:
    return any(m in (model or "") for m in _ADAPTIVE_MODELS)


def is_available() -> bool:
    """True when both an API key and the anthropic package are present."""
    if not get_key("ANTHROPIC_API_KEY"):
        return False
    try:
        import anthropic  # noqa: F401
        return True
    except ImportError:
        return False


def complete(prompt: str, *, system: str | None = None,
             model: str = DEFAULT_MODEL, max_tokens: int = 2000,
             adaptive_thinking: bool = False) -> dict | None:
    """One Messages API call.

    Returns:
      - {"text", "model", "stop_reason", "input_tokens", "output_tokens"} on success
      - {"error": "<reason>"} when the API call itself failed (key was present)
      - None when no key / no library (feature unavailable, not an error)
    """
    api_key = get_key("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        from anthropic import Anthropic
    except ImportError:
        print("[llm] anthropic package not installed — run: uv sync")
        return None
    try:
        client = Anthropic(api_key=api_key)
        kwargs: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system
        if adaptive_thinking and supports_adaptive_thinking(model):
            kwargs["thinking"] = {"type": "adaptive"}
        resp = client.messages.create(**kwargs)
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        if not text:
            return {"error": f"empty response (stop_reason={resp.stop_reason})"}
        return {
            "text": text,
            "model": resp.model,
            "stop_reason": resp.stop_reason,
            "input_tokens": resp.usage.input_tokens,
            "output_tokens": resp.usage.output_tokens,
        }
    except Exception as e:
        print(f"[llm] call failed: {e}")
        return {"error": f"{type(e).__name__}: {e}"}
