from __future__ import annotations

from functools import lru_cache

from pymongo import MongoClient
from pymongo.database import Database

from .config import get_settings


@lru_cache
def _client(uri: str) -> MongoClient:
    return MongoClient(uri, tz_aware=True, serverSelectionTimeoutMS=8000)


def get_db() -> Database:
    """FastAPI dependency (tests override it) and the entry point for the command-line jobs."""
    s = get_settings()
    if not s.mongodb_uri:
        raise RuntimeError("MONGODB_URI is not set. Put it in .env or the environment.")
    return _client(s.mongodb_uri)[s.mongodb_db]
