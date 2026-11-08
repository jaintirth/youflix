from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

import httpx

VIDEO_ID = re.compile(r"^[\w-]{11}$")
TIMEOUT = 8.0


def parse_youtube(raw: str):
    """Returns (kind, id) with kind 'video' or 'playlist', or None."""
    try:
        url = urlparse(raw.strip())
    except ValueError:
        return None
    host = re.sub(r"^www\.|^m\.", "", url.hostname or "")
    q = parse_qs(url.query)
    lst, v = (q.get("list") or [None])[0], (q.get("v") or [None])[0]
    if host in ("youtube.com", "music.youtube.com"):
        if url.path == "/playlist" and lst:
            return "playlist", lst
        if v and VIDEO_ID.match(v):
            return ("playlist" if lst else "video"), (lst or v)
        m = re.match(r"^/(embed|shorts|live)/([\w-]{11})", url.path)
        if m:
            return "video", m.group(2)
    elif host == "youtu.be":
        vid = url.path[1:12]
        if VIDEO_ID.match(vid):
            return ("playlist" if lst else "video"), (lst or vid)
    return None


def fetch_oembed(url: str):
    """YouTube's public oEmbed record, {'embedBlocked': True} when the owner disabled embedding, or None."""
    try:
        r = httpx.get("https://www.youtube.com/oembed", params={"format": "json", "url": url}, timeout=TIMEOUT)
    except httpx.HTTPError:
        return None
    if r.status_code == 401:
        return {"embedBlocked": True}      # video exists but the owner disabled embedding
    if r.status_code >= 400:
        return None
    try:
        return r.json()
    except ValueError:
        return None


_YEAR = re.compile(r"\b(19[2-9]\d|20[0-4]\d)\b")
_SPLIT = re.compile(r"\s[|–—]\s|\s-\s(?=.*(?:full|movie|hd|film|official))", re.I)
_BRACKETS = re.compile(r"[(\[][^)\]]*[)\]]")
_NOISE = re.compile(r"\b(full|new|latest|hindi|english|tamil|telugu|punjabi|bollywood|hollywood|dubbed|hd|4k|1080p|720p|movie|movies|film|official|episode|episodes|with english subtitles?|eng sub)\b", re.I)
_SYMBOLS = re.compile(r"(?:[^\w'&:! ]|_)+")


def search_query_from_title(raw: str) -> tuple[str, int | None]:
    """A clean TMDB search term from a YouTube title: strips 'Full Movie', years, quality tags, channel suffixes."""
    m = _YEAR.search(raw)
    year = int(m.group(1)) if m else None
    t = _SPLIT.split(raw)[0]
    t = _BRACKETS.sub(" ", t)
    t = _NOISE.sub(" ", t)
    t = _YEAR.sub(" ", t)
    t = _SYMBOLS.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return (t or raw), year
