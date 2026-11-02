# YOUFLIX MongoDB design

Companion to `scripts/migrate_to_mongo.py`. YOUFLIX is a discovery site: it tells people that a piece of free, legal content exists somewhere and sends them to it. So the model is deliberately small: **one item, one source link** (a video, or a playlist / first episode). There are no per-episode records.

The design has to cope with more than YouTube movies and series: other providers (Dailymotion, Internet Archive, Project Gutenberg...) and other content types (audiobooks, music, podcasts, theatre, courses, books). It does that without extra collections.

## Collections

| Collection | Holds | Source |
|---|---|---|
| `items` | the published catalogue, any content type | `data/titles.json` |
| `candidates` | the unpublished shortlist awaiting a source link | `data/candidates.json` |
| `admin_sessions` | admin logins (replaces the in-memory `Set`) | new, no data |
| `metadata_cache` | cached lookups from TMDB and other metadata APIs (replaces the in-memory `Map`) | new, no data |
| `migrations` | one audit document per import run | written by the script |

Later, user features (my list, resume position) get their own collections keyed by `userId` + `itemId`. They never go inside `items`, because they are unbounded and write-heavy.

## `items`

```jsonc
{
  "_id": "17c80d04-1608-40d8-a754-cb479e39f462",
  // ---- shared core: the same for every content type ----
  "type": "movie",                 // movie | series | audiobook | music | podcast | theatre | course | book
  "title": "Welcome",
  "description": "...",
  "category": "Comedy",
  "genres": [],
  "year": 2007,
  "thumbnail": "https://...", "poster": "https://...",
  "externalIds": [ { "system": "tmdb:movie", "id": 20294 } ],
  "source": {                      // the one link users are sent to
    "provider": "youtube",
    "kind": "video",               // video | playlist today; open for other providers
    "externalId": "AKiynoClCaA",
    "url": "https://youtu.be/AKiynoClCaA",
    "channel": "Shemaroo Movies"
  },
  // ---- type-specific: only the fields that make sense for this type ----
  "details": {                     // movie / series
    "isAnime": false,
    "popularity": 2.3,             // TMDB score; null until scored
    "trailerKey": "MIfMuGSIzag"    // only present when an admin set a custom trailer
  },
  "addedAt": ISODate("2026-10-24T10:43:30.342Z"),
  "updatedAt": ISODate("2026-10-24T10:43:30.342Z")
}
```

An audiobook would look the same except for `externalIds` (`[{ "system": "openlibrary", "id": "OL123W" }]`), `source` (`provider: "librivox"`) and `details` (`{ "narrators": [...], "authors": [...], "durationSec": 41000 }`). It has no popularity score or trailer, and nothing breaks without them.

- **`_id` is the existing UUID string.** `/movie/<id>` links and the API's `id` keep working. The API maps `_id` to `id` on the way out.
- **`type` is what the content is**; `source.provider` is where it lives. Adding a content type means adding a value to `ITEM_TYPES` in the script and running the validator update (`python scripts/migrate_to_mongo.py` re-applies it); no data changes.
- **`source` is a single embedded object**, not an array. If one title is ever found on two providers, that is two items or a deliberate redesign; do not add an array speculatively. Everything that locates the content is inside it, so replacing a dead link is one `$set` on `source`.
- **`externalIds`** are the work's ids in other databases, as `{system, id}` pairs: `tmdb:movie` and `tmdb:tv` today (TMDB numbers movies and TV separately), later `isbn`, `musicbrainz`, `openlibrary`. A new system needs no new index and no schema change. An item with no external id has `[]`.
- **Dates are BSON dates.** The API serialises them back to `2026-10-24T10:43:30.342Z` (`to_iso()` in the script; the tests check all 135 titles round-trip identically).
- **Core vs `details`.** Anything every type has (title, genres, artwork, where to find it) is top-level. Anything only some types have goes in `details`. `popularity`, `trailerKey` and `isAnime` are screen-content fields from TMDB, so they live in `details` and only exist on movies and series. The importer warns if another type carries them.
- **`details` is an open object.** The database validator checks the core, and checks the three screen fields' types when present, but allows any other keys. Which keys each type may have (narrators, hosts, instructor, runtime...) is validated in the application, one model per type, because `$jsonSchema` has no if/then. Adding a type's fields is a code change, not a migration.
- **Fields that were sometimes missing are now always there**: `details.isAnime` defaults to `false`, `genres` to `[]`, `details.popularity` to `null`. The frontend only tests them for truthiness or `(genres || []).length`, so behaviour is unchanged. 86 titles have no `genres` (only anime were backfilled); filling them stays an explicit TMDB backfill command, not something startup does.
- **`details.trailerKey` stays absent when unset**, because "use TMDB's trailer" is meaningful. Clearing it is `$unset`.
- Unknown fields in the JSON are kept and reported, never dropped.

### Indexes

| Index | Why |
|---|---|
| `(source.provider, source.externalId)` unique | the "already in the catalogue" rule for every provider, race-proof; a duplicate-key error becomes the existing `409` |
| `(externalIds.system, externalIds.id)` unique, partial on `externalIds.system` existing | stops the same TMDB title being published twice. Partial because an item with no external ids would otherwise index as a single null key and collide with every other such item |
| `(type, details.popularity -1, addedAt -1)` | browsing one content type, most popular first. MongoDB sorts missing and `null` lowest, so descending puts unscored items last, newest first: exactly `byPopularity()` in `server.js`. Types with no score (audiobooks...) simply come out newest first. If a type later gets its own ranking, add it to `details` and index it the same way |

No index on `category`, `genres` or `languages` yet: the browser does all filtering and search on the full list. Add them when search moves server-side.

### Validation

`items` and `candidates` get a `$jsonSchema` validator (`validationLevel: strict`, `validationAction: error`), so a bug in the new backend cannot write an item with an unknown `type`, a string `year`, or no `source`.

## `candidates`

An item that has not been published yet: `type`, `title`, `year`, `description`, `poster`, `backdrop`, `category`, `details` (e.g. `isAnime`, copied into the item on approval), `externalIds` (one entry from whichever discovery API found it), and `sourceUrl` (the link the admin pasted, or `null`). `_id` is the UUID. A new **`createdAt`** replaces the array order the file relied on (newest first); the importer gives existing records falling timestamps in file order.

Indexes: the same unique `externalIds` index as `items`, and `createdAt -1`.

On approval the backend parses `sourceUrl` with the right provider adapter and builds `items.source`.

### Approving a candidate

The Express code publishes, then rewrites the candidate file; a crash in between leaves a published title and a stale candidate. In MongoDB:

1. Insert the item. A duplicate `source` or `externalIds` is the `409`.
2. Delete the candidate by `_id`.

To make a retry safe, if step 1 fails with a duplicate on the candidate's own `externalIds`, treat the publish as done and run step 2. (On Atlas, a replica set, both steps can instead run in a transaction.)

## `admin_sessions`

`{ tokenHash, expiresAt }`. Store a SHA-256 of the cookie token, never the token. Unique index on `tokenHash`, TTL index on `expiresAt` (`expireAfterSeconds: 0`). The TTL sweep runs about once a minute, so the backend must still check `expiresAt > now` on each request. This is what lets more than one server process share logins.

## `metadata_cache`

`{ _id: "tmdb:movie:123", data, expiresAt }` with a TTL index. Replaces the unbounded in-memory `detailCache`, survives restarts, and is shared between workers. The `_id` is the same `system:id` pair that `externalIds` uses, so one collection serves every metadata API.

## Detail from several APIs

TMDB only knows screen content. Audiobooks, podcasts, music, courses and theatre will each need their own API (Open Library, a podcast directory, MusicBrainz...), and what each returns differs. The design splits what is stored from what is fetched:

| | Where it lives | Examples |
|---|---|---|
| Identity: which record in which API | `items.externalIds` | `{system: "openlibrary", id: "OL123W"}` |
| Fields the site browses, filters, sorts or lists on | `items` core and `items.details` | title, genres, poster, `details.narrators`, `details.popularity` |
| Rich display detail, bulky or changing | `metadata_cache`, fetched on demand | cast, reviews, similar titles, episode lists, track lists |

- **Rich detail is not copied into `items`.** It is large, it goes stale, and third-party API terms often limit how long it may be kept. The item page asks the adapter for it (cache first, API on a miss), exactly as the TMDB cast and reviews work today.
- **Promote a field into `details` only when you query or list by it**, for example an author you want to search or show on every card.
- **One adapter per API, in code**, each declaring which `type`s it supports and doing three things: `search` (for the admin shortlist), `lookup` (core and `details` fields from an id) and `extras` (the cached rich detail). A type can use more than one API; each contributes an `externalIds` entry.
- **The admin shortlist is per type**: choose the type, the matching adapter searches, and its result becomes a candidate with that API's id in `externalIds`.
- **Per-API refresh jobs** update only that API's fields in `details` (the TMDB popularity refresh is one such job). They are independent, so a failing API never blocks another.
- Optionally, store a `syncedAt` on an `externalIds` entry when a job needs to know how stale it is.

## `migrations`

One document per import: when, row counts, SHA-256 of `titles.json`, whether `--overwrite` was used.

## Adding a provider or content type

Providers and metadata sources are **code** (one adapter each: parse a URL into `{provider, kind, externalId}`, fetch a title and thumbnail, optionally enrich), not database rows.

- New provider: write the adapter. No schema change.
- New content type: add the value to `ITEM_TYPES`, re-run the script to update the validator, add its `details` model in the application, and write the metadata adapter for it (Open Library for books, MusicBrainz for music...).

## Changes the backend needs beyond a straight port

- **Per-document writes.** Add, edit and delete become `insert_one` / `update_one` / `delete_one`. The daily popularity refresh should be one `bulk_write` of `$set: {"details.popularity": ..., updatedAt}`; today it rewrites the whole file and can clobber an admin edit made while it runs.
- **Old API shape.** The frontend reads flat `youtubeId`, `youtubeUrl`, `kind`, `channel`, `tmdbId`, `isAnime`, `popularity` and `trailerKey`. Until the frontend changes, the API should project them from `source`, `externalIds` and `details`, and rename `_id` to `id`.
- **Pagination.** Titles average about 850 bytes, so returning the whole catalogue is about 115 KB today and would be about 8.5 MB at 10,000 items. Somewhere past a thousand items, add `GET /api/items?type=&cursor=` with keyset pagination on `(details.popularity, _id)`, and move search server-side.
- **Popularity for series.** `tmdbPopularity` always calls the movie endpoints. Choose `movie` or `tv` from the item.
- **Category backfills** (`inferCategory` / anime genres at startup) become explicit commands, not part of boot.
- **Scheduler.** With several workers a `setInterval` runs once per worker. Run the refresh as a separate cron/scheduled job.
- **Error shape.** Keep `{ "error": "..." }` for every failure, including database validation and duplicate-key errors.

## Running the migration

```bash
pip install -r scripts/requirements.txt
python scripts/migrate_to_mongo.py --dry-run          # validates both files; no database needed
python scripts/migrate_to_mongo.py                    # import; MONGODB_URI from the environment or .env
python scripts/migrate_to_mongo.py --verify-only      # re-compare the database with the files
```

- Re-running is safe: documents that already exist are skipped, so edits made through the admin after cutover are not overwritten. `--overwrite` replaces them from the files.
- It stops before touching the database if the files have errors (missing fields, bad dates, duplicate ids, duplicate source, duplicate external id). Warnings (e.g. a `youtubeUrl` that disagrees with `youtubeId`) do not block.
- A missing `candidates.json` counts as empty (it is git-ignored).

Suggested cutover: dry run, import into a throwaway database and check it, freeze admin writes, final import into the real one with `--verify-only` afterwards, switch the backend, keep the JSON files as the rollback.

## After cutover

`data/titles.json` stops being the source of truth, so the `data/titles-update` branch workflow in `CLAUDE.md` no longer applies. Use Atlas backups (or a periodic `mongoexport`) in its place.
