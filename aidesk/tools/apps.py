"""App and window management tools."""
from __future__ import annotations

import os
import shutil
import subprocess

from . import Risk, tool

# Short name -> launch target mapping for common apps.
# The 'start' shell can open most registered apps by name.
# (Turkish names like "not defteri"/"ayarlar" are kept: the user may say them.)
_KNOWN_APPS = {
    "spotify": "spotify:",
    "apple music": "msmusic:",
    "chrome": "chrome",
    "edge": "msedge",
    "firefox": "firefox",
    "notepad": "notepad",
    "not defteri": "notepad",
    "hesap makinesi": "calc",
    "calculator": "calc",
    "explorer": "explorer",
    "dosya gezgini": "explorer",
    "terminal": "wt",
    "cmd": "cmd",
    "ayarlar": "ms-settings:",
    "settings": "ms-settings:",
    "vscode": "code",
    "vs code": "code",
}


@tool(
    name="open_app",
    description=(
        "Opens an app or a URI. Recognizes common names like 'spotify', 'chrome', "
        "'not defteri' (Notepad); for an unknown one it tries to open it by name via "
        "the Windows shell. If the app is already open, brings it to the front."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "App name or launch target (e.g. 'spotify').",
            }
        },
        "required": ["name"],
    },
    risk=Risk.MEDIUM,
)
def open_app(name: str) -> str:
    key = name.strip().lower()
    target = _KNOWN_APPS.get(key, name.strip())
    try:
        if os.name == "nt":
            # If it's a protocol/URI (e.g. spotify:) or ms-settings:, start directly.
            if target.endswith(":") or "://" in target:
                os.startfile(target)  # type: ignore[attr-defined]
            elif shutil.which(target):
                subprocess.Popen(target, shell=False)
            else:
                # Open a registered app by name via the shell.
                subprocess.Popen(["cmd", "/c", "start", "", target], shell=False)
        else:
            subprocess.Popen([target])
        return f"Opened '{name}'."
    except Exception as e:  # noqa: BLE001
        return f"Could not open '{name}': {e}"


@tool(
    name="list_windows",
    description="Lists the titles of open windows.",
    risk=Risk.SAFE,
)
def list_windows() -> str:
    try:
        import pygetwindow as gw

        titles = [t for t in gw.getAllTitles() if t.strip()]
        if not titles:
            return "No visible windows."
        return "Open windows:\n- " + "\n- ".join(titles[:40])
    except Exception as e:  # noqa: BLE001
        return f"Could not read windows: {e}"


@tool(
    name="focus_window",
    description="Brings to the front/activates the window whose title contains the given text.",
    parameters={
        "type": "object",
        "properties": {
            "title_contains": {
                "type": "string",
                "description": "Text to look for in the window title (e.g. 'Spotify').",
            }
        },
        "required": ["title_contains"],
    },
    risk=Risk.MEDIUM,
)
def focus_window(title_contains: str) -> str:
    try:
        import pygetwindow as gw

        needle = title_contains.lower()
        for w in gw.getAllWindows():
            if needle in (w.title or "").lower():
                if w.isMinimized:
                    w.restore()
                w.activate()
                return f"Brought '{w.title}' to the front."
        return f"No window containing '{title_contains}' found."
    except Exception as e:  # noqa: BLE001
        return f"Could not bring the window to the front: {e}"


@tool(
    name="close_app",
    description="Closes (terminates) the process/app with the given name.",
    parameters={
        "type": "object",
        "properties": {
            "process_name": {
                "type": "string",
                "description": "Process name (e.g. 'spotify', 'notepad'). No .exe needed.",
            }
        },
        "required": ["process_name"],
    },
    risk=Risk.HIGH,
)
def close_app(process_name: str) -> str:
    import psutil

    name = process_name.lower().removesuffix(".exe")
    killed = 0
    for proc in psutil.process_iter(["name"]):
        try:
            pname = (proc.info["name"] or "").lower().removesuffix(".exe")
            if pname == name:
                proc.terminate()
                killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if killed:
        return f"Terminated {killed} process(es) ('{process_name}')."
    return f"No running process named '{process_name}' found."
