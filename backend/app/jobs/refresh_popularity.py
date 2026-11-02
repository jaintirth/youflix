"""Refresh TMDB popularity scores. TMDB recalculates them daily, so run this once a day from a scheduler:

    python -m app.jobs.refresh_popularity

It is a separate command (not a timer inside the web server) so it runs once no matter how many workers serve the site,
and it only $sets the popularity field, so it cannot overwrite an edit made in the admin while it runs.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

from .. import tmdb
from ..db import get_db
from ..schema import SCREEN_TYPES, tmdb_system
from ..serialize import tmdb_id_of


def main() -> int:
    if not tmdb.configured():
        print("TMDB is not configured. Set TMDB_API_KEY (or TMDB_TOKEN).", file=sys.stderr)
        return 1
    items = get_db()["items"]
    changed = 0
    for item in list(items.find({"type": {"$in": list(SCREEN_TYPES)}})):
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
    print(f"Updated TMDB popularity for {changed} title(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
