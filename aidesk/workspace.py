"""Working-folder tools for terminal mode (similar to Claude Code / Codex).

All paths are resolved relative to the working folder (ROOT) and cannot escape
outside it. Read tools are free; writing/editing/running commands depend on the
"Terminal: changes" permission (default: ask for approval in the terminal).
"""
from __future__ import annotations

import difflib
import fnmatch
import os
import re
import subprocess
from pathlib import Path

from .tools import Risk, tool

ROOT = Path.cwd()
IGNORE_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build", ".idea",
               ".vscode", ".mypy_cache", ".pytest_cache", ".next", "target", "bin", "obj"}
MAX_READ = 60_000


def set_root(path: str | os.PathLike) -> None:
    global ROOT
    ROOT = Path(path).resolve()


def _resolve(path: str) -> Path:
    p = (ROOT / (path or ".")).resolve()
    if p != ROOT and ROOT not in p.parents:
        raise PermissionError(f"Cannot access outside the working folder: {path}")
    return p


def _rel(p: Path) -> str:
    return str(p.relative_to(ROOT)) if p != ROOT else "."


def _is_text(p: Path) -> bool:
    try:
        with open(p, "rb") as f:
            return b"\0" not in f.read(4096)
    except OSError:
        return False


def tree_summary(max_entries: int = 60) -> str:
    """A short summary of the working folder (added to the system instruction)."""
    lines = []
    try:
        for entry in sorted(ROOT.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))[:max_entries]:
            lines.append(entry.name + ("/" if entry.is_dir() else ""))
    except OSError:
        pass
    git = ""
    if (ROOT / ".git").exists():
        try:
            out = subprocess.run(["git", "status", "--short", "--branch"], cwd=ROOT, capture_output=True,
                                 text=True, timeout=5, encoding="utf-8", errors="replace").stdout
            git = "\nGit status:\n" + "\n".join(out.splitlines()[:20])
        except Exception:  # noqa: BLE001
            pass
    return f"Working folder: {ROOT}\nContents: " + ", ".join(lines) + git


@tool(
    name="ws_list",
    description="Lists files and folders in the working folder (excluding hidden/build folders).",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative folder (default '.')."},
            "depth": {"type": "integer", "description": "How many levels deep (default 2)."},
        },
    },
    risk=Risk.SAFE,
)
def ws_list(path: str = ".", depth: int = 2) -> str:
    base = _resolve(path)
    out: list[str] = []
    depth = max(1, min(6, int(depth or 2)))
    for dirpath, dirs, files in os.walk(base):
        rel_depth = len(Path(dirpath).relative_to(base).parts)
        dirs[:] = sorted(d for d in dirs if d not in IGNORE_DIRS and not d.startswith("."))
        if rel_depth >= depth:
            dirs[:] = []
        indent = "  " * rel_depth
        if rel_depth:
            out.append(f"{indent[:-2]}{Path(dirpath).name}/")
        for f in sorted(files)[:200]:
            size = (Path(dirpath) / f).stat().st_size
            out.append(f"{indent}{f}  ({size:,} B)")
        if len(out) > 400:
            out.append("… (truncated)")
            break
    return "\n".join(out) or "(empty)"


@tool(
    name="ws_read",
    description="Reads a file with line numbers. For large files give a start/end line range.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative file path."},
            "start": {"type": "integer", "description": "Start line (from 1)."},
            "end": {"type": "integer", "description": "End line (inclusive)."},
        },
        "required": ["path"],
    },
    risk=Risk.SAFE,
)
def ws_read(path: str, start: int = 1, end: int | None = None) -> str:
    p = _resolve(path)
    if not p.is_file():
        return f"No such file: {path}"
    if not _is_text(p):
        return f"Binary (non-text) file: {path}"
    lines = p.read_text("utf-8", errors="replace").splitlines()
    start = max(1, int(start or 1))
    end = min(len(lines), int(end or len(lines)))
    body = "\n".join(f"{i:5}| {lines[i - 1]}" for i in range(start, end + 1))
    if len(body) > MAX_READ:
        body = body[:MAX_READ] + "\n… (truncated; read the rest with start/end)"
    return f"{_rel(p)} ({len(lines)} lines)\n{body}"


@tool(
    name="ws_search",
    description="Searches text/regex inside files (like grep). Filter file type with glob (e.g. '*.py').",
    parameters={
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Text or regex to search for."},
            "glob": {"type": "string", "description": "File pattern (default '*')."},
        },
        "required": ["pattern"],
    },
    risk=Risk.SAFE,
)
def ws_search(pattern: str, glob: str = "*") -> str:
    try:
        rx = re.compile(pattern, re.I)
    except re.error:
        rx = re.compile(re.escape(pattern), re.I)
    hits: list[str] = []
    for dirpath, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not d.startswith(".")]
        for f in files:
            if not fnmatch.fnmatch(f, glob or "*"):
                continue
            p = Path(dirpath) / f
            if p.stat().st_size > 2_000_000 or not _is_text(p):
                continue
            for n, line in enumerate(p.read_text("utf-8", errors="replace").splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{_rel(p)}:{n}: {line.strip()[:200]}")
                    if len(hits) >= 150:
                        return "\n".join(hits) + "\n… (first 150 results)"
    return "\n".join(hits) or "No matches."


def diff_text(old: str, new: str, name: str) -> str:
    d = difflib.unified_diff(old.splitlines(), new.splitlines(), f"a/{name}", f"b/{name}", lineterm="", n=2)
    out = "\n".join(d)
    return out if len(out) < 6000 else out[:6000] + "\n… (diff truncated)"


@tool(
    name="ws_write",
    description="Creates a file with the given content or OVERWRITES it entirely. For small changes use ws_edit.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative file path."},
            "content": {"type": "string", "description": "The full new content of the file."},
        },
        "required": ["path", "content"],
    },
    risk=Risk.HIGH,
)
def ws_write(path: str, content: str) -> str:
    p = _resolve(path)
    existed = p.exists()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, "utf-8")
    return f"{'Updated' if existed else 'Created'}: {_rel(p)} ({len(content.splitlines())} lines)"


@tool(
    name="ws_edit",
    description=(
        "Replaces an EXACTLY matching piece of text in a file with a new one (it must occur exactly once "
        "in the file; if not, add more context). Read the file with ws_read first."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative file path."},
            "old": {"type": "string", "description": "The existing text to replace (exact)."},
            "new": {"type": "string", "description": "The new text."},
        },
        "required": ["path", "old", "new"],
    },
    risk=Risk.HIGH,
)
def ws_edit(path: str, old: str, new: str) -> str:
    p = _resolve(path)
    if not p.is_file():
        return f"No such file: {path}"
    text = p.read_text("utf-8", errors="replace")
    count = text.count(old)
    if count == 0:
        return "ERROR: The text to replace was not found in the file (must be exact, including whitespace). Re-read with ws_read first."
    if count > 1:
        return f"ERROR: The text occurs {count} times in the file; add more surrounding lines to select a single spot."
    p.write_text(text.replace(old, new, 1), "utf-8")
    return f"Edited: {_rel(p)}\n" + diff_text(text, text.replace(old, new, 1), _rel(p))


@tool(
    name="ws_run",
    description=(
        "Runs a PowerShell command in the working folder and returns its output (e.g. tests, git, "
        "pip, npm, python scripts). Not suitable for long-running/interactive commands. Timeout 120 s."
    ),
    parameters={
        "type": "object",
        "properties": {"command": {"type": "string", "description": "The command to run."}},
        "required": ["command"],
    },
    risk=Risk.HIGH,
)
def ws_run(command: str) -> str:
    try:
        args = (["powershell", "-NoProfile", "-NonInteractive", "-Command", command]
                if os.name == "nt" else ["bash", "-lc", command])
        proc = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=120,
                              encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return "ERROR: The command did not finish within 120 seconds."
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    parts = []
    if out:
        parts.append(out[-8000:])
    if err:
        parts.append("[stderr]\n" + err[-3000:])
    parts.append(f"(exit code {proc.returncode})")
    return "\n".join(parts)


WS_TOOLS = {"ws_list", "ws_read", "ws_search", "ws_write", "ws_edit", "ws_run"}
