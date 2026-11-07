"""API tests: the real FastAPI app on an in-memory MongoDB (mongomock), with TMDB and YouTube faked.

    pip install -r requirements-dev.txt
    cd backend && python -m unittest discover tests
"""
import json
import os
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import mongomock
from fastapi.testclient import TestClient
from pymongo.errors import DuplicateKeyError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from app import config, schema, tmdb, youtube  # noqa: E402
from app.db import get_db  # noqa: E402
from app.main import create_app  # noqa: E402
import migrate_to_mongo as m  # noqa: E402

VID = "abcdefghijk"
OEMBED = {"title": "Some Movie Full Movie 2005", "author_name": "Shemaroo Movies", "thumbnail_url": "https://i.ytimg.com/vi/x/hq.jpg"}
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def item(n, pop=None, type="movie", tmdb_id=None, anime=False, trailer=None, **over):
    ids = [{"system": schema.tmdb_system(type), "id": tmdb_id}] if tmdb_id else []
    details = {"isAnime": anime, "popularity": pop}
    if trailer:
        details["trailerKey"] = trailer
    d = {"_id": f"id-{n}", "type": type, "title": f"Title {n}", "description": "d", "category": "Drama", "genres": [], "year": 2000 + n,
         "thumbnail": "t", "poster": "p", "externalIds": ids,
         "source": {"provider": "youtube", "kind": "video", "externalId": f"vid{n:08d}", "url": f"https://youtu.be/vid{n:08d}", "channel": "Ch"},
         "details": details, "addedAt": T0 + timedelta(days=n), "updatedAt": T0 + timedelta(days=n)}
    d.update(over)
    return d


class ApiTest(unittest.TestCase):
    TMDB = False     # subclasses switch TMDB on

    def setUp(self):
        env = {"ADMIN_PASSWORD": "pw", "TMDB_API_KEY": "key" if self.TMDB else "", "TMDB_TOKEN": "", "MONGODB_URI": ""}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        config.get_settings.cache_clear()
        self.addCleanup(config.get_settings.cache_clear)

        self.db = mongomock.MongoClient(tz_aware=True)["t"]
        with mock.patch.object(schema, "ensure_collection"):     # mongomock cannot create validated collections
            schema.ensure_schema(self.db)
        app = create_app()
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app, raise_server_exceptions=False)

        self.oembed = mock.patch.object(youtube, "fetch_oembed", side_effect=lambda url: dict(OEMBED))
        self.oembed_mock = self.oembed.start()
        self.addCleanup(self.oembed.stop)

    def login(self):
        r = self.client.post("/api/admin/login", json={"password": "pw"})
        self.assertEqual(r.status_code, 200)

    def seed(self, *docs):
        self.db.items.insert_many(docs)


class StaticAndErrors(ApiTest):
    def test_pages(self):
        self.assertIn("YOUFLIX", self.client.get("/").text)
        self.assertEqual(self.client.get("/admin").status_code, 200)
        self.assertEqual(self.client.get("/movie/anything").status_code, 200)
        self.assertEqual(self.client.get("/style.css").status_code, 200)

    def test_html_urls_redirect(self):
        for page in ("admin", "movie"):
            r = self.client.get(f"/{page}.html", follow_redirects=False)
            self.assertEqual((r.status_code, r.headers["location"]), (301, f"/{page}"))

    def test_errors_use_the_error_key(self):
        r = self.client.get("/no-such-page")
        self.assertEqual((r.status_code, r.json()), (404, {"error": "Not Found"}))
        self.assertEqual(self.client.get("/api/titles/zzz/details").json(), {"error": "Not found"})
        self.login()
        r = self.client.patch("/api/titles/x", json=[1, 2])     # not an object
        self.assertEqual((r.status_code, r.json()), (400, {"error": "Invalid request"}))


class Auth(ApiTest):
    def test_login_logout(self):
        r = self.client.post("/api/admin/login", json={"password": "nope"})
        self.assertEqual((r.status_code, r.json()), (401, {"error": "Wrong password"}))
        self.assertEqual(self.client.post("/api/admin/login", json={}).status_code, 401)
        self.assertFalse(self.client.get("/api/admin/me").json()["admin"])
        self.login()
        self.assertTrue(self.client.get("/api/admin/me").json()["admin"])
        header = self.client.post("/api/admin/logout").headers["set-cookie"]
        self.assertIn("Max-Age=0", header)
        self.assertFalse(self.client.get("/api/admin/me").json()["admin"])

    def test_cookie_flags_and_hashed_storage(self):
        r = self.client.post("/api/admin/login", json={"password": "pw"})
        cookie = r.headers["set-cookie"]
        for flag in ("HttpOnly", "SameSite=strict", "Path=/", "Max-Age=86400"):
            self.assertIn(flag, cookie)
        token = r.cookies["yf_admin"]
        stored = self.db.admin_sessions.find_one()
        self.assertNotIn(token, json.dumps(stored, default=str))      # only a hash is stored

    def test_protected_routes_need_a_session(self):
        for method, path in (("get", "/api/admin/config"), ("get", "/api/admin/candidates"), ("post", "/api/titles"),
                             ("patch", "/api/titles/x"), ("delete", "/api/titles/x"), ("delete", "/api/admin/candidates/x")):
            r = getattr(self.client, method)(path)
            self.assertEqual((r.status_code, r.json()), (401, {"error": "Not authorised"}), path)

    def test_expired_session_is_rejected(self):
        self.login()
        self.db.admin_sessions.update_many({}, {"$set": {"expiresAt": datetime.now(timezone.utc) - timedelta(seconds=1)}})
        self.assertFalse(self.client.get("/api/admin/me").json()["admin"])
        self.assertEqual(self.client.get("/api/admin/config").status_code, 401)


class Catalogue(ApiTest):
    def test_order_shape_and_dates(self):
        self.seed(item(1, pop=1.5), item(2), item(3, pop=9.0, anime=True, trailer="JUD-51_SwrQ"), item(4))
        titles = self.client.get("/api/titles").json()
        self.assertEqual([t["id"] for t in titles], ["id-3", "id-1", "id-4", "id-2"])     # popular first, unscored newest first
        t = titles[0]
        self.assertEqual((t["isAnime"], t["trailerKey"], t["popularity"], t["youtubeId"], t["kind"]), (True, "JUD-51_SwrQ", 9.0, "vid00000003", "video"))
        self.assertEqual(t["addedAt"], "2026-01-04T00:00:00.000Z")
        self.assertNotIn("popularity", titles[3])
        self.assertNotIn("trailerKey", titles[3])

    def test_real_catalogue_matches_what_the_old_server_returned(self):
        titles_json = m.ROOT / "data" / "titles.json"
        if not titles_json.exists():
            self.skipTest("data/titles.json not present")
        rep = m.Report()
        docs, _ = m.build(titles_json, m.ROOT / "data" / "candidates.json", rep, T0)
        self.assertEqual(rep.errors, [])
        self.db.items.insert_many(docs)
        got = {t["id"]: t for t in self.client.get("/api/titles").json()}
        raw = json.loads(titles_json.read_text(encoding="utf-8-sig"))
        self.assertEqual(len(got), len(raw))
        for r in raw:
            g = got[r["id"]]
            for k, v in r.items():
                self.assertEqual(g[k], v, f"{r['title']}: {k}")
            self.assertEqual(set(g) - set(r), {"genres", "isAnime"} - set(r))      # only the defaults we fill in
        self.assertEqual(list(got), m.js_popularity_order(docs))

    def test_add_title_from_youtube_link(self):
        self.login()
        r = self.client.post("/api/titles", json={"url": f"https://youtu.be/{VID}"})
        self.assertEqual(r.status_code, 201, r.text)
        t = r.json()
        self.assertEqual((t["title"], t["category"], t["channel"], t["kind"], t["youtubeId"]), ("Some Movie Full Movie 2005", "General", "Shemaroo Movies", "video", VID))
        self.assertEqual(t["thumbnail"], f"https://i.ytimg.com/vi/{VID}/hqdefault.jpg")
        self.assertEqual(len(self.client.get("/api/titles").json()), 1)

    def test_add_title_errors(self):
        self.login()
        post = lambda body: self.client.post("/api/titles", json=body)
        self.assertEqual((post({}).status_code, post({}).json()["error"]), (400, "Paste the free YouTube link first"))
        self.assertEqual(post({"url": "https://example.com"}).json()["error"], "Not a valid YouTube video or playlist URL")
        self.assertEqual(post({"url": f"https://youtu.be/{VID}"}).status_code, 201)
        r = post({"url": f"https://www.youtube.com/watch?v={VID}"})
        self.assertEqual((r.status_code, r.json()["error"]), (409, "That YouTube link is already in the catalogue"))
        self.oembed_mock.side_effect = lambda url: None
        r = post({"url": "https://youtu.be/zzzzzzzzzzz"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("YouTube could not find", r.json()["error"])
        self.assertEqual(post({"url": "https://youtu.be/zzzzzzzzzzz", "title": "Manual"}).status_code, 201)

    def test_add_playlist_uses_the_oembed_thumbnail(self):
        self.login()
        t = self.client.post("/api/titles", json={"url": "https://youtube.com/playlist?list=PLabc", "type": "series", "isAnime": "true"}).json()
        self.assertEqual((t["kind"], t["type"], t["isAnime"], t["thumbnail"]), ("playlist", "series", True, OEMBED["thumbnail_url"]))

    def test_edit_title(self):
        self.seed(item(1), item(2, trailer="JUD-51_SwrQ"))
        self.login()
        patch = lambda i, body: self.client.patch(f"/api/titles/{i}", json=body)
        r = patch("id-1", {"youtubeUrl": f"https://youtube.com/playlist?list=PLxyz", "trailerUrl": "https://youtu.be/MIfMuGSIzag", "isAnime": True})
        self.assertEqual(r.status_code, 200, r.text)
        t = r.json()
        self.assertEqual((t["kind"], t["youtubeId"], t["trailerKey"], t["isAnime"], t["channel"]), ("playlist", "PLxyz", "MIfMuGSIzag", True, "Shemaroo Movies"))
        self.assertNotIn("trailerKey", patch("id-2", {"trailerUrl": ""}).json())            # empty goes back to TMDB's trailer
        self.assertEqual(self.db.items.find_one({"_id": "id-1"})["updatedAt"].year, datetime.now().year)

    def test_edit_title_errors(self):
        self.seed(item(1), item(2))
        self.login()
        patch = lambda i, body: self.client.patch(f"/api/titles/{i}", json=body)
        self.assertEqual(patch("nope", {}).status_code, 404)
        self.assertEqual(patch("id-1", {"youtubeUrl": "https://example.com"}).status_code, 400)
        self.assertEqual(patch("id-1", {"trailerUrl": "https://youtube.com/playlist?list=PLxyz"}).json()["error"], "Trailer link must be a YouTube video URL")
        r = patch("id-1", {"youtubeUrl": "https://youtu.be/vid00000002"})
        self.assertEqual((r.status_code, r.json()["error"]), (409, "That YouTube link is already used by another title"))
        self.oembed_mock.side_effect = lambda url: None
        self.assertEqual(patch("id-1", {"youtubeUrl": "https://youtu.be/zzzzzzzzzzz"}).status_code, 400)
        self.assertEqual(self.db.items.find_one({"_id": "id-1"})["source"]["externalId"], "vid00000001")   # nothing half-applied

    def test_keeping_the_same_link_does_not_look_it_up_again(self):
        self.seed(item(1))
        self.login()
        r = self.client.patch("/api/titles/id-1", json={"youtubeUrl": "https://www.youtube.com/watch?v=vid00000001"})
        self.assertEqual(r.status_code, 200)
        self.oembed_mock.assert_not_called()

    def test_delete_title(self):
        self.seed(item(1))
        self.login()
        self.assertEqual(self.client.delete("/api/titles/id-1").json(), {"ok": True})
        self.assertEqual(self.client.delete("/api/titles/id-1").status_code, 404)


class Candidates(ApiTest):
    def shortlist(self, **over):
        body = {"tmdbId": 77, "type": "movie", "title": "Cand", "year": 1999, "description": "x", "poster": "p", "backdrop": "b", "isAnime": False}
        body.update(over)
        return self.client.post("/api/admin/candidates", json=body)

    def test_shortlist_list_delete(self):
        self.login()
        r = self.shortlist()
        self.assertEqual(r.status_code, 201)
        c = r.json()
        self.assertEqual((c["tmdbId"], c["title"], c["youtubeUrl"], c["isAnime"]), (77, "Cand", None, False))
        self.assertEqual([x["id"] for x in self.client.get("/api/admin/candidates").json()], [c["id"]])
        self.assertEqual(self.client.delete(f"/api/admin/candidates/{c['id']}").json(), {"ok": True})
        self.assertEqual(self.client.get("/api/admin/candidates").json(), [])

    def test_list_is_newest_first(self):
        self.login()
        a = self.shortlist(tmdbId=1, title="A").json()["id"]
        b = self.shortlist(tmdbId=2, title="B").json()["id"]
        self.assertEqual([x["id"] for x in self.client.get("/api/admin/candidates").json()], [b, a])

    def test_shortlist_rules(self):
        self.seed(item(1, tmdb_id=500))
        self.login()
        self.assertEqual(self.shortlist(tmdbId=None).json()["error"], "Missing TMDB data")
        self.assertEqual(self.shortlist(title="").status_code, 400)
        self.assertEqual(self.shortlist(tmdbId=500).json()["error"], "Already in the catalogue")
        self.assertEqual(self.shortlist(tmdbId=500, type="series").status_code, 201)       # TMDB id spaces differ per type
        self.assertEqual(self.shortlist().status_code, 201)
        r = self.shortlist()
        self.assertEqual((r.status_code, r.json()["error"]), (409, "Already shortlisted"))

    def test_reshortlisting_attaches_a_missing_link(self):
        self.login()
        self.shortlist()
        r = self.shortlist(youtubeUrl="https://youtu.be/abcdefghijk")
        self.assertEqual((r.status_code, r.json()["youtubeUrl"]), (200, "https://youtu.be/abcdefghijk"))
        self.assertEqual(self.shortlist(youtubeUrl="https://youtu.be/other000000").status_code, 409)

    def test_approve_publishes_and_removes_the_candidate(self):
        self.login()
        cid = self.shortlist(category="Comedy").json()["id"]
        r = self.client.post(f"/api/admin/candidates/{cid}/approve", json={"url": f"https://youtu.be/{VID}", "isAnime": True})
        self.assertEqual(r.status_code, 201, r.text)
        t = r.json()
        self.assertEqual((t["title"], t["tmdbId"], t["category"], t["isAnime"], t["poster"], t["thumbnail"]), ("Cand", 77, "Comedy", True, "p", "b"))
        self.assertEqual(self.client.get("/api/admin/candidates").json(), [])
        self.assertEqual(self.shortlist().json()["error"], "Already in the catalogue")

    def test_failed_approval_keeps_the_candidate(self):
        self.login()
        cid = self.shortlist().json()["id"]
        r = self.client.post(f"/api/admin/candidates/{cid}/approve", json={"url": "nope"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.client.post("/api/admin/candidates/missing/approve", json={"url": "x"}).status_code, 404)
        self.assertEqual(len(self.client.get("/api/admin/candidates").json()), 1)

    def test_approval_retry_after_a_half_finished_publish(self):
        """The title was published but removing the candidate failed: approving again finishes the job."""
        self.login()
        cid = self.shortlist().json()["id"]
        url = f"https://youtu.be/{VID}"
        first = self.client.post(f"/api/admin/candidates/{cid}/approve", json={"url": url}).json()
        self.db.candidates.insert_one({"_id": cid, "type": "movie", "title": "Cand", "year": 1999, "details": {"isAnime": False},
                                       "externalIds": [{"system": "tmdb:movie", "id": 77}], "sourceUrl": None, "createdAt": T0})
        r = self.client.post(f"/api/admin/candidates/{cid}/approve", json={"url": url})
        self.assertEqual((r.status_code, r.json()["id"]), (200, first["id"]))
        self.assertEqual(self.db.candidates.count_documents({}), 0)
        self.assertEqual(self.db.items.count_documents({}), 1)


class WithTmdb(ApiTest):
    TMDB = True

    def fake(self, responses):
        calls = []

        def request(path, **params):
            calls.append((path, params))
            for prefix, value in responses.items():
                if path.startswith(prefix):
                    if isinstance(value, Exception):
                        raise value
                    return value
            raise AssertionError(f"unexpected TMDB call {path}")
        p = mock.patch.object(tmdb, "request", side_effect=request)
        p.start()
        self.addCleanup(p.stop)
        return calls

    def test_publish_finds_genres_popularity_and_id_for_a_series(self):
        calls = self.fake({"/search/tv": {"results": [{"id": 42}]}, "/tv/42": {"genres": [{"name": "Animation"}, {"name": "Action"}], "popularity": 12.3456}})
        self.login()
        t = self.client.post("/api/titles", json={"url": "https://youtube.com/playlist?list=PLabc", "type": "series", "isAnime": True, "title": "Show", "year": 2020}).json()
        self.assertEqual((t["tmdbId"], t["popularity"], t["genres"], t["category"]), (42, 12.35, ["Animation", "Action"], "Action"))
        self.assertTrue(all("/movie" not in path for path, _ in calls))                   # series use the TV endpoints
        self.assertEqual(calls[0][1]["first_air_date_year"], 2020)

    def test_a_wrong_tmdb_guess_that_belongs_to_another_title_is_dropped(self):
        self.seed(item(1, tmdb_id=42))
        self.fake({"/search/movie": {"results": [{"id": 42}]}, "/movie/42": {"genres": [], "popularity": 1.0}})
        self.login()
        # mongomock does not enforce the partial multikey unique index, so raise what MongoDB would.
        real_insert = mongomock.collection.Collection.insert_one

        def insert(coll, doc, *a, **kw):
            if coll.name == "items" and doc.get("externalIds") and doc["externalIds"][0]["id"] == 42:
                raise DuplicateKeyError("E11000 duplicate key error index: uniq_externalId")
            return real_insert(coll, doc, *a, **kw)
        with mock.patch.object(mongomock.collection.Collection, "insert_one", insert):
            r = self.client.post("/api/titles", json={"url": f"https://youtu.be/{VID}"})
        self.assertEqual(r.status_code, 201, r.text)
        self.assertIsNone(r.json()["tmdbId"])
        self.assertEqual(r.json()["popularity"], 1.0)
        with mock.patch.object(mongomock.collection.Collection, "insert_one", insert):     # an explicit duplicate id is a 409
            r = self.client.post("/api/titles", json={"url": "https://youtu.be/zzzzzzzzzzz", "tmdbId": 42})
        self.assertEqual((r.status_code, r.json()["error"]), (409, "That title is already in the catalogue"))

    def test_tmdb_search(self):
        self.fake({"/search/movie": {"page": 2, "total_pages": 900, "total_results": 18000, "results": [
            {"id": 5, "title": "Four Rooms", "release_date": "1995-12-09", "overview": "o", "poster_path": "/p.jpg", "backdrop_path": None, "genre_ids": [16], "original_language": "ja"}]}})
        self.login()
        d = self.client.get("/api/admin/tmdb/search", params={"q": "rooms", "page": "2"}).json()
        self.assertEqual((d["page"], d["totalPages"], d["totalResults"]), (2, 500, 18000))
        self.assertEqual(d["results"][0], {"tmdbId": 5, "type": "movie", "title": "Four Rooms", "year": 1995, "description": "o",
                                           "poster": "https://image.tmdb.org/t/p/w342/p.jpg", "backdrop": None, "isAnime": True})
        self.assertEqual(self.client.get("/api/admin/tmdb/search", params={"q": " "}).json()["results"], [])

    def test_tmdb_errors_are_reported_with_their_status(self):
        self.fake({"/search": tmdb.TmdbError("TMDB request failed (401)")})
        self.login()
        r = self.client.get("/api/admin/tmdb/search", params={"q": "x"})
        self.assertEqual((r.status_code, r.json()), (502, {"error": "TMDB request failed (401)"}))

    def test_details_are_cached_and_trailer_override_wins(self):
        self.seed(item(1, tmdb_id=9, trailer="JUD-51_SwrQ"))
        calls = self.fake({"/movie/9": {"tagline": "t", "overview": "o", "genres": [{"name": "Drama"}], "runtime": 120, "vote_average": 7.26, "vote_count": 10,
                                        "original_language": "hi", "videos": {"results": [{"site": "YouTube", "type": "Trailer", "key": "TMDBTRAILER"}]},
                                        "credits": {"cast": [{"name": "A", "character": "B", "profile_path": "/a.jpg"}], "crew": [{"name": "D", "job": "Director"}, {"name": "X", "job": "Gaffer"}]},
                                        "reviews": {"results": [{"author": "me", "author_details": {"rating": 8}, "created_at": "2020-01-02T00:00:00Z", "content": "x" * 800, "url": "u"}]},
                                        "similar": {"results": [{"title": "S", "release_date": "2001-01-01", "poster_path": "/s.jpg", "vote_average": 5.55}, {"title": "no poster"}]}}})
        d = self.client.get("/api/titles/id-1/details").json()
        self.assertEqual(d["title"]["id"], "id-1")
        x = d["details"]
        self.assertEqual((x["trailer"], x["rating"], x["runtime"], x["genres"]), ("JUD-51_SwrQ", 7.3, 120, ["Drama"]))
        self.assertEqual(x["crew"], [{"name": "D", "job": "Director"}])
        self.assertTrue(x["reviews"][0]["content"].endswith("..."))
        self.assertEqual((x["reviews"][0]["rating"], x["reviews"][0]["date"]), (8, "2020-01-02"))
        self.assertEqual([s["title"] for s in x["similar"]], ["S"])
        self.assertEqual(x["cast"][0]["photo"], "https://image.tmdb.org/t/p/w185/a.jpg")
        self.client.get("/api/titles/id-1/details")
        self.assertEqual(len(calls), 1)                                                   # second call came from metadata_cache
        self.db.metadata_cache.update_many({}, {"$set": {"expiresAt": datetime.now(timezone.utc) - timedelta(seconds=1)}})
        self.client.get("/api/titles/id-1/details")
        self.assertEqual(len(calls), 2)                                                   # expired entries are refetched

    def test_details_survive_a_tmdb_failure(self):
        self.seed(item(1, tmdb_id=9))
        self.fake({"/movie": tmdb.TmdbError("TMDB request failed (500)")})
        d = self.client.get("/api/titles/id-1/details").json()
        self.assertEqual((d["title"]["id"], d["details"], d["error"]), ("id-1", None, "TMDB request failed (500)"))

    def test_config_reports_tmdb(self):
        self.login()
        self.assertEqual(self.client.get("/api/admin/config").json(), {"tmdb": True})


class WithoutTmdb(ApiTest):
    def test_details_without_tmdb(self):
        self.seed(item(1, trailer="JUD-51_SwrQ"), item(2))
        self.assertEqual(self.client.get("/api/titles/id-1/details").json()["details"], {"trailer": "JUD-51_SwrQ"})
        self.assertIsNone(self.client.get("/api/titles/id-2/details").json()["details"])

    def test_search_says_tmdb_is_not_configured(self):
        self.login()
        r = self.client.get("/api/admin/tmdb/search", params={"q": "x"})
        self.assertEqual(r.status_code, 503)
        self.assertIn("not configured", r.json()["error"])
        self.assertEqual(self.client.get("/api/admin/config").json(), {"tmdb": False})

    def test_youtube_title_cleanup(self):
        self.login()
        self.oembed_mock.side_effect = lambda url: {"title": "Dilwale Dulhania Le Jayenge (1995) | Full Hindi Movie | Shah Rukh Khan - Shemaroo", "author_name": "Shemaroo"}
        d = self.client.get("/api/admin/youtube-title", params={"url": f"https://youtu.be/{VID}"}).json()
        self.assertEqual((d["query"], d["year"], d["channel"]), ("Dilwale Dulhania Le Jayenge", 1995, "Shemaroo"))
        self.assertEqual(self.client.get("/api/admin/youtube-title", params={"url": "x"}).status_code, 400)
        self.oembed_mock.side_effect = lambda url: None
        self.assertEqual(self.client.get("/api/admin/youtube-title", params={"url": f"https://youtu.be/{VID}"}).status_code, 404)


class Jobs(ApiTest):
    TMDB = True

    def test_refresh_popularity_only_touches_the_score(self):
        from app.jobs import refresh_popularity
        self.seed(item(1, pop=1.0, tmdb_id=9), item(2, tmdb_id=None, type="series"), item(3, type="audiobook"))
        self.db.items.update_one({"_id": "id-1"}, {"$set": {"title": "Edited in admin"}})
        calls = []

        def request(path, **params):
            calls.append(path)
            return {"results": [{"id": 77}]} if path.startswith("/search") else {"popularity": 5.5}
        with mock.patch.object(tmdb, "request", side_effect=request), mock.patch.object(refresh_popularity, "get_db", return_value=self.db):
            self.assertEqual(refresh_popularity.main(), 0)
        one, two, three = (self.db.items.find_one({"_id": f"id-{i}"}) for i in (1, 2, 3))
        self.assertEqual((one["details"]["popularity"], one["title"]), (5.5, "Edited in admin"))
        self.assertEqual((two["details"]["popularity"], two["externalIds"]), (5.5, [{"system": "tmdb:tv", "id": 77}]))
        self.assertIsNone(three["details"].get("popularity"))                      # audiobooks are not scored
        self.assertTrue(all("/movie" not in c for c in calls if "/tv" in c))


if __name__ == "__main__":
    unittest.main()


class SplitDeployment(ApiTest):
    def make(self, **env):
        with mock.patch.dict(os.environ, env):
            config.get_settings.cache_clear()
            app = create_app()
        app.dependency_overrides[get_db] = lambda: self.db
        return TestClient(app, raise_server_exceptions=False)

    def test_bearer_token_auth_without_cookie(self):
        token = self.client.post("/api/admin/login", json={"password": "pw"}).json()["token"]
        fresh = TestClient(self.client.app, raise_server_exceptions=False)      # no cookies
        self.assertFalse(fresh.get("/api/admin/me").json()["admin"])
        h = {"Authorization": f"Bearer {token}"}
        self.assertTrue(fresh.get("/api/admin/me", headers=h).json()["admin"])
        self.assertEqual(fresh.get("/api/admin/config", headers=h).status_code, 200)
        fresh.post("/api/admin/logout", headers=h)
        self.assertFalse(fresh.get("/api/admin/me", headers=h).json()["admin"])

    def test_cors_only_for_configured_origins(self):
        c = self.make(CORS_ORIGINS="https://youflix.onrender.com/")
        ok = c.options("/api/titles", headers={"Origin": "https://youflix.onrender.com", "Access-Control-Request-Method": "GET",
                                               "Access-Control-Request-Headers": "authorization"})
        self.assertEqual(ok.headers.get("access-control-allow-origin"), "https://youflix.onrender.com")
        bad = c.get("/api/titles", headers={"Origin": "https://evil.example"})
        self.assertNotIn("access-control-allow-origin", bad.headers)

    def test_api_only_mode_serves_no_pages(self):
        c = self.make(SERVE_FRONTEND="false")
        for path in ("/", "/admin", "/movie/x", "/style.css"):
            self.assertEqual(c.get(path).status_code, 404, path)
        self.assertEqual(c.get("/api/titles").status_code, 200)
