"""Medya kontrolü — Spotify, Apple Music, tarayıcı vb. ARKA PLANDA.

Windows System Media Transport Controls (SMTC) kullanır: uygulamayı öne
getirmeden oynat/duraklat/sonraki/önceki ve "şu an ne çalıyor".

`play_music` kapalı bir müzik uygulamasını pencere açmadan (simge durumunda)
başlatır, medya oturumunun hazır olmasını bekler ve en son çalınan şarkıyı
kaldığı yerden oynatır.
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

# Uygulama -> SMTC kimliğinde aranacak parçalar
APP_KEYS = {
    "spotify": ("spotify",),
    "apple music": ("applemusic", "apple music", "itunes"),
}
MUSIC_KEYS = tuple(k for keys in APP_KEYS.values() for k in keys)
STATUS = {0: "kapalı", 1: "açık", 2: "değişiyor", 3: "durduruldu", 4: "oynatılıyor", 5: "duraklatıldı"}
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
    """İstenen uygulamanın oturumu; uygulama verilmezse en mantıklı oturum:
    çalan müzik uygulaması > çalan herhangi biri > müzik uygulaması > mevcut oturum."""
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
    return session.source_app_user_model_id or "bilinmeyen uygulama"


# ---------------------------------------------------------------------------
# Arka planda başlatma
# ---------------------------------------------------------------------------
def _is_running(exe_name: str) -> bool:
    import psutil

    name = exe_name.lower()
    return any((p.info["name"] or "").lower() == name for p in psutil.process_iter(["name"]))


def _minimize_windows_of(exe_name: str, seconds: float, keep_foreground: int | None) -> None:
    """Uygulamanın açılan pencerelerini (odak çalmadan) simge durumuna küçültür."""
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
        else:  # Microsoft Store sürümü
            os.startfile("spotify:")  # type: ignore[attr-defined]
        _minimize_windows_of("Spotify.exe", 6.0, fg)
        return "Spotify"
    if app == "apple music":
        subprocess.Popen(["explorer.exe", r"shell:AppsFolder\AppleInc.AppleMusicWin_nzyj5cx40ttqa!App"])
        _minimize_windows_of("AppleMusic.exe", 6.0, fg)
        return "Apple Music"
    raise ValueError(f"Desteklenmeyen uygulama: {app}")


def _press_media_play() -> None:
    if os.name == "nt":
        import ctypes

        VK_MEDIA_PLAY_PAUSE = 0xB3
        ctypes.windll.user32.keybd_event(VK_MEDIA_PLAY_PAUSE, 0, 0, 0)
        ctypes.windll.user32.keybd_event(VK_MEDIA_PLAY_PAUSE, 0, 2, 0)


# ---------------------------------------------------------------------------
# Araçlar
# ---------------------------------------------------------------------------
@tool(
    name="play_music",
    description=(
        "Müzik uygulamasında EN SON dinlenen şarkıyı kaldığı yerden çalar. Uygulama "
        "kapalıysa pencere açmadan arka planda başlatır. 'son dinlediğim şarkıyı aç', "
        "'müziği aç/başlat', 'spotify'ı aç' gibi isteklerde TEK BAŞINA bunu kullan. "
        "app: 'spotify' veya 'apple music' (belirtilmezse spotify)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "app": {"type": "string", "enum": ["spotify", "apple music"], "description": "Müzik uygulaması."}
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
                log.info("%s arka planda başlatılıyor", label)
                await asyncio.to_thread(_launch_in_background, app)
            session = await _wait_session(15.0)
        if session is None:
            # Bazı sürümler oturumu ancak çalmaya başlayınca açar: medya tuşu gönder.
            _press_media_play()
            return f"{label} arka planda açıldı ve oynat komutu gönderildi."
        if _status(session) != PLAYING:
            await session.try_play_async()
            for _ in range(12):  # çalmaya başladı mı?
                await asyncio.sleep(0.25)
                if _status(session) == PLAYING:
                    break
        state = "çalıyor" if _status(session) == PLAYING else "hazır ama başlatılamadı"
        return f"{label}: {await _describe(session)} {state}."

    return _run(_play())


@tool(
    name="now_playing",
    description=(
        "Şu anda çalan veya en son çalınan medyayı söyler (şarkı, sanatçı, uygulama). "
        "Spotify/Apple Music/tarayıcı fark etmez; arka planda okur."
    ),
    parameters={
        "type": "object",
        "properties": {
            "app": {"type": "string", "description": "İsteğe bağlı: 'spotify' veya 'apple music'."}
        },
    },
    risk=Risk.SAFE,
)
def now_playing(app: str | None = None) -> str:
    async def _inner() -> str:
        mgr = await _manager()
        session = _find(mgr, _norm_app(app))
        if session is None:
            return "Şu anda aktif bir medya oturumu yok."
        state = STATUS.get(_status(session), "bilinmiyor")
        return f"{_app_label(session)}: {await _describe(session)} ({state})"

    return _run(_inner())


@tool(
    name="media_control",
    description=(
        "Çalan medyayı arka planda kontrol eder: 'pause', 'toggle', 'next', 'previous', "
        "'stop', 'play'. Uygulama verilmezse çalan müzik uygulaması seçilir. "
        "Kapalı bir uygulamada şarkı başlatmak için play_music kullan."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["play", "pause", "toggle", "next", "previous", "stop"],
                "description": "Yapılacak işlem.",
            },
            "app": {"type": "string", "description": "İsteğe bağlı: 'spotify' veya 'apple music'."},
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
            return "Aktif medya oturumu yok."
        fn = {
            "play": session.try_play_async,
            "pause": session.try_pause_async,
            "toggle": session.try_toggle_play_pause_async,
            "next": session.try_skip_next_async,
            "previous": session.try_skip_previous_async,
            "stop": session.try_stop_async,
        }.get(action)
        if fn is None:
            return f"Geçersiz işlem: {action}"
        ok = await fn()
        if not ok:
            return f"{_app_label(session)} bu işlemi reddetti."
        if action in ("next", "previous"):
            await asyncio.sleep(0.6)
            return f"{_app_label(session)}: {await _describe(session)}"
        words = {"play": "oynatılıyor", "pause": "duraklatıldı", "toggle": "değiştirildi", "stop": "durduruldu"}
        return f"{_app_label(session)} {words[action]}."

    return _run(_inner())
