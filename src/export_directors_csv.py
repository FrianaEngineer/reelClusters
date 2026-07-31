"""
Exports the full director list behind the "Explore Directors by Cluster" tab
as a flat CSV, for anyone who wants it outside the website.

Reuses the exact same splitting/slugify logic as site/assets/director-utils.js
and src/build_director_directory.py, applied to the same authoritative
dataset (site/assets/films-data.js), so this file always matches what the
site itself shows -- one row per director, clusters and film count derived
the same way, nothing hand-entered.

Writes output/directors.csv with columns:
    name, slug, cluster_count, clusters, film_count

Usage:
    python3 export_directors_csv.py
"""

import csv
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
FILMS_DATA_PATH = REPO_ROOT / "site" / "assets" / "films-data.js"
OUT_PATH = REPO_ROOT / "output" / "directors.csv"


def load_films():
    text = FILMS_DATA_PATH.read_text(encoding="utf-8")
    match = re.search(r"window\.FILMS = (\[.*?\]);\nwindow\.FILMS_MAX_DEGREE", text, re.S)
    if not match:
        raise SystemExit(f"Could not find window.FILMS in {FILMS_DATA_PATH}")
    return json.loads(match.group(1))


def split_directors(raw):
    if not raw:
        return []
    normalized = re.sub(r"\s*,?\s+and\s+", ", ", raw, flags=re.I)
    seen = []
    for part in normalized.split(","):
        name = part.strip()
        if name and name not in seen:
            seen.append(name)
    return seen


def strip_diacritics(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def slugify(name):
    n = strip_diacritics(name).lower()
    n = re.sub(r"['’.]", "", n)
    n = re.sub(r"[^a-z0-9]+", "-", n).strip("-")
    return n or "unknown"


def better_name(a, b):
    if a == b:
        return a
    a_has_diacritic = strip_diacritics(a) != a
    b_has_diacritic = strip_diacritics(b) != b
    if a_has_diacritic and not b_has_diacritic:
        return a
    if b_has_diacritic and not a_has_diacritic:
        return b
    return a if a <= b else b


def main():
    films = load_films()

    names = {}
    clusters = defaultdict(set)
    tconsts = defaultdict(set)

    for film in films:
        for raw_name in split_directors(film.get("director")):
            slug = slugify(raw_name)
            names[slug] = better_name(names[slug], raw_name) if slug in names else raw_name
            clusters[slug].add(film["clusterName"])
            tconsts[slug].add(film["t"])

    rows = []
    for slug, name in names.items():
        cluster_list = sorted(clusters[slug])
        rows.append({
            "name": name,
            "slug": slug,
            "cluster_count": len(cluster_list),
            "clusters": "; ".join(cluster_list),
            "film_count": len(tconsts[slug]),
        })
    rows.sort(key=lambda r: r["name"].lower())

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["name", "slug", "cluster_count", "clusters", "film_count"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} directors to {OUT_PATH}")


if __name__ == "__main__":
    main()
