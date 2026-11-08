"""Admin sessions live in MongoDB (hashed token, expiry), so they survive restarts and are shared between workers."""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request

from .db import get_db

COOKIE = "yf_admin"
SESSION_SECONDS = 24 * 60 * 60


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db) -> str:
    token = secrets.token_hex(24)
    now = datetime.now(timezone.utc)
    db["admin_sessions"].insert_one({"tokenHash": _hash(token), "createdAt": now, "expiresAt": now + timedelta(seconds=SESSION_SECONDS)})
    return token


def delete_session(db, token: str | None) -> None:
    if token:
        db["admin_sessions"].delete_one({"tokenHash": _hash(token)})


def is_admin(db, token: str | None) -> bool:
    # The TTL index only sweeps about once a minute, so expiry is checked here too.
    return bool(token) and db["admin_sessions"].count_documents(
        {"tokenHash": _hash(token), "expiresAt": {"$gt": datetime.now(timezone.utc)}}, limit=1) > 0


def get_token(request: Request) -> str | None:
    """`Authorization: Bearer <token>` (cross-origin frontend) or the cookie (same-origin)."""
    header = request.headers.get("authorization", "")
    if header[:7].lower() == "bearer " and header[7:].strip():
        return header[7:].strip()
    return request.cookies.get(COOKIE)


def require_admin(request: Request, db=Depends(get_db)) -> None:
    if not is_admin(db, get_token(request)):
        raise HTTPException(401, "Not authorised")
