"""Checks API keys: are they valid, do they have credit/quota?

Used by the "Check keys" button in the settings window. Free calls are used
where possible (the model list); for credit/quota, a single very small request.
"""
from __future__ import annotations

import logging

log = logging.getLogger("aidesk.keycheck")

# Model suggestions in the settings window (another model can also be typed by hand)
MODEL_SUGGESTIONS = {
    "gemini": ["gemini-3.5-flash", "gemini-3.6-flash", "gemini-3.8-flash", "gemini-3.5-flash-lite"],
    "openai": ["gpt-5-mini", "gpt-5", "gpt-4.1", "gpt-4.1-mini", "gpt-4o"],
    "anthropic": ["claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5"],
}


def check(provider: str, key: str) -> tuple[bool, str]:
    """Returns (is_working, description)."""
    key = (key or "").strip()
    if not key:
        return False, "no key entered"
    try:
        if provider == "openai":
            from openai import OpenAI

            c = OpenAI(api_key=key, timeout=15)
            n = len(list(c.models.list()))
            c.chat.completions.create(model="gpt-4.1-mini", max_tokens=1,
                                      messages=[{"role": "user", "content": "hi"}])
            return True, f"✓ working ({n} models)"
        if provider == "gemini":
            from google import genai
            from google.genai import types

            c = genai.Client(api_key=key, http_options=types.HttpOptions(
                timeout=15_000, retry_options=types.HttpRetryOptions(attempts=1)))
            models = [m.name for m in c.models.list()]
            from . import apierrors

            usable = [m.split("/")[-1] for m in models if "flash" in m and not apierrors.is_cooling(m.split("/")[-1])]
            return True, f"✓ valid ({len(models)} models)" + ("" if usable else " — today's free quota may be used up")
        if provider == "anthropic":
            import anthropic

            c = anthropic.Anthropic(api_key=key, timeout=15)
            n = len(list(c.models.list()))
            return True, f"✓ valid ({n} models)"
    except Exception as e:  # noqa: BLE001
        return False, describe(e)
    return False, "unknown provider"


def describe(e: Exception) -> str:
    text = str(e).lower()
    if "no credits" in text or "insufficient_quota" in text or "credit balance" in text:
        return "✗ no credit — add credit from the provider's site (Billing)"
    if "429" in text or "resource_exhausted" in text or "rate limit" in text:
        return "✗ quota exhausted — try again later/tomorrow"
    if any(k in text for k in ("401", "invalid api key", "incorrect api key", "api_key_invalid", "unauthorized")):
        return "✗ key invalid"
    if any(k in text for k in ("connect", "timeout", "timed out", "getaddrinfo")):
        return "✗ could not connect (internet?)"
    return "✗ " + str(e)[:80]
