from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
ROOT = BACKEND_DIR.parent
FRONTEND_DIR = ROOT / "frontend"

log = logging.getLogger("youflix")


class Settings(BaseSettings):
    """Read from the environment, or from .env in the repository root. Real environment variables win."""
    model_config = SettingsConfigDict(env_file=ROOT / ".env", env_file_encoding="utf-8-sig", extra="ignore")

    mongodb_uri: str = ""
    mongodb_db: str = "youflix"
    admin_password: str = "admin"
    tmdb_api_key: str = ""
    tmdb_token: str = ""      # v4 read access token (alternative to the v3 key)


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if s.admin_password == "admin":
        log.warning('ADMIN_PASSWORD not set - using default "admin". Set it before deploying.')
    return s
