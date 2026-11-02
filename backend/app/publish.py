"""Publishing a title into the catalogue (direct add, or approving a candidate)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

from . import tmdb, youtube
from .schema import tmdb_system


@dataclass
class Result:
    status: int
    item: dict | None = None
    error: str | None = None


def loose_int(value):
    """int from a JSON number or numeric text, else None (the old API accepted both)."""
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        n = int(float(value))
    except (TypeError, ValueError):
        return None
    return n or None


def text(value):
    s = str(value).strip() if value is not None else ""
    return s or None


def external_id_filter(item_type: str, tmdb_id):
    return {"externalIds": {"$elemMatch": {"system": tmdb_system(item_type), "id": tmdb_id}}}


def publish(db, base: dict, url) -> Result:
    """`base` carries optional TMDB metadata (title, year, poster, backdrop, category, tmdbId, isAnime...) that takes
    precedence over YouTube's."""
    url = str(url or "").strip()
    if not url:
        return Result(400, error="Paste the free YouTube link first")
    parsed = youtube.parse_youtube(url)
    if not parsed:
        return Result(400, error="Not a valid YouTube video or playlist URL")
    kind, yid = parsed

    source_filter = {"source.provider": "youtube", "source.externalId": yid}
    if db["items"].find_one(source_filter, {"_id": 1}):
        return Result(409, error="That YouTube link is already in the catalogue")
    meta = youtube.fetch_oembed(url)
    given_title = text(base.get("title"))
    if (not meta or not meta.get("title")) and not given_title:
        return Result(400, error="YouTube could not find that link (private or removed?). Enter a title manually to add anyway.")

    name = given_title or meta["title"].strip()
    item_type = "series" if base.get("type") == "series" else "movie"
    year = loose_int(base.get("year"))
    tmdb_id = loose_int(base.get("tmdbId"))
    genres = tmdb.infer_genres(item_type, tmdb_id, name, year) or []
    is_anime = base.get("isAnime") is True or base.get("isAnime") == "true"
    yt_thumb = f"https://i.ytimg.com/vi/{yid}/hqdefault.jpg" if kind == "video" else (meta or {}).get("thumbnail_url")
    now = datetime.now(timezone.utc)

    details = {"isAnime": is_anime, "popularity": None}
    auto_found = False
    pop = tmdb.popularity(item_type, tmdb_id, name, year)
    if pop:
        details["popularity"] = pop[1]
        if not tmdb_id:
            tmdb_id, auto_found = pop[0], True

    doc = {
        "_id": str(uuid.uuid4()),
        "type": item_type,
        "title": name,
        "description": text(base.get("description")) or "",
        "category": text(base.get("category")) or (tmdb.anime_category(genres) if is_anime else None) or (genres[0] if genres else None) or "General",
        "genres": genres,
        "year": year,
        "thumbnail": text(base.get("backdrop")) or text(base.get("poster")) or yt_thumb,
        "poster": text(base.get("poster")),
        "externalIds": [{"system": tmdb_system(item_type), "id": tmdb_id}] if tmdb_id else [],
        "source": {"provider": "youtube", "kind": kind, "externalId": yid, "url": url, "channel": (meta or {}).get("author_name")},
        "details": details,
        "addedAt": now,
        "updatedAt": now,
    }
    try:
        db["items"].insert_one(doc)
    except DuplicateKeyError:
        if db["items"].find_one(source_filter, {"_id": 1}):      # lost a race for the same link
            return Result(409, error="That YouTube link is already in the catalogue")
        if auto_found:                                            # our TMDB guess matched another item: keep ours without the guess
            doc["externalIds"] = []
            try:
                db["items"].insert_one(doc)
            except DuplicateKeyError:
                return Result(409, error="That YouTube link is already in the catalogue")
        else:
            return Result(409, error="That title is already in the catalogue")
    return Result(201, item=doc)
