"""Anthropic (Claude) sağlayıcısı."""
from __future__ import annotations

from typing import Any

from .base import AssistantTurn, Provider, ToolCall


class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(self, api_key: str, model: str) -> None:
        super().__init__(api_key, model)
        import anthropic  # tembel içe aktarma

        self.client = anthropic.Anthropic(api_key=api_key)

    @staticmethod
    def format_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "name": t["name"],
                "description": t["description"],
                "input_schema": t["parameters"],
            }
            for t in tools
        ]

    def chat(self, system, messages, tools) -> AssistantTurn:
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=system,
            messages=messages,
            tools=tools or [],
        )
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(id=block.id, name=block.name, arguments=dict(block.input))
                )
        return AssistantTurn(
            text="".join(text_parts),
            tool_calls=tool_calls,
            raw=resp.content,  # content bloklarını geçmişe ekleyeceğiz
        )

    def append_assistant(self, messages, turn: AssistantTurn) -> None:
        # Claude için assistant mesajı doğrudan content bloklarıdır.
        content = []
        for block in turn.raw:
            if block.type == "text":
                content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                content.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })
        messages.append({"role": "assistant", "content": content})

    def append_tool_results(self, messages, results) -> None:
        content = [
            {
                "type": "tool_result",
                "tool_use_id": call.id,
                "content": output,
            }
            for call, output in results
        ]
        messages.append({"role": "user", "content": content})
