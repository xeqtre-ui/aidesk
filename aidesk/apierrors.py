"""API error handling: a quota (429) cooldown list and readable Turkish messages.

On the Gemini free tier the quota is PER MODEL (e.g. 20 requests a day).
When a model hits its quota we skip it until it resets and move to another;
we don't let the library wait for minutes and retry.

Note: user-facing messages returned by humanize() are kept in Turkish on purpose,
because they are shown to the user and spoken aloud by Jarvis (Turkish voice).
"""
from __future__ import annotations

import re
import threading
import time

_lock = threading.Lock()
_cooldown: dict[str, float] = {}   # model -> don't use until this time
_loaded = False


def _file():
    from .config import CONFIG_DIR

    return CONFIG_DIR / "cooldown.json"


def _load() -> None:
    """When the app restarts, remember quota-exhausted/busy models (avoid pointless waiting)."""
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        import json

        now = time.time()
        data = json.loads(_file().read_text("utf-8"))
        _cooldown.update({k: float(v) for k, v in data.items() if float(v) > now})
    except Exception:  # noqa: BLE001
        pass


def cool(model: str, seconds: float) -> None:
    import json

    with _lock:
        _load()
        _cooldown[model] = time.time() + seconds
        now = time.time()
        try:
            _file().write_text(json.dumps({k: v for k, v in _cooldown.items() if v > now}), "utf-8")
        except Exception:  # noqa: BLE001
            pass


def is_cooling(model: str) -> bool:
    with _lock:
        _load()
        return _cooldown.get(model, 0) > time.time()


def retry_delay(e: Exception, default: float = 600.0) -> float:
    m = re.search(r"retryDelay'?\"?:\s*'?\"?(\d+(?:\.\d+)?)s", str(e))
    return float(m.group(1)) if m else default


def status_code(e: Exception) -> int | None:
    for attr in ("code", "status_code"):
        v = getattr(e, attr, None)
        if isinstance(v, int):
            return v
    m = re.match(r"\s*(\d{3})\b", str(e))
    return int(m.group(1)) if m else None


def is_quota_error(e: Exception) -> bool:
    """Is this a quota / credit / rate-limit error? (worth switching to another provider)"""
    low = str(e).lower()
    return status_code(e) == 429 or any(k in low for k in (
        "resource_exhausted", "no credits", "insufficient_quota", "rate limit", "credit balance",
        "no usable gemini model"))


def humanize(e: Exception) -> str:
    """Turns a raw API error into a short Turkish sentence to show the user."""
    code = status_code(e)
    text = str(e)
    low = text.lower()
    if "no credits" in low or "insufficient_quota" in low or "credit balance is too low" in low:
        return ("Seçili yapay zekâ hesabında API kredisi yok. Sağlayıcının sitesinde Billing "
                "bölümünden kredi yükle (ChatGPT/Claude aboneliği API kredisi içermez).")
    if code == 429 or "RESOURCE_EXHAUSTED" in text or "rate limit" in text.lower():
        hours = retry_delay(e, 0) / 3600
        when = f" (yaklaşık {hours:.0f} saat sonra sıfırlanır)" if hours >= 1 else ""
        return ("Yapay zekâ kotan doldu" + when + ". Ücretsiz Gemini'de model başına "
                "günlük istek sınırı var; Google AI Studio'da faturalandırmayı açarsan kalkar.")
    if code in (401, 403) or "API_KEY_INVALID" in text or "invalid api key" in text.lower():
        return "API anahtarı geçersiz ya da yetkisiz. Ayarlar'dan anahtarı kontrol et."
    if code == 404:
        return "Seçili yapay zekâ modeli artık mevcut değil. Ayarlar'dan başka bir sağlayıcı dene."
    if code and code >= 500:
        return "Yapay zekâ servisi şu an yanıt vermiyor, birazdan tekrar dene."
    low = text.lower()
    if any(k in low for k in ("connect", "timeout", "timed out", "getaddrinfo", "network")):
        return "İnternet bağlantısı yok ya da çok yavaş."
    if "No API key found" in text:
        return text
    return f"Bir hata oluştu: {text[:160]}"
