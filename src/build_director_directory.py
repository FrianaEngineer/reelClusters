"""
Preprocessing for the "Explore Directors by Cluster" tab.

The actual director -> film -> cluster index used at runtime by
site/movie-map.html and site/director.html is derived live, in the browser,
from window.FILMS (site/assets/films-data.js) by site/assets/director-utils.js
-- there's nothing to hand-generate there, and re-deriving it at page-load
means it can never drift out of sync with that dataset.

What *does* need a static, hand-editable file is director photos and
biographies, which don't exist in this project's data yet and will be added
later. This script generates/updates that file:

    site/assets/director-info.js

Re-running it is safe: it adds a blank stub entry for any director slug
that's new (e.g. after films-data.js is regenerated with more films) and
leaves every existing entry -- including any photo/bio a human has already
filled in -- untouched. It never removes an entry, even if that director no
longer appears in the dataset, so in-progress edits are never lost.

It also prints a verification report: total unique directors, per-cluster
director counts, and any raw director-name spelling variants that collapsed
into the same slug (these are treated as one person -- see slugify() in
director-utils.js).

Usage:
    python3 build_director_directory.py
"""

import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SITE_ASSETS = REPO_ROOT / "site" / "assets"
FILMS_DATA_PATH = SITE_ASSETS / "films-data.js"
INFO_PATH = SITE_ASSETS / "director-info.js"

INFO_HEADER = '''\
// EDIT THIS FILE to add director photos and biographies.
//
// Auto-generated / merged by src/build_director_directory.py -- safe to
// hand-edit and safe to re-run: re-running only ADDS entries for directors
// that are new to the dataset, and never touches or removes an entry that
// already exists (so anything you fill in below is preserved).
//
// One entry per director, keyed by the same URL-safe slug used in
// director.html?director=<slug> links (see slugify() in director-utils.js).
// Leave any field "" to fall back to the neutral placeholder used across
// the site -- nothing needs to be filled in for the page to work.
//
//   image:   relative path from site/, e.g. "assets/directors/bergman.jpg"
//   imageAlt: short descriptive alt text for the photo (required if image is set)
//   bio:     a few sentences of biography, plain text (no HTML)
//   credit:  optional photo credit/attribution line, plain text
//
// Example of a filled-in entry:
//   "ingmar-bergman": {
//     "image": "assets/directors/ingmar-bergman.jpg",
//     "imageAlt": "Portrait of Ingmar Bergman on a film set",
//     "bio": "Swedish director and writer...",
//     "credit": "Photo: Svensk Filmindustri"
//   },

'''


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


def load_existing_info():
    if not INFO_PATH.exists():
        return {}
    text = INFO_PATH.read_text(encoding="utf-8")
    match = re.search(r"window\.DIRECTOR_INFO = (\{.*\});", text, re.S)
    if not match:
        return {}
    return json.loads(match.group(1))


def main():
    films = load_films()

    slug_names = defaultdict(set)
    slug_clusters = defaultdict(set)
    cluster_directors = defaultdict(set)
    cluster_names = {}

    for film in films:
        cluster_names[film["cluster"]] = film["clusterName"]
        for name in split_directors(film.get("director")):
            slug = slugify(name)
            slug_names[slug].add(name)
            slug_clusters[slug].add(film["cluster"])
            cluster_directors[film["cluster"]].add(slug)

    all_slugs = sorted(slug_names.keys())

    existing = load_existing_info()
    merged = dict(existing)
    added = 0
    for slug in all_slugs:
        if slug not in merged:
            merged[slug] = {"image": "", "imageAlt": "", "bio": "", "credit": ""}
            added += 1
    merged = {slug: merged[slug] for slug in sorted(merged.keys())}

    SITE_ASSETS.mkdir(parents=True, exist_ok=True)
    body = json.dumps(merged, ensure_ascii=False, indent=2)
    INFO_PATH.write_text(
        INFO_HEADER + f"window.DIRECTOR_INFO = {body};\n", encoding="utf-8"
    )

    # ── Verification report ────────────────────────────────────────────
    print(f"Directors total: {len(all_slugs)}")
    print(f"director-info.js: {added} new stub(s) added, {len(merged) - added} existing entr(y/ies) preserved")
    print()
    print("Directors per cluster:")
    for cluster_id, slugs in sorted(cluster_directors.items(), key=lambda kv: -len(kv[1])):
        print(f"  {cluster_names[cluster_id]:<28} {len(slugs)}")
    print()
    collisions = {s: names for s, names in slug_names.items() if len(names) > 1}
    if collisions:
        print(f"Spelling variants merged into one profile ({len(collisions)}):")
        for slug, names in sorted(collisions.items()):
            print(f"  {slug}: {sorted(names)}")
    else:
        print("No slug collisions (no spelling variants needed merging).")


if __name__ == "__main__":
    main()
