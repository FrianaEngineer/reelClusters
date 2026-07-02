"""
Run once to bootstrap criterion_graph.duckdb from source CSVs.
Re-run any time the source CSVs change.
"""

import duckdb
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "db" / "criterion_graph.duckdb"
DATA_DIR = Path(__file__).parent.parent / "data"

con = duckdb.connect(str(DB_PATH))

# --- raw tables ---
con.execute("""
    CREATE OR REPLACE TABLE actor_filmographies AS
    SELECT * FROM read_csv_auto(?)
""", [str(DATA_DIR / "actor_filmographies.csv")])

con.execute("""
    CREATE OR REPLACE TABLE actor_names AS
    SELECT * FROM read_csv_auto(?)
""", [str(DATA_DIR / "actor_names.csv")])

con.execute("""
    CREATE OR REPLACE TABLE criterion_basic_info AS
    SELECT * FROM read_csv_auto(?)
""", [str(DATA_DIR / "criterion_basic_info.csv")])

con.execute("""
    CREATE OR REPLACE TABLE title_name_translations AS
    SELECT * FROM read_csv_auto(?)
""", [str(DATA_DIR / "title_name_translations.csv")])

# --- derived: movie-movie edge list ---
con.execute("""
    CREATE OR REPLACE TABLE movie_edges AS
    SELECT
        a.title_tconst AS movie_a,
        b.title_tconst AS movie_b,
        count(*)        AS shared_actors,
        list(n.actor_name ORDER BY n.actor_name) AS actor_list
    FROM actor_filmographies a
    JOIN actor_filmographies b
      ON a.actor_nconst = b.actor_nconst
     AND a.title_tconst < b.title_tconst
    JOIN actor_names n ON n.actor_nconst = a.actor_nconst
    GROUP BY 1, 2
""")

counts = {
    "actor_filmographies": con.execute("SELECT count(*) FROM actor_filmographies").fetchone()[0],
    "actor_names":         con.execute("SELECT count(*) FROM actor_names").fetchone()[0],
    "criterion_basic_info":con.execute("SELECT count(*) FROM criterion_basic_info").fetchone()[0],
    "movie_edges":         con.execute("SELECT count(*) FROM movie_edges").fetchone()[0],
}

for table, n in counts.items():
    print(f"  {table}: {n:,} rows")

print(f"\nDatabase ready at {DB_PATH}")
con.close()
