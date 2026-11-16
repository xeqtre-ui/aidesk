"""Memory — the user's preferences and "remember this" notes (persistent).

Stored as plain text in %APPDATA%\\aidesk\\memory.json; given to the AI with every
request as "what you know about the user".
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time

from .config import CONFIG_DIR
from .tools import Risk, tool

log = logging.getLogger("aidesk.memory")
FILE = CONFIG_DIR / "memory.json"
MAX_ITEMS = 60
_lock = threading.Lock()


def _load() -> list[dict]:
    try:
        data = json.loads(FILE.read_text("utf-8"))
        return [d for d in data if isinstance(d, dict) and d.get("text")]
    except Exception:  # noqa: BLE001
        return []


def _save(items: list[dict]) -> None:
    FILE.write_text(json.dumps(items[-MAX_ITEMS:], ensure_ascii=False, indent=1), "utf-8")


def facts() -> list[str]:
    with _lock:
        return [d["text"] for d in _load()]


def _words(text: str) -> set[str]:
    t = text.replace("I", "ı").replace("İ", "i").lower()
    return {w for w in re.sub(r"[^\wçğıöşü ]+", " ", t).split() if len(w) >= 4}


def related(text: str) -> list[str]:
    """Notes that share a word (4+ letters) with the text."""
    w = _words(text)
    return [f for f in facts() if w & _words(f)]


def as_context() -> str:
    items = facts()
    if not items:
        return ""
    return ("\nWHAT YOU REMEMBER ABOUT THE USER (persistent memory; personalize the request accordingly):\n"
            + "\n".join(f"- {f}" for f in items[-30:]) + "\n")


@tool(
    name="remember",
    description=(
        "Saves a persistent fact/preference about the user. Use it when the user says 'remember this' "
        "or states a clear preference (e.g. 'when I say Emrin Olur I mean the Kayahan version', "
        "'call me Hasan'). Write a single, short, clear sentence."
    ),
    parameters={
        "type": "object",
        "properties": {"fact": {"type": "string", "description": "The fact to save (a single sentence)."}},
        "required": ["fact"],
    },
    risk=Risk.SAFE,
)
def remember(fact: str) -> str:
    fact = " ".join((fact or "").split())[:300]
    if not fact:
        return "Nothing to save."
    with _lock:
        items = _load()
        if any(d["text"].lower() == fact.lower() for d in items):
            return "I already remember that."
        items.append({"text": fact, "ts": int(time.time())})
        _save(items)
    log.info("Added to memory: %s", fact)
    return f"I'll remember: {fact}"


@tool(
    name="forget",
    description="Deletes notes from memory that contain the given phrase ('forget that'). 'all' (or Turkish 'hepsi') clears all memory.",
    parameters={
        "type": "object",
        "properties": {"about": {"type": "string", "description": "The phrase in the notes to delete, or 'all'."}},
        "required": ["about"],
    },
    risk=Risk.MEDIUM,
)
def forget(about: str) -> str:
    about = (about or "").strip().lower()
    with _lock:
        items = _load()
        # Turkish/English "all" keywords (functional): what the user says to clear everything.
        if about in ("hepsi", "tümü", "her şey", "all"):
            keep: list[dict] = []
        else:
            w = _words(about)
            keep = [d for d in items if about not in d["text"].lower() and not (w and w <= _words(d["text"]))]
        removed = len(items) - len(keep)
        _save(keep)
    return f"Deleted {removed} note(s)." if removed else "I couldn't find a note about that."
