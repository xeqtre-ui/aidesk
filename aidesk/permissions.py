"""Permissions — which tool category runs without asking, which asks for approval,
which is fully blocked.

Modes:
- "standard": safe defaults (dangerous actions ask for approval)
- "full"    : Full Access — nothing is asked (the user enables it on purpose)
- "custom"  : per-category user choice
"""
from __future__ import annotations

ALLOW, ASK, DENY = "allow", "ask", "deny"
LEVEL_LABELS = {ALLOW: "Allow", ASK: "Ask", DENY: "Block"}

# (key, name, description, level in standard mode)
CATEGORIES = [
    ("media", "Music and media", "Play/pause/skip in Spotify / Apple Music / browser", ALLOW),
    ("memory", "Memory", "Saving / deleting your preferences and 'remember this' notes", ALLOW),
    ("web", "Internet", "Web search, reading pages, opening search/address/YouTube in the browser", ALLOW),
    ("apps", "Opening apps", "Launching apps, listing and bringing windows to the front", ALLOW),
    ("processes", "Closing apps", "Terminating running apps", ASK),
    ("files", "Files", "Searching, reading and opening files", ALLOW),
    ("screen", "Screenshot", "Taking a screenshot of the screen", ALLOW),
    ("clipboard", "Clipboard", "Reading copied text / writing to the clipboard", ALLOW),
    ("system", "Volume", "Adjusting the system volume", ALLOW),
    ("input", "Keyboard and mouse", "Typing, pressing keys and clicking on your behalf", ASK),
    ("shell", "Command line", "Running PowerShell commands (the most powerful permission)", ASK),
    ("terminal", "Terminal mode: changes", "Writing/editing files and running commands in terminal mode", ASK),
]
CATEGORY_KEYS = [c[0] for c in CATEGORIES]
STANDARD = {c[0]: c[3] for c in CATEGORIES}

TOOL_CATEGORY = {
    "play_music": "media", "play_song": "media", "now_playing": "media", "media_control": "media",
    "web_search": "web", "read_webpage": "web", "youtube_search": "web", "youtube_play": "web",
    "open_search": "web", "open_url": "web",
    "remember": "memory", "forget": "memory",
    "open_app": "apps", "list_windows": "apps", "focus_window": "apps",
    "close_app": "processes",
    "search_files": "files", "read_text_file": "files", "open_path": "files",
    "screenshot": "screen", "look_at_screen": "screen", "click_on_screen": "input",
    "type_into": "input", "scroll_screen": "input",
    "get_clipboard": "clipboard", "set_clipboard": "clipboard",
    "set_volume": "system",
    "type_text": "input", "press_keys": "input", "click": "input",
    "run_shell": "shell",
    "ws_list": "files", "ws_read": "files", "ws_search": "files",
    "ws_write": "terminal", "ws_edit": "terminal", "ws_run": "terminal",
}


def category_of(tool_name: str) -> str:
    return TOOL_CATEGORY.get(tool_name, "shell")  # unknown tool = strictest category


def level_for(settings, category: str) -> str:
    mode = getattr(settings, "permission_mode", "standard")
    if mode == "full":
        return ALLOW
    if mode == "custom":
        lvl = (getattr(settings, "permissions", None) or {}).get(category)
        if lvl in (ALLOW, ASK, DENY):
            return lvl
    return STANDARD.get(category, ASK)


def tool_level(settings, tool_name: str) -> str:
    return level_for(settings, category_of(tool_name))
