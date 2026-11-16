"""Assistant orchestrator — tool-using (agentic) loop.

Takes the user's request, talks to the selected provider, runs tools as the
model calls them (asking for confirmation on risky ones) and feeds the results
back. When the model stops calling tools, it returns the final answer.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import logging

from . import apierrors, config, permissions, tools
from .providers import Provider, ToolCall, get_provider

# NOTE: The assistant intentionally replies in Turkish; the directive below is
# part of the product behavior and is kept on purpose. Only the prompt wording
# around it has been translated to English.
SYSTEM_PROMPT = """You are a Windows desktop assistant called "aidesk". You speak Turkish.
You can control the user's computer on their behalf: opening apps, media control
(Spotify/Apple Music in the background), window management, keyboard/mouse,
shell commands, and searching and opening files.

Principles:
- Your replies are shown in a small bubble: write at most 1-2 short sentences,
  do NOT use markdown (**, `, #, lists), write plain text.
- If you completed an action, confirm it in a single sentence.
- For music requests ("son dinlediğim şarkıyı aç", "müziği başlat") call ONLY
  the play_music tool once; do NOT bring the app to the front with open_app.
- If a SPECIFIC song or artist is requested ("Swimming Pools'u aç", "Tarkan çal")
  call ONLY play_song(query="song artist"). Speech recognition may have mis-typed it;
  provide the corrected query (e.g. "Kendric Lamar" -> "Kendrick Lamar").
  Use media_control for pause/next/previous. Never use screenshot or click for music.
- THINK and RESEARCH: If the request needs information you don't know, that is
  current, or open to interpretation (e.g. "Tame Impala'nın GTA 6 için yaptığı
  müzik", "X'in en yeni şarkısı", news, prices) FIRST find it with web_search
  (also youtube_search for music/video), then perform the action with the correct
  info (e.g. play_song(query="Flower In A Hurricane Justice")).
  Do at most 2-3 searches; if the results contain the answer, decide right away and act.
  If results conflict, pick the most repeated and most up-to-date one.
- "Google'da X'i arat" -> open_search(query, site="google"); "YouTube'da X'i aç/oynat"
  -> youtube_play; "YouTube'da X'i ara" -> open_search(site="youtube"); "Trendyol'da/
  bir sitede X'e bak" -> open_search(site=...); an address -> open_url. For these NEVER
  type into the browser with type_text / press_keys / click.
- NEVER claim you did something you didn't. Only say "done" for an action after you
  called the relevant tool and got a successful result; if there is no suitable tool, say so clearly.
- MEMORY: If the user says "remember this" or states a lasting preference/personal detail,
  save it with remember; if they say "forget", use forget. Use information from memory to
  personalize the request (e.g. which version of a song they want).
- CONTEXT: Interpret phrases like "on this site", "here", "this", "that" based on the window,
  page address, playing media and recent commands in the CURRENT STATE (e.g. with YouTube open,
  "burada Duman ara" -> open_search(site="youtube")).
- Finish with the fewest tool calls; speed matters.
- VISION: If you need to know what is on the screen (an error, an open page, a playing video)
  do not guess, look with look_at_screen.
- ACTIONS INSIDE A BROWSER/APP ("click the first video", "type X into the search box", "add to cart",
  "scroll down"): first look with look_at_screen if needed; then do it with click_on_screen,
  type_into, scroll_screen; if unsure, look again after the action and verify.
  Do not guess coordinates and use click. Ask the user before irreversible steps like payment,
  purchase, sending a message, or deletion.
- If unsure, ask the user a short question; don't make assumptions that could cause harm.
- For destructive operations (deleting files, killing processes) explain why it is needed.
"""

CLI_PROMPT = """You are "aidesk" in TERMINAL MODE: you are talking to the user in PowerShell, in a
working folder (a coding and file assistant like Claude Code / Codex). Reply in the user's language.

How you work:
- Work on files with the ws_* tools: inspect with ws_list / ws_search / ws_read; make small changes
  with ws_edit (exact text replacement), create new files with ws_write; run commands with ws_run
  (tests, build, git, pip, npm, python...). Always read a file before changing it.
- Understand first, then change: look at a few files if needed; keep changes small and focused.
- After a change, verify with ws_run if possible (test/run) and report the result honestly.
- Don't claim you did something you didn't; if a command failed, summarize its output.
- You may use web_search if you need current information you don't know.
- The user may approve or reject file changes/commands; if they reject, suggest another way.
- Your answer is shown in the terminal: write short and clear; use markdown, code blocks and lists
  when useful. At the end, briefly summarize what you did (files changed, commands run).
"""

VOICE_PROMPT = """
YOU ARE NOW TALKING OUT LOUD (Jarvis mode): your answer will be read aloud.
- Form 1-3 short, natural Turkish sentences; be friendly but respectful, say "efendim" if needed.
- Don't use lists, markdown, emoji or links; write numbers and abbreviations in a readable way.
- If you did an action, state what you did in a single sentence.
"""

log = logging.getLogger("aidesk.assistant")

TOOL_LABELS = {
    "ws_list": "Listing folder",
    "ws_read": "Reading",
    "ws_search": "Searching",
    "ws_write": "Writing",
    "ws_edit": "Editing",
    "ws_run": "Running",
    "type_into": "Typing into box",
    "scroll_screen": "Scrolling page",
    "look_at_screen": "Looking at screen",
    "click_on_screen": "Finding and clicking element on screen",
    "remember": "Saving to memory",
    "forget": "Removing from memory",
    "web_search": "Searching the web",
    "read_webpage": "Reading page",
    "youtube_search": "Searching YouTube",
    "youtube_play": "Opening on YouTube",
    "open_search": "Searching in browser",
    "open_url": "Opening address",
    "play_song": "Searching for song",
    "play_music": "Starting music",
    "now_playing": "Checking current track",
    "media_control": "Controlling music",
    "open_app": "Opening app",
    "close_app": "Closing app",
    "focus_window": "Bringing window to front",
    "list_windows": "Checking windows",
    "search_files": "Searching files",
    "open_path": "Opening file",
    "read_text_file": "Reading file",
    "screenshot": "Taking screenshot",
    "click": "Clicking",
    "type_text": "Typing",
    "press_keys": "Pressing keys",
    "run_shell": "Running command",
    "set_volume": "Setting volume",
    "get_clipboard": "Reading clipboard",
    "set_clipboard": "Copying to clipboard",
}

# Confirmation callback: (tool_name, arguments, risk) -> approved?
ConfirmFn = Callable[[str, dict, str], bool]
# Progress notification: (message) -> None
ProgressFn = Callable[[str], None]


@dataclass
class Assistant:
    settings: config.Settings
    confirm: ConfirmFn | None = None
    on_progress: ProgressFn | None = None
    mode: str = "desktop"          # "desktop" (desktop/Jarvis) | "cli" (terminal mode)

    def __post_init__(self) -> None:
        tools.load_all()
        self._provider: Provider | None = None
        self._messages: list = []
        self._tool_schema = tools.schema()

    @property
    def provider(self) -> Provider:
        if self._provider is None:
            self._provider = get_provider(self.settings)
        return self._provider

    def reset(self) -> None:
        self._messages = []

    def _alternatives(self) -> list[str]:
        """Other providers whose key is set and whose quota is not currently exhausted."""
        current = self.provider.name
        return [p for p in ("gemini", "openai", "anthropic")
                if p != current and config.get_api_key(p) and not apierrors.is_cooling(f"provider:{p}")]

    def _switch_provider(self, name: str) -> Provider:
        from dataclasses import replace

        log.warning("Switching provider: %s -> %s", self.provider.name, name)
        self._provider = get_provider(replace(self.settings, provider=name))
        return self._provider

    def _progress(self, msg: str) -> None:
        if self.on_progress:
            self.on_progress(msg)

    def _allowed_schema(self) -> list:
        """Tools from denied categories are never shown to the model."""
        from .workspace import WS_TOOLS

        return [t for t in self._tool_schema
                if permissions.tool_level(self.settings, t["name"]) != permissions.DENY
                and (self.mode == "cli" or t["name"] not in WS_TOOLS)]   # folder tools only in terminal

    def _run_tool_calls(
        self, calls: list[ToolCall]
    ) -> list[tuple[ToolCall, str]]:
        results: list[tuple[ToolCall, str]] = []
        for call in calls:
            tool = tools.get_tool(call.name)
            if tool is None:
                results.append((call, f"ERROR: '{call.name}' not found."))
                continue
            level = permissions.tool_level(self.settings, call.name)
            if level == permissions.DENY:
                results.append((call, "No permission for this action (Settings > Permissions). Tell the user."))
                continue
            if level == permissions.ASK:
                self._progress(f"Waiting for approval: {TOOL_LABELS.get(call.name, call.name)}")
                # If there is no UI to ask for approval, fail safe: reject.
                approved = bool(self.confirm and self.confirm(call.name, call.arguments, tool.risk.value))
                if not approved:
                    results.append((call, "The user did not approve this action."))
                    continue
            target = call.arguments.get("path") or call.arguments.get("command") or call.arguments.get("pattern") or ""
            label = TOOL_LABELS.get(call.name, f"Running {call.name}")
            self._progress(f"{label}: {str(target)[:80]}…" if target else label + "…")
            log.info("Tool: %s %s", call.name, call.arguments)
            output = tools.execute(call.name, call.arguments)
            log.info("Tool result (%s): %s", call.name, output[:200].replace("\n", " | "))
            results.append((call, output))
        return results

    def ask(self, user_text: str, voice: bool = False, context: str = "") -> str:
        """Processes the user message, returns the final answer.
        voice=True: the answer will be read aloud (Jarvis mode) — short, spoken style."""
        provider = self.provider
        # If the selected provider just hit a quota/credit limit, start directly with the backup
        if apierrors.is_cooling(f"provider:{provider.name}") and self._alternatives():
            provider = self._switch_provider(self._alternatives()[0])
            self._messages = []
        if len(self._messages) > 40:  # reset an overly long history
            self._messages = []
        self._messages.append(provider.user_message(user_text))

        provider_tools = provider.format_tools(self._allowed_schema())
        if self.mode == "cli":
            system = CLI_PROMPT + (context or "")
        else:
            system = SYSTEM_PROMPT + (VOICE_PROMPT if voice else "") + (context or "")
        last_text = ""
        last_action = ""     # if the step limit is hit, at least report what was done
        info_tools = ("web_search", "read_webpage", "youtube_search", "now_playing", "list_windows",
                      "search_files", "read_text_file", "get_clipboard")

        first_error: Exception | None = None
        limit = 40 if self.mode == "cli" else self.settings.max_tool_iterations   # coding jobs take longer
        for step in range(limit):
            try:
                turn = provider.chat(system, self._messages, provider_tools)
            except Exception as e:  # noqa: BLE001
                # Quota/credit error on the first step: retry the same request with another provider that has a key
                if step > 0 or not apierrors.is_quota_error(e):
                    raise
                apierrors.cool(f"provider:{provider.name}", 600)
                first_error = first_error or e
                alts = self._alternatives()
                if not alts:
                    raise first_error
                provider = self._switch_provider(alts[0])
                self._messages = [provider.user_message(user_text)]   # formats differ: start clean
                provider_tools = provider.format_tools(self._allowed_schema())
                try:
                    turn = provider.chat(system, self._messages, provider_tools)
                except Exception as e2:  # noqa: BLE001
                    if apierrors.is_quota_error(e2):
                        apierrors.cool(f"provider:{provider.name}", 600)
                    raise first_error from e2
            provider.append_assistant(self._messages, turn)
            if turn.text:
                last_text = turn.text
            if not turn.wants_tools:
                break
            if turn.text:
                self._progress(turn.text)
            results = self._run_tool_calls(turn.tool_calls)
            provider.append_tool_results(self._messages, results)
            for call, output in results:
                if call.name not in info_tools:
                    last_action = output     # last result of the action tools
        else:
            log.warning("Reached tool step limit")
            if not last_text:
                last_text = last_action or "Bunu tamamlayamadım, isteği biraz daha açık söyler misin?"

        return last_text or last_action or "Tamamlandı."
