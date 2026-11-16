"""Common provider interface and data structures."""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    """A tool the model wants to call."""
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class AssistantTurn:
    """The model's response in one step.

    `text` is the text to show the user; if there are `tool_calls` the tools must
    be run and the results fed back. `raw` is the provider-specific message object
    and is appended to the history.
    """
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: Any = None

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


class Provider(abc.ABC):
    """The contract all AI providers implement."""

    name: str = "base"

    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    def user_message(self, text: str) -> Any:
        """Builds the user message in the format the provider expects."""
        return {"role": "user", "content": text}

    @abc.abstractmethod
    def chat(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AssistantTurn:
        """Runs one turn of chat.

        Args:
            system: The system instruction.
            messages: The chat history in the provider-specific format.
            tools: Provider-appropriate tool definitions produced by `tools.schema`.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def append_assistant(
        self, messages: list[dict[str, Any]], turn: AssistantTurn
    ) -> None:
        """Appends the model's response to the history (in the provider-specific format)."""

    @abc.abstractmethod
    def append_tool_results(
        self,
        messages: list[dict[str, Any]],
        results: list[tuple[ToolCall, str]],
    ) -> None:
        """Appends tool results to the history."""

    @staticmethod
    @abc.abstractmethod
    def format_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Converts the common tool schema to the format the provider expects."""
