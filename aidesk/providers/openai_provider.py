"""OpenAI (GPT) provider."""
from __future__ import annotations

import json
from typing import Any

from .base import AssistantTurn, Provider, ToolCall


class OpenAIProvider(Provider):
    name = "openai"

    def __init__(self, api_key: str, model: str) -> None:
        super().__init__(api_key, model)
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key)

    @staticmethod
    def format_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["parameters"],
                },
            }
            for t in tools
        ]

    def chat(self, system, messages, tools) -> AssistantTurn:
        full = [{"role": "system", "content": system}, *messages]
        extra = {}
        if self.model.startswith(("gpt-5", "o3", "o4")):
            extra["reasoning_effort"] = "low"     # reasoning models: don't keep the voice assistant waiting
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=full,
            tools=tools or None,
            tool_choice="auto" if tools else None,
            **extra,
        )
        msg = resp.choices[0].message
        tool_calls: list[ToolCall] = []
        for tc in msg.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))
        return AssistantTurn(text=msg.content or "", tool_calls=tool_calls, raw=msg)

    def append_assistant(self, messages, turn: AssistantTurn) -> None:
        msg = turn.raw
        entry: dict[str, Any] = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            entry["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]
        messages.append(entry)

    def append_tool_results(self, messages, results) -> None:
        for call, output in results:
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": output,
            })
