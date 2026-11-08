"""Admin login, TMDB discovery and the approval queue. Nothing found on TMDB is public: the admin shortlists a
candidate, finds it free on YouTube, pastes the link and approves it; only then does it enter the catalogue."""
import hmac
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pymongo.errors import DuplicateKeyError

from .. import auth, tmdb, youtube
from ..config import get_settings
from ..db import get_db
from ..jobs.refresh_popularity import refresh as refresh_popularity
from ..publish import external_id_filter, loose_int, publish, text
from ..schemas import ApproveBody, CandidateBody, LoginBody
from ..schema import tmdb_system
from ..serialize import candidate_to_api, item_to_api

router = APIRouter()
protected = APIRouter(dependencies=[Depends(auth.require_admin)])


# ---------- session ----------
@router.post("/api/admin/login")
def login(response: Response, body: LoginBody = Body(default_factory=LoginBody), db=Depends(get_db)):
    given = str(body.password or "").encode()
    real = get_settings().admin_password.encode()
    if not hmac.compare_digest(given, real):
        raise HTTPException(401, "Wrong password")
    token = auth.create_session(db)
    response.set_cookie(auth.COOKIE, token, max_age=auth.SESSION_SECONDS, httponly=True, samesite="strict", path="/")
    return {"ok": True, "token": token}


@router.post("/api/admin/logout")
def logout(request: Request, response: Response, db=Depends(get_db)):
    auth.delete_session(db, auth.get_token(request))
    response.delete_cookie(auth.COOKIE, path="/")
    return {"ok": True}


@router.get("/api/admin/me")
def me(request: Request, db=Depends(get_db)):
    return {"admin": auth.is_admin(db, auth.get_token(request))}


# ---------- discovery ----------
@protected.get("/api/admin/config")
def config():
    return {"tmdb": tmdb.configured()}


@protected.post("/api/admin/refresh-popularity")
def refresh_popularity_slice(offset: int = 0, limit: int = 25, db=Depends(get_db)):
    """Refresh a slice of the catalogue's TMDB popularity scores. The admin button calls this repeatedly, following
    `next`, so each request stays short (a title needs one or two TMDB calls)."""
    if not tmdb.configured():
        raise HTTPException(503, "TMDB is not configured. Set TMDB_API_KEY (or TMDB_TOKEN) and restart.")
    limit = min(max(limit, 1), 50)
    offset = max(offset, 0)
    r = refresh_popularity(db, offset, limit)
    return {**r, "next": offset + limit if offset + limit < r["total"] else None}


@protected.get("/api/admin/tmdb/search")
def tmdb_search(type: str = "movie", q: str = "", page: str = "1"):
    item_type = "series" if type == "series" else "movie"
    q = q.strip()
    if not q:
        return {"results": [], "page": 1, "totalPages": 0, "totalResults": 0}
    n = max(1, min(500, loose_int(page) or 1))     # TMDB caps at 500
    try:
        return tmdb.search(item_type, q, n)
    except tmdb.TmdbError as e:
        raise HTTPException(e.status, str(e))


@protected.get("/api/admin/youtube-title")
def youtube_title(url: str = ""):
    """Turns a YouTube link into a clean search term for TMDB."""
    if not youtube.parse_youtube(url):
        raise HTTPException(400, "Not a valid YouTube video or playlist URL")
    meta = youtube.fetch_oembed(url)
    if not meta or not meta.get("title"):
        raise HTTPException(404, "YouTube could not find that link (private, removed or embedding disabled)")
    query, year = youtube.search_query_from_title(meta["title"])
    return {"raw": meta["title"], "query": query, "year": year, "channel": meta.get("author_name")}


# ---------- approval queue ----------
@protected.get("/api/admin/candidates")
def list_candidates(db=Depends(get_db)):
    return [candidate_to_api(c) for c in db["candidates"].find().sort("createdAt", -1)]


@protected.post("/api/admin/candidates")
def add_candidate(body: CandidateBody = Body(default_factory=CandidateBody), db=Depends(get_db)):
    tmdb_id = loose_int(body.tmdbId)
    title = text(body.title)
    if not tmdb_id or not title:
        raise HTTPException(400, "Missing TMDB data")
    item_type = "series" if body.type == "series" else "movie"
    ext = external_id_filter(item_type, tmdb_id)
    link = text(body.youtubeUrl)

    dup = db["candidates"].find_one(ext)
    if dup:
        # Re-shortlisting from a YouTube link: keep the candidate but attach the link it was missing.
        if link and not dup.get("sourceUrl"):
            db["candidates"].update_one({"_id": dup["_id"]}, {"$set": {"sourceUrl": link}})
            return candidate_to_api({**dup, "sourceUrl": link})
        raise HTTPException(409, "Already shortlisted")
    if db["items"].find_one(ext, {"_id": 1}):
        raise HTTPException(409, "Already in the catalogue")

    cand = {
        "_id": str(uuid.uuid4()),
        "type": item_type,
        "title": title,
        "year": loose_int(body.year),
        "description": text(body.description) or "",
        "poster": text(body.poster),
        "backdrop": text(body.backdrop),
        "category": text(body.category),
        "details": {"isAnime": body.isAnime is True},
        "externalIds": [{"system": tmdb_system(item_type), "id": tmdb_id}],
        "sourceUrl": link,
        "createdAt": datetime.now(timezone.utc),
    }
    try:
        db["candidates"].insert_one(cand)
    except DuplicateKeyError:
        raise HTTPException(409, "Already shortlisted")
    return JSONResponse(candidate_to_api(cand), status_code=201)


@protected.post("/api/admin/candidates/{cand_id}/approve")
def approve_candidate(cand_id: str, body: ApproveBody = Body(default_factory=ApproveBody), db=Depends(get_db)):
    """Attach the YouTube link the admin verified, then publish."""
    cand = db["candidates"].find_one({"_id": cand_id})
    if not cand:
        raise HTTPException(404, "Not found")
    base = candidate_to_api(cand)
    if isinstance(body.isAnime, bool):
        base["isAnime"] = body.isAnime
    url = body.url

    # Retry safety: if an earlier approval published the title but failed to remove the candidate, finish that job.
    existing = db["items"].find_one(external_id_filter(cand["type"], base["tmdbId"]))
    parsed = youtube.parse_youtube(str(url or ""))
    if existing and parsed and existing["source"]["externalId"] == parsed[1]:
        db["candidates"].delete_one({"_id": cand_id})
        return item_to_api(existing)

    r = publish(db, base, url)
    if r.item:
        db["candidates"].delete_one({"_id": cand_id})
    return JSONResponse(item_to_api(r.item) if r.item else {"error": r.error}, status_code=r.status)


@protected.delete("/api/admin/candidates/{cand_id}")
def delete_candidate(cand_id: str, db=Depends(get_db)):
    db["candidates"].delete_one({"_id": cand_id})
    return {"ok": True}


router.include_router(protected)
