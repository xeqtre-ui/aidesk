"""Ortak sağlayıcı arayüzü ve veri yapıları."""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    """Modelin çağırmak istediği bir araç."""
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class AssistantTurn:
    """Modelin bir adımdaki yanıtı.

    `text` kullanıcıya gösterilecek metin; `tool_calls` varsa araçlar
    çalıştırılıp sonuçlar geri beslenmeli. `raw` sağlayıcıya özgü mesaj
    nesnesidir ve geçmişe eklenir.
    """
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: Any = None

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


class Provider(abc.ABC):
    """Tüm AI sağlayıcılarının uyguladığı sözleşme."""

    name: str = "base"

    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    def user_message(self, text: str) -> Any:
        """Kullanıcı mesajını sağlayıcının beklediği biçimde oluşturur."""
        return {"role": "user", "content": text}

    @abc.abstractmethod
    def chat(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AssistantTurn:
        """Bir tur sohbet yürütür.

        Args:
            system: Sistem yönergesi.
            messages: Sağlayıcıya özgü biçimde sohbet geçmişi.
            tools: `tools.schema` ile üretilmiş sağlayıcıya uygun araç tanımları.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def append_assistant(
        self, messages: list[dict[str, Any]], turn: AssistantTurn
    ) -> None:
        """Modelin yanıtını geçmişe ekler (sağlayıcıya özgü biçimde)."""

    @abc.abstractmethod
    def append_tool_results(
        self,
        messages: list[dict[str, Any]],
        results: list[tuple[ToolCall, str]],
    ) -> None:
        """Araç sonuçlarını geçmişe ekler."""

    @staticmethod
    @abc.abstractmethod
    def format_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Ortak araç şemasını sağlayıcının beklediği biçime çevirir."""
