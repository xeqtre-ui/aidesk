"""File tools — opening, searching, reading."""
from __future__ import annotations

import os
from pathlib import Path

from . import Risk, tool

# Turkish folder names (Masaüstü, Belgeler, İndirilenler) are kept: on Turkish
# Windows these are the real localized folder names to search.
_SEARCH_ROOTS = [
    Path.home() / "Desktop",
    Path.home() / "Masaüstü",
    Path.home() / "Documents",
    Path.home() / "Belgeler",
    Path.home() / "Downloads",
    Path.home() / "İndirilenler",
]


@tool(
    name="open_path",
    description=(
        "Opens a file or folder with its default app. Provide the full path."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path of the file/folder to open."}
        },
        "required": ["path"],
    },
    risk=Risk.MEDIUM,
)
def open_path(path: str) -> str:
    p = Path(os.path.expandvars(os.path.expanduser(path)))
    if not p.exists():
        return f"Not found: {p}"
    try:
        if os.name == "nt":
            os.startfile(str(p))  # type: ignore[attr-defined]
        else:
            import subprocess

            subprocess.Popen(["xdg-open", str(p)])
        return f"Opened: {p}"
    except Exception as e:  # noqa: BLE001
        return f"Could not open: {e}"


@tool(
    name="search_files",
    description=(
        "Searches by file name in the Desktop, Documents and Downloads folders. "
        "Use it to find the path of a file you want to open."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Text to look for in the file name.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum results to return (default 15).",
            },
        },
        "required": ["query"],
    },
    risk=Risk.SAFE,
)
def search_files(query: str, limit: int = 15) -> str:
    q = query.lower()
    hits: list[str] = []
    for root in _SEARCH_ROOTS:
        if not root.exists():
            continue
        for dirpath, _dirs, filenames in os.walk(root):
            # Don't go too deep.
            if dirpath.count(os.sep) - str(root).count(os.sep) > 4:
                continue
            for fn in filenames:
                if q in fn.lower():
                    hits.append(str(Path(dirpath) / fn))
                    if len(hits) >= limit:
                        return "Found:\n- " + "\n- ".join(hits)
    if not hits:
        return f"No file matching '{query}' found."
    return "Found:\n- " + "\n- ".join(hits)


@tool(
    name="read_text_file",
    description="Reads the contents of a text file (first 8000 characters).",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path of the file to read."}
        },
        "required": ["path"],
    },
    risk=Risk.SAFE,
)
def read_text_file(path: str) -> str:
    p = Path(os.path.expandvars(os.path.expanduser(path)))
    if not p.exists() or not p.is_file():
        return f"File not found: {p}"
    try:
        return p.read_text("utf-8", errors="replace")[:8000]
    except Exception as e:  # noqa: BLE001
        return f"Could not read: {e}"
