"""
Build the co-occurrence graph and run Louvain community detection.
Writes cluster assignments back to the database as the cluster_assignments table.
"""

import duckdb
import networkx as nx
import community as community_louvain
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


def save_clusters(con: duckdb.DuckDBPyConnection, partition: dict) -> None:
    import pandas as pd

    df = pd.DataFrame(
        list(partition.items()), columns=["imdb_tconst", "cluster_id"]
    )
    con.execute("CREATE OR REPLACE TABLE cluster_assignments AS SELECT * FROM df")
    print(f"Saved {len(df):,} node assignments across {df['cluster_id'].nunique()} clusters")


if __name__ == "__main__":
    con = duckdb.connect(str(DB_PATH))
    G = build_graph(con)
    print(f"Graph: {G.number_of_nodes():,} nodes, {G.number_of_edges():,} edges")

    partition = run_louvain(G)
    save_clusters(con, partition)
    con.close()
