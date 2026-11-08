#!/usr/bin/env python3
"""Migrate data/titles.json and data/candidates.json into MongoDB.

    pip install -r backend/requirements.txt

    python backend/scripts/migrate_to_mongo.py --dry-run     # validate the JSON files, touch no database
    python backend/scripts/migrate_to_mongo.py               # import (safe to re-run: existing documents are skipped)
    python backend/scripts/migrate_to_mongo.py --overwrite   # re-import, replacing documents that already exist
    python backend/scripts/migrate_to_mongo.py --verify-only # compare the database with the files, write nothing

Connection: --uri / MONGODB_URI (also read from .env), database --db / MONGODB_DB (default "youflix").
The JSON files are only ever read. titles.json becomes the `items` collection, candidates.json the `candidates`
collection. The schema and the reasoning are in docs/mongodb-design.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
ROOT = BACKEND.parent                   # the repository root: data/ and .env live here
sys.path.insert(0, str(BACKEND))        # so `python backend/scripts/migrate_to_mongo.py` can import the app package

from app.schema import (ITEM_TYPES, SCREEN_TYPES, SOURCE_KINDS, ensure_schema, tmdb_system)  # noqa: E402
from app.serialize import to_iso  # noqa: E402
from app.youtube import VIDEO_ID, parse_youtube  # noqa: E402

TITLE_FIELDS = {
    "id", "type", "isAnime", "title", "description", "category", "genres", "year", "kind", "youtubeId",
    "youtubeUrl", "thumbnail", "poster", "tmdbId", "channel", "addedAt", "popularity", "trailerKey",
}
CANDIDATE_FIELDS = {
    "id", "tmdbId", "type", "title", "year", "description", "poster", "backdrop", "category", "isAnime", "youtubeUrl",
}


# ---------- reporting ----------
@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def error(self, where: str, msg: str) -> None:
        self.errors.append(f"{where}: {msg}")

    def warn(self, where: str, msg: str) -> None:
        self.warnings.append(f"{where}: {msg}")


# ---------- helpers ----------
def parse_iso(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def ext_keys(doc: dict) -> list[tuple]:
    return [(e["system"], e["id"]) for e in doc.get("externalIds", [])]


def as_int(value, where: str, name: str, rep: Report):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        rep.error(where, f"{name} is a boolean, expected a number")
        return None
    if isinstance(value, int):
        return value
    try:
        n = int(str(value).strip())
    except ValueError:
        rep.error(where, f"{name} {value!r} is not an integer")
        return None
    rep.warn(where, f"{name} {value!r} was text, stored as the number {n}")
    return n


def as_str(value, default=None):
    if value is None:
        return default
    s = str(value).strip()
    return s if s else default


def read_json_list(path: Path, label: str, rep: Report, required: bool):
    if not path.exists():
        (rep.error if required else rep.warn)(label, f"{path} not found" + ("" if required else " - treated as empty"))
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        rep.error(label, f"cannot read {path}: {e}")
        return []
    if not isinstance(data, list):
        rep.error(label, f"{path} must contain a JSON array")
        return []
    return data


# ---------- transforms (JSON record -> MongoDB document) ----------
def transform_item(raw: dict, n: int, rep: Report):
    if not isinstance(raw, dict):
        rep.error(f"titles[{n}]", "not an object")
        return None
    where = f"titles[{n}] {as_str(raw.get('title'), '?')!r}"
    start = len(rep.errors)

    for k in sorted(set(raw) - TITLE_FIELDS):
        rep.warn(where, f"unknown field {k!r} kept as-is")

    _id = as_str(raw.get("id"))
    title = as_str(raw.get("title"))
    itype = raw.get("type")
    kind = raw.get("kind")
    yid = as_str(raw.get("youtubeId"))
    yurl = as_str(raw.get("youtubeUrl"))
    added = parse_iso(raw.get("addedAt"))
    if not _id:
        rep.error(where, "missing id")
    if not title:
        rep.error(where, "missing title")
    if itype not in ITEM_TYPES:
        rep.error(where, f"type {itype!r} must be one of {ITEM_TYPES}")
    if kind not in SOURCE_KINDS:
        rep.error(where, f"kind {kind!r} must be one of {SOURCE_KINDS}")
    if not yid:
        rep.error(where, "missing youtubeId")
    if not yurl:
        rep.error(where, "missing youtubeUrl")
    if added is None:
        rep.error(where, f"addedAt {raw.get('addedAt')!r} is not an ISO date")
    if yid and kind == "video" and not VIDEO_ID.match(yid):
        rep.warn(where, f"video youtubeId {yid!r} is not 11 characters")
    if yurl and yid:
        parsed = parse_youtube(yurl)
        if parsed is None:
            rep.warn(where, "youtubeUrl is not a recognised YouTube link")
        elif parsed != (kind, yid):
            rep.warn(where, f"youtubeUrl points to {parsed[0]} {parsed[1]!r} but youtubeId/kind say {kind} {yid!r}")

    year = as_int(raw.get("year"), where, "year", rep)
    tmdb_id = as_int(raw.get("tmdbId"), where, "tmdbId", rep)
    pop = raw.get("popularity")
    if isinstance(pop, bool) or not (pop is None or isinstance(pop, (int, float))):
        rep.error(where, f"popularity {pop!r} is not a number")
        pop = None
    genres = raw.get("genres") or []
    if not isinstance(genres, list) or not all(isinstance(g, str) for g in genres):
        rep.error(where, "genres must be a list of strings")
        genres = []
    if not as_str(raw.get("category")):
        rep.warn(where, "no category, using 'General' like the server does")
    if itype not in SCREEN_TYPES and (pop is not None or raw.get("trailerKey") or raw.get("isAnime")):
        rep.warn(where, f"popularity / trailerKey / isAnime only apply to {SCREEN_TYPES}, kept in details anyway")

    if len(rep.errors) > start:
        return None

    # Fields that only make sense for some types live in `details`; the shared core stays the same for every type.
    details = {"isAnime": raw.get("isAnime") is True or raw.get("isAnime") == "true",   # missing -> false
               "popularity": None if pop is None else float(pop)}                       # TMDB score; null until scored
    if as_str(raw.get("trailerKey")):     # only present when an admin set a custom trailer
        details["trailerKey"] = as_str(raw.get("trailerKey"))
        if not VIDEO_ID.match(details["trailerKey"]):
            rep.warn(where, f"trailerKey {details['trailerKey']!r} is not an 11 character video id")

    doc = {
        "_id": _id,                       # the public id; /movie/<id> links keep working
        "type": itype,
        "title": title,
        "description": as_str(raw.get("description"), ""),
        "category": as_str(raw.get("category"), "General"),
        "genres": genres,                 # missing -> []
        "year": year,
        "thumbnail": as_str(raw.get("thumbnail")),
        "poster": as_str(raw.get("poster")),
        # ids of this work in other databases (TMDB today; ISBN, MusicBrainz... later)
        "externalIds": [] if tmdb_id is None else [{"system": tmdb_system(itype), "id": tmdb_id}],
        # where the content lives: the one link users are sent to (a video, or a playlist / first episode)
        "source": {"provider": "youtube", "kind": kind, "externalId": yid, "url": yurl, "channel": as_str(raw.get("channel"))},
        "details": details,
        "addedAt": added,                 # BSON Date; the API serialises it back with to_iso()
        "updatedAt": added,
    }
    for k in sorted(set(raw) - TITLE_FIELDS):
        doc[k] = raw[k]
    return doc


def transform_candidate(raw: dict, n: int, created_at: datetime, rep: Report):
    if not isinstance(raw, dict):
        rep.error(f"candidates[{n}]", "not an object")
        return None
    where = f"candidates[{n}] {as_str(raw.get('title'), '?')!r}"
    start = len(rep.errors)
    for k in sorted(set(raw) - CANDIDATE_FIELDS):
        rep.warn(where, f"unknown field {k!r} kept as-is")
    _id, title = as_str(raw.get("id")), as_str(raw.get("title"))
    if not _id:
        rep.error(where, "missing id")
    if not title:
        rep.error(where, "missing title")
    if raw.get("type") not in ITEM_TYPES:
        rep.error(where, f"type {raw.get('type')!r} must be one of {ITEM_TYPES}")
    tmdb_id = as_int(raw.get("tmdbId"), where, "tmdbId", rep)
    if tmdb_id is None:
        rep.error(where, "missing tmdbId")
    year = as_int(raw.get("year"), where, "year", rep)
    yurl = as_str(raw.get("youtubeUrl"))
    if yurl and parse_youtube(yurl) is None:
        rep.warn(where, "youtubeUrl is not a recognised YouTube link")
    if len(rep.errors) > start:
        return None
    doc = {
        "_id": _id,
        "type": raw["type"],
        "title": title,
        "year": year,
        "description": as_str(raw.get("description"), ""),
        "poster": as_str(raw.get("poster")),
        "backdrop": as_str(raw.get("backdrop")),
        "category": as_str(raw.get("category")),
        "details": {"isAnime": raw.get("isAnime") is True},
        "externalIds": [{"system": tmdb_system(raw["type"]), "id": tmdb_id}],
        "sourceUrl": yurl,                # the link the admin pasted, if any; becomes items.source on approval
        "createdAt": created_at,
    }
    for k in sorted(set(raw) - CANDIDATE_FIELDS):
        doc[k] = raw[k]
    return doc


def check_duplicates(items: list[dict], cands: list[dict], rep: Report) -> None:
    def dupes(docs, keys, label):
        seen = {}
        for d in docs:
            for k in keys(d):
                if k in seen:
                    rep.error(label, f"duplicate {k!r}: {seen[k]!r} and {d['_id']!r}")
                seen[k] = d["_id"]
        return seen

    dupes(items, lambda d: [d["_id"]], "items._id")
    dupes(items, lambda d: [(d["source"]["provider"], d["source"]["externalId"])], "items.source")
    in_catalogue = dupes(items, ext_keys, "items.externalIds")
    dupes(cands, lambda d: [d["_id"]], "candidates._id")
    dupes(cands, ext_keys, "candidates.externalIds")
    for c in cands:
        if any(k in in_catalogue for k in ext_keys(c)):
            rep.warn("candidates", f"{c['title']!r} is already published as an item; the candidate is stale")


def build(titles_path: Path, cands_path: Path, rep: Report, now: datetime):
    raw_titles = read_json_list(titles_path, "titles", rep, required=True)
    raw_cands = read_json_list(cands_path, "candidates", rep, required=False)
    items = [d for i, r in enumerate(raw_titles) if (d := transform_item(r, i, rep))]
    # The file is newest-first (the server unshifts); give candidates falling timestamps so that order survives.
    cands = [d for i, r in enumerate(raw_cands) if (d := transform_candidate(r, i, now - timedelta(seconds=i), rep))]
    check_duplicates(items, cands, rep)
    return items, cands


# ---------- database ----------
def import_docs(coll, docs: list[dict], overwrite: bool, rep: Report) -> dict:
    from pymongo.errors import DuplicateKeyError, WriteError

    out = {"inserted": 0, "skipped": 0, "replaced": 0, "written_ids": set()}
    for d in docs:
        try:
            if overwrite:
                r = coll.replace_one({"_id": d["_id"]}, d, upsert=True)
                out["inserted" if r.upserted_id is not None else "replaced"] += 1
            else:
                body = {k: v for k, v in d.items() if k != "_id"}
                r = coll.update_one({"_id": d["_id"]}, {"$setOnInsert": body}, upsert=True)
                out["inserted" if r.upserted_id is not None else "skipped"] += 1
            if overwrite or r.upserted_id is not None:
                out["written_ids"].add(d["_id"])
        except DuplicateKeyError as e:
            rep.error(f"{coll.name} {d['_id']}", f"unique index conflict (a different document already has this value): {(e.details or {}).get('errmsg', e)}")
        except WriteError as e:
            rep.error(f"{coll.name} {d['_id']}", f"rejected by the collection validator: {e}")
    return out


def js_popularity_order(items: list[dict]) -> list[str]:
    """The order GET /api/titles returns today: byPopularity() in server.js (unscored titles last, newest first)."""
    key = lambda d: (-1 if d["details"].get("popularity") is None else d["details"]["popularity"], to_iso(d["addedAt"]))
    return [d["_id"] for d in sorted(items, key=key, reverse=True)]


def verify(db, items: list[dict], cands: list[dict], written: dict[str, set], rep: Report) -> None:
    """Read everything back. A difference on a document written in this run is an error; on one that already
    existed it is only a warning (it may have been edited in the admin since)."""
    for name, docs in (("items", items), ("candidates", cands)):
        stored = {d["_id"]: d for d in db[name].find()}
        for d in docs:
            got = stored.get(d["_id"])
            if got is None:
                rep.error(f"verify {name}", f"{d['_id']} is missing from the database")
            elif got != d:
                diff = sorted(k for k in set(got) | set(d) if got.get(k) != d.get(k))
                (rep.error if d["_id"] in written.get(name, ()) else rep.warn)(
                    f"verify {name} {d['_id']}", f"differs from the file in: {', '.join(diff)}")
        extra = set(stored) - {d["_id"] for d in docs}
        if extra:
            rep.warn(f"verify {name}", f"{len(extra)} document(s) in the database are not in the file (added since?)")
        print(f"  {name}: file {len(docs)}, database {len(stored)}")

    if db["items"].count_documents({}) == len(items) and not rep.errors:
        got = [d["_id"] for d in db["items"].find({}, {"_id": 1}).sort([("details.popularity", -1), ("addedAt", -1)])]
        if got == js_popularity_order(items):
            print("  catalogue order: identical to the current /api/titles order")
        else:
            rep.warn("verify items", "sort order differs from the current byPopularity() order (ties on popularity and addedAt?)")


# ---------- cli ----------
def load_env_file(path: Path) -> None:
    """Minimal .env reader so MONGODB_URI can live next to the other settings. Real environment variables win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$", line)
        if m and not line.lstrip().startswith("#"):
            os.environ.setdefault(m.group(1), m.group(2).strip("\"'"))


def summarise(items: list[dict], cands: list[dict]) -> None:
    by_type = {t: sum(i["type"] == t for i in items) for t in ITEM_TYPES}
    print(f"  items: {len(items)} ({', '.join(f'{n} {t}' for t, n in by_type.items() if n)}; {sum(i['details'].get('isAnime', False) for i in items)} anime)")
    print(f"    without external id: {sum(not i['externalIds'] for i in items)}, without popularity score: {sum(i['details'].get('popularity') is None for i in items)}, "
          f"with custom trailer: {sum('trailerKey' in i['details'] for i in items)}, without genres: {sum(not i['genres'] for i in items)}")
    print(f"  candidates: {len(cands)}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--titles", type=Path, default=ROOT / "data" / "titles.json")
    ap.add_argument("--candidates", type=Path, default=ROOT / "data" / "candidates.json")
    ap.add_argument("--uri", help="MongoDB connection string (default: $MONGODB_URI)")
    ap.add_argument("--db", help="database name (default: $MONGODB_DB or 'youflix')")
    ap.add_argument("--dry-run", action="store_true", help="validate and report only; no database connection")
    ap.add_argument("--overwrite", action="store_true", help="replace documents that already exist (default: skip them)")
    ap.add_argument("--verify-only", action="store_true", help="compare the database with the files and write nothing")
    args = ap.parse_args(argv)

    load_env_file(ROOT / ".env")
    rep = Report()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    print("Reading JSON files")
    items, cands = build(args.titles, args.candidates, rep, now)
    summarise(items, cands)

    if not args.dry_run and not rep.errors:
        uri = args.uri or os.environ.get("MONGODB_URI")
        if not uri:
            rep.error("config", "no connection string: pass --uri or set MONGODB_URI (or use --dry-run)")
        else:
            from pymongo import MongoClient
            from pymongo.errors import PyMongoError
            name = args.db or os.environ.get("MONGODB_DB") or "youflix"
            print(f"Target: {re.sub(r'//[^@/]*@', '//***@', uri)}  database '{name}'")
            try:
                client = MongoClient(uri, tz_aware=True, serverSelectionTimeoutMS=8000)
                run(client[name], items, cands, args, rep, now)
            except PyMongoError as e:
                rep.error("mongodb", str(e))

    for w in rep.warnings:
        print(f"WARNING  {w}")
    for e in rep.errors:
        print(f"ERROR    {e}")
    print(f"{'FAILED' if rep.errors else 'OK'}: {len(rep.errors)} error(s), {len(rep.warnings)} warning(s)"
          + (" (dry run, nothing written)" if args.dry_run else ""))
    return 1 if rep.errors else 0


def run(db, items, cands, args, rep: Report, now: datetime) -> None:
    written = {"items": set(), "candidates": set()}
    if not args.verify_only:
        print("Creating collections, validators and indexes")
        ensure_schema(db)
        print("Importing")
        for name, docs in (("items", items), ("candidates", cands)):
            r = import_docs(db[name], docs, args.overwrite, rep)
            written[name] = r.pop("written_ids")
            print(f"  {name}: {r['inserted']} inserted, {r['skipped']} already present (skipped), {r['replaced']} replaced")
        if not rep.errors:
            src = hashlib.sha256(args.titles.read_bytes()).hexdigest()
            db["migrations"].insert_one({"name": "import_json", "ranAt": now, "items": len(items), "candidates": len(cands),
                                         "titlesSha256": src, "overwrite": args.overwrite})
    print("Verifying")
    verify(db, items, cands, written, rep)


if __name__ == "__main__":
    sys.exit(main())
