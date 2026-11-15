"""Sistem kontrolü — fare, klavye, ekran, pano, kabuk.

DİKKAT: Bu araçlar bilgisayarı doğrudan kontrol eder (tam otomasyon).
Yüksek riskli olanlar (kabuk komutu, tıklama) asistan döngüsünde kullanıcı
onayından geçer.
"""
from __future__ import annotations

import base64
import io
import subprocess
from pathlib import Path

from . import Risk, tool


def _pyautogui():
    import pyautogui

    pyautogui.FAILSAFE = True   # fareyi sol-üst köşeye atınca durdur
    pyautogui.PAUSE = 0.05
    return pyautogui


@tool(
    name="type_text",
    description="Odaktaki pencereye verilen metni yazar (klavye simülasyonu).",
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Yazılacak metin."}
        },
        "required": ["text"],
    },
    risk=Risk.HIGH,
)
def type_text(text: str) -> str:
    pg = _pyautogui()
    pg.typewrite(text, interval=0.01)
    return f"{len(text)} karakter yazıldı."


@tool(
    name="press_keys",
    description=(
        "Klavye kısayolu/tuş gönderir. Örnekler: 'enter', 'ctrl+c', "
        "'alt+tab', 'win+d'. Birden çok tuş '+' ile birleştirilir."
    ),
    parameters={
        "type": "object",
        "properties": {
            "keys": {
                "type": "string",
                "description": "Tuş kombinasyonu, ör. 'ctrl+shift+esc'.",
            }
        },
        "required": ["keys"],
    },
    risk=Risk.HIGH,
)
def press_keys(keys: str) -> str:
    pg = _pyautogui()
    combo = [k.strip() for k in keys.lower().replace(" ", "").split("+") if k.strip()]
    if not combo:
        return "Boş tuş kombinasyonu."
    pg.hotkey(*combo)
    return f"'{keys}' gönderildi."


@tool(
    name="click",
    description=(
        "Ekranda verilen (x, y) koordinatına tıklar. button: 'left', 'right', "
        "'double'. Koordinatları belirlemek için önce 'screenshot' alınabilir."
    ),
    parameters={
        "type": "object",
        "properties": {
            "x": {"type": "integer", "description": "X koordinatı (piksel)."},
            "y": {"type": "integer", "description": "Y koordinatı (piksel)."},
            "button": {
                "type": "string",
                "enum": ["left", "right", "double"],
                "description": "Tıklama türü.",
            },
        },
        "required": ["x", "y"],
    },
    risk=Risk.HIGH,
)
def click(x: int, y: int, button: str = "left") -> str:
    pg = _pyautogui()
    if button == "double":
        pg.doubleClick(x, y)
    else:
        pg.click(x, y, button=button)
    return f"({x}, {y}) konumuna {button} tıklandı."


@tool(
    name="screenshot",
    description=(
        "Ekranın görüntüsünü alır ve kaydeder. Döndürdüğü dosya yolu, görsel "
        "akıl yürütme için modele geri verilebilir. Yüksek çözünürlüğü küçültür."
    ),
    risk=Risk.SAFE,
)
def screenshot() -> str:
    pg = _pyautogui()
    from ..config import CONFIG_DIR

    img = pg.screenshot()
    # Boyutu makul tut.
    img.thumbnail((1600, 1600))
    out = CONFIG_DIR / "last_screenshot.png"
    img.save(out)
    return f"Ekran görüntüsü kaydedildi: {out}"


@tool(
    name="get_clipboard",
    description="Panodaki (clipboard) metni okur.",
    risk=Risk.SAFE,
)
def get_clipboard() -> str:
    import pyperclip

    text = pyperclip.paste()
    return text or "(pano boş)"


@tool(
    name="set_clipboard",
    description="Panoya (clipboard) metin kopyalar.",
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Panoya kopyalanacak metin."}
        },
        "required": ["text"],
    },
    risk=Risk.MEDIUM,
)
def set_clipboard(text: str) -> str:
    import pyperclip

    pyperclip.copy(text)
    return "Panoya kopyalandı."


@tool(
    name="run_shell",
    description=(
        "Bir kabuk komutu çalıştırır (Windows'ta PowerShell) ve çıktısını "
        "döner. Çok güçlüdür; sadece gerektiğinde kullanın. 20 sn zaman aşımı."
    ),
    parameters={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Çalıştırılacak komut."}
        },
        "required": ["command"],
    },
    risk=Risk.HIGH,
)
def run_shell(command: str) -> str:
    import os

    try:
        if os.name == "nt":
            args = ["powershell", "-NoProfile", "-NonInteractive", "-Command", command]
        else:
            args = ["bash", "-lc", command]
        proc = subprocess.run(
            args, capture_output=True, text=True, timeout=20
        )
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        parts = []
        if out:
            parts.append(out[:4000])
        if err:
            parts.append(f"[stderr] {err[:1000]}")
        parts.append(f"(çıkış kodu {proc.returncode})")
        return "\n".join(parts)
    except subprocess.TimeoutExpired:
        return "HATA: Komut 20 saniyede tamamlanmadı."


@tool(
    name="set_volume",
    description="Sistem ses seviyesini ayarlar (0-100) veya sessize alır.",
    parameters={
        "type": "object",
        "properties": {
            "level": {
                "type": "integer",
                "description": "0-100 arası ses seviyesi. mute=true ise yok sayılır.",
            },
            "mute": {
                "type": "boolean",
                "description": "true ise sessize alır/açar.",
            },
        },
    },
    risk=Risk.MEDIUM,
)
def set_volume(level: int | None = None, mute: bool | None = None) -> str:
    # pyautogui üzerinden medya tuşları ile kaba ayar (ek bağımlılık gerekmez).
    pg = _pyautogui()
    if mute:
        pg.press("volumemute")
        return "Ses sessize alındı/açıldı."
    if level is not None:
        level = max(0, min(100, int(level)))
        # Önce sıfırla, sonra kademeli artır (her basış ~%2).
        for _ in range(50):
            pg.press("volumedown")
        for _ in range(level // 2):
            pg.press("volumeup")
        return f"Ses yaklaşık %{level} seviyesine ayarlandı."
    return "Bir 'level' veya 'mute' belirtin."
