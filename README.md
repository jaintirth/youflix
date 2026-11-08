# YOUFLIX

A Netflix-style front end for movies and series that are **already free on YouTube**. YOUFLIX hosts no video: it is a discovery site that links to the official source (played through YouTube's embedded player, with a "Watch on YouTube" link back).

## Layout

```
frontend/   static site (HTML, CSS, JavaScript); hosted by server.js on Render, or by the backend in local dev
server.js   tiny Node host for frontend/ (Render); package.json only declares `npm start`
backend/    FastAPI + MongoDB
  app/        the API, routes, TMDB and YouTube clients, schema, popularity and category jobs
  scripts/    one-off tools, e.g. the JSON -> MongoDB migration
  tests/      backend tests (in-memory MongoDB, TMDB and YouTube faked)
data/       the old JSON storage; only the migration reads it
docs/       design notes (MongoDB schema)
```

## Features

- Public browse page: hero banner, Movies / Anime tabs, rows by category, search, click-to-watch modal, title pages with cast, reviews and trailer
- Admin page (`/admin`), password protected: paste a YouTube video URL (movie) or playlist URL (series); title and thumbnail come from YouTube
- TMDB discovery: search TMDB and shortlist titles into a review queue. Nothing is public until you check YouTube yourself, paste the free link and click Approve & publish (needs a free TMDB key)
- Edit watch and trailer links, remove titles
- Ranked by TMDB's popularity score, refreshed on demand from the admin page

## Run it

You need Python 3.11+ and a MongoDB (a free [Atlas](https://www.mongodb.com/atlas) cluster works).

```bash
python -m venv .venv
.venv/Scripts/activate            # Windows PowerShell: .venv\Scripts\Activate.ps1   (macOS/Linux: source .venv/bin/activate)
pip install -r backend/requirements.txt
cp .env.example .env              # then fill it in
```

`.env` (repository root, git-ignored):

| Variable | Meaning |
|---|---|
| `MONGODB_URI` | MongoDB connection string |
| `MONGODB_DB` | database name (default `youflix`) |
| `ADMIN_PASSWORD` | admin login. The default is `admin`; set your own before deploying |
| `TMDB_API_KEY` or `TMDB_TOKEN` | TMDB v3 key or v4 token. Without one the manual add form still works |

First time only, create the collections and indexes and import the old JSON data (see [docs/mongodb-design.md](docs/mongodb-design.md)):

```bash
python backend/scripts/migrate_to_mongo.py --dry-run     # check the JSON files, touches nothing
python backend/scripts/migrate_to_mongo.py               # import
```

Start the site:

```bash
cd backend
uvicorn app.main:app --reload
```

Open http://localhost:8000, and http://localhost:8000/admin for the admin screen. Interactive API docs are at `/api/docs`.

## Popularity scores

A title gets its TMDB popularity score when it is added. TMDB recalculates the scores daily, so the order drifts over time:
click **Refresh popularity** in the admin page (Catalogue tab) to re-read every score. It works through the catalogue a
slice at a time, so it is safe on hosts with short request limits. There is no scheduler to set up.

The same refresh, and the category backfill, are also available as commands, run from the `backend` folder:

```bash
python -m app.jobs.refresh_popularity     # refresh all TMDB popularity scores
python -m app.jobs.backfill_categories    # occasionally: fill in missing categories and genres from TMDB
```

## Tests

```bash
pip install -r backend/requirements-dev.txt
cd backend
python -m unittest discover tests
```

## Deploying

**API** (e.g. Wasmer): Build `pip install -r backend/requirements.txt`. Start `uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port $PORT`. Set the variables above plus:

| Variable | Meaning |
|---|---|
| `SERVE_FRONTEND` | `false` on the API-only deployment (default `true` serves `frontend/` too, for local dev) |
| `CORS_ORIGINS` | comma-separated frontend origins allowed to call the API, e.g. `https://youflix.onrender.com` |

**Frontend** (Render web service, see `render.yaml`): a Node service. Build `npm install`, start `npm start`, health check `/healthz`. `server.js` has no dependencies: it serves `frontend/`, builds `/config.js` from the `API_BASE` environment variable (the API's URL, no trailing slash) at request time, and keeps `/movie/<id>` and `/admin` working. Add the site's address to the API's `CORS_ORIGINS`, or the browser will block every API call.

Admin auth is a bearer token: `POST /api/admin/login` returns `{token}`, which the admin page stores and sends as `Authorization: Bearer ...`. The cookie is still set for same-origin use. Sessions and caches are stored in MongoDB, so more than one worker is fine.

## Content policy

Only add titles that the rights holder has published for free on YouTube (e.g. an official movie channel). Do not add re-uploads.

## Roadmap

- Other sources (Dailymotion, Internet Archive...) and content types (audiobooks, podcasts, music, theatre, courses): the schema already allows them
- Pagination and server-side search
- User accounts and "my list"
- Link-health checks for removed videos
