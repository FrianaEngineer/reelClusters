"""
Build the movie co-occurrence graph and persist it as a GraphML file.

Nodes  = Criterion movies (identified by imdb_tconst)
Edges  = two movies share at least one common actor
Weights = number of shared actors
"""

import duckdb
import networkx as nx
from pathlib import Path

DB_PATH  = Path(__file__).parent.parent / "db" / "criterion_graph.duckdb"
OUT_PATH = Path(__file__).parent.parent / "output" / "criterion_graph.graphml"


def build_graph(con: duckdb.DuckDBPyConnection) -> nx.Graph:
    # edges: movie pairs with at least one shared actor
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

    # node attributes from criterion_basic_info
    nodes = con.execute("""
        SELECT imdb_tconst, title, criterion_director, criterion_year, imdb_runtime_minutes
        FROM criterion_basic_info
    """).df()

    for _, row in nodes.iterrows():
        tconst = row["imdb_tconst"]
        if tconst in G:
            G.nodes[tconst]["title"]     = row["title"] or ""
            G.nodes[tconst]["director"]  = row["criterion_director"] or ""
            G.nodes[tconst]["year"]      = int(row["criterion_year"]) if row["criterion_year"] else 0
            G.nodes[tconst]["runtime"]   = int(row["imdb_runtime_minutes"]) if row["imdb_runtime_minutes"] else 0

    return G


if __name__ == "__main__":
    con = duckdb.connect(str(DB_PATH))
    G = build_graph(con)
    con.close()

    n_nodes     = G.number_of_nodes()
    n_edges     = G.number_of_edges()
    n_isolated  = sum(1 for n in G.nodes() if G.degree(n) == 0)
    avg_degree  = sum(dict(G.degree()).values()) / n_nodes if n_nodes else 0

    print(f"Nodes (movies):   {n_nodes:,}")
    print(f"Edges:            {n_edges:,}")
    print(f"Isolated nodes:   {n_isolated:,}")
    print(f"Avg degree:       {avg_degree:.1f}")

    nx.write_graphml(G, OUT_PATH)
    print(f"\nGraph saved to {OUT_PATH}")
