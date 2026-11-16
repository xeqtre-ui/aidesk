"""AI provider abstraction.

All providers (Anthropic, OpenAI, Gemini) talk through a common `Provider`
interface. The assistant loop is provider-independent; it only calls
`chat(messages, tools)` and processes the returned `AssistantTurn` object.
"""
from __future__ import annotations

from .base import AssistantTurn, Provider, ToolCall
from .factory import get_provider

__all__ = ["AssistantTurn", "Provider", "ToolCall", "get_provider"]
