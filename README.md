# YOUFLIX

A Netflix-style front end for movies and series that are **already free on YouTube**. YOUFLIX hosts no video: every title plays through YouTube's official embedded player, with a "Watch on YouTube" link back to the source.

## Phase 1 (this release)

- Public browse page: hero banner, Movies / Series filter, rows grouped by category, click-to-watch modal
- Admin page (`/admin.html`), password protected: paste a YouTube video URL (movie) or playlist URL (series); title and thumbnail are fetched from YouTube automatically
- TMDB discovery: search TMDB for movies/series and shortlist them into a review queue. Nothing is public until you check YouTube yourself, paste the free link and click Approve & publish (needs a free TMDB key)
- Remove titles from the catalogue
- Storage in a local JSON file (`data/titles.json`)

## Run

```bash
npm install
ADMIN_PASSWORD=your-password TMDB_API_KEY=your-tmdb-key npm start
```

On Windows PowerShell: `$env:ADMIN_PASSWORD="your-password"; $env:TMDB_API_KEY="your-tmdb-key"; npm start`

Get a free TMDB key at https://www.themoviedb.org/settings/api (a v4 token also works via `TMDB_TOKEN`). Without a key the manual add form still works.

The banner (first 6) and Top 10 are ranked by TMDB's popularity score, refreshed daily. Titles without a score yet show newest first.

Open http://localhost:3000, and http://localhost:3000/admin.html for the admin screen.

## Content policy

Only add titles that the rights holder has published for free on YouTube (e.g. an official movie channel). Do not add re-uploads.

## Roadmap

- Phase 2: individual episode lists for series, search, user accounts and "my list"
- Phase 3: database, deployment, link-health checks for removed videos

