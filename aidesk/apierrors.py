"""API hata yönetimi: kota (429) bekleme listesi ve anlaşılır Türkçe mesajlar.

Gemini ücretsiz katmanında kota MODEL BAŞINA ayrıdır (ör. günde 20 istek).
Bir model kotayı doldurunca onu sıfırlanana kadar atlayıp diğerine geçeriz;
kütüphanenin dakikalarca bekleyip yeniden denemesine izin vermeyiz.
"""
from __future__ import annotations

import re
import threading
import time

_lock = threading.Lock()
_cooldown: dict[str, float] = {}   # model -> bu zamana kadar kullanma


def cool(model: str, seconds: float) -> None:
    with _lock:
        _cooldown[model] = time.time() + seconds


def is_cooling(model: str) -> bool:
    with _lock:
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


def humanize(e: Exception) -> str:
    """Ham API hatasını kullanıcıya gösterilecek kısa Türkçe cümleye çevirir."""
    code = status_code(e)
    text = str(e)
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
    if "API anahtarı bulunamadı" in text:
        return text
    return f"Bir hata oluştu: {text[:160]}"
