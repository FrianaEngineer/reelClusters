"""
Query cluster assignments joined with Criterion metadata for analysis.
"""

import duckdb
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "db" / "criterion_graph.duckdb"


def cluster_summary(con: duckdb.DuckDBPyConnection):
    return con.execute("""
        SELECT
            ca.cluster_id,
            count(*)                        AS num_films,
            list(cbi.title ORDER BY cbi.title) AS titles
        FROM cluster_assignments ca
        JOIN criterion_basic_info cbi ON cbi.imdb_tconst = ca.imdb_tconst
        GROUP BY ca.cluster_id
        ORDER BY num_films DESC
    """).df()


def top_edges(con: duckdb.DuckDBPyConnection, n: int = 20):
    return con.execute("""
        SELECT
            cbi_a.title AS film_a,
            cbi_b.title AS film_b,
            me.shared_actors,
            me.actor_list
        FROM movie_edges me
        JOIN criterion_basic_info cbi_a ON cbi_a.imdb_tconst = me.movie_a
        JOIN criterion_basic_info cbi_b ON cbi_b.imdb_tconst = me.movie_b
        ORDER BY me.shared_actors DESC
        LIMIT ?
    """, [n]).df()


if __name__ == "__main__":
    con = duckdb.connect(str(DB_PATH))

    print("=== Cluster summary (top 10) ===")
    print(cluster_summary(con).head(10).to_string(index=False))

    print("\n=== Strongest edges ===")
    print(top_edges(con).to_string(index=False))

    con.close()
