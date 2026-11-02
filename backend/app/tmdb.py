"""TMDB client: discovery search, genres, popularity and the detail data for the title page.

TMDB only knows screen content (movies and TV). Other content types get their own adapters later; see docs/mongodb-design.md.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import httpx

from .config import get_settings
from .serialize import item_to_api, tmdb_id_of

API = "https://api.themoviedb.org/3"
TIMEOUT = 10.0
CACHE_TTL = timedelta(days=1)


class TmdbError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def configured() -> bool:
    s = get_settings()
    return bool(s.tmdb_api_key or s.tmdb_token)


def request(path: str, **params):
    s = get_settings()
    if not configured():
        raise TmdbError("TMDB is not configured. Set TMDB_API_KEY (or TMDB_TOKEN) and restart.", 503)
    headers = {}
    if s.tmdb_token:
        headers["Authorization"] = "Bearer " + s.tmdb_token
    else:
        params["api_key"] = s.tmdb_api_key
    try:
        r = httpx.get(API + path, params=params, headers=headers, timeout=TIMEOUT)
    except httpx.HTTPError as e:
        raise TmdbError("TMDB request failed (network error)") from e
    if r.status_code >= 400:
        raise TmdbError(f"TMDB request failed ({r.status_code})")
    return r.json()


def img(path, size):
    return f"https://image.tmdb.org/t/p/{size}{path}" if path else None


def js_round(x: float) -> int:
    return math.floor(x + 0.5)


def kind_of(item_type: str) -> str:
    return "tv" if item_type == "series" else "movie"


def search_id(kind: str, title: str, year):
    params = {"query": title}
    if year:
        params["first_air_date_year" if kind == "tv" else "year"] = year
    results = request(f"/search/{kind}", **params).get("results") or []
    return results[0]["id"] if results else None


def infer_genres(item_type: str, tmdb_id, title: str, year):
    """All of a title's TMDB genres (e.g. ['Animation', 'Action']). None when TMDB can't say."""
    if not configured():
        return None
    try:
        kind = kind_of(item_type)
        tid = tmdb_id or search_id(kind, title, year)
        if not tid:
            return None
        names = [g["name"] for g in request(f"/{kind}/{tid}").get("genres") or []]
        return names or None
    except (TmdbError, KeyError, TypeError):
        return None


def anime_category(genres):
    """'Animation' says nothing about an anime, so its category is the first real genre."""
    return next((g for g in genres or [] if g != "Animation"), None)


def popularity(item_type: str, tmdb_id, title: str, year):
    """(tmdb id, popularity score) for a title, finding it on TMDB first when only the name is known. None when unknown."""
    if not configured():
        return None
    try:
        kind = kind_of(item_type)
        tid = tmdb_id or search_id(kind, title, year)
        if not tid:
            return None
        return tid, js_round(request(f"/{kind}/{tid}")["popularity"] * 100) / 100
    except (TmdbError, KeyError, TypeError):
        return None


def from_tmdb(x: dict, item_type: str) -> dict:
    date = x.get("release_date") or x.get("first_air_date") or ""
    return {
        "tmdbId": x["id"],
        "type": item_type,
        "title": x.get("title") or x.get("name"),
        "year": int(date[:4]) if date[:4].isdigit() else None,
        "description": x.get("overview") or "",
        "poster": img(x.get("poster_path"), "w342"),
        "backdrop": img(x.get("backdrop_path"), "w780"),
        # TMDB has no anime flag: Japanese-language animation is the closest match. Admin can override.
        "isAnime": 16 in (x.get("genre_ids") or []) and x.get("original_language") == "ja",
    }


def search(item_type: str, q: str, page: int) -> dict:
    data = request("/search/tv" if item_type == "series" else "/search/movie", query=q, include_adult="false", page=page)
    return {
        "results": [from_tmdb(x, item_type) for x in data["results"]],
        "page": data["page"],
        "totalPages": min(data["total_pages"], 500),
        "totalResults": data["total_results"],
    }


def _round1(x) -> float:
    return js_round((x or 0) * 10) / 10


def build_details(d: dict) -> dict:
    videos = (d.get("videos") or {}).get("results") or []
    trailer = (next((v for v in videos if v.get("site") == "YouTube" and v.get("type") == "Trailer"), None)
               or next((v for v in videos if v.get("site") == "YouTube"), None))
    credits = d.get("credits") or {}

    def review(r):
        content = r.get("content") or ""
        return {
            "author": r.get("author"),
            "rating": (r.get("author_details") or {}).get("rating"),
            "date": (r.get("created_at") or "")[:10],
            "content": content[:700].strip() + "..." if len(content) > 700 else content,
            "url": r.get("url"),
        }

    return {
        "tagline": d.get("tagline") or "",
        "overview": d.get("overview") or "",
        "genres": [g["name"] for g in d.get("genres") or []],
        "runtime": d.get("runtime") or (d.get("episode_run_time") or [None])[0] or None,
        "rating": _round1(d["vote_average"]) if d.get("vote_average") else None,
        "votes": d.get("vote_count") or 0,
        "language": d.get("original_language"),
        "seasons": d.get("number_of_seasons") or None,
        "backdrop": img(d.get("backdrop_path"), "w1280"),
        "poster": img(d.get("poster_path"), "w780"),
        "trailer": trailer["key"] if trailer else None,
        "cast": [{"name": c["name"], "character": c.get("character"), "photo": img(c.get("profile_path"), "w185")}
                 for c in (credits.get("cast") or [])[:14]],
        "crew": [{"name": c["name"], "job": c["job"]} for c in (credits.get("crew") or [])
                 if c.get("job") in ("Director", "Writer", "Screenplay", "Producer")][:6],
        "reviews": [review(r) for r in ((d.get("reviews") or {}).get("results") or [])[:6]],
        "similar": [{"title": x.get("title") or x.get("name"),
                     "year": (x.get("release_date") or x.get("first_air_date") or "")[:4],
                     "poster": img(x["poster_path"], "w342"),
                     "rating": _round1(x.get("vote_average"))}
                    for x in ((d.get("similar") or {}).get("results") or []) if x.get("poster_path")][:12],
    }


def title_details(db, item: dict) -> dict:
    """Everything on the title page beyond what is stored: cast, reviews, trailer, similar titles.
    TMDB's answer is cached in the metadata_cache collection."""
    trailer_key = (item.get("details") or {}).get("trailerKey")
    base = {"title": item_to_api(item), "details": {"trailer": trailer_key} if trailer_key else None}
    if not configured() or item["type"] not in ("movie", "series"):
        return base
    try:
        kind = kind_of(item["type"])
        tid = tmdb_id_of(item) or search_id(kind, item["title"], item.get("year"))
        if not tid:
            return base
        key, now = f"tmdb:{kind}:{tid}", datetime.now(timezone.utc)
        cached = db["metadata_cache"].find_one({"_id": key, "expiresAt": {"$gt": now}})
        if cached:
            data = cached["data"]
        else:
            data = build_details(request(f"/{kind}/{tid}", append_to_response="credits,reviews,videos,similar"))
            db["metadata_cache"].replace_one({"_id": key}, {"_id": key, "data": data, "expiresAt": now + CACHE_TTL}, upsert=True)
        return {"title": base["title"], "details": {**data, "trailer": trailer_key} if trailer_key else data}
    except TmdbError as e:
        return {**base, "error": str(e)}
