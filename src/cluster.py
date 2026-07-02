"""
Build the co-occurrence graph and run Louvain community detection.
Writes cluster assignments back to the database as the cluster_assignments table.

Post-processing: any Louvain cluster with exactly 2 films is merged into a
single custom cluster called 'hiddenGems' rather than kept as isolated pairs.
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


def run_louvain(G: nx.Graph, weight: str = "shared_actors") -> dict:
    return community_louvain.best_partition(G, weight=weight)


def apply_hidden_gems(partition: dict) -> dict:
    """Merge all 2-film Louvain clusters into a single 'hiddenGems' cluster."""
    cluster_sizes = Counter(partition.values())
    two_film_ids  = {cid for cid, size in cluster_sizes.items() if size == 2}

    merged = {}
    for tconst, cid in partition.items():
        merged[tconst] = "hiddenGems" if cid in two_film_ids else str(cid)
    return merged


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
