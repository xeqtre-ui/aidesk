"""Hızlı yol — sık kullanılan müzik komutlarını AI'ya sormadan tanır.

Cümledeki TÜM kelimeler bilinen kelimelerden oluşuyorsa (ör. "Spotify'dan son
dinlediğim şarkıyı aç") doğrudan araç çalıştırılır; anında sonuç verir.
Tanımadığı bir kelime varsa (ör. sanatçı adı) hiçbir şey yapmaz ve istek AI'ya
gider. Böylece yanlış eşleşme riski düşük tutulur.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Intent:
    tool: str
    args: dict
    label: str


def _normalize(text: str) -> list[str]:
    t = text.replace("I", "ı").replace("İ", "i").lower()
    t = re.sub(r"[’'`´]", " ", t)                 # spotify'dan -> spotify dan
    t = re.sub(r"[^\wçğıöşü ]+", " ", t)
    return t.split()


def _detect_app(tokens: list[str]) -> str | None:
    joined = " ".join(tokens)
    if "spotify" in joined or "spotifay" in joined:
        return "spotify"
    if "apple" in joined or "itunes" in joined:
        return "apple music"
    return None


# Anlamı değiştirmeyen dolgu kelimeleri ve ekler
FILLER = {
    "lütfen", "hadi", "bir", "bana", "benim", "şu", "bu", "şimdi", "biraz", "artık", "hemen",
    "de", "da", "dan", "den", "tan", "ten", "ı", "i", "u", "ü", "yı", "yi", "yu", "yü",
    "nı", "ni", "a", "e", "ya", "ye", "ta", "te", "dı", "ki", "mi", "mı",
    "en", "son", "sonuncu", "dinlediğim", "dinlediğimi", "dinlediğim", "dinledigim",
    "dinlediğimiz", "çaldığım", "kaldığım", "kaldığı", "yerden", "kaldığımız",
    "apple", "music", "itunes", "müzik", "müziği", "müziğe", "müzikler", "muzik",
    "şarkı", "şarkıyı", "şarkıya", "şarkımı", "şarkıları", "şarkıyla", "sarki",
    "parça", "parçayı", "parçaya", "playlist", "listemi", "çalma", "listesi",
}
MUSIC_CONTEXT = {
    "müzik", "müziği", "müziğe", "muzik", "şarkı", "şarkıyı", "şarkıya", "şarkımı", "sarki",
    "parça", "parçayı", "dinlediğim", "dinlediğimi", "dinledigim", "kaldığım", "yerden",
}
PLAY = {"aç", "ac", "çal", "cal", "başlat", "baslat", "oynat", "devam", "et", "ettir", "aç ver", "ver"}
STRONG_PLAY = {"çal", "cal", "başlat", "baslat", "oynat", "devam"}
PAUSE = {"durdur", "duraklat", "dur", "sustur", "kes", "kapat"}
NEXT = {"sonraki", "sonrakine", "geç", "atla", "değiştir", "ileri", "diğer", "diğerine", "sıradaki", "sıradakine"}
PREV = {"önceki", "öncekine", "geri", "başa", "dön", "al"}


def _is_app_token(tok: str) -> bool:
    return tok.startswith(("spotify", "spotifay"))


def match(text: str) -> Intent | None:
    tokens = _normalize(text)
    if not tokens or len(tokens) > 10:
        return None
    app = _detect_app(tokens)
    rest = {t for t in tokens if t not in FILLER and not _is_app_token(t)}
    has_music = bool(MUSIC_CONTEXT & set(tokens)) or app is not None
    joined = " ".join(tokens)
    args = {"app": app} if app else {}

    # "ne çalıyor", "hangi şarkı çalıyor", "bu ne şarkı"
    if re.search(r"\b(ne|hangi)\b.*\b(çalıyor|çalan|şarkı|şarkı bu)\b", joined) or "çalan ne" in joined:
        return Intent("now_playing", args, "Ne çalıyor?")
    if not rest:
        return None
    if rest <= PLAY and (MUSIC_CONTEXT & set(tokens) or rest & STRONG_PLAY):
        return Intent("play_music", {"app": app or "spotify"}, "Müzik açılıyor")
    if rest <= PAUSE and ("kapat" not in rest or has_music):
        return Intent("media_control", {"action": "pause", **args}, "Duraklatılıyor")
    if rest <= NEXT and (has_music or rest & {"sonraki", "sonrakine", "atla", "sıradaki", "sıradakine"}):
        return Intent("media_control", {"action": "next", **args}, "Sonraki şarkı")
    if rest <= PREV and (has_music or rest & {"önceki", "öncekine"}):
        return Intent("media_control", {"action": "previous", **args}, "Önceki şarkı")
    return None
