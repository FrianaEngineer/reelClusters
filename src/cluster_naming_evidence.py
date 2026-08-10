"""
Phase 5/6 support: run Louvain from scratch on the full augmented graph (no
old NAME_OVERRIDES applied) and print per-community evidence -- size, year
range, top genres, top directors, representative (highest-degree) films,
internal/external edge ratio -- so cluster names can be chosen from measured
evidence rather than reused from the old 10-cluster run.

Does not write cluster_assignments or output/clusters.csv -- read-only
analysis step. cluster.py does the real (writing) run once names are chosen.

    python3 cluster_naming_evidence.py [--min-report-size N]
"""

import argparse
from collections import Counter
from pathlib import Path

import duckdb
import networkx as nx
import community as community_louvain
import pandas as pd

from cluster import build_graph, run_louvain, apply_hidden_gems

DB_PATH = Path(__file__).parent.parent / "db" / "criterion_graph.duckdb"


def load_film_meta(con):
    basic = con.execute("""
        SELECT imdb_tconst, title, criterion_director, criterion_year
        FROM (
            SELECT *, row_number() OVER (
                PARTITION BY imdb_tconst
                ORDER BY (source = 'best_picture_nominee') ASC, confidence_score DESC NULLS LAST
            ) AS rn
            FROM criterion_basic_info
        ) WHERE rn = 1
    """).df().set_index("imdb_tconst")

    genres = con.execute("SELECT imdb_tconst, genres FROM read_csv_auto(?)",
                          [str(Path(__file__).parent.parent / "data" / "imdb_genres.csv")]).df()
    genre_map = {}
    for row in genres.itertuples(index=False):
        g = row.genres if isinstance(row.genres, str) else ""
        genre_map[row.imdb_tconst] = [x for x in g.split(",") if x]

    return basic, genre_map


def report(G, partition, basic, genre_map, min_report_size):
    con_stats = Counter(partition.values())
    print(f"{len(con_stats)} raw Louvain communities, sizes: {sorted(con_stats.values(), reverse=True)}\n")

    # Internal vs external edges per community
    internal = Counter()
    external = Counter()
    for u, v, data in G.edges(data=True):
        w = data.get("shared_actors", 1)
        cu, cv = partition[u], partition[v]
        if cu == cv:
            internal[cu] += w
        else:
            external[cu] += w
            external[cv] += w

    degree = dict(G.degree())

    for cid, size in sorted(con_stats.items(), key=lambda kv: -kv[1]):
        if size < min_report_size:
            continue
        members = [t for t, c in partition.items() if c == cid]
        years = [int(basic.loc[t, "criterion_year"]) for t in members
                 if t in basic.index and pd.notna(basic.loc[t, "criterion_year"])]
        directors = Counter()
        for t in members:
            if t in basic.index and pd.notna(basic.loc[t, "criterion_director"]):
                directors[basic.loc[t, "criterion_director"]] += 1
        genres = Counter()
        for t in members:
            for g in genre_map.get(t, []):
                genres[g] += 1
        top_by_degree = sorted(members, key=lambda t: -degree.get(t, 0))[:8]

        ie, ee = internal[cid], external[cid]
        ratio = ie / (ie + ee) if (ie + ee) else 0.0

        print(f"=== community {cid} -- {size} films (internal/external edge ratio {ratio:.2f}) ===")
        if years:
            print(f"  years: {min(years)}-{max(years)} (median {sorted(years)[len(years)//2]})")
        print(f"  top genres: {genres.most_common(6)}")
        print(f"  top directors: {directors.most_common(6)}")
        print("  representative (highest shared-actor degree) films:")
        for t in top_by_degree:
            title = basic.loc[t, "title"] if t in basic.index else t
            year = basic.loc[t, "criterion_year"] if t in basic.index else ""
            print(f"    {title} ({year}) [{t}] degree={degree.get(t,0)}")
        print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-report-size", type=int, default=3)
    args = ap.parse_args()

    con = duckdb.connect(str(DB_PATH), read_only=True)
    G = build_graph(con)
    basic, genre_map = load_film_meta(con)
    con.close()

    print(f"Graph: {G.number_of_nodes():,} nodes, {G.number_of_edges():,} edges\n")

    partition = run_louvain(G)
    report(G, partition, basic, genre_map, args.min_report_size)

    sizes = Counter(partition.values())
    for threshold in (1, 2, 3):
        n = sum(1 for s in sizes.values() if s <= threshold)
        films = sum(s for s in sizes.values() if s <= threshold)
        print(f"communities of size <= {threshold}: {n} communities, {films} films total")


if __name__ == "__main__":
    main()
