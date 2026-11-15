"""Bilgisayar kontrol araçları.

Her araç bir `Tool` olarak kaydedilir: ad, açıklama, JSON Schema girdi
tanımı, çağrılabilir fonksiyon ve bir "risk" seviyesi. Riskli araçlar
(ör. kabuk komutu, dosya silme) çalıştırılmadan önce kullanıcı onayı ister.

Araç şeması sağlayıcıdan bağımsızdır; her sağlayıcı kendi biçimine çevirir.
"""
from __future__ import annotations

import traceback
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable


class Risk(str, Enum):
    SAFE = "safe"        # okuma / zararsız
    MEDIUM = "medium"    # uygulama açma, medya, yazma
    HIGH = "high"        # kabuk komutu, dosya silme, tıklama otomasyonu


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    func: Callable[..., str]
    risk: Risk = Risk.SAFE


_REGISTRY: dict[str, Tool] = {}


def tool(
    name: str,
    description: str,
    parameters: dict[str, Any] | None = None,
    risk: Risk = Risk.SAFE,
) -> Callable[[Callable[..., str]], Callable[..., str]]:
    """Bir fonksiyonu araç olarak kaydeden dekoratör."""

    def deco(func: Callable[..., str]) -> Callable[..., str]:
        _REGISTRY[name] = Tool(
            name=name,
            description=description,
            parameters=parameters or {"type": "object", "properties": {}},
            func=func,
            risk=risk,
        )
        return func

    return deco


def all_tools() -> list[Tool]:
    return list(_REGISTRY.values())


def get_tool(name: str) -> Tool | None:
    return _REGISTRY.get(name)


def schema() -> list[dict[str, Any]]:
    """Ortak (sağlayıcıdan bağımsız) araç şeması."""
    return [
        {"name": t.name, "description": t.description, "parameters": t.parameters}
        for t in _REGISTRY.values()
    ]


def execute(name: str, arguments: dict[str, Any]) -> str:
    """Bir aracı çalıştırır ve metin sonucu döner. Hatalar yakalanır."""
    t = get_tool(name)
    if t is None:
        return f"HATA: '{name}' adlı araç bulunamadı."
    try:
        result = t.func(**(arguments or {}))
        return str(result) if result is not None else "Tamamlandı."
    except TypeError as e:
        return f"HATA: Geçersiz argümanlar ({e})."
    except Exception as e:  # noqa: BLE001 — araç hatasını modele geri bildiriyoruz
        return f"HATA: {e}\n{traceback.format_exc(limit=2)}"


def load_all() -> None:
    """Tüm araç modüllerini içe aktararak kaydolmalarını sağlar."""
    from . import apps, files, media, system  # noqa: F401
