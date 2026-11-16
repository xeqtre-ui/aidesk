"""Vision — shows a screenshot to the AI.

- look_at_screen  : answers questions like "what's on screen / what does this error say" by looking.
- click_on_screen : finds the described element in the screenshot and clicks it.

The image is sent in a separate request to a provider that has a key (Gemini > OpenAI > Anthropic).
Gemini is especially good at giving an element's position as a 0-1000 scaled box
([ymin, xmin, ymax, xmax]); it is preferred for clicking.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import re

from . import Risk, tool

log = logging.getLogger("aidesk.vision")

# The UI sets this: overlay(True) -> hide the orb/bubbles, overlay(False) -> bring them back.
# So that in a screenshot our own windows don't cover the click target.
OVERLAY_HOOK = None


def _screenshot(max_side: int = 1600):
    """Returns (PNG bytes, image size, screen size)."""
    import time

    import pyautogui

    if OVERLAY_HOOK:
        OVERLAY_HOOK(True)
        time.sleep(0.25)
    try:
        img = pyautogui.screenshot()
    finally:
        if OVERLAY_HOOK:
            OVERLAY_HOOK(False)
    screen = img.size
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue(), img.size, screen


def _providers() -> list[tuple[str, str]]:
    from .. import apierrors, config

    order = [config.load_settings().provider, "gemini", "openai", "anthropic"]
    out = []
    for p in dict.fromkeys(order):
        key = config.get_api_key(p)
        if key and not apierrors.is_cooling(f"provider:{p}"):
            out.append((p, key))
    return out


def ask_image(png: bytes, prompt: str, prefer: str | None = None) -> tuple[str, str]:
    """Image + question -> (answer, provider_used)."""
    from .. import apierrors, config

    provs = _providers()
    if prefer:
        provs.sort(key=lambda x: x[0] != prefer)
    last: Exception | None = None
    for prov, key in provs:
        try:
            if prov == "gemini":
                from google import genai
                from google.genai import types

                c = genai.Client(api_key=key, http_options=types.HttpOptions(
                    timeout=40_000, retry_options=types.HttpRetryOptions(attempts=1)))
                models = [m for m in ("gemini-3.5-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite")
                          if not apierrors.is_cooling(m)]
                for m in models:
                    try:
                        cfg = types.GenerateContentConfig(
                            thinking_config=types.ThinkingConfig(thinking_level="low")) if m.startswith("gemini-3") else None
                        r = c.models.generate_content(model=m, config=cfg, contents=[
                            types.Part.from_bytes(data=png, mime_type="image/png"), prompt])
                        return (r.text or "").strip(), prov
                    except Exception as e:  # noqa: BLE001
                        last = e
                        if apierrors.is_quota_error(e):
                            apierrors.cool(m, apierrors.retry_delay(e))
                            continue
                        raise
                continue
            if prov == "openai":
                from openai import OpenAI

                c = OpenAI(api_key=key, timeout=40)
                model = config.load_settings().model.get("openai") or "gpt-5-mini"
                r = c.chat.completions.create(model=model, messages=[{"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}},
                ]}])
                return (r.choices[0].message.content or "").strip(), prov
            if prov == "anthropic":
                import anthropic

                c = anthropic.Anthropic(api_key=key, timeout=40)
                model = config.load_settings().model.get("anthropic") or "claude-sonnet-5-5"
                r = c.messages.create(model=model, max_tokens=1024, messages=[{"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                 "data": base64.b64encode(png).decode()}},
                    {"type": "text", "text": prompt},
                ]}])
                return "".join(b.text for b in r.content if b.type == "text").strip(), prov
        except Exception as e:  # noqa: BLE001
            last = e
            if apierrors.is_quota_error(e):
                apierrors.cool(f"provider:{prov}", 600)
            log.warning("Vision (%s) failed: %s", prov, str(e)[:120])
    raise RuntimeError(f"Could not interpret the screenshot: {last}")


@tool(
    name="look_at_screen",
    description=(
        "Takes a screenshot and answers the question by looking at it (e.g. 'what's on screen', "
        "'what does this error say', 'which video is playing', 'what does this page say'). Don't guess "
        "without looking; use this when needed."
    ),
    parameters={
        "type": "object",
        "properties": {"question": {"type": "string", "description": "A question to answer by looking at the screen."}},
        "required": ["question"],
    },
    risk=Risk.SAFE,
)
def look_at_screen(question: str) -> str:
    png, _size, _screen = _screenshot()
    # The directive to answer in Turkish is kept on purpose (the assistant replies in Turkish).
    answer, prov = ask_image(png, "This is a screenshot of a computer screen. Answer in Turkish and keep it short.\nQuestion: " + question)
    return answer or "I couldn't see anything meaningful on the screen."


@tool(
    name="click_on_screen",
    description=(
        "Finds the described element (button, link, icon, box) in the image and clicks it. "
        "For elements on a browser page, try browser_read/browser_click first; otherwise use this. "
        "target: a clear description of the element (e.g. 'the blue Sign In button in the top right')."
    ),
    parameters={
        "type": "object",
        "properties": {
            "target": {"type": "string", "description": "Description of the element to click."},
            "double": {"type": "boolean", "description": "true if a double-click is needed."},
        },
        "required": ["target"],
    },
    risk=Risk.HIGH,
)
def click_on_screen(target: str, double: bool = False) -> str:
    import pyautogui

    png, (iw, ih), (sw, sh) = _screenshot(max_side=1280)
    # The standard request format Google recommends for object detection (most accurate)
    prompt = (f"Detect {target}. Output a JSON list where each entry contains the 2D bounding box "
              f'in "box_2d" and a text label in "label". Return only the single best match. '
              f"If it is not visible on the screen, output [].")
    answer, prov = ask_image(png, prompt, prefer="gemini")
    # Flexible parsing: the key name sometimes comes back malformed like "box_2"
    m = re.search(r'"box[^"]*"\s*:\s*\[\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*\]', answer)
    if not m:
        return f"Could not find '{target}' on the screen."
    label = re.search(r'"label"\s*:\s*"([^"]*)"', answer)
    data = {"label": label.group(1) if label else target}
    box = [m.group(i) for i in range(1, 5)]
    ymin, xmin, ymax, xmax = (float(v) for v in box)
    x = int((xmin + xmax) / 2 / 1000 * sw)
    y = int((ymin + ymax) / 2 / 1000 * sh)
    pyautogui.FAILSAFE = True
    (pyautogui.doubleClick if double else pyautogui.click)(x, y)
    log.info("Clicked on screen: %r -> (%d, %d) [%s]", target, x, y, prov)
    return f"Clicked '{data.get('label') or target}' ({x}, {y})."


@tool(
    name="type_into",
    description=(
        "Clicks the described text box (e.g. 'the YouTube search box', 'the email field'), "
        "types the given text and presses Enter if requested. Use it to fill search/forms in "
        "the browser and apps."
    ),
    parameters={
        "type": "object",
        "properties": {
            "target": {"type": "string", "description": "Description of the text box."},
            "text": {"type": "string", "description": "The text to type."},
            "submit": {"type": "boolean", "description": "Whether to press Enter after typing (default true)."},
        },
        "required": ["target", "text"],
    },
    risk=Risk.HIGH,
)
def type_into(target: str, text: str, submit: bool = True) -> str:
    import time

    import pyautogui

    from .system import paste_text

    clicked = click_on_screen(target)
    if "Could not find" in clicked:
        return clicked
    time.sleep(0.3)
    pyautogui.hotkey("ctrl", "a")          # select existing text in the box (so it's overwritten)
    paste_text(text)
    if submit:
        time.sleep(0.1)
        pyautogui.press("enter")
    return f"Typed into the '{target}' box: {text}" + (" and submitted." if submit else ".")


@tool(
    name="scroll_screen",
    description="Scrolls the window/page under the mouse cursor. direction: 'down' or 'up'.",
    parameters={
        "type": "object",
        "properties": {
            "direction": {"type": "string", "enum": ["down", "up"], "description": "Direction."},
            "amount": {"type": "integer", "description": "How many steps (default 5)."},
        },
        "required": ["direction"],
    },
    risk=Risk.MEDIUM,
)
def scroll_screen(direction: str = "down", amount: int = 5) -> str:
    import pyautogui

    steps = max(1, min(30, int(amount or 5)))
    pyautogui.scroll((-1 if direction == "down" else 1) * steps * 120)
    return f"Scrolled the page {'down' if direction == 'down' else 'up'}."
