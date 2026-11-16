"""Finding and playing a SPECIFIC song on Spotify (works on Spotify Free too).

The Spotify desktop app has no official "play this song" command (Web API playback
control requires Premium + developer registration). Instead:

1. If Spotify is closed, it's started without opening a window (minimized).
2. A search is opened with `spotify:search:<query>`; the window is minimized
   immediately and the user's foreground window is returned (works while minimized).
3. The SONG rows in the search results are read with Windows UI Automation
   (accessibility); the "Play" button of the one most similar to the query is
   pressed without using the mouse.
4. The media session is used to verify that song is actually playing.

Notes:
- Spotify (Chromium) closes the accessibility tree if it isn't queried for a while;
  the first scan may come back empty, so it is retried a few times.
- When the song changes the page updates and old elements become invalid; every
  element access is guarded against errors.
- The UI may be Turkish or English ("Çal"/"Play", "Şarkı"/"Song"), so the word
  tuples below contain both and are kept as-is (functional matching).
"""
from __future__ import annotations

import asyncio
import difflib
import logging
import os
import re
import time
import urllib.parse

from . import Risk, media, tool

log = logging.getLogger("aidesk.spotify")

PLAY_WORDS = ("Çal", "Play")
SONG_WORDS = ("Şarkı", "Song")
# Sections that aren't search results and are expensive to scan (library sidebar etc.)
SKIP_MARKERS = ("Çalma listesi •", "Playlist •", " Sanatçı", " Artist", "Beğenilen Şarkılar", "Liked Songs")


def _norm(text: str) -> str:
    t = text.replace("I", "ı").replace("İ", "i").lower()
    t = re.sub(r"\(.*?\)|\[.*?\]", " ", t)               # (Drank), [Remastered] etc.
    return " ".join(re.sub(r"[^\wçğıöşü ]+", " ", t).split())


def _similarity(query: str, title: str, artist: str) -> float:
    q = _norm(query)
    cand = _norm(f"{title} {artist}")
    words = set(q.split())
    cwords = cand.split()
    # Soft match for misheard words ("emirin" ~ "emrin")
    hits = sum(1 for w in words if any(difflib.SequenceMatcher(None, w, c).ratio() >= 0.8 for c in cwords))
    overlap = hits / max(1, len(words))
    return 0.65 * overlap + 0.35 * difflib.SequenceMatcher(None, q, cand).ratio()


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:  # noqa: BLE001 — elements become invalid when the page changes
        return default


class _OffscreenRender:
    """Spotify doesn't render its content while minimized (the accessibility tree stays empty).
    For the duration of the operation it keeps the window 'open' OFF-SCREEN without taking focus;
    then restores it to the state the user left it in (minimized/open position)."""

    def __init__(self, hwnd: int) -> None:
        import ctypes
        import ctypes.wintypes as wt

        class WINDOWPLACEMENT(ctypes.Structure):
            _fields_ = [("length", ctypes.c_uint), ("flags", ctypes.c_uint), ("showCmd", ctypes.c_uint),
                        ("ptMinPosition", wt.POINT), ("ptMaxPosition", wt.POINT), ("rcNormalPosition", wt.RECT)]

        self.u = ctypes.windll.user32
        self.wt, self.ctypes = wt, ctypes
        self.hwnd = hwnd
        self.wp = WINDOWPLACEMENT()
        self.wp.length = ctypes.sizeof(self.wp)
        self.u.GetWindowPlacement(hwnd, ctypes.byref(self.wp))
        r = self.wp.rcNormalPosition
        self.orig = (r.left, r.top, r.right, r.bottom, self.wp.showCmd)
        self.hidden = bool(self.u.IsIconic(hwnd)) or not self.u.IsWindowVisible(hwnd)

    def __enter__(self):
        if self.hidden:   # if the user left Spotify open, don't touch it
            left, top, right, bottom, _ = self.orig
            self.wp.rcNormalPosition = self.wt.RECT(-32000, top, -32000 + (right - left), bottom)
            self.wp.showCmd = 4      # SW_SHOWNOACTIVATE: without stealing focus
            self.u.SetWindowPlacement(self.hwnd, self.ctypes.byref(self.wp))
        return self

    def __exit__(self, *exc):
        if self.hidden:
            left, top, right, bottom, _ = self.orig
            self.wp.rcNormalPosition = self.wt.RECT(left, top, right, bottom)
            self.wp.showCmd = 7      # SW_SHOWMINNOACTIVE: minimized again
            self.u.SetWindowPlacement(self.hwnd, self.ctypes.byref(self.wp))
        return False


def _spotify_window():
    import psutil
    import uiautomation as auto

    pids = {p.pid for p in psutil.process_iter(["name"]) if (p.info["name"] or "").lower() == "spotify.exe"}
    for c in _safe(lambda: auto.GetRootControl().GetChildren(), []):
        if _safe(lambda: c.ProcessId) in pids and _safe(lambda: c.ControlTypeName) == "WindowControl" \
                and _safe(lambda: c.Name):
            return c
    return None


_NAME, _CTYPE = 30005, 30003           # UIA property ids
_BUTTON, _DATAITEM = 50000, 50029       # UIA control types


def _song_rows(win) -> list[dict]:
    """The song rows in the search results: title, artist and the 'Play' button.

    The whole tree is cached in a SINGLE call (~0.1 s); instead of querying element
    by element (~2 s) it is read from the cache."""
    try:
        from uiautomation.uiautomation import _AutomationClient

        iu = _AutomationClient.instance().IUIAutomation
        cr = iu.CreateCacheRequest()
        cr.AddProperty(_NAME)
        cr.AddProperty(_CTYPE)
        cr.TreeScope = 7                    # element + all descendants
        cr.TreeFilter = iu.RawViewCondition
        root = win.Element.BuildUpdatedCache(cr)
    except Exception:  # noqa: BLE001
        log.debug("Could not get the cached tree", exc_info=True)
        return []
    rows: list[dict] = []

    def kids(el):
        arr = _safe(el.GetCachedChildren)
        return [arr.GetElement(i) for i in range(arr.Length)] if arr else []

    def walk(el, depth: int) -> None:
        if depth > 32 or len(rows) >= 12:
            return
        for ch in kids(el):
            name = (ch.CachedName or "").strip()
            if ch.CachedControlType == _DATAITEM and name and depth >= 15:
                if any(m in name for m in SKIP_MARKERS):
                    continue                    # a playlist/artist in the library: skip
                row = _parse_row(ch, name, kids)
                if row:
                    rows.append(row)
                    continue
            walk(ch, depth + 1)

    walk(root, 0)
    return rows


def _parse_row(item, title: str, kids) -> dict | None:
    button, kind, artist = None, "", ""
    stack = [(item, 0)]
    while stack:
        el, depth = stack.pop()
        for ch in kids(el):
            name = (ch.CachedName or "").strip()
            ctype = ch.CachedControlType
            if ctype == _BUTTON and button is None and (
                    name in PLAY_WORDS or any(name.startswith(w + ":") for w in PLAY_WORDS)):
                button = ch
            elif ctype == _DATAITEM and "•" in name and not kind:
                parts = [p.strip() for p in name.replace(" ", " ").split("•")]
                kind = parts[0]
                artist = parts[-1] if len(parts) > 1 else ""
            if depth < 6:
                stack.append((ch, depth + 1))
    if button is None or not any(w in kind for w in SONG_WORDS):
        return None
    return {"title": title, "artist": artist, "button": button}


def _invoke(element) -> bool:
    import uiautomation as auto

    return _safe(lambda: auto.Control.CreateControlFromElement(element).GetInvokePattern().Invoke(), "error") != "error"


def _give_back_focus(fg: int) -> None:
    """If Spotify took focus, return it to the user's window (working around Windows'
    'a background app can't come to the front' lock with the ALT trick)."""
    import ctypes

    u = ctypes.windll.user32
    if fg and u.GetForegroundWindow() != fg:
        u.keybd_event(0x12, 0, 0, 0)
        u.keybd_event(0x12, 0, 0x0002, 0)
        u.SetForegroundWindow(fg)


async def _current_track() -> tuple[str, int] | None:
    mgr = await media._manager()
    s = media._find(mgr, "spotify")
    if s is None:
        return None
    props = await s.try_get_media_properties_async()
    return f"{props.title} — {props.artist}", media._status(s)


def _in_plain_thread(fn):
    """Run WinRT (media session) calls on a thread SEPARATE from the one where UI
    Automation set up COM (to avoid an 'RPC server' error)."""
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(fn).result()


async def _wait_playing(title: str, timeout: float = 5.0) -> str | None:
    want = _norm(title)[:14]
    end = time.time() + timeout
    while time.time() < end:
        cur = await _current_track()
        if cur and cur[1] == media.PLAYING and want and want in _norm(cur[0]):
            return cur[0]
        await asyncio.sleep(0.25)
    return None


def _search_and_pick(query: str, fg: int):
    """Searches; returns the song row most similar to the query (best, similarity, rows)."""
    win = _spotify_window()
    before = {r["title"] for r in _song_rows(win)} if win else set()
    os.startfile("spotify:search:" + urllib.parse.quote(query))  # type: ignore[attr-defined]
    best, best_score, rows, last_titles = None, 0.0, [], None
    end = time.time() + 10.0
    while time.time() < end:
        time.sleep(0.25)
        _give_back_focus(fg)   # Spotify tries to come to the front: return focus immediately
        win = _spotify_window()
        rows = _song_rows(win) if win else []
        if not rows:
            continue
        scored = [(_similarity(query, r["title"], r["artist"]), r) for r in rows[:8]]
        best_score, best = max(scored, key=lambda x: x[0])
        titles = [r["title"] for r in rows]
        if best_score >= 0.55 or (set(titles) != before and titles == last_titles):
            break
        last_titles = titles
    return best, best_score, rows


@tool(
    name="play_song",
    description=(
        "Searches a SPECIFIC song (or an artist's song) on Spotify and plays it right away; "
        "does NOT bring Spotify to the front. When the user says a song name or artist, use this "
        "ON ITS OWN (do NOT use open_app, screenshot, click). "
        "query: 'song name artist' (e.g. 'Swimming Pools Kendrick Lamar')."
    ),
    parameters={
        "type": "object",
        "properties": {"query": {"type": "string", "description": "Song name and artist if any."}},
        "required": ["query"],
    },
    risk=Risk.MEDIUM,
)
def play_song(query: str) -> str:
    import ctypes

    import uiautomation as auto

    query = (query or "").strip()
    if not query:
        return "I couldn't tell which song you wanted me to play."
    t0 = time.time()
    with auto.UIAutomationInitializerInThread():
        fg = ctypes.windll.user32.GetForegroundWindow()
        if not media._is_running("Spotify.exe"):
            media._launch_in_background("spotify")
            for _ in range(60):                   # wait for the main window (up to 15 s)
                if _spotify_window() is not None:
                    break
                time.sleep(0.25)
            time.sleep(2.0)                       # let the UI load
        win = _spotify_window()
        if win is None:
            return "Could not open Spotify."
        with _OffscreenRender(win.NativeWindowHandle):
            best, best_score, rows = _search_and_pick(query, fg)
            if best is None:
                return f"No song found on Spotify for '{query}'."
            if best_score < 0.4:
                # An old page or an irrelevant result: rather than play the wrong song, say so
                log.info("Spotify: not sure for %r (best: %s, %.2f)", query, best["title"], best_score)
                return (f"I couldn't find a song I'm sure about on Spotify for '{query}'. "
                        "Could you say the song name and artist a bit more clearly?")
            log.info("Spotify: %r -> %s — %s (similarity %.2f, %d candidates, %.1f s)",
                     query, best["title"], best["artist"], best_score, len(rows), time.time() - t0)
            if not _invoke(best["button"]):
                return f"Found '{best['title']}' but could not start it."
        _give_back_focus(fg)
        playing = _safe(lambda: _in_plain_thread(lambda: asyncio.run(_wait_playing(best["title"]))))
        log.info("Spotify playback verification: %r (total %.1f s)", playing, time.time() - t0)
        if playing:
            return f"Spotify: {playing} is playing."
        return f"Started '{best['title']} — {best['artist']}' on Spotify."
