"""Computer control tools.

Each tool is registered as a `Tool`: a name, description, JSON Schema input
definition, a callable function and a "risk" level. Risky tools (e.g. shell
command, deleting files) ask for user approval before running.

The tool schema is provider-independent; each provider converts it to its own format.
"""
from __future__ import annotations

import traceback
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable


class Risk(str, Enum):
    SAFE = "safe"        # reading / harmless
    MEDIUM = "medium"    # opening apps, media, writing
    HIGH = "high"        # shell command, deleting files, click automation


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    func: Callable[..., str]
    risk: Risk = Risk.SAFE


_REGISTRY: dict[str, Tool] = {}


def tool(
    name: str,
    description: str,
    parameters: dict[str, Any] | None = None,
    risk: Risk = Risk.SAFE,
) -> Callable[[Callable[..., str]], Callable[..., str]]:
    """Decorator that registers a function as a tool."""

    def deco(func: Callable[..., str]) -> Callable[..., str]:
        _REGISTRY[name] = Tool(
            name=name,
            description=description,
            parameters=parameters or {"type": "object", "properties": {}},
            func=func,
            risk=risk,
        )
        return func

    return deco


def all_tools() -> list[Tool]:
    return list(_REGISTRY.values())


def get_tool(name: str) -> Tool | None:
    return _REGISTRY.get(name)


def schema() -> list[dict[str, Any]]:
    """The common (provider-independent) tool schema."""
    return [
        {"name": t.name, "description": t.description, "parameters": t.parameters}
        for t in _REGISTRY.values()
    ]


def execute(name: str, arguments: dict[str, Any]) -> str:
    """Runs a tool and returns a text result. Errors are caught."""
    t = get_tool(name)
    if t is None:
        return f"ERROR: no tool named '{name}' found."
    try:
        result = t.func(**(arguments or {}))
        return str(result) if result is not None else "Done."
    except TypeError as e:
        return f"ERROR: invalid arguments ({e})."
    except Exception as e:  # noqa: BLE001 — we report the tool error back to the model
        return f"ERROR: {e}\n{traceback.format_exc(limit=2)}"


def load_all() -> None:
    """Imports all tool modules so they register themselves."""
    from . import apps, files, media, spotify_search, system, vision, web  # noqa: F401
    from .. import memory  # noqa: F401  (remember / forget tools)
    from .. import workspace  # noqa: F401  (terminal mode: ws_* tools)
