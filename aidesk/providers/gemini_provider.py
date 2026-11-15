"""Google (Gemini) sağlayıcısı — resmi `google-genai` kütüphanesi ile."""
from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from .. import config as app_config
from .base import AssistantTurn, Provider, ToolCall

log = logging.getLogger("aidesk.gemini")


def _to_gemini_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """JSON Schema'yı Gemini'nin kabul ettiği alt kümeye çevirir."""
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
        # Kütüphanenin kendi bekle-yeniden-dene döngüsünü kapat (kota dolunca
        # dakikalarca donuyordu). Yedek modele geçişi biz yönetiyoruz.
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
            if params.get("properties"):  # boş nesne şeması gönderilmez
                d["parameters"] = params
            decls.append(d)
        return [{"function_declarations": decls}]

    def user_message(self, text: str) -> Any:
        types = self._types
        return types.Content(role="user", parts=[types.Part.from_text(text=text)])

    def _flash_candidates(self) -> list[str]:
        """Yedek modeller: 'gemini-X-flash' (yeniden eskiye), sonra '-flash-lite'."""
        if self._candidates_cache is None:
            flash, lite = [], []
            try:
                for m in self.client.models.list():
                    match = re.fullmatch(r"models/(gemini-(\d+(?:\.\d+)?)-flash(-lite)?)", m.name or "")
                    if match:
                        (lite if match.group(3) else flash).append((float(match.group(2)), match.group(1)))
            except Exception:  # noqa: BLE001
                log.warning("Gemini model listesi alınamadı", exc_info=True)
            self._candidates_cache = [n for _, n in sorted(flash, reverse=True)] + \
                                     [n for _, n in sorted(lite, reverse=True)]
        return [m for m in self._candidates_cache if m != self.model]

    def _generate(self, model: str, messages, config):
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
        resp = None
        first_error: Exception | None = None
        for model in [self.model, *self._flash_candidates()]:
            if apierrors.is_cooling(model):
                continue
            try:
                resp = self._generate(model, messages, config)
            except (errors.ClientError, errors.ServerError) as e:
                code = e.code or 0
                if code == 429:      # bu modelin kotası doldu: sıfırlanana kadar atla
                    apierrors.cool(model, apierrors.retry_delay(e))
                elif code == 404:    # model kaldırılmış
                    apierrors.cool(model, 86_400)
                elif code >= 500:    # Google tarafı yoğun: kısa süre atla
                    apierrors.cool(model, 120)
                else:
                    raise            # ör. geçersiz anahtar: başka modele geçmek anlamsız
                log.warning("Gemini %s kullanılamadı (%s), sıradaki modele geçiliyor", model, code)
                first_error = first_error or e
                continue
            if model != self.model:
                # Çalışan modeli kaydet: bir dahaki açılışta boşuna denemeyle vakit kaybetmesin.
                log.warning("Gemini modeli %s olarak değiştirildi", model)
                s = app_config.load_settings()
                s.model = {**s.model, "gemini": model}
                app_config.save_settings(s)
                self.model = model
            break
        if resp is None:
            raise first_error or RuntimeError("Kullanılabilir Gemini modeli yok (hepsinin kotası dolu).")
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
