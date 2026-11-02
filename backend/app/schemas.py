"""Request bodies. Deliberately loose (Any): the admin UI has always sent numbers or text for the same field and the
handlers normalise them, so type strictness here would be a behaviour change. Unknown keys are kept, as before."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class Loose(BaseModel):
    model_config = ConfigDict(extra="allow")


class LoginBody(Loose):
    password: Any = None


class AddTitleBody(Loose):
    url: Any = None
    type: Any = None
    title: Any = None
    description: Any = None
    category: Any = None
    year: Any = None
    poster: Any = None
    backdrop: Any = None
    tmdbId: Any = None
    isAnime: Any = None


class EditTitleBody(Loose):
    youtubeUrl: Any = None
    trailerUrl: Any = None
    isAnime: Any = None


class CandidateBody(Loose):
    tmdbId: Any = None
    type: Any = None
    title: Any = None
    year: Any = None
    description: Any = None
    poster: Any = None
    backdrop: Any = None
    youtubeUrl: Any = None
    category: Any = None
    isAnime: Any = None


class ApproveBody(Loose):
    url: Any = None
    isAnime: Any = None
