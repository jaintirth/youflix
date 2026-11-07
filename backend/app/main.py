"""YOUFLIX API and site. Run from the backend folder:  uvicorn app.main:app --reload"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import FRONTEND_DIR, get_settings
from .routes import admin, public, titles

log = logging.getLogger("youflix")


def create_app() -> FastAPI:
    app = FastAPI(title="YOUFLIX", docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)

    # The admin UI reads `error` from every failure, so keep that shape (FastAPI's default is {"detail": ...}).
    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        return JSONResponse({"error": str(exc.detail)}, status_code=exc.status_code, headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        return JSONResponse({"error": "Invalid request"}, status_code=400)

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception):
        log.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse({"error": "Something went wrong"}, status_code=500)

    settings = get_settings()
    if settings.cors_origin_list:
        # Auth is a bearer token in the Authorization header, so cookies/credentials are not needed cross-origin.
        app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_methods=["*"],
                           allow_headers=["Authorization", "Content-Type"], max_age=600)

    app.include_router(public.router)
    app.include_router(admin.router)
    app.include_router(titles.router)

    if settings.serve_frontend:
        # Clean URLs: /movie/<id> and /admin instead of the .html files.
        @app.get("/movie.html", include_in_schema=False)
        @app.get("/admin.html", include_in_schema=False)
        def drop_html(request: Request):
            return RedirectResponse(request.url.path.removesuffix(".html"), status_code=301)

        @app.get("/movie/{title_id}", include_in_schema=False)
        def movie_page(title_id: str):
            return FileResponse(FRONTEND_DIR / "movie.html")

        @app.get("/admin", include_in_schema=False)
        def admin_page():
            return FileResponse(FRONTEND_DIR / "admin.html")

        # Everything else is the static frontend; mounted last so the routes above win.
        app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

    return app


app = create_app()
