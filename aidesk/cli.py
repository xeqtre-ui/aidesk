"""aidesk terminal mode — works in a folder in PowerShell like Claude Code / Codex.

Usage:
    aidesk                     # start a chat in the current folder
    aidesk "what's in this project"  # one-off question
    aidesk --dir C:\\project    # start in another folder
    aidesk --yes               # don't ask for approval for file changes/commands this session

In-session commands: /exit  /clear  /help  /model
(Turkish aliases /çık /temizle /yardım are also accepted.)
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

# --- Terminal appearance ------------------------------------------------------
RESET, DIM, BOLD = "\033[0m", "\033[2m", "\033[1m"
GREEN, RED, CYAN, YELLOW, MAG = "\033[32m", "\033[31m", "\033[36m", "\033[33m", "\033[35m"


def _enable_ansi() -> None:
    if os.name == "nt":
        try:
            import ctypes

            k = ctypes.windll.kernel32
            h = k.GetStdHandle(-11)
            mode = ctypes.c_uint32()
            if k.GetConsoleMode(h, ctypes.byref(mode)):
                k.SetConsoleMode(h, mode.value | 0x0004)   # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        except Exception:  # noqa: BLE001
            pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass


def _p(text: str = "", color: str = "") -> None:
    print(f"{color}{text}{RESET}" if color else text, flush=True)


def _colored_diff(diff: str) -> str:
    out = []
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            out.append(GREEN + line + RESET)
        elif line.startswith("-") and not line.startswith("---"):
            out.append(RED + line + RESET)
        elif line.startswith("@@"):
            out.append(CYAN + line + RESET)
        else:
            out.append(DIM + line + RESET)
    return "\n".join(out)


# --- Confirmation -------------------------------------------------------------
class TerminalConfirm:
    def __init__(self, allow_all: bool = False) -> None:
        self.allow_all = allow_all

    def preview(self, name: str, args: dict) -> str:
        from . import workspace

        try:
            if name == "ws_edit":
                p = workspace._resolve(args.get("path", ""))
                old_text = p.read_text("utf-8", errors="replace") if p.is_file() else ""
                new_text = old_text.replace(args.get("old", ""), args.get("new", ""), 1)
                return _colored_diff(workspace.diff_text(old_text, new_text, args.get("path", "")))
            if name == "ws_write":
                p = workspace._resolve(args.get("path", ""))
                new_text = args.get("content", "")
                if p.is_file():
                    return _colored_diff(workspace.diff_text(p.read_text("utf-8", errors="replace"),
                                                             new_text, args.get("path", "")))
                head = "\n".join(new_text.splitlines()[:25])
                more = len(new_text.splitlines()) - 25
                return GREEN + head + RESET + (f"\n{DIM}… (+{more} lines){RESET}" if more > 0 else "")
            if name == "ws_run":
                return f"{YELLOW}> {args.get('command', '')}{RESET}"
        except Exception as e:  # noqa: BLE001
            return f"{DIM}(no preview: {e}){RESET}"
        return f"{DIM}{args}{RESET}"

    def __call__(self, name: str, args: dict, risk: str) -> bool:
        if self.allow_all:
            return True
        labels = {"ws_write": "File will be written", "ws_edit": "File will be edited",
                  "ws_run": "Command will run"}
        target = args.get("path") or ""
        _p(f"\n{BOLD}{YELLOW}⚠ {labels.get(name, name)}{RESET} {target}")
        _p(self.preview(name, args))
        while True:
            try:
                ans = input(f"{BOLD}Approve? [y]es / [n]o / [a]ll (always yes this session): {RESET}")
            except EOFError:
                return False
            ans = ans.strip().lower()
            if ans in ("e", "evet", "y", "yes"):
                return True
            if ans in ("h", "hayır", "hayir", "n", "no", ""):
                return False
            if ans in ("t", "tümü", "tumu", "a", "all"):
                self.allow_all = True
                return True


# --- Main loop ----------------------------------------------------------------
HELP = f"""{BOLD}Commands{RESET}
  /exit       close the session (Ctrl+C also works)
  /clear      reset the conversation history
  /model      show the provider/model in use
  /help       this help
Write what you want in natural language: "explain this project", "fix the bug in main.py", "run the tests"."""


def _setup_logging() -> None:
    from logging.handlers import RotatingFileHandler

    from .config import CONFIG_DIR

    h = RotatingFileHandler(CONFIG_DIR / "aidesk-cli.log", maxBytes=1_000_000, backupCount=1, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [h]           # don't print logs to the terminal
    root.setLevel(logging.INFO)


def main(argv: list[str] | None = None) -> int:
    _enable_ansi()
    _setup_logging()
    ap = argparse.ArgumentParser(prog="aidesk", description="aidesk terminal mode")
    ap.add_argument("prompt", nargs="*", help="one-off request (if omitted, a chat starts)")
    ap.add_argument("--dir", help="working folder (default: current folder)")
    ap.add_argument("--yes", action="store_true", help="don't ask for approval for file changes/commands")
    ap.add_argument("--sor", "--ask", dest="ask", action="store_true",
                    help="ask for approval for every file change/command even if Full Access is on")
    args = ap.parse_args(argv)

    from . import config, workspace
    from .apierrors import humanize
    from .assistant import Assistant

    workspace.set_root(args.dir or os.getcwd())
    settings = config.load_settings()
    if not config.is_configured():
        _p("No API key. Open the desktop app first and enter a key in Settings.", RED)
        return 1

    from dataclasses import replace

    from . import permissions

    if args.ask:   # terminal changes always confirmed this session
        levels = {k: permissions.level_for(settings, k) for k in permissions.CATEGORY_KEYS}
        settings = replace(settings, permission_mode="custom", permissions={**levels, "terminal": "ask"})
    unattended = args.yes or permissions.level_for(settings, "terminal") == permissions.ALLOW
    confirm = TerminalConfirm(allow_all=args.yes)
    progress = lambda m: _p(f"  · {m}", DIM)  # noqa: E731
    assistant = Assistant(settings=settings, confirm=confirm, on_progress=progress, mode="cli")

    def ask(text: str) -> None:
        try:
            answer = assistant.ask(text, context="\n" + workspace.tree_summary() + "\n")
        except KeyboardInterrupt:
            _p("\n(cancelled)", YELLOW)
            return
        except Exception as e:  # noqa: BLE001
            _p(f"⚠ {humanize(e)}", RED)
            return
        _p()
        _p(answer)
        _p()

    if args.prompt:
        ask(" ".join(args.prompt))
        return 0

    prov = settings.provider
    _p(f"{BOLD}{MAG}✦ aidesk{RESET}  {DIM}{workspace.ROOT}{RESET}")
    _p(f"{DIM}{prov} · {settings.model.get(prov, '')} · /help · /exit to quit{RESET}")
    if unattended:
        _p(f"{YELLOW}⚠ Full Access is on: file changes and commands run WITHOUT approval "
           f"(to require it: aidesk --sor){RESET}")
    _p()
    while True:
        try:
            text = input(f"{BOLD}{CYAN}› {RESET}").strip()
        except (EOFError, KeyboardInterrupt):
            _p("\nGoodbye.", DIM)
            return 0
        if not text:
            continue
        cmd = text.lower()
        if cmd in ("/çık", "/cik", "/exit", "/quit", "exit", "quit", "çık"):
            _p("Goodbye.", DIM)
            return 0
        if cmd in ("/temizle", "/clear", "/reset"):
            assistant.reset()
            _p("Conversation history cleared.", DIM)
            continue
        if cmd in ("/yardım", "/yardim", "/help", "?"):
            _p(HELP)
            continue
        if cmd == "/model":
            p = assistant.provider
            _p(f"{p.name} · {p.model}", DIM)
            continue
        ask(text)


if __name__ == "__main__":
    raise SystemExit(main())
