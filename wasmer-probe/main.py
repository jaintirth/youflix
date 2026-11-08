"""Throwaway app to find out what Wasmer Edge supports before deploying YOUFLIX's API. Delete when done.

Routes:  /          hello
         /env       which env vars are set (names only, never values)
         /libs      which libraries import, and their versions
         /mongo     connects to MONGODB_URI and runs `ping`
Set MONGODB_URI in Wasmer's environment settings to test /mongo.
"""
import importlib
import os
import platform
import sys
import time

from fastapi import FastAPI

app = FastAPI()


@app.get("/")
async def root():
    return {"message": "Hello from the probe", "python": sys.version, "platform": platform.platform()}


@app.get("/env")
async def env():
    return {name: bool(os.environ.get(name)) for name in ("MONGODB_URI", "MONGODB_DB", "ADMIN_PASSWORD", "TMDB_API_KEY", "PORT")}


@app.get("/libs")
async def libs():
    out = {}
    for name in ("fastapi", "uvicorn", "pymongo", "bson", "httpx", "certifi", "pydantic", "pydantic_core", "uvloop", "httptools", "dns"):
        try:
            mod = importlib.import_module(name)
            out[name] = getattr(mod, "__version__", "ok")
        except Exception as e:
            out[name] = f"FAILED: {type(e).__name__}: {e}"
    try:
        import bson
        out["bson_c_extension"] = bson.has_c()
    except Exception as e:
        out["bson_c_extension"] = f"FAILED: {e}"
    return out


@app.get("/mongo")
def mongo():
    uri = os.environ.get("MONGODB_URI")
    if not uri:
        return {"ok": False, "error": "MONGODB_URI is not set"}
    started = time.time()
    try:
        from pymongo import MongoClient
        import certifi      # Wasmer's Python has no system CA bundle, so hand pymongo one
        client = MongoClient(uri, serverSelectionTimeoutMS=8000, tlsCAFile=certifi.where())
        client.admin.command("ping")
        return {"ok": True, "ms": round((time.time() - started) * 1000), "databases_visible": len(client.list_database_names())}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "ms": round((time.time() - started) * 1000)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
