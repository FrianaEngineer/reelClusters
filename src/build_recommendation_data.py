"""
Compiles one JSON-ish record per film for the "Find Your Film" recommendation
survey, using only real fields already present in this project's data:
title/director/country/year/runtime/confidence (criterion_basic_info.csv),
genres (data/imdb_genres.csv, see extract_imdb_genres.py), cluster membership
and color (db + cluster_colors.py), shared-actor graph degree and nearest
neighbors (movie_edges), color/b&w (film_color.csv), and outbound links
(criterion_film_links.csv / criterion_channel_links.csv).

No plot summaries, posters, or metadata are invented -- fields this project
doesn't have (e.g. a structured language field) are left off the record; the
recommendation UI derives soft signals from what's here (see
recommendation-mappings.js) rather than pretending they exist in the data.

Writes site/assets/films-data.js as `window.FILMS = [...]` (a plain script
tag, not a fetch()'d JSON file, so the survey works from a file:// URL during
local testing and needs no path-prefix logic under GitHub Pages project
subpaths).

    python3 build_recommendation_data.py
"""

import json
from pathlib import Path

import duckdb
import pandas as pd

from hex_grid import DB_PATH, display_name
from cluster_colors import COLOR_MAP

REPO_ROOT = Path(__file__).parent.parent
DATA_DIR = REPO_ROOT / "data"
CLUSTERS_DIR = REPO_ROOT / "clusters"
SITE_ASSETS = REPO_ROOT / "site" / "assets"

# Countries whose Criterion productions are overwhelmingly English-language.
# A defensible proxy, not a real language field -- documented here and in
# recommendation-mappings.js rather than presented as ground truth.
ENGLISH_SPEAKING_COUNTRIES = {
    "United States", "United Kingdom", "Canada", "Australia",
    "New Zealand", "Ireland",
}

MAX_NEIGHBORS = 8


def load_basic_info():
    """Best (highest-confidence) row per imdb_tconst, same rule build_site.py
    uses for cluster_stats/hub_films."""
    df = pd.read_csv(DATA_DIR / "criterion_basic_info.csv")
    df = df.sort_values("confidence_score", ascending=False)
    df = df.drop_duplicates(subset="imdb_tconst", keep="first")
    return df


def load_genres():
    df = pd.read_csv(DATA_DIR / "imdb_genres.csv", dtype={"genres": str})
    df["genres"] = df["genres"].fillna("")
    genre_map = {}
    for row in df.itertuples(index=False):
        genres = [g for g in row.genres.split(",") if g]
        genre_map[row.imdb_tconst] = genres
    return genre_map


def load_links():
    film_links = pd.read_csv(DATA_DIR / "criterion_film_links.csv")
    channel_links = pd.read_csv(DATA_DIR / "criterion_channel_links.csv")
    film_map = dict(zip(film_links["title"], film_links["criterion_url"]))
    channel_map = dict(zip(channel_links["title"], channel_links["channel_url"]))
    return film_map, channel_map


def load_color():
    df = pd.read_csv(DATA_DIR / "film_color.csv")
    return dict(zip(df["imdb_tconst"], df["color_label"]))


def load_clusters(con):
    df = con.execute("SELECT imdb_tconst, cluster_id FROM cluster_assignments").df()
    return dict(zip(df["imdb_tconst"], df["cluster_id"]))


def load_degree_and_neighbors(con):
    """Total shared-actor degree (whole graph, not just within-cluster -- used
    as an 'accessibility' proxy: well-connected films are more central to the
    collection, isolated ones are more of an unusual pick) plus each film's
    strongest shared-actor neighbors, capped for payload size."""
    edges = con.execute("SELECT movie_a, movie_b, shared_actors FROM movie_edges").df()

    degree = {}
    neighbors = {}
    for row in edges.itertuples(index=False):
        for a, b in ((row.movie_a, row.movie_b), (row.movie_b, row.movie_a)):
            degree[a] = degree.get(a, 0) + 1
            neighbors.setdefault(a, []).append((b, row.shared_actors))

    for tconst, lst in neighbors.items():
        lst.sort(key=lambda x: -x[1])
        neighbors[tconst] = lst[:MAX_NEIGHBORS]

    return degree, neighbors


def build_records():
    con = duckdb.connect(str(DB_PATH), read_only=True)

    basic = load_basic_info()
    genre_map = load_genres()
    film_links, channel_links = load_links()
    color_map = load_color()
    cluster_map = load_clusters(con)
    degree_map, neighbor_map = load_degree_and_neighbors(con)

    con.close()

    records = []
    for row in basic.itertuples(index=False):
        tconst = row.imdb_tconst
        cluster_id = cluster_map.get(tconst)
        if cluster_id is None:
            continue  # no actor credits at all -- not part of the graph

        country = row.criterion_country if pd.notna(row.criterion_country) else None
        year = int(row.criterion_year) if pd.notna(row.criterion_year) else None
        runtime = int(row.imdb_runtime_minutes) if pd.notna(row.imdb_runtime_minutes) else None

        neighbors = [
            {"t": n_tconst, "shared": int(shared)}
            for n_tconst, shared in neighbor_map.get(tconst, [])
        ]

        records.append({
            "t": tconst,
            "title": row.title,
            "director": row.criterion_director if pd.notna(row.criterion_director) else None,
            "country": country,
            "englishSpeaking": country in ENGLISH_SPEAKING_COUNTRIES if country else None,
            "year": year,
            "runtime": runtime,
            "genres": genre_map.get(tconst, []),
            "cluster": cluster_id,
            "clusterName": display_name(cluster_id),
            "color": COLOR_MAP.get(cluster_id, "#888888"),
            "colorLabel": color_map.get(tconst),
            "degree": degree_map.get(tconst, 0),
            "neighbors": neighbors,
            "criterionUrl": film_links.get(row.title),
            "channelUrl": channel_links.get(row.title),
        })

    return records


def main():
    records = build_records()
    records.sort(key=lambda r: r["title"])

    max_degree = max((r["degree"] for r in records), default=1) or 1

    js = (
        "// Generated by src/build_recommendation_data.py -- do not hand-edit.\n"
        "// One record per Criterion film that has actor-credit data (i.e. is\n"
        "// part of the shared-actor graph and cluster assignment). Fields:\n"
        "//   t, title, director, country, englishSpeaking, year, runtime,\n"
        "//   genres[], cluster, clusterName, color, colorLabel, degree,\n"
        "//   neighbors[{t, shared}], criterionUrl, channelUrl\n"
        f"window.FILMS = {json.dumps(records, ensure_ascii=False)};\n"
        f"window.FILMS_MAX_DEGREE = {max_degree};\n"
    )

    SITE_ASSETS.mkdir(parents=True, exist_ok=True)
    out_path = SITE_ASSETS / "films-data.js"
    out_path.write_text(js)
    print(f"Wrote {len(records):,} film records to {out_path}")


if __name__ == "__main__":
    main()
