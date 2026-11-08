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
    cors_origins: str = ""    # comma-separated frontend origins allowed to call the API, e.g. https://youflix.onrender.com
    serve_frontend: bool = True   # False on the API-only deployment (frontend hosted elsewhere)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if s.admin_password == "admin":
        log.warning('ADMIN_PASSWORD not set - using default "admin". Set it before deploying.')
    return s
