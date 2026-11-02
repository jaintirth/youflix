"""MongoDB schema: what an item is, its validators and indexes. The reasoning is in docs/mongodb-design.md."""
from __future__ import annotations

# What an item is. Only movie and series exist in the data today; the rest are allowed so adding a content type is not a migration.
ITEM_TYPES = ("movie", "series", "audiobook", "music", "podcast", "theatre", "course", "book")
SCREEN_TYPES = ("movie", "series")      # the types that have a popularity score, a trailer and an anime flag (all from TMDB)
SOURCE_KINDS = ("video", "playlist")    # kinds present in the data; the validator keeps this open for other providers


def tmdb_system(item_type: str) -> str:
    """TMDB numbers movies and TV shows separately, so the id space is part of the key."""
    return "tmdb:tv" if item_type == "series" else "tmdb:movie"


EXTERNAL_IDS_SCHEMA = {
    "bsonType": "array",
    "items": {
        "bsonType": "object",
        "required": ["system", "id"],
        "properties": {"system": {"bsonType": "string", "minLength": 1}, "id": {"bsonType": ["int", "long", "string"]}},
    },
}


def item_validator():
    s_or_null = ["string", "null"]
    return {"$jsonSchema": {
        "bsonType": "object",
        "required": ["_id", "type", "title", "category", "genres", "externalIds", "source", "details", "addedAt"],
        "properties": {
            "_id": {"bsonType": "string"},
            "type": {"enum": list(ITEM_TYPES)},
            # Open object: each type's own fields. Their per-type shape is validated by the application.
            "details": {"bsonType": "object", "properties": {
                "isAnime": {"bsonType": "bool"},
                "popularity": {"bsonType": ["int", "long", "double", "null"]},
                "trailerKey": {"bsonType": "string"},
            }},
            "title": {"bsonType": "string", "minLength": 1},
            "description": {"bsonType": "string"},
            "category": {"bsonType": "string"},
            "genres": {"bsonType": "array", "items": {"bsonType": "string"}},
            "year": {"bsonType": ["int", "long", "null"]},
            "thumbnail": {"bsonType": s_or_null},
            "poster": {"bsonType": s_or_null},
            "externalIds": EXTERNAL_IDS_SCHEMA,
            "source": {
                "bsonType": "object",
                "required": ["provider", "externalId", "kind", "url"],
                "properties": {
                    "provider": {"bsonType": "string", "minLength": 1},
                    "externalId": {"bsonType": "string", "minLength": 1},
                    "kind": {"bsonType": "string", "minLength": 1},
                    "url": {"bsonType": "string", "minLength": 1},
                    "channel": {"bsonType": s_or_null},
                },
            },
            "addedAt": {"bsonType": "date"},
            "updatedAt": {"bsonType": "date"},
        },
    }}


def candidate_validator():
    return {"$jsonSchema": {
        "bsonType": "object",
        "required": ["_id", "type", "title", "details", "externalIds", "createdAt"],
        "properties": {
            "_id": {"bsonType": "string"},
            "type": {"enum": list(ITEM_TYPES)},
            "title": {"bsonType": "string", "minLength": 1},
            "year": {"bsonType": ["int", "long", "null"]},
            "details": {"bsonType": "object"},
            "externalIds": {**EXTERNAL_IDS_SCHEMA, "minItems": 1},
            "sourceUrl": {"bsonType": ["string", "null"]},
            "createdAt": {"bsonType": "date"},
        },
    }}


def ensure_collection(db, name: str, validator: dict) -> None:
    opts = {"validator": validator, "validationLevel": "strict", "validationAction": "error"}
    if name in db.list_collection_names():
        db.command("collMod", name, **opts)
    else:
        db.create_collection(name, **opts)


# Items without any external id have an empty array, which would index as a single null key and collide with
# each other, so only items that have one take part in the unique index.
EXTERNAL_ID_INDEX = dict(unique=True, name="uniq_externalId", partialFilterExpression={"externalIds.system": {"$exists": True}})


def ensure_schema(db) -> None:
    """Create the collections, validators and indexes. Safe to run repeatedly."""
    ensure_collection(db, "items", item_validator())
    ensure_collection(db, "candidates", candidate_validator())

    i = db["items"]
    i.create_index([("source.provider", 1), ("source.externalId", 1)], unique=True, name="uniq_source")
    i.create_index([("externalIds.system", 1), ("externalIds.id", 1)], **EXTERNAL_ID_INDEX)
    # Browse a type, most popular first. Types without a score (audiobooks...) fall back to newest first.
    i.create_index([("type", 1), ("details.popularity", -1), ("addedAt", -1)], name="by_type_popularity")

    c = db["candidates"]
    c.create_index([("externalIds.system", 1), ("externalIds.id", 1)], **EXTERNAL_ID_INDEX)
    c.create_index([("createdAt", -1)], name="by_created")

    # Collections for the backend: created lazily by these indexes.
    db["admin_sessions"].create_index("tokenHash", unique=True, name="uniq_tokenHash")
    db["admin_sessions"].create_index("expiresAt", expireAfterSeconds=0, name="ttl_expiresAt")
    db["metadata_cache"].create_index("expiresAt", expireAfterSeconds=0, name="ttl_expiresAt")
