"""Web tools — web search, reading pages, searching/opening in the browser, YouTube.

- web_search      : title + snippet + real link from Yahoo results (no API key needed).
- read_webpage    : the plain text of a page (to deepen research).
- youtube_search  : YouTube video titles (an info source for music/video questions).
- youtube_play    : opens the first video from the search in the browser.
- open_search     : opens a site's OWN search page in the browser (Google / YouTube /
                    Wikipedia / stores etc.); for an unknown site a Google "site:" search.
- open_url        : opens an address in the default browser.
"""
from __future__ import annotations

import html
import json
import logging
import os
import re
import urllib.parse

from . import Risk, tool

log = logging.getLogger("aidesk.web")

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
}
COOKIES = {"CONSENT": "YES+1", "SOCS": "CAI"}   # skip the Google/YouTube cookie-consent page


def _clean(fragment: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", fragment, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _get(url: str, **params):
    import requests

    return requests.get(url, params=params or None, headers=HEADERS, cookies=COOKIES, timeout=10)


def _open(url: str) -> None:
    os.startfile(url)  # type: ignore[attr-defined]  # default browser


# ---------------------------------------------------------------------------
# Web search
# ---------------------------------------------------------------------------
def _yahoo_html(query: str) -> str:
    """Yahoo occasionally returns a transient 500: try a few times."""
    import time

    import requests

    for attempt in range(4):
        r = requests.get("https://search.yahoo.com/search", params={"p": query}, headers=HEADERS, timeout=10)
        if r.status_code == 200 and "algo" in r.text:
            return r.text
        time.sleep(0.4 + 0.4 * attempt)
    return ""


def _wikipedia(query: str, limit: int) -> list[dict]:
    import requests

    out: list[dict] = []
    for lang in ("tr", "en"):
        r = requests.get(f"https://{lang}.wikipedia.org/w/api.php", headers=HEADERS, timeout=10, params={
            "action": "query", "list": "search", "srsearch": query, "format": "json", "srlimit": limit})
        for it in r.json().get("query", {}).get("search", []):
            out.append({"title": it["title"], "snippet": _clean(it.get("snippet", "")),
                        "url": f"https://{lang}.wikipedia.org/wiki/" + urllib.parse.quote(it["title"].replace(" ", "_"))})
        if out:
            break
    return out[:limit]


def search_results(query: str, limit: int = 6) -> list[dict]:
    text = _yahoo_html(query)
    if not text:
        log.warning("Yahoo did not respond, falling back to Wikipedia")
        return _wikipedia(query, limit)
    blocks = re.findall(r'<div class="[^"]*\balgo\b[^"]*".*?(?=<div class="[^"]*\balgo\b|</ol>)', text, re.S)
    out: list[dict] = []
    for b in blocks:
        href = re.search(r'href="([^"]*?/RU=[^"]+)"', b) or re.search(r'href="(https?://(?!search\.yahoo)[^"]+)"', b)
        title = re.search(r"<h3[^>]*>(.*?)</h3>", b, re.S)
        if not href or not title:
            continue
        link = html.unescape(href.group(1))
        real = re.search(r"/RU=([^/]+)/R[KS]=", link)
        url = urllib.parse.unquote(real.group(1)) if real else link
        t = _clean(title.group(1))
        # Strip the "site.com › path" part stuck in front of the title
        t = re.sub(r"^\S+\.\S+(\s›\s\S+)*\s", "", t) if "›" in t else t
        snip = re.search(r'class="compText[^"]*"[^>]*>(.*?)</div>', b, re.S)
        out.append({"title": t, "url": url, "snippet": _clean(snip.group(1)) if snip else ""})
        if len(out) >= limit:
            break
    return out


@tool(
    name="web_search",
    description=(
        "Searches the web and returns the titles, snippets and links of the results. "
        "Use this FIRST for any information you don't know, that is current, or that you're "
        "unsure about (e.g. 'the song X made for Y', new releases, news, prices). "
        "If the results aren't enough, read a page with read_webpage. Does NOT open anything in the browser."
    ),
    parameters={
        "type": "object",
        "properties": {"query": {"type": "string", "description": "Search query (in English if needed)."}},
        "required": ["query"],
    },
    risk=Risk.SAFE,
)
def web_search(query: str) -> str:
    try:
        results = search_results(query)
    except Exception as e:  # noqa: BLE001
        return f"Could not search (internet connection?): {e}"
    if not results:
        return f"No results found for '{query}'."
    lines = [f"{i}. {r['title']}\n   {r['snippet'][:260]}\n   {r['url']}" for i, r in enumerate(results, 1)]
    return "Search results:\n" + "\n".join(lines)


@tool(
    name="read_webpage",
    description="Reads the text of a web page (first ~6000 characters). To deepen research.",
    parameters={
        "type": "object",
        "properties": {"url": {"type": "string", "description": "The address of the page to read."}},
        "required": ["url"],
    },
    risk=Risk.SAFE,
)
def read_webpage(url: str) -> str:
    if not re.match(r"https?://", url):
        url = "https://" + url
    try:
        r = _get(url)
    except Exception as e:  # noqa: BLE001
        return f"Could not open the page: {e}"
    title = re.search(r"<title[^>]*>(.*?)</title>", r.text, re.S | re.I)
    body = re.search(r"<body[^>]*>(.*)</body>", r.text, re.S | re.I)
    text = _clean(body.group(1) if body else r.text)
    return f"Title: {_clean(title.group(1)) if title else '-'}\n{text[:6000]}"


# ---------------------------------------------------------------------------
# YouTube
# ---------------------------------------------------------------------------
def youtube_videos(query: str, limit: int = 6) -> list[dict]:
    r = _get("https://www.youtube.com/results", search_query=query)
    m = re.search(r"var ytInitialData = (\{.*?\});</script>", r.text, re.S)
    if not m:
        ids = re.findall(r'"videoId":"([\w-]{11})"', r.text)
        return [{"id": i, "title": "", "channel": "", "duration": ""} for i in dict.fromkeys(ids)][:limit]
    vids: list[dict] = []

    def walk(o) -> None:
        if len(vids) >= limit:
            return
        if isinstance(o, dict):
            v = o.get("videoRenderer")
            if v and v.get("videoId"):
                vids.append({
                    "id": v["videoId"],
                    "title": "".join(x.get("text", "") for x in v.get("title", {}).get("runs", [])),
                    "channel": ((v.get("ownerText") or {}).get("runs") or [{}])[0].get("text", ""),
                    "duration": (v.get("lengthText") or {}).get("simpleText", ""),
                })
            for x in o.values():
                walk(x)
        elif isinstance(o, list):
            for x in o:
                walk(x)

    walk(json.loads(m.group(1)))
    return vids


@tool(
    name="youtube_search",
    description=(
        "Searches YouTube and returns video titles/channels (does NOT open the browser). "
        "A good info source for music and video questions (e.g. the song of a game/movie)."
    ),
    parameters={
        "type": "object",
        "properties": {"query": {"type": "string", "description": "Search query."}},
        "required": ["query"],
    },
    risk=Risk.SAFE,
)
def youtube_search(query: str) -> str:
    try:
        vids = youtube_videos(query)
    except Exception as e:  # noqa: BLE001
        return f"Could not search YouTube: {e}"
    if not vids:
        return "No results found."
    return "YouTube results:\n" + "\n".join(
        f"{i}. {v['title']} | {v['channel']} {v['duration']} | https://www.youtube.com/watch?v={v['id']}"
        for i, v in enumerate(vids, 1))


@tool(
    name="youtube_play",
    description=(
        "Searches YouTube and opens and plays the BEST first video in the browser. Use this for "
        "'open/play X on YouTube' requests. If you know a specific video address, use open_url."
    ),
    parameters={
        "type": "object",
        "properties": {"query": {"type": "string", "description": "Video search (e.g. 'Duman Bu Akşam live')."}},
        "required": ["query"],
    },
    risk=Risk.MEDIUM,
)
def youtube_play(query: str) -> str:
    try:
        vids = youtube_videos(query, limit=3)
    except Exception as e:  # noqa: BLE001
        return f"Could not search YouTube: {e}"
    if not vids:
        _open("https://www.youtube.com/results?" + urllib.parse.urlencode({"search_query": query}))
        return "No video found; opened the YouTube search results."
    v = vids[0]
    _open(f"https://www.youtube.com/watch?v={v['id']}")
    return f"Opened on YouTube: {v['title'] or v['id']} ({v['channel']})."


# ---------------------------------------------------------------------------
# Searching / opening an address in the browser
# ---------------------------------------------------------------------------
# NOTE: the keys below (including Turkish site names like "vikipedi", "görseller",
# "haritalar", "ekşi sözlük") are matched against the user's spoken site name; kept as-is.
SITE_SEARCH = {
    "google": "https://www.google.com/search?q={q}",
    "youtube": "https://www.youtube.com/results?search_query={q}",
    "bing": "https://www.bing.com/search?q={q}",
    "duckduckgo": "https://duckduckgo.com/?q={q}",
    "vikipedi": "https://tr.wikipedia.org/w/index.php?search={q}",
    "wikipedia": "https://en.wikipedia.org/w/index.php?search={q}",
    "google haritalar": "https://www.google.com/maps/search/{q}",
    "haritalar": "https://www.google.com/maps/search/{q}",
    "maps": "https://www.google.com/maps/search/{q}",
    "google görseller": "https://www.google.com/search?tbm=isch&q={q}",
    "görseller": "https://www.google.com/search?tbm=isch&q={q}",
    "github": "https://github.com/search?q={q}",
    "reddit": "https://www.reddit.com/search/?q={q}",
    "x": "https://x.com/search?q={q}",
    "twitter": "https://x.com/search?q={q}",
    "instagram": "https://www.instagram.com/explore/search/keyword/?q={q}",
    "ekşi sözlük": "https://eksisozluk.com/?q={q}",
    "eksisozluk": "https://eksisozluk.com/?q={q}",
    "trendyol": "https://www.trendyol.com/sr?q={q}",
    "hepsiburada": "https://www.hepsiburada.com/ara?q={q}",
    "amazon": "https://www.amazon.com.tr/s?k={q}",
    "n11": "https://www.n11.com/arama?q={q}",
    "sahibinden": "https://www.sahibinden.com/kelime-ile-arama?query_text={q}",
    "spotify": "https://open.spotify.com/search/{q}",
    "twitch": "https://www.twitch.tv/search?term={q}",
    "kick": "https://kick.com/search?query={q}",
    "imdb": "https://www.imdb.com/find/?q={q}",
    "stackoverflow": "https://stackoverflow.com/search?q={q}",
    "chatgpt": "https://chatgpt.com/?q={q}",
}


def _site_key(site: str) -> str:
    s = site.strip().lower().replace("İ", "i")
    s = re.sub(r"^(https?://)?(www\.)?", "", s).split("/")[0]
    s = re.sub(r"\.(com|org|net|tv|com\.tr)(\.tr)?$", "", s)
    return {"youtube'da": "youtube", "google'da": "google", "yt": "youtube", "wiki": "vikipedi"}.get(s, s)


@tool(
    name="open_search",
    description=(
        "Opens a site's OWN search page in the browser (the user sees the results on screen). "
        "site: 'google' (default), 'youtube', 'vikipedi', 'haritalar', 'görseller', 'github', "
        "'reddit', 'x', 'ekşi sözlük', 'trendyol', 'hepsiburada', 'amazon', 'sahibinden', 'imdb' or "
        "any domain name (e.g. 'webtekno.com' -> searches that site via Google). Use this for "
        "'search X on Google', 'search X on YouTube', 'look up X on Trendyol' requests; don't type with the keyboard."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The text to search for."},
            "site": {"type": "string", "description": "Site name or domain. Default: google."},
        },
        "required": ["query"],
    },
    risk=Risk.MEDIUM,
)
def open_search(query: str, site: str = "google") -> str:
    key = _site_key(site or "google")
    q = urllib.parse.quote_plus(query)
    template = SITE_SEARCH.get(key)
    if template:
        url = template.format(q=q if "{q}" in template and "/maps/" not in template else urllib.parse.quote(query))
        label = site
    else:
        domain = re.sub(r"^(https?://)?(www\.)?", "", site.strip()).split("/")[0]
        if "." not in domain:
            domain += ".com"
        url = "https://www.google.com/search?q=" + urllib.parse.quote_plus(f"site:{domain} {query}")
        label = f"Google (within {domain})"
    _open(url)
    return f"Opened a search for '{query}' on {label} in the browser."


@tool(
    name="open_url",
    description="Opens a web address in the default browser (e.g. 'youtube.com', 'https://...').",
    parameters={
        "type": "object",
        "properties": {"url": {"type": "string", "description": "The address to open."}},
        "required": ["url"],
    },
    risk=Risk.MEDIUM,
)
def open_url(url: str) -> str:
    url = url.strip()
    if not re.match(r"[a-z][a-z0-9+.-]*:", url, re.I):
        url = "https://" + url
    if not re.match(r"https?://", url, re.I):
        return "Only http/https addresses can be opened."
    _open(url)
    return f"Opened in the browser: {url}"
