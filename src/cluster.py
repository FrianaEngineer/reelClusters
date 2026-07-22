"""
Build the co-occurrence graph and run Louvain community detection.
Writes cluster assignments back to the database as the cluster_assignments table.

Post-processing:
  1. Any Louvain cluster with exactly 2 films is merged into a single custom
     cluster called 'hiddenGems' rather than kept as isolated pairs.
  2. NAME_OVERRIDES renames Louvain's arbitrary numeric community IDs to the
     stable, human-readable names used site-wide (NAMED_CLUSTERS in
     build_site.py, CLUSTERS_TO_RENDER in cluster_graph_viz.py, COLOR_MAP in
     cluster_colors.py). Louvain's numbering isn't stable across reruns and
     carries no identity of its own -- this mapping is derived by comparing
     each run's output against the previous named assignments (majority
     film-overlap per new cluster; see db/backup/ for the pre-documentary
     -removal baseline used for the 2026-07 rebuild) and is only valid for
     THIS graph. Any numeric ID left unmapped falls back to 'hiddenGems'.
     Re-derive this dict (same overlap comparison, or fresh judgment for any
     newly-merged/split community) any time the underlying film set changes
     enough to reshuffle Louvain's communities.
"""

import duckdb
import networkx as nx
import community as community_louvain
import pandas as pd
from collections import Counter
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "db" / "criterion_graph.duckdb"


def build_graph(con: duckdb.DuckDBPyConnection) -> nx.Graph:
    edges = con.execute("""
        SELECT movie_a, movie_b, shared_actors
        FROM movie_edges
    """).df()

    G = nx.from_pandas_edgelist(
        edges,
        source="movie_a",
        target="movie_b",
        edge_attr="shared_actors",
    )
    return G


def run_louvain(G: nx.Graph, weight: str = "shared_actors", random_state: int = 42) -> dict:
    # Fixed seed: best_partition is otherwise non-deterministic run-to-run,
    # which would silently invalidate NAME_OVERRIDES below (it's keyed to
    # this specific partition's numeric community IDs).
    return community_louvain.best_partition(G, weight=weight, random_state=random_state)


def apply_hidden_gems(partition: dict) -> dict:
    """Merge all 2-film Louvain clusters into a single 'hiddenGems' cluster."""
    cluster_sizes = Counter(partition.values())
    two_film_ids  = {cid for cid, size in cluster_sizes.items() if size == 2}

    merged = {}
    for tconst, cid in partition.items():
        merged[tconst] = "hiddenGems" if cid in two_film_ids else str(cid)
    return merged


# See the module docstring -- valid only for run_louvain's fixed random_state=42
# on the 2026-07 documentary-free graph, derived by majority film-overlap
# against db/backup/cluster_assignments_pre_doc_removal.csv, plus one manual
# call: cluster '7' (59% US / 21% Germany) is kept as a single combined
# cluster per user decision, rather than split back into the two old ones --
# confirmed stable (same 59/37 split) across multiple reruns of Louvain, not
# a one-off artifact.
NAME_OVERRIDES = {
    '2':  'european_art_cinema',
    '19': 'european_art_cinema',
    '23': 'european_art_cinema',
    '0':  'anglophone_classic',
    '1':  'anglophone_classic',
    '10': 'hong_kong_taiwan_cinema',
    '11': 'japanese_cinema',
    '5':  'japanese_cinema',
    '6':  'japanese_cinema',
    '14': 'czech_new_wave',
    '16': 'satyajit_ray_indian',
    '4':  'bergman_scandinavian',
    '7':  'transatlantic_auteur_cinema',
    '8':  'youssef_chahine_egyptian',
    '9':  'soviet_cinema',
}


def apply_name_overrides(partition: dict) -> dict:
    """Rename Louvain's numeric community IDs to stable names; anything not
    in NAME_OVERRIDES (small leftover communities with no clear identity of
    their own) folds into hiddenGems alongside the merged 2-film pairs."""
    return {
        tconst: NAME_OVERRIDES.get(cid, "hiddenGems") if cid != "hiddenGems" else cid
        for tconst, cid in partition.items()
    }


def save_clusters(con: duckdb.DuckDBPyConnection, partition: dict) -> None:
    df = pd.DataFrame(list(partition.items()), columns=["imdb_tconst", "cluster_id"])
    con.execute("CREATE OR REPLACE TABLE cluster_assignments AS SELECT * FROM df")

    named   = df[df["cluster_id"] == "hiddenGems"]
    numeric = df[df["cluster_id"] != "hiddenGems"]
    print(f"  hiddenGems:          {len(named):,} films ({len(named)//2} pairs)")
    print(f"  Louvain clusters:    {numeric['cluster_id'].nunique()}")
    print(f"  Total nodes saved:   {len(df):,}")


if __name__ == "__main__":
    con = duckdb.connect(str(DB_PATH))
    G = build_graph(con)
    print(f"Graph: {G.number_of_nodes():,} nodes, {G.number_of_edges():,} edges\n")

    partition = run_louvain(G)
    partition = apply_hidden_gems(partition)
    partition = apply_name_overrides(partition)
    save_clusters(con, partition)

    con.execute("""
        COPY (
            SELECT
                ca.cluster_id,
                count(*) OVER (PARTITION BY ca.cluster_id) AS cluster_size,
                cbi.title,
                cbi.criterion_director,
                cbi.criterion_year,
                cbi.imdb_runtime_minutes
            FROM cluster_assignments ca
            JOIN criterion_basic_info cbi ON cbi.imdb_tconst = ca.imdb_tconst
            ORDER BY
                CASE WHEN ca.cluster_id = 'hiddenGems' THEN 1 ELSE 0 END,
                cluster_size DESC,
                ca.cluster_id,
                cbi.criterion_year
        ) TO ? (HEADER, DELIMITER ',')
    """, [str(Path(__file__).parent.parent / "output" / "clusters.csv")])
    print(f"\nClusters written to output/clusters.csv")
    con.close()
