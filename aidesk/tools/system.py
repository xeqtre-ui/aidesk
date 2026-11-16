"""System control — mouse, keyboard, screen, clipboard, shell.

CAUTION: These tools control the computer directly (full automation).
High-risk ones (shell command, clicking) go through user approval in the
assistant loop.
"""
from __future__ import annotations

import base64
import io
import subprocess
from pathlib import Path

from . import Risk, tool


def _pyautogui():
    import pyautogui

    pyautogui.FAILSAFE = True   # stop when the mouse is thrown to the top-left corner
    pyautogui.PAUSE = 0.05
    return pyautogui


@tool(
    name="type_text",
    description="Types the given text into the focused window (keyboard simulation).",
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "The text to type."}
        },
        "required": ["text"],
    },
    risk=Risk.HIGH,
)
def type_text(text: str) -> str:
    paste_text(text)
    return f"Typed {len(text)} characters."


def paste_text(text: str) -> None:
    """Types the text by pasting from the clipboard: Turkish characters (ş, ğ, ı, İ…) and
    emoji come out correctly (keyboard simulation can't type them). The previous clipboard
    content is restored."""
    import time

    import pyperclip

    pg = _pyautogui()
    try:
        old = pyperclip.paste()
    except Exception:  # noqa: BLE001
        old = None
    pyperclip.copy(text)
    time.sleep(0.05)
    pg.hotkey("ctrl", "v")
    time.sleep(0.15)
    if old is not None:
        try:
            pyperclip.copy(old)
        except Exception:  # noqa: BLE001
            pass


@tool(
    name="press_keys",
    description=(
        "Sends a keyboard shortcut/key. Examples: 'enter', 'ctrl+c', "
        "'alt+tab', 'win+d'. Multiple keys are joined with '+'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "keys": {
                "type": "string",
                "description": "Key combination, e.g. 'ctrl+shift+esc'.",
            }
        },
        "required": ["keys"],
    },
    risk=Risk.HIGH,
)
def press_keys(keys: str) -> str:
    pg = _pyautogui()
    combo = [k.strip() for k in keys.lower().replace(" ", "").split("+") if k.strip()]
    if not combo:
        return "Empty key combination."
    pg.hotkey(*combo)
    return f"Sent '{keys}'."


@tool(
    name="click",
    description=(
        "Clicks the given (x, y) coordinate on the screen. button: 'left', 'right', "
        "'double'. A 'screenshot' can be taken first to determine the coordinates."
    ),
    parameters={
        "type": "object",
        "properties": {
            "x": {"type": "integer", "description": "X coordinate (pixels)."},
            "y": {"type": "integer", "description": "Y coordinate (pixels)."},
            "button": {
                "type": "string",
                "enum": ["left", "right", "double"],
                "description": "Click type.",
            },
        },
        "required": ["x", "y"],
    },
    risk=Risk.HIGH,
)
def click(x: int, y: int, button: str = "left") -> str:
    pg = _pyautogui()
    if button == "double":
        pg.doubleClick(x, y)
    else:
        pg.click(x, y, button=button)
    return f"{button}-clicked at ({x}, {y})."


@tool(
    name="screenshot",
    description=(
        "Takes a screenshot of the screen and saves it. The returned file path can be "
        "given back to the model for visual reasoning. Shrinks high resolutions."
    ),
    risk=Risk.SAFE,
)
def screenshot() -> str:
    pg = _pyautogui()
    from ..config import CONFIG_DIR

    img = pg.screenshot()
    # Keep the size reasonable.
    img.thumbnail((1600, 1600))
    out = CONFIG_DIR / "last_screenshot.png"
    img.save(out)
    return f"Screenshot saved: {out}"


@tool(
    name="get_clipboard",
    description="Reads the text on the clipboard.",
    risk=Risk.SAFE,
)
def get_clipboard() -> str:
    import pyperclip

    text = pyperclip.paste()
    return text or "(clipboard empty)"


@tool(
    name="set_clipboard",
    description="Copies text to the clipboard.",
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "The text to copy to the clipboard."}
        },
        "required": ["text"],
    },
    risk=Risk.MEDIUM,
)
def set_clipboard(text: str) -> str:
    import pyperclip

    pyperclip.copy(text)
    return "Copied to clipboard."


@tool(
    name="run_shell",
    description=(
        "Runs a shell command (PowerShell on Windows) and returns its output. "
        "Very powerful; use only when needed. 20 s timeout."
    ),
    parameters={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The command to run."}
        },
        "required": ["command"],
    },
    risk=Risk.HIGH,
)
def run_shell(command: str) -> str:
    import os

    try:
        if os.name == "nt":
            args = ["powershell", "-NoProfile", "-NonInteractive", "-Command", command]
        else:
            args = ["bash", "-lc", command]
        proc = subprocess.run(
            args, capture_output=True, text=True, timeout=20
        )
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        parts = []
        if out:
            parts.append(out[:4000])
        if err:
            parts.append(f"[stderr] {err[:1000]}")
        parts.append(f"(exit code {proc.returncode})")
        return "\n".join(parts)
    except subprocess.TimeoutExpired:
        return "ERROR: The command did not finish within 20 seconds."


@tool(
    name="set_volume",
    description="Sets the system volume (0-100) or mutes.",
    parameters={
        "type": "object",
        "properties": {
            "level": {
                "type": "integer",
                "description": "Volume level 0-100. Ignored if mute=true.",
            },
            "mute": {
                "type": "boolean",
                "description": "If true, toggles mute.",
            },
        },
    },
    risk=Risk.MEDIUM,
)
def set_volume(level: int | None = None, mute: bool | None = None) -> str:
    # Rough adjustment via media keys through pyautogui (no extra dependency needed).
    pg = _pyautogui()
    if mute:
        pg.press("volumemute")
        return "Toggled mute."
    if level is not None:
        level = max(0, min(100, int(level)))
        # First reset, then step up gradually (each press ~2%).
        for _ in range(50):
            pg.press("volumedown")
        for _ in range(level // 2):
            pg.press("volumeup")
        return f"Set volume to approximately {level}%."
    return "Specify a 'level' or 'mute'."
