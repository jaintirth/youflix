"""One-off: fix titles added before categories and genres were automatic. Run it by hand when you need it:

    python -m app.jobs.backfill_categories

- titles still on category "General" get their main TMDB genre;
- anime without genres get every TMDB genre (so One-Punch Man shows under both Action and Comedy) and a real
  category instead of "Animation".
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone

from .. import tmdb
from ..db import get_db
from ..schema import SCREEN_TYPES
from ..serialize import tmdb_id_of


def main() -> int:
    if not tmdb.configured():
        print("TMDB is not configured. Set TMDB_API_KEY (or TMDB_TOKEN).", file=sys.stderr)
        return 1
    items = get_db()["items"]
    changed = 0
    for item in list(items.find({"type": {"$in": list(SCREEN_TYPES)}})):
        is_anime = (item.get("details") or {}).get("isAnime")
        needs_category = item.get("category") in (None, "", "General")
        needs_genres = is_anime and not item.get("genres")
        if not (needs_category or needs_genres):
            continue
        genres = tmdb.infer_genres(item["type"], tmdb_id_of(item), item["title"], item.get("year"))
        if not genres:
            continue
        set_ = {}
        if needs_genres:
            set_["genres"] = genres
        if needs_category or (needs_genres and item.get("category") == "Animation"):
            category = (tmdb.anime_category(genres) if is_anime else genres[0]) or item.get("category")
            if category and category != item.get("category"):
                set_["category"] = category
        if set_:
            items.update_one({"_id": item["_id"]}, {"$set": {**set_, "updatedAt": datetime.now(timezone.utc)}})
            changed += 1
    print(f"Categorised {changed} existing title(s) from TMDB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
