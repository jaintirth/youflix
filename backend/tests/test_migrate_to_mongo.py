"""Tests for migrate_to_mongo.py against an in-memory MongoDB (mongomock).

    pip install -r requirements-dev.txt
    cd backend && python -m unittest discover tests

Unique-index enforcement and the collection validator are MongoDB features that mongomock only partly emulates,
so run `migrate_to_mongo.py` once against a throwaway database (e.g. a free Atlas cluster) before the real import.
"""
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import mongomock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import migrate_to_mongo as m  # noqa: E402
from app import schema  # noqa: E402

NOW = datetime(2026, 11, 3, tzinfo=timezone.utc)
REAL_TITLES = m.ROOT / "data" / "titles.json"


def title(n, **over):
    d = {"id": f"id-{n}", "type": "movie", "title": f"Movie {n}", "description": "d", "category": "Drama", "year": 2000 + n,
         "kind": "video", "youtubeId": f"abcdefghi{n:02d}", "youtubeUrl": f"https://www.youtube.com/watch?v=abcdefghi{n:02d}",
         "thumbnail": "t", "poster": "p", "tmdbId": 100 + n, "channel": "Ch", "addedAt": f"2026-01-{n:02d}T10:00:00.000Z", "popularity": float(n)}
    d.update(over)
    return d


def cand(n, **over):
    d = {"id": f"c-{n}", "tmdbId": 500 + n, "type": "movie", "title": f"Cand {n}", "year": 1999, "description": "", "poster": None,
         "backdrop": None, "category": None, "isAnime": False, "youtubeUrl": None}
    d.update(over)
    return d


class Args:
    def __init__(self, titles_path, overwrite=False, verify_only=False):
        self.titles, self.overwrite, self.verify_only = titles_path, overwrite, verify_only


class MigrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = mongomock.MongoClient(tz_aware=True)["youflix_test"]
        # mongomock cannot create collections with a validator; that part needs a real server.
        patcher = mock.patch.object(schema, "ensure_collection")
        patcher.start()
        self.addCleanup(patcher.stop)

        # Likewise it wrongly rejects re-creating the partial multikey unique index once documents exist (real
        # MongoDB treats an identical createIndex as a no-op), so build the schema only on the first run.
        real_ensure_schema = m.ensure_schema
        first_only = lambda db: None if "uniq_source" in db["items"].index_information() else real_ensure_schema(db)
        patcher = mock.patch.object(m, "ensure_schema", side_effect=first_only)
        patcher.start()
        self.addCleanup(patcher.stop)

    def files(self, titles, cands=None):
        d = Path(self.tmp.name)
        (d / "titles.json").write_text(json.dumps(titles), encoding="utf-8")
        if cands is not None:
            (d / "candidates.json").write_text(json.dumps(cands), encoding="utf-8")
        return d / "titles.json", d / "candidates.json"

    def build(self, titles, cands=None):
        rep = m.Report()
        t, c = m.build(*self.files(titles, cands), rep, NOW)
        return t, c, rep

    def run_import(self, titles, cands, **kw):
        t, c, rep = self.build(titles, cands)
        self.assertEqual(rep.errors, [])
        m.run(self.db, t, c, Args(self.files(titles, cands)[0], **kw), rep, NOW)
        return t, c, rep

    # ----- transforms -----
    def test_title_shape(self):
        t, _, rep = self.build([title(1, isAnime=None, genres=None, popularity=None, trailerKey="JUD-51_SwrQ")])
        self.assertEqual(rep.errors, [])
        d = t[0]
        self.assertEqual(d["_id"], "id-1")
        self.assertNotIn("id", d)
        self.assertIs(d["details"]["isAnime"], False)
        self.assertEqual(d["genres"], [])
        self.assertIsNone(d["details"]["popularity"])
        self.assertEqual(d["details"]["trailerKey"], "JUD-51_SwrQ")
        for moved in ("isAnime", "popularity", "trailerKey"):
            self.assertNotIn(moved, d)   # type-specific fields live in details only
        self.assertEqual(d["addedAt"], datetime(2026, 1, 1, 10, tzinfo=timezone.utc))
        # one source per item, and the old flat fields are gone
        self.assertEqual(d["source"], {"provider": "youtube", "kind": "video", "externalId": "abcdefghi01",
                                       "url": "https://www.youtube.com/watch?v=abcdefghi01", "channel": "Ch"})
        self.assertEqual(d["externalIds"], [{"system": "tmdb:movie", "id": 101}])
        for legacy in ("youtubeId", "youtubeUrl", "kind", "tmdbId", "channel"):
            self.assertNotIn(legacy, d)

    def test_series_use_the_tmdb_tv_id_space(self):
        t, _, _ = self.build([title(1, type="series", kind="playlist", youtubeId="PLabc",
                                    youtubeUrl="https://youtube.com/playlist?list=PLabc")])
        self.assertEqual(t[0]["externalIds"], [{"system": "tmdb:tv", "id": 101}])
        self.assertEqual(t[0]["source"]["kind"], "playlist")

    def test_screen_only_fields_on_other_types_are_flagged(self):
        _, _, rep = self.build([title(1, type="audiobook", popularity=3.0)])
        self.assertEqual(rep.errors, [])
        self.assertTrue(any("only apply to" in w for w in rep.warnings))

    def test_missing_trailer_stays_absent(self):
        t, _, _ = self.build([title(1)])
        self.assertNotIn("trailerKey", t[0]["details"])

    def test_bad_titles_are_rejected_with_reasons(self):
        _, _, rep = self.build([title(1, type="film"), title(2, addedAt="yesterday"), title(3, youtubeId=""), title(4, year="abc"), "nope"])
        text = "\n".join(rep.errors)
        for needle in ("type 'film'", "addedAt 'yesterday'", "missing youtubeId", "year 'abc'", "not an object"):
            self.assertIn(needle, text)

    def test_text_numbers_are_coerced_with_a_warning(self):
        t, _, rep = self.build([title(1, year="2001", tmdbId="7")])
        self.assertEqual((t[0]["year"], t[0]["externalIds"][0]["id"]), (2001, 7))
        self.assertEqual(len([w for w in rep.warnings if "was text" in w]), 2)

    def test_url_that_disagrees_with_youtube_id_warns(self):
        _, _, rep = self.build([title(1, youtubeUrl="https://www.youtube.com/watch?v=zzzzzzzzzzz")])
        self.assertEqual(rep.errors, [])
        self.assertTrue(any("youtubeUrl points to" in w for w in rep.warnings))

    def test_playlist_url_parses_like_server_js(self):
        self.assertEqual(m.parse_youtube("https://youtube.com/playlist?list=PLabc&si=x"), ("playlist", "PLabc"))
        self.assertEqual(m.parse_youtube("https://youtu.be/abcdefghijk?list=PLz"), ("playlist", "PLz"))
        self.assertEqual(m.parse_youtube("https://www.youtube.com/shorts/abcdefghijk"), ("video", "abcdefghijk"))
        self.assertIsNone(m.parse_youtube("https://example.com/watch?v=abcdefghijk"))

    def test_duplicates_are_errors(self):
        _, _, rep = self.build([title(1), title(2, id="id-1"), title(3, youtubeId="abcdefghi01"), title(4, tmdbId=101)])
        text = "\n".join(rep.errors)
        for needle in ("items._id", "items.source", "items.externalIds"):
            self.assertIn(needle, text)

    def test_same_tmdb_id_for_movie_and_series_is_fine(self):
        _, _, rep = self.build([title(1, tmdbId=5), title(2, tmdbId=5, type="series")])
        self.assertEqual(rep.errors, [])

    def test_titles_without_tmdb_id_do_not_collide(self):
        t, _, rep = self.build([title(1, tmdbId=None), title(2, tmdbId=None)])
        self.assertEqual(rep.errors, [])
        self.assertEqual([d["externalIds"] for d in t], [[], []])

    def test_candidates_keep_file_order_and_flag_stale_ones(self):
        t, c, rep = self.build([title(1)], [cand(1), cand(2), cand(3, tmdbId=101)])
        self.assertEqual(rep.errors, [])
        self.assertEqual([x["_id"] for x in sorted(c, key=lambda x: x["createdAt"], reverse=True)], ["c-1", "c-2", "c-3"])
        self.assertTrue(any("already published" in w for w in rep.warnings))
        self.assertEqual(c[0]["externalIds"], [{"system": "tmdb:movie", "id": 501}])
        self.assertIsNone(c[0]["sourceUrl"])
        self.assertNotIn("tmdbId", c[0])

    def test_missing_candidates_file_is_an_empty_list(self):
        _, c, rep = self.build([title(1)])
        self.assertEqual((c, rep.errors), ([], []))

    def test_missing_titles_file_is_an_error(self):
        rep = m.Report()
        m.build(Path(self.tmp.name) / "nope.json", Path(self.tmp.name) / "nope2.json", rep, NOW)
        self.assertEqual(len(rep.errors), 1)

    # ----- import -----
    def test_import_is_idempotent(self):
        titles, cands = [title(1), title(2)], [cand(1)]
        _, _, rep = self.run_import(titles, cands)
        self.assertEqual((self.db.items.count_documents({}), self.db.candidates.count_documents({})), (2, 1))
        self.assertEqual(rep.errors, [])
        self.run_import(titles, cands)
        self.assertEqual(self.db.items.count_documents({}), 2)
        self.assertEqual(self.db.migrations.count_documents({}), 2)

    def test_rerun_does_not_clobber_edits_made_after_the_first_import(self):
        titles = [title(1)]
        self.run_import(titles, [])
        self.db.items.update_one({"_id": "id-1"}, {"$set": {"details.trailerKey": "JUD-51_SwrQ"}})
        _, _, rep = self.run_import(titles, [])
        self.assertEqual(self.db.items.find_one({"_id": "id-1"})["details"]["trailerKey"], "JUD-51_SwrQ")
        self.assertEqual(rep.errors, [])
        self.assertTrue(any("differs from the file" in w for w in rep.warnings))

    def test_overwrite_replaces(self):
        titles = [title(1)]
        self.run_import(titles, [])
        self.db.items.update_one({"_id": "id-1"}, {"$set": {"title": "Edited"}})
        _, _, rep = self.run_import(titles, [], overwrite=True)
        self.assertEqual(self.db.items.find_one({"_id": "id-1"})["title"], "Movie 1")
        self.assertEqual(rep.errors, [])

    def test_verify_flags_missing_documents(self):
        titles = [title(1), title(2)]
        t, c, rep = self.run_import(titles, [])
        self.db.items.delete_one({"_id": "id-2"})
        rep2 = m.Report()
        m.verify(self.db, t, c, {"items": set(), "candidates": set()}, rep2)
        self.assertTrue(any("id-2 is missing" in e for e in rep2.errors))

    def test_unique_index_conflict_is_reported_not_raised(self):
        self.run_import([title(1)], [])
        rep = m.Report()
        clash = m.transform_item(title(9, youtubeId="abcdefghi01", tmdbId=999), 0, rep)
        m.import_docs(self.db.items, [clash], False, rep)
        self.assertTrue(any("unique index conflict" in e for e in rep.errors), rep.errors)

    def test_indexes_exist(self):
        self.run_import([title(1)], [])
        names = set(self.db.items.index_information())
        self.assertTrue({"uniq_source", "uniq_externalId", "by_type_popularity"} <= names)

    # ----- the real data -----
    @unittest.skipUnless(REAL_TITLES.exists(), "data/titles.json not present")
    def test_real_data_round_trips(self):
        rep = m.Report()
        t, c = m.build(REAL_TITLES, m.ROOT / "data" / "candidates.json", rep, NOW)
        self.assertEqual(rep.errors, [])
        raw = json.loads(REAL_TITLES.read_text(encoding="utf-8-sig"))
        self.assertEqual(len(t), len(raw))
        self.assertEqual({d["_id"] for d in t}, {r["id"] for r in raw})
        for d, r in zip(t, raw):
            self.assertEqual(m.to_iso(d["addedAt"]), r["addedAt"])   # dates survive the round trip to the API format
            self.assertEqual(d["title"], r["title"])
            self.assertEqual(d["source"]["url"], r["youtubeUrl"])
            self.assertEqual((d["source"]["externalId"], d["source"]["kind"]), (r["youtubeId"], r["kind"]))
            self.assertEqual([e["id"] for e in d["externalIds"]], [r["tmdbId"]])
        m.run(self.db, t, c, Args(REAL_TITLES), rep, NOW)
        self.assertEqual(rep.errors, [])
        self.assertEqual(self.db.items.count_documents({}), len(raw))


if __name__ == "__main__":
    unittest.main()
