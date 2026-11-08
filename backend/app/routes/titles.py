"""Admin catalogue management: add, edit and delete titles."""
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import JSONResponse
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from .. import youtube
from ..auth import require_admin
from ..db import get_db
from ..publish import publish
from ..schemas import AddTitleBody, EditTitleBody
from ..serialize import item_to_api

router = APIRouter(dependencies=[Depends(require_admin)])


def js_str(value) -> str:
    """String(value) as JavaScript does it, so an explicit null is rejected like any other bad link."""
    return "null" if value is None else str(value)


@router.post("/api/titles")
def add_title(body: AddTitleBody = Body(default_factory=AddTitleBody), db=Depends(get_db)):
    """Add a title directly from a YouTube URL."""
    base = body.model_dump()
    r = publish(db, base, base.pop("url"))
    return JSONResponse(item_to_api(r.item) if r.item else {"error": r.error}, status_code=r.status)


@router.patch("/api/titles/{title_id}")
def edit_title(title_id: str, body: EditTitleBody = Body(default_factory=EditTitleBody), db=Depends(get_db)):
    """Change a title's movie link and/or trailer link. An empty trailer link goes back to TMDB's trailer."""
    item = db["items"].find_one({"_id": title_id})
    if not item:
        raise HTTPException(404, "Not found")
    given = body.model_dump(exclude_unset=True)
    set_, unset = {}, {}
    if "isAnime" in given:
        set_["details.isAnime"] = given["isAnime"] is True

    if "youtubeUrl" in given:
        link = js_str(given["youtubeUrl"])
        parsed = youtube.parse_youtube(link)
        if not parsed:
            raise HTTPException(400, "Watch link is not a valid YouTube video or playlist URL")
        kind, yid = parsed
        taken = {"source.provider": "youtube", "source.externalId": yid}
        if db["items"].find_one({**taken, "_id": {"$ne": title_id}}, {"_id": 1}):
            raise HTTPException(409, "That YouTube link is already used by another title")
        channel = item["source"].get("channel")
        if yid != item["source"]["externalId"]:
            meta = youtube.fetch_oembed(link)
            if not meta:
                raise HTTPException(400, "YouTube could not find that link (private or removed?)")
            channel = meta.get("author_name") or channel or None
        set_.update({"source.url": link.strip(), "source.externalId": yid, "source.kind": kind, "source.channel": channel})

    if "trailerUrl" in given:
        raw = js_str(given["trailerUrl"]).strip()
        if not raw:
            unset["details.trailerKey"] = ""
        else:
            parsed = youtube.parse_youtube(raw)
            if not parsed or parsed[0] != "video":
                raise HTTPException(400, "Trailer link must be a YouTube video URL")
            set_["details.trailerKey"] = parsed[1]

    update = {"$set": {**set_, "updatedAt": datetime.now(timezone.utc)}}
    if unset:
        update["$unset"] = unset
    try:
        updated = db["items"].find_one_and_update({"_id": title_id}, update, return_document=ReturnDocument.AFTER)
    except DuplicateKeyError:
        raise HTTPException(409, "That YouTube link is already used by another title")
    if not updated:
        raise HTTPException(404, "Not found")
    return item_to_api(updated)


@router.delete("/api/titles/{title_id}")
def delete_title(title_id: str, db=Depends(get_db)):
    if db["items"].delete_one({"_id": title_id}).deleted_count == 0:
        raise HTTPException(404, "Not found")
    return {"ok": True}
