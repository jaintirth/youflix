"""MongoDB documents <-> the JSON shape the frontend has always received (flat fields, ISO dates)."""
from __future__ import annotations

from datetime import datetime, timezone


def to_iso(dt: datetime) -> str:
    """The format the API has always returned: 2026-11-02T16:03:47.791Z."""
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def tmdb_id_of(doc: dict):
    for e in doc.get("externalIds", []):
        if e["system"].startswith("tmdb:"):
            return e["id"]
    return None


def item_to_api(doc: dict) -> dict:
    src, det = doc["source"], doc.get("details", {})
    out = {
        "id": doc["_id"],
        "type": doc["type"],
        "isAnime": bool(det.get("isAnime")),
        "title": doc["title"],
        "description": doc.get("description", ""),
        "category": doc["category"],
        "genres": doc.get("genres", []),
        "year": doc.get("year"),
        "kind": src["kind"],
        "youtubeId": src["externalId"],
        "youtubeUrl": src["url"],
        "thumbnail": doc.get("thumbnail"),
        "poster": doc.get("poster"),
        "tmdbId": tmdb_id_of(doc),
        "channel": src.get("channel"),
        "addedAt": to_iso(doc["addedAt"]),
    }
    if det.get("popularity") is not None:   # absent until TMDB has scored the title, as before
        out["popularity"] = det["popularity"]
    if det.get("trailerKey"):
        out["trailerKey"] = det["trailerKey"]
    return out


def candidate_to_api(doc: dict) -> dict:
    return {
        "id": doc["_id"],
        "tmdbId": tmdb_id_of(doc),
        "type": doc["type"],
        "title": doc["title"],
        "year": doc.get("year"),
        "description": doc.get("description", ""),
        "poster": doc.get("poster"),
        "backdrop": doc.get("backdrop"),
        "category": doc.get("category"),
        "isAnime": bool(doc.get("details", {}).get("isAnime")),
        "youtubeUrl": doc.get("sourceUrl"),
    }
