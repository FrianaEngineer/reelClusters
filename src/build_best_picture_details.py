"""
Fetches each Best Picture winner's studio (production company) and full
release date from TMDB, keyed by imdb_tconst -- neither field exists
anywhere in this project's own data (db/criterion_graph.duckdb only has
criterion_year/imdb_year, no month/day; no studio column at all). Used by
the "Reeling Through the Years" video's clapperboard (cinematic_history_
animation.py), which shows these alongside director for whichever film's
poster is currently on screen.

data/best_picture_winners.csv has imdb_tconst but no tmdb_id; the sibling
ReelWrangling repo's poster-pipeline query.csv already has the
(imdbId -> tmdbId) mapping these posters were downloaded with, so that's
reused here rather than re-resolving titles to TMDB ids from scratch (same
boundary cinematic_history_posters.py's POSTER_QUERY_CSV_PATH already
relies on).

Writes data/best_picture_winner_details.csv (imdb_tconst, studio,
release_date, status). Requires TMDB_BEARER_TOKEN (env var or .env file at
repo root, gitignored) -- same token/pattern as fetch_film_languages.py.

    python3 build_best_picture_details.py
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
WINNERS_CSV = DATA_DIR / "best_picture_winners.csv"
QUERY_CSV = REPO_ROOT.parent / "ReelWrangling" / "data" / "output" / "query.csv"
OUT_CSV = DATA_DIR / "best_picture_winner_details.csv"

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


def load_winner_tmdb_ids():
    """-> [(imdb_tconst, title, tmdb_id), ...] for every winner resolvable
    to a tmdb_id via query.csv's own (imdbId -> tmdbId) mapping. A winner
    missing from query.csv (e.g. a ceremony year not covered by the poster
    pipeline's own query) is reported, not guessed at."""
    with WINNERS_CSV.open(newline="") as f:
        winners = list(csv.DictReader(f))

    imdb_to_tmdb = {}
    with QUERY_CSV.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            imdb_id, tmdb_id = row.get("imdbId"), row.get("tmdbId")
            if imdb_id and tmdb_id:
                imdb_to_tmdb[imdb_id] = tmdb_id

    resolved, unresolved = [], []
    for row in winners:
        tconst = row["imdb_tconst"]
        tmdb_id = imdb_to_tmdb.get(tconst)
        if tmdb_id:
            resolved.append((tconst, row["title"], tmdb_id))
        else:
            unresolved.append((tconst, row["title"]))
    return resolved, unresolved


def fetch_one(session, token, tconst, title, tmdb_id):
    url = f"{TMDB_API_BASE}/movie/{tmdb_id}"
    params = {"language": "en-US"}
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
            return {"imdb_tconst": tconst, "title": title, "studio": "", "release_date": "",
                    "status": f"http_{resp.status_code}"}

        data = resp.json()
        companies = data.get("production_companies") or []
        studio = companies[0].get("name", "") if companies else ""
        return {
            "imdb_tconst": tconst,
            "title": title,
            "studio": studio,
            "release_date": data.get("release_date", "") or "",
            "status": "ok",
        }

    return {"imdb_tconst": tconst, "title": title, "studio": "", "release_date": "",
            "status": f"failed: {last_error}"}


def main():
    token = load_token()
    resolved, unresolved = load_winner_tmdb_ids()
    print(f"Fetching TMDB studio/release_date for {len(resolved)} Best Picture winners "
          f"({len(unresolved)} unresolved to a tmdb_id, skipped)...")

    rows = []
    session = requests.Session()
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(fetch_one, session, token, tconst, title, tmdb_id): tconst
                   for tconst, title, tmdb_id in resolved}
        done = 0
        for future in as_completed(futures):
            rows.append(future.result())
            done += 1
            if done % 25 == 0 or done == len(resolved):
                print(f"  {done}/{len(resolved)}")

    for tconst, title in unresolved:
        rows.append({"imdb_tconst": tconst, "title": title, "studio": "", "release_date": "",
                      "status": "no_tmdb_id"})

    rows.sort(key=lambda r: r["imdb_tconst"])

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["imdb_tconst", "title", "studio", "release_date", "status"])
        writer.writeheader()
        writer.writerows(rows)

    ok = sum(1 for r in rows if r["status"] == "ok" and r["studio"] and r["release_date"])
    print(f"Wrote {len(rows)} rows -> {OUT_CSV}")
    print(f"  ok (studio + release_date both present): {ok}")
    for r in rows:
        if r["status"] != "ok" or not r["studio"] or not r["release_date"]:
            print(f"  {r['imdb_tconst']} ({r['title']}): status={r['status']} studio={r['studio']!r} "
                  f"release_date={r['release_date']!r}")


if __name__ == "__main__":
    main()
