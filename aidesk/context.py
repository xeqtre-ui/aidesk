"""Context — gives the AI "what's happening right now" with every request.

- Date / time
- The foreground window (what the user was looking at the MOMENT they gave the
  command) and its app
- If in a browser, the page address (from the address bar via Windows UI Automation)
- Playing media
- Recent commands and their results (for follow-up commands: "stop it", "open the previous one")
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import logging
import os
import threading
import time
from collections import deque
from datetime import datetime

log = logging.getLogger("aidesk.context")

BROWSERS = {"chrome.exe", "msedge.exe", "brave.exe", "firefox.exe", "opera.exe", "vivaldi.exe", "arc.exe"}
# Turkish day/month names: this is the assistant's locale, used in the date shown to the model.
DAYS = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül",
          "Ekim", "Kasım", "Aralık"]

_history: deque[tuple[str, str]] = deque(maxlen=6)
_hist_lock = threading.Lock()


def remember_command(text: str, result: str) -> None:
    with _hist_lock:
        _history.append((text.strip()[:160], " ".join(str(result).split())[:160]))


def recent_commands() -> list[tuple[str, str]]:
    with _hist_lock:
        return list(_history)


# ---------------------------------------------------------------------------
# Foreground window
# ---------------------------------------------------------------------------
def window_info(hwnd: int) -> dict | None:
    if not hwnd or os.name != "nt":
        return None
    u = ctypes.windll.user32
    if not u.IsWindow(hwnd):
        return None
    buf = ctypes.create_unicode_buffer(512)
    u.GetWindowTextW(hwnd, buf, 512)
    pid = wt.DWORD()
    u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    try:
        import psutil

        exe = psutil.Process(pid.value).name()
    except Exception:  # noqa: BLE001
        exe = ""
    if pid.value == os.getpid():
        return None          # our own window (menu/orb): not context
    return {"hwnd": hwnd, "title": buf.value, "exe": exe}


def foreground_snapshot() -> dict | None:
    """Called the MOMENT the shortcut/wake is pressed (before the menu/orb takes focus)."""
    if os.name != "nt":
        return None
    return window_info(ctypes.windll.user32.GetForegroundWindow())


def browser_url(hwnd: int) -> str:
    """The address in the address bar of Chromium-based browsers (on a separate COM thread)."""
    result: list[str] = []

    def work() -> None:
        try:
            import uiautomation as auto
            from uiautomation.uiautomation import _AutomationClient

            with auto.UIAutomationInitializerInThread():
                iu = _AutomationClient.instance().IUIAutomation
                el = iu.ElementFromHandle(hwnd)
                cond = iu.CreatePropertyCondition(30003, 50004)   # ControlType = Edit
                arr = el.FindAll(4, cond)                          # child elements
                for i in range(min(arr.Length, 8)):
                    e = arr.GetElement(i)
                    name = (e.CurrentName or "").lower()
                    # Turkish/English address-bar accessibility names; kept as-is (matched on Turkish Windows)
                    if any(k in name for k in ("adres", "address", "search or enter", "arama çubuğu")):
                        v = e.GetCurrentPropertyValue(30045)        # Value property
                        if v:
                            result.append(str(v))
                            return
        except Exception:  # noqa: BLE001
            log.debug("Could not read address", exc_info=True)

    th = threading.Thread(target=work, daemon=True)
    th.start()
    th.join(1.5)
    url = result[0] if result else ""
    if url and not url.startswith(("http://", "https://", "file:", "chrome:", "edge:", "brave:", "about:")):
        url = "https://" + url
    return url


def start(snapshot: dict | None):
    """Starts gathering context in the background (so it's ready while the user is speaking)."""
    from concurrent.futures import ThreadPoolExecutor

    ex = ThreadPoolExecutor(max_workers=1)
    fut = ex.submit(build, snapshot)
    ex.shutdown(wait=False)
    return fut


def build(snapshot: dict | None, include_media: bool = True) -> str:
    now = datetime.now()
    lines = [f"- Date/time: {now.day} {MONTHS[now.month - 1]} {now.year} {DAYS[now.weekday()]}, "
             f"{now:%H:%M}"]
    if snapshot:
        lines.append(f"- Window the user is looking at: \"{snapshot['title'][:120]}\" ({snapshot['exe']})")
        if snapshot["exe"].lower() in BROWSERS:
            url = browser_url(snapshot["hwnd"])
            if url:
                lines.append(f"- Page in the browser: {url}")
    if include_media:
        try:
            from .tools import media

            playing = media.now_playing()
            if "no active media session" not in playing:
                lines.append(f"- Media: {playing}")
        except Exception:  # noqa: BLE001
            pass
    hist = recent_commands()
    if hist:
        lines.append("- Recent commands (oldest to newest):")
        lines += [f"    • \"{c}\" → {r}" for c, r in hist]
    from . import memory

    return ("\nCURRENT STATE (automatic, the user did not say this; interpret Turkish references "
            "like 'bu', 'şu', 'burada', 'onu' accordingly):\n" + "\n".join(lines) + "\n" + memory.as_context())


if __name__ == "__main__":   # quick test
    t = time.time()
    print(build(foreground_snapshot()), f"({time.time() - t:.2f} s)")
