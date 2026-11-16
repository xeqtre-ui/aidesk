"""Fast path — recognizes common music commands without asking the AI.

If EVERY word in the sentence consists of known words (e.g. "play the last song
I listened to on Spotify") the tool is run directly for an instant result.
If there is an unknown word (e.g. an artist name) it does nothing and the
request is forwarded to the AI. This keeps the risk of false matches low.

Note: the keyword sets below are Turkish because they match the user's spoken
Turkish commands; they are functional data, not display text, so they are kept
as-is.
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


# Filler words and suffixes that do not change the meaning
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
    if not tokens:
        return None
    if len(tokens) > 10:            # long sentence: may only be a specific song request
        return match_song(text)
    app = _detect_app(tokens)
    rest = {t for t in tokens if t not in FILLER and not _is_app_token(t)}
    has_music = bool(MUSIC_CONTEXT & set(tokens)) or app is not None
    joined = " ".join(tokens)
    args = {"app": app} if app else {}

    # "ne çalıyor", "hangi şarkı çalıyor", "bu ne şarkı"
    if re.search(r"\b(ne|hangi)\b.*\b(çalıyor|çalan|şarkı|şarkı bu)\b", joined) or "çalan ne" in joined:
        return Intent("now_playing", args, "What's playing?")
    if not rest:
        return None
    if rest <= PLAY and (MUSIC_CONTEXT & set(tokens) or rest & STRONG_PLAY):
        return Intent("play_music", {"app": app or "spotify"}, "Starting music")
    if rest <= PAUSE and ("kapat" not in rest or has_music):
        return Intent("media_control", {"action": "pause", **args}, "Pausing")
    if rest <= NEXT and (has_music or rest & {"sonraki", "sonrakine", "atla", "sıradaki", "sıradakine"}):
        return Intent("media_control", {"action": "next", **args}, "Next track")
    if rest <= PREV and (has_music or rest & {"önceki", "öncekine"}):
        return Intent("media_control", {"action": "previous", **args}, "Previous track")
    return match_song(text)


# --- Specific song: "play the song X", "start X from Spotify", "play Tarkan" -------
SONG_VERBS = {
    "aç", "ac", "açar", "açsana", "açabilir", "açıver", "çal", "cal", "çalar", "çalsana", "çalabilir",
    "başlat", "baslat", "başlatır", "başlatsana", "başlatmanı", "başlatabilir", "oynat", "oynatır",
    "oynatsana", "dinlet", "dinletir", "koy", "koyar", "koysana", "aç bakalım",
}
STRONG_SONG_VERBS = {"çal", "cal", "çalar", "çalsana", "çalabilir", "oynat", "oynatır", "oynatsana",
                     "dinlet", "dinletir"}
SONG_WORDS = {"şarkı", "şarkısı", "şarkısını", "şarkıyı", "şarkıları", "şarkısından", "parça", "parçası",
              "parçasını", "parçayı", "parçasından", "sarki", "sarkisini"}
POLITE = {
    "mısın", "misin", "musun", "müsün", "mi", "mı", "mu", "mü", "lütfen", "usta", "ustam", "kanka", "abi",
    "kardeşim", "bana", "bize", "şunu", "onu", "bunu", "şu", "bu", "bir", "ve", "istiyorum", "isterim",
    "ister", "rica", "ederim", "hadi", "haydi", "bakalım", "hemen", "şimdi", "bi", "de", "da", "ile",
    "dan", "den", "tan", "ten", "ı", "i", "u", "ü", "ın", "in", "un", "ün", "nı", "ni", "nu", "nü",
    "yı", "yi", "yu", "yü", "ını", "ini", "unu", "ünü", "nın", "nin", "a", "e", "ya", "ye", "ta", "te",
    "uygulamasından", "uygulamasında", "üzerinden", "müzik", "müziği", "müziğini",
}


# These words indicate the request requires "thinking" ("the music X made for
# GTA 6", "their newest song"): instead of the fast path it is left to the AI
# to research.
DESCRIPTIVE = {
    "için", "yaptığı", "yaptığını", "söylediği", "söylediğini", "çıkardığı", "çıkan", "olan", "ait",
    "gibi", "en", "yeni", "eski", "ilk", "son", "popüler", "meşhur", "ünlü", "film", "filmi", "filminin",
    "filmindeki", "dizi", "dizisi", "dizisinin", "dizisindeki", "oyun", "oyunu", "oyununun", "oyunundaki",
    "soundtrack", "tarafından", "düet", "hangi", "hangisi", "benzer", "tarzında", "çalan", "geçen",
    "reklam", "reklamındaki", "trailer", "fragman", "fragmanındaki", "albüm", "albümünden", "albümü",
    "sözleri", "sözlerinde", "youtube", "youtubeda", "google", "googleda",
}


def match_song(text: str) -> Intent | None:
    tokens = _normalize(text)
    if DESCRIPTIVE & set(tokens):
        return None
    if not tokens or len(tokens) > 16:
        return None
    toks = set(tokens)
    verbs = toks & SONG_VERBS
    if not verbs:
        return None
    has_song_word = bool(toks & SONG_WORDS)
    app = _detect_app(tokens)
    # "aç" alone is too generic (could mean open an app/file): a song word or Spotify is required
    if not (has_song_word or app == "spotify" or verbs & STRONG_SONG_VERBS):
        return None
    query = [t for t in tokens
             if t not in SONG_VERBS and t not in SONG_WORDS and t not in POLITE and t not in FILLER
             and not _is_app_token(t)]
    if not query or len(query) > 6:
        return None            # empty ("open Spotify") or too complex: let the AI think
    try:
        from . import memory

        if memory.related(" ".join(query)):
            return None        # memory has a preference for this song/artist: let the AI apply it
    except Exception:  # noqa: BLE001
        pass
    return Intent("play_song", {"query": " ".join(query)}, "Searching for song")
