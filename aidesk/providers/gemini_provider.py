"""Google (Gemini) provider — using the official `google-genai` library."""
from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from .. import config as app_config
from .base import AssistantTurn, Provider, ToolCall

log = logging.getLogger("aidesk.gemini")


def _to_gemini_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Converts JSON Schema to the subset Gemini accepts."""
    out: dict[str, Any] = {}
    for k, v in schema.items():
        if k == "type" and isinstance(v, str):
            out["type"] = v.upper()          # object -> OBJECT
        elif k == "properties" and isinstance(v, dict):
            out["properties"] = {pk: _to_gemini_schema(pv) for pk, pv in v.items()}
        elif k == "items" and isinstance(v, dict):
            out["items"] = _to_gemini_schema(v)
        elif k in ("description", "enum", "required"):
            out[k] = v
    return out


class GeminiProvider(Provider):
    name = "gemini"

    def __init__(self, api_key: str, model: str) -> None:
        super().__init__(api_key, model)
        from google import genai
        from google.genai import types

        self._types = types
        # Turn off the library's own wait-and-retry loop (on quota exhaustion it used
        # to freeze for minutes). We manage the switch to a backup model ourselves.
        self.client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=30_000, retry_options=types.HttpRetryOptions(attempts=1)
            ),
        )
        self._candidates_cache: list[str] | None = None

    @staticmethod
    def format_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        decls = []
        for t in tools:
            d: dict[str, Any] = {"name": t["name"], "description": t["description"]}
            params = _to_gemini_schema(t["parameters"])
            if params.get("properties"):  # an empty object schema is not sent
                d["parameters"] = params
            decls.append(d)
        return [{"function_declarations": decls}]

    def user_message(self, text: str) -> Any:
        types = self._types
        return types.Content(role="user", parts=[types.Part.from_text(text=text)])

    def _flash_candidates(self) -> list[str]:
        """Backup models: 'gemini-X-flash' (newest to oldest), then '-flash-lite'."""
        if self._candidates_cache is None:
            flash, lite = [], []
            try:
                for m in self.client.models.list():
                    match = re.fullmatch(r"models/(gemini-(\d+(?:\.\d+)?)-flash(-lite)?)", m.name or "")
                    if match:
                        (lite if match.group(3) else flash).append((float(match.group(2)), match.group(1)))
            except Exception:  # noqa: BLE001
                log.warning("Could not get the Gemini model list", exc_info=True)
            self._candidates_cache = [n for _, n in sorted(flash, reverse=True)] + \
                                     [n for _, n in sorted(lite, reverse=True)]
        return [m for m in self._candidates_cache if m != self.model]

    def _generate(self, model: str, messages, config, timeout_ms: int | None = None):
        if timeout_ms:
            config = config.model_copy(update={"http_options": self._types.HttpOptions(timeout=timeout_ms)})
        return self.client.models.generate_content(model=model, contents=messages, config=config)

    def chat(self, system, messages, tools) -> AssistantTurn:
        types = self._types
        from google.genai import errors

        from .. import apierrors

        config = types.GenerateContentConfig(
            system_instruction=system,
            tools=tools or None,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        if self.model.startswith("gemini-3") and not getattr(self, "_no_thinking_cfg", False):
            # The default long "thinking" keeps the voice assistant waiting (~2 s/step -> ~1 s)
            config = config.model_copy(update={"thinking_config": types.ThinkingConfig(thinking_level="low")})
        resp = None
        first_error: Exception | None = None
        for i, model in enumerate([self.model, *self._flash_candidates()]):
            if apierrors.is_cooling(model):
                continue
            try:
                # Try backup models quickly: a busy (504) model shouldn't keep everyone waiting
                resp = self._generate(model, messages, config, None if i == 0 else 12_000)
            except (errors.ClientError, errors.ServerError) as e:
                code = e.code or 0
                if code == 400 and "thinking" in str(e).lower() and config.thinking_config is not None:
                    # This model doesn't support the thinking setting: retry without it
                    self._no_thinking_cfg = True
                    config = config.model_copy(update={"thinking_config": None})
                    resp = self._generate(model, messages, config)
                    break
                if code == 429:      # this model's quota is used up: skip until it resets
                    apierrors.cool(model, apierrors.retry_delay(e))
                elif code == 404:    # the model was removed
                    apierrors.cool(model, 86_400)
                elif code >= 500:    # Google side is busy: skip for a while
                    apierrors.cool(model, 3600)  # busy model: skip for 1 hour
                else:
                    raise            # e.g. invalid key: switching to another model is pointless
                log.warning("Gemini %s unusable (%s), moving to the next model", model, code)
                first_error = first_error or e
                continue
            except Exception as e:  # noqa: BLE001 — network timeout etc.: skip this model
                if "timeout" not in type(e).__name__.lower() and "timed out" not in str(e).lower():
                    raise
                apierrors.cool(model, 600)
                log.warning("Gemini %s timed out, moving to the next model", model)
                first_error = first_error or e
                continue
            if model != self.model:
                # Quota (429) / load (5xx) are temporary: the backup model is used ONLY this
                # session; the next day it returns to the main model. A permanent change is made
                # only if the main model was removed entirely (404).
                retired = first_error is not None and (getattr(first_error, "code", 0) or 0) == 404
                log.warning("Gemini model switched to %s (%s)", model,
                            "permanent" if retired else "for this session")
                if retired and not model.endswith("-lite"):
                    s = app_config.load_settings()
                    s.model = {**s.model, "gemini": model}
                    app_config.save_settings(s)
                self.model = model
            break
        if resp is None:
            raise first_error or RuntimeError("No usable Gemini model (all quotas exhausted).")
        content = resp.candidates[0].content if resp.candidates else None
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for part in (content.parts or []) if content else []:
            fc = part.function_call
            if fc and fc.name:
                tool_calls.append(
                    ToolCall(id=fc.id or uuid.uuid4().hex, name=fc.name, arguments=dict(fc.args or {}))
                )
            elif part.text and not getattr(part, "thought", False):
                text_parts.append(part.text)
        return AssistantTurn(text="".join(text_parts), tool_calls=tool_calls, raw=content)

    def append_assistant(self, messages, turn: AssistantTurn) -> None:
        if turn.raw is not None:
            messages.append(turn.raw)

    def append_tool_results(self, messages, results) -> None:
        types = self._types
        parts = []
        for call, output in results:
            part = types.Part.from_function_response(name=call.name, response={"result": output})
            if part.function_response is not None and call.id:
                part.function_response.id = call.id
            parts.append(part)
        messages.append(types.Content(role="user", parts=parts))
