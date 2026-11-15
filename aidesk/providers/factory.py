"""Ayarlara göre doğru sağlayıcıyı oluşturan fabrika."""
from __future__ import annotations

from .. import config
from .base import Provider


def get_provider(settings: config.Settings | None = None) -> Provider:
    settings = settings or config.load_settings()
    provider = settings.provider
    api_key = config.get_api_key(provider)
    if not api_key:
        raise RuntimeError(
            f"'{provider}' için API anahtarı bulunamadı. Kurulumu çalıştırın."
        )
    model = settings.active_model()

    if provider == "anthropic":
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider(api_key, model)
    if provider == "openai":
        from .openai_provider import OpenAIProvider
        return OpenAIProvider(api_key, model)
    if provider == "gemini":
        from .gemini_provider import GeminiProvider
        return GeminiProvider(api_key, model)
    raise ValueError(f"Bilinmeyen sağlayıcı: {provider}")
