"""
Fetches each film's real original-language code (ISO 639-1, e.g. "en", "fr",
"ja") from TMDB, keyed by the IMDb tconst this project already uses
everywhere else. Writes data/film_language.csv (imdb_tconst, tmdb_id,
original_language, status) for build_recommendation_data.py to fold into
site/assets/films-data.js as a `language` field.

Uses TMDB's /find/{imdb_id}?external_source=imdb_id endpoint: an exact
IMDb-ID lookup (no fuzzy title matching needed, unlike the poster pipeline in
ReelWrangling/get_poster.py) that returns original_language directly in the
same response, so it's one API call per film.

Requires TMDB_BEARER_TOKEN (a TMDB API v4 Read Access Token) in the
environment or in a .env file at the repo root (gitignored).

    python3 fetch_film_languages.py
"""

import csv
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).parent.parent
DATA_DIR = REPO_ROOT / "data"
SITE_ASSETS = REPO_ROOT / "site" / "assets"
OUT_CSV = DATA_DIR / "film_language.csv"

TMDB_API_BASE = "https://api.themoviedb.org/3"
MAX_WORKERS = 8
MAX_RETRIES = 4
REQUEST_TIMEOUT_SECONDS = 15


def load_token():
    load_dotenv(REPO_ROOT / ".env")
    token = os.environ.get("TMDB_BEARER_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TMDB_BEARER_TOKEN not set (env var or .env file at repo root).")
    return token


def load_tconsts():
    """Every tconst currently on the site, read straight from films-data.js
    (the same authoritative set every other per-film enrichment in this
    project keys off of)."""
    import json

    text = (SITE_ASSETS / "films-data.js").read_text()
    start = text.index("window.FILMS = ") + len("window.FILMS = ")
    end = text.index("];\n", start) + 1
    films = json.loads(text[start:end])
    return sorted({f["t"] for f in films})


def fetch_one(session, token, tconst):
    url = f"{TMDB_API_BASE}/find/{tconst}"
    params = {"external_source": "imdb_id"}
    headers = {"Authorization": f"Bearer {token}", "accept": "application/json"}

    last_error = "unknown error"
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
        except requests.RequestException as exc:
            last_error = str(exc)
            time.sleep(2 ** attempt)
            continue

        if resp.status_code == 401:
            raise RuntimeError("TMDB rejected the token (HTTP 401) -- check TMDB_BEARER_TOKEN.")

        if resp.status_code == 429 or 500 <= resp.status_code < 600:
            wait = resp.headers.get("Retry-After")
            time.sleep(float(wait) if wait else 2 ** attempt)
            last_error = f"HTTP {resp.status_code}"
            continue

        if resp.status_code >= 400:
            return {"imdb_tconst": tconst, "tmdb_id": "", "original_language": "", "status": f"http_{resp.status_code}"}

        data = resp.json()
        results = data.get("movie_results") or []
        if not results:
            return {"imdb_tconst": tconst, "tmdb_id": "", "original_language": "", "status": "no_match"}

        movie = results[0]
        return {
            "imdb_tconst": tconst,
            "tmdb_id": movie.get("id", ""),
            "original_language": movie.get("original_language", ""),
            "status": "ok",
        }

    return {"imdb_tconst": tconst, "tmdb_id": "", "original_language": "", "status": f"failed: {last_error}"}


def main():
    token = load_token()
    tconsts = load_tconsts()
    print(f"Fetching TMDB original_language for {len(tconsts):,} films...")

    rows = []
    session = requests.Session()
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(fetch_one, session, token, t): t for t in tconsts}
        done = 0
        for future in as_completed(futures):
            rows.append(future.result())
            done += 1
            if done % 200 == 0 or done == len(tconsts):
                print(f"  {done:,}/{len(tconsts):,}")

    rows.sort(key=lambda r: r["imdb_tconst"])

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["imdb_tconst", "tmdb_id", "original_language", "status"])
        writer.writeheader()
        writer.writerows(rows)

    ok = sum(1 for r in rows if r["status"] == "ok" and r["original_language"])
    no_match = sum(1 for r in rows if r["status"] == "no_match")
    failed = sum(1 for r in rows if r["status"] not in ("ok", "no_match"))
    print(f"Wrote {len(rows):,} rows to {OUT_CSV}")
    print(f"  ok: {ok:,}   no_match: {no_match:,}   failed: {failed:,}")
    if failed:
        print("Failed rows:")
        for r in rows:
            if r["status"] not in ("ok", "no_match"):
                print(f"  {r['imdb_tconst']}: {r['status']}")


if __name__ == "__main__":
    main()
