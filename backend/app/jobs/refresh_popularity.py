"""Refresh TMDB popularity scores. TMDB recalculates them daily. The admin page has a "Refresh popularity" button that
calls refresh() a slice at a time; the same thing can be run from a command line:

    python -m app.jobs.refresh_popularity

It only $sets the popularity field, so it cannot overwrite an edit made in the admin while it runs.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

from .. import tmdb
from ..db import get_db
from ..schema import SCREEN_TYPES, tmdb_system
from ..serialize import tmdb_id_of


def refresh(db, offset: int = 0, limit: int | None = None) -> dict:
    """Refresh the score of one slice of the screen titles (by id, so slices are stable between calls).
    Returns {"total": titles in the catalogue, "checked": titles looked at, "updated": scores changed}.
    The admin button walks the catalogue a slice at a time, so no single request runs long."""
    items = db["items"]
    query = {"type": {"$in": list(SCREEN_TYPES)}}
    total = items.count_documents(query)
    cursor = items.find(query).sort("_id", 1).skip(max(offset, 0))
    if limit:
        cursor = cursor.limit(limit)
    checked = changed = 0
    for item in list(cursor):
        checked += 1
        known_id = tmdb_id_of(item)
        found = tmdb.popularity(item["type"], known_id, item["title"], item.get("year"))
        if not found:
            continue
        tid, pop = found
        if (item.get("details") or {}).get("popularity") == pop and known_id:
            continue
        update = {"$set": {"details.popularity": pop, "updatedAt": datetime.now(timezone.utc)}}
        if not known_id:
            update["$push"] = {"externalIds": {"system": tmdb_system(item["type"]), "id": tid}}
        try:
            items.update_one({"_id": item["_id"]}, update)
        except DuplicateKeyError:    # our TMDB guess belongs to another item: keep the score, skip the id
            update.pop("$push")
            items.update_one({"_id": item["_id"]}, update)
        changed += 1
    return {"total": total, "checked": checked, "updated": changed}


def main() -> int:
    if not tmdb.configured():
        print("TMDB is not configured. Set TMDB_API_KEY (or TMDB_TOKEN).", file=sys.stderr)
        return 1
    result = refresh(get_db())
    print(f"Updated TMDB popularity for {result['updated']} title(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
