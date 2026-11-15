"""Dosya araçları — açma, arama, okuma."""
from __future__ import annotations

import os
from pathlib import Path

from . import Risk, tool

_SEARCH_ROOTS = [
    Path.home() / "Desktop",
    Path.home() / "Masaüstü",
    Path.home() / "Documents",
    Path.home() / "Belgeler",
    Path.home() / "Downloads",
    Path.home() / "İndirilenler",
]


@tool(
    name="open_path",
    description=(
        "Bir dosya veya klasörü varsayılan uygulamasıyla açar. Tam yol verin."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Açılacak dosya/klasör yolu."}
        },
        "required": ["path"],
    },
    risk=Risk.MEDIUM,
)
def open_path(path: str) -> str:
    p = Path(os.path.expandvars(os.path.expanduser(path)))
    if not p.exists():
        return f"Bulunamadı: {p}"
    try:
        if os.name == "nt":
            os.startfile(str(p))  # type: ignore[attr-defined]
        else:
            import subprocess

            subprocess.Popen(["xdg-open", str(p)])
        return f"Açıldı: {p}"
    except Exception as e:  # noqa: BLE001
        return f"Açılamadı: {e}"


@tool(
    name="search_files",
    description=(
        "Masaüstü, Belgeler ve İndirilenler klasörlerinde dosya adına göre "
        "arama yapar. Açmak istenen dosyanın yolunu bulmak için kullanın."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Dosya adında aranacak metin.",
            },
            "limit": {
                "type": "integer",
                "description": "Dönecek en fazla sonuç (varsayılan 15).",
            },
        },
        "required": ["query"],
    },
    risk=Risk.SAFE,
)
def search_files(query: str, limit: int = 15) -> str:
    q = query.lower()
    hits: list[str] = []
    for root in _SEARCH_ROOTS:
        if not root.exists():
            continue
        for dirpath, _dirs, filenames in os.walk(root):
            # Çok derine inme.
            if dirpath.count(os.sep) - str(root).count(os.sep) > 4:
                continue
            for fn in filenames:
                if q in fn.lower():
                    hits.append(str(Path(dirpath) / fn))
                    if len(hits) >= limit:
                        return "Bulunanlar:\n- " + "\n- ".join(hits)
    if not hits:
        return f"'{query}' ile eşleşen dosya bulunamadı."
    return "Bulunanlar:\n- " + "\n- ".join(hits)


@tool(
    name="read_text_file",
    description="Bir metin dosyasının içeriğini okur (ilk 8000 karakter).",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Okunacak dosyanın yolu."}
        },
        "required": ["path"],
    },
    risk=Risk.SAFE,
)
def read_text_file(path: str) -> str:
    p = Path(os.path.expandvars(os.path.expanduser(path)))
    if not p.exists() or not p.is_file():
        return f"Dosya bulunamadı: {p}"
    try:
        return p.read_text("utf-8", errors="replace")[:8000]
    except Exception as e:  # noqa: BLE001
        return f"Okunamadı: {e}"
