"""AI sağlayıcı soyutlaması.

Tüm sağlayıcılar (Anthropic, OpenAI, Gemini) ortak bir `Provider` arayüzü
üzerinden konuşur. Asistan döngüsü sağlayıcıdan bağımsızdır; sadece
`chat(messages, tools)` çağırır ve dönen `AssistantTurn` nesnesini işler.
"""
from __future__ import annotations

from .base import AssistantTurn, Provider, ToolCall
from .factory import get_provider

__all__ = ["AssistantTurn", "Provider", "ToolCall", "get_provider"]
