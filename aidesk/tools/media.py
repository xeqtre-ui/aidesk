"""Media control — Spotify, Apple Music, browser etc. IN THE BACKGROUND.

Uses the Windows System Media Transport Controls (SMTC): play/pause/next/previous
and "what's playing now" without bringing the app to the front.

`play_music` starts a closed music app without opening a window (minimized),
waits for the media session to be ready and plays the last-played song from
where it left off.
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import time
from pathlib import Path

from . import Risk, tool

log = logging.getLogger("aidesk.media")

# App -> substrings to look for in the SMTC id
APP_KEYS = {
    "spotify": ("spotify",),
    "apple music": ("applemusic", "apple music", "itunes"),
}
MUSIC_KEYS = tuple(k for keys in APP_KEYS.values() for k in keys)
STATUS = {0: "closed", 1: "opened", 2: "changing", 3: "stopped", 4: "playing", 5: "paused"}
PLAYING = 4


def _norm_app(app: str | None) -> str | None:
    if not app:
        return None
    a = app.lower().strip()
    if "spot" in a:
        return "spotify"
    if "apple" in a or "itunes" in a or "music" == a:
        return "apple music"
    return None


async def _manager():
    from winsdk.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as SessionManager,
    )

    return await SessionManager.request_async()


def _app_id(session) -> str:
    return (session.source_app_user_model_id or "").lower()


def _status(session) -> int:
    try:
        return int(session.get_playback_info().playback_status)
    except Exception:  # noqa: BLE001
        return -1


def _find(mgr, app: str | None):
    """The session of the requested app; if no app is given, the most sensible session:
    a playing music app > any playing one > a music app > the current session."""
    sessions = list(mgr.get_sessions())
    if app:
        keys = APP_KEYS.get(app, (app,))
        return next((s for s in sessions if any(k in _app_id(s) for k in keys)), None)
    is_music = lambda s: any(k in _app_id(s) for k in MUSIC_KEYS)  # noqa: E731
    for pred in (
        lambda s: _status(s) == PLAYING and is_music(s),
        lambda s: _status(s) == PLAYING,
        is_music,
    ):
        found = next((s for s in sessions if pred(s)), None)
        if found:
            return found
    return mgr.get_current_session()


def _run(coro):
    return asyncio.run(coro)


async def _describe(session) -> str:
    props = await session.try_get_media_properties_async()
    title = props.title or "-"
    artist = f" — {props.artist}" if props.artist else ""
    return f"{title}{artist}"


def _app_label(session) -> str:
    aid = _app_id(session)
    if "spotify" in aid:
        return "Spotify"
    if any(k in aid for k in APP_KEYS["apple music"]):
        return "Apple Music"
    return session.source_app_user_model_id or "unknown app"


# ---------------------------------------------------------------------------
# Launching in the background
# ---------------------------------------------------------------------------
def _is_running(exe_name: str) -> bool:
    import psutil

    name = exe_name.lower()
    return any((p.info["name"] or "").lower() == name for p in psutil.process_iter(["name"]))


def _minimize_windows_of(exe_name: str, seconds: float, keep_foreground: int | None) -> None:
    """Minimizes the app's opened windows (without stealing focus)."""
    if os.name != "nt":
        return
    import ctypes
    import ctypes.wintypes as wt

    import psutil

    user32 = ctypes.windll.user32
    SW_SHOWMINNOACTIVE = 7
    deadline = time.time() + seconds
    while time.time() < deadline:
        pids = {p.pid for p in psutil.process_iter(["name"]) if (p.info["name"] or "").lower() == exe_name.lower()}
        hits: list[int] = []

        @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
        def _enum(hwnd, _lparam):
            pid = wt.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value in pids and user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
                if user32.GetWindowTextLengthW(hwnd) > 0:
                    hits.append(hwnd)
            return True

        user32.EnumWindows(_enum, 0)
        for hwnd in hits:
            user32.ShowWindow(hwnd, SW_SHOWMINNOACTIVE)
            if keep_foreground:
                user32.SetForegroundWindow(keep_foreground)
        time.sleep(0.15)


def _launch_in_background(app: str) -> str:
    fg = None
    if os.name == "nt":
        import ctypes

        fg = ctypes.windll.user32.GetForegroundWindow()
    if app == "spotify":
        exe = Path(os.environ.get("APPDATA", "")) / "Spotify" / "Spotify.exe"
        if exe.exists():
            subprocess.Popen([str(exe), "--minimized"], close_fds=True)
        else:  # Microsoft Store version
            os.startfile("spotify:")  # type: ignore[attr-defined]
        _minimize_windows_of("Spotify.exe", 6.0, fg)
        return "Spotify"
    if app == "apple music":
        subprocess.Popen(["explorer.exe", r"shell:AppsFolder\AppleInc.AppleMusicWin_nzyj5cx40ttqa!App"])
        _minimize_windows_of("AppleMusic.exe", 6.0, fg)
        return "Apple Music"
    raise ValueError(f"Unsupported app: {app}")


def _press_media_play() -> None:
    if os.name == "nt":
        import ctypes

        VK_MEDIA_PLAY_PAUSE = 0xB3
        ctypes.windll.user32.keybd_event(VK_MEDIA_PLAY_PAUSE, 0, 0, 0)
        ctypes.windll.user32.keybd_event(VK_MEDIA_PLAY_PAUSE, 0, 2, 0)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
@tool(
    name="play_music",
    description=(
        "Plays the LAST-played song in the music app from where it left off. If the app "
        "is closed, starts it in the background without opening a window. Use this ON ITS OWN "
        "for requests like 'play the last song I listened to', 'open/start the music', 'open Spotify'. "
        "app: 'spotify' or 'apple music' (spotify if unspecified)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "app": {"type": "string", "enum": ["spotify", "apple music"], "description": "Music app."}
        },
    },
    risk=Risk.MEDIUM,
)
def play_music(app: str = "spotify") -> str:
    app = _norm_app(app) or "spotify"
    exe = "Spotify.exe" if app == "spotify" else "AppleMusic.exe"

    async def _wait_session(timeout: float):
        mgr = await _manager()
        end = time.time() + timeout
        while time.time() < end:
            s = _find(mgr, app)
            if s is not None:
                return s
            await asyncio.sleep(0.25)
        return None

    async def _play() -> str:
        mgr = await _manager()
        session = _find(mgr, app)
        label = "Spotify" if app == "spotify" else "Apple Music"
        if session is None:
            if not _is_running(exe):
                log.info("Starting %s in the background", label)
                await asyncio.to_thread(_launch_in_background, app)
            session = await _wait_session(15.0)
        if session is None:
            # Some versions only open the session once playback starts: send a media key.
            _press_media_play()
            return f"{label} opened in the background and a play command was sent."
        if _status(session) != PLAYING:
            await session.try_play_async()
            for _ in range(12):  # did it start playing?
                await asyncio.sleep(0.25)
                if _status(session) == PLAYING:
                    break
        state = "playing" if _status(session) == PLAYING else "ready but could not start"
        return f"{label}: {await _describe(session)} {state}."

    return _run(_play())


@tool(
    name="now_playing",
    description=(
        "Says what media is playing now or was last played (song, artist, app). "
        "Spotify/Apple Music/browser all work; reads in the background."
    ),
    parameters={
        "type": "object",
        "properties": {
            "app": {"type": "string", "description": "Optional: 'spotify' or 'apple music'."}
        },
    },
    risk=Risk.SAFE,
)
def now_playing(app: str | None = None) -> str:
    async def _inner() -> str:
        mgr = await _manager()
        session = _find(mgr, _norm_app(app))
        if session is None:
            return "There is no active media session right now."
        state = STATUS.get(_status(session), "unknown")
        return f"{_app_label(session)}: {await _describe(session)} ({state})"

    return _run(_inner())


@tool(
    name="media_control",
    description=(
        "Controls the playing media in the background: 'pause', 'toggle', 'next', 'previous', "
        "'stop', 'play'. If no app is given, the playing music app is chosen. "
        "To start a song in a closed app, use play_music."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["play", "pause", "toggle", "next", "previous", "stop"],
                "description": "The action to perform.",
            },
            "app": {"type": "string", "description": "Optional: 'spotify' or 'apple music'."},
        },
        "required": ["action"],
    },
    risk=Risk.MEDIUM,
)
def media_control(action: str, app: str | None = None) -> str:
    async def _inner() -> str:
        mgr = await _manager()
        session = _find(mgr, _norm_app(app))
        if session is None:
            return "No active media session."
        fn = {
            "play": session.try_play_async,
            "pause": session.try_pause_async,
            "toggle": session.try_toggle_play_pause_async,
            "next": session.try_skip_next_async,
            "previous": session.try_skip_previous_async,
            "stop": session.try_stop_async,
        }.get(action)
        if fn is None:
            return f"Invalid action: {action}"
        ok = await fn()
        if not ok:
            return f"{_app_label(session)} rejected this action."
        if action in ("next", "previous"):
            await asyncio.sleep(0.6)
            return f"{_app_label(session)}: {await _describe(session)}"
        words = {"play": "playing", "pause": "paused", "toggle": "toggled", "stop": "stopped"}
        return f"{_app_label(session)} {words[action]}."

    return _run(_inner())
