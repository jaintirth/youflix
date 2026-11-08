from __future__ import annotations

from functools import lru_cache

import certifi
from pymongo import MongoClient
from pymongo.database import Database

from .config import get_settings


@lru_cache
def _client(uri: str) -> MongoClient:
    # certifi's CA bundle: some hosts (e.g. Wasmer) ship Python without a system certificate store.
    return MongoClient(uri, tz_aware=True, serverSelectionTimeoutMS=8000, tlsCAFile=certifi.where())


def get_db() -> Database:
    """FastAPI dependency (tests override it) and the entry point for the command-line jobs."""
    s = get_settings()
    if not s.mongodb_uri:
        raise RuntimeError("MONGODB_URI is not set. Put it in .env or the environment.")
    return _client(s.mongodb_uri)[s.mongodb_db]
