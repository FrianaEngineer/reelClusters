"""
Run once to bootstrap criterion_graph.duckdb from source CSVs.
Re-run any time the source CSVs change.

Source CSVs in data/ are pre-filtered to unambiguous feature-length movies only
(imdb_title_type='movie', runtime>=60min, confidence>=85).
Raw/full data lives in ReelWrangling/data/output/.
"""

import duckdb
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "db" / "criterion_graph.duckdb"
DATA_DIR = Path(__file__).parent.parent / "data"

con = duckdb.connect(str(DB_PATH))

con.execute("""
    CREATE OR REPLACE TABLE criterion_basic_info AS
    SELECT * FROM read_csv_auto(?)
""", [str(DATA_DIR / "criterion_basic_info.csv")])

con.execute("""
    CREATE OR REPLACE TABLE actor_filmographies AS
    SELECT * FROM read_csv_auto(?)
""", [str(DATA_DIR / "actor_filmographies.csv")])

con.execute("""
    CREATE OR REPLACE TABLE actor_names AS
    SELECT * FROM read_csv_auto(?)
""", [str(DATA_DIR / "actor_names.csv")])

con.execute("""
    CREATE OR REPLACE TABLE title_name_translations AS
    SELECT * FROM read_csv_auto(?)
""", [str(DATA_DIR / "title_name_translations.csv")])

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

movies  = con.execute("SELECT count(*) FROM criterion_basic_info").fetchone()[0]
actors  = con.execute("SELECT count(DISTINCT actor_nconst) FROM actor_filmographies").fetchone()[0]
edges   = con.execute("SELECT count(*) FROM movie_edges").fetchone()[0]

print(f"  {movies:,} movies | {actors:,} actors | {edges:,} edges")
print(f"\nDatabase ready at {DB_PATH}")
con.close()
