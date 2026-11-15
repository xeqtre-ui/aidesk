"""Uygulama ve pencere yönetimi araçları."""
from __future__ import annotations

import os
import shutil
import subprocess

from . import Risk, tool

# Yaygın uygulamalar için kısa ad -> başlatma hedefi eşlemesi.
# 'start' kabuğu çoğu kayıtlı uygulamayı adıyla açabilir.
_KNOWN_APPS = {
    "spotify": "spotify:",
    "apple music": "msmusic:",
    "chrome": "chrome",
    "edge": "msedge",
    "firefox": "firefox",
    "notepad": "notepad",
    "not defteri": "notepad",
    "hesap makinesi": "calc",
    "calculator": "calc",
    "explorer": "explorer",
    "dosya gezgini": "explorer",
    "terminal": "wt",
    "cmd": "cmd",
    "ayarlar": "ms-settings:",
    "settings": "ms-settings:",
    "vscode": "code",
    "vs code": "code",
}


@tool(
    name="open_app",
    description=(
        "Bir uygulamayı veya URI'yi açar. 'spotify', 'chrome', 'not defteri' "
        "gibi yaygın adları tanır; tanımadığını Windows kabuğu üzerinden "
        "adıyla açmayı dener. Uygulama zaten açıksa öne getirir."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Uygulama adı veya başlatma hedefi (ör. 'spotify').",
            }
        },
        "required": ["name"],
    },
    risk=Risk.MEDIUM,
)
def open_app(name: str) -> str:
    key = name.strip().lower()
    target = _KNOWN_APPS.get(key, name.strip())
    try:
        if os.name == "nt":
            # Protokol/URI (ör. spotify:) veya ms-settings: ise doğrudan start.
            if target.endswith(":") or "://" in target:
                os.startfile(target)  # type: ignore[attr-defined]
            elif shutil.which(target):
                subprocess.Popen(target, shell=False)
            else:
                # Kabuk üzerinden kayıtlı uygulama adıyla aç.
                subprocess.Popen(["cmd", "/c", "start", "", target], shell=False)
        else:
            subprocess.Popen([target])
        return f"'{name}' açıldı."
    except Exception as e:  # noqa: BLE001
        return f"'{name}' açılamadı: {e}"


@tool(
    name="list_windows",
    description="Açık pencerelerin başlıklarını listeler.",
    risk=Risk.SAFE,
)
def list_windows() -> str:
    try:
        import pygetwindow as gw

        titles = [t for t in gw.getAllTitles() if t.strip()]
        if not titles:
            return "Görünür pencere yok."
        return "Açık pencereler:\n- " + "\n- ".join(titles[:40])
    except Exception as e:  # noqa: BLE001
        return f"Pencereler okunamadı: {e}"


@tool(
    name="focus_window",
    description="Başlığında verilen metni içeren pencereyi öne getirir/etkinleştirir.",
    parameters={
        "type": "object",
        "properties": {
            "title_contains": {
                "type": "string",
                "description": "Pencere başlığında aranacak metin (ör. 'Spotify').",
            }
        },
        "required": ["title_contains"],
    },
    risk=Risk.MEDIUM,
)
def focus_window(title_contains: str) -> str:
    try:
        import pygetwindow as gw

        needle = title_contains.lower()
        for w in gw.getAllWindows():
            if needle in (w.title or "").lower():
                if w.isMinimized:
                    w.restore()
                w.activate()
                return f"'{w.title}' öne getirildi."
        return f"'{title_contains}' içeren pencere bulunamadı."
    except Exception as e:  # noqa: BLE001
        return f"Pencere öne getirilemedi: {e}"


@tool(
    name="close_app",
    description="Verilen ada sahip süreci/uygulamayı kapatır (sonlandırır).",
    parameters={
        "type": "object",
        "properties": {
            "process_name": {
                "type": "string",
                "description": "Süreç adı (ör. 'spotify', 'notepad'). .exe gerekmez.",
            }
        },
        "required": ["process_name"],
    },
    risk=Risk.HIGH,
)
def close_app(process_name: str) -> str:
    import psutil

    name = process_name.lower().removesuffix(".exe")
    killed = 0
    for proc in psutil.process_iter(["name"]):
        try:
            pname = (proc.info["name"] or "").lower().removesuffix(".exe")
            if pname == name:
                proc.terminate()
                killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if killed:
        return f"{killed} süreç sonlandırıldı ('{process_name}')."
    return f"'{process_name}' adlı çalışan süreç bulunamadı."
