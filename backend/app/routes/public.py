from fastapi import APIRouter, Depends, HTTPException

from .. import tmdb
from ..db import get_db
from ..serialize import item_to_api

router = APIRouter()


@router.get("/api/titles")
def list_titles(db=Depends(get_db)):
    """Most popular first (TMDB's daily popularity score): the banner (first 6) and the Top 10 row follow this order.
    Titles without a score yet sort last, newest first."""
    docs = db["items"].find().sort([("details.popularity", -1), ("addedAt", -1)])
    return [item_to_api(d) for d in docs]


@router.get("/api/titles/{title_id}/details")
def title_details(title_id: str, db=Depends(get_db)):
    item = db["items"].find_one({"_id": title_id})
    if not item:
        raise HTTPException(404, "Not found")
    return tmdb.title_details(db, item)
