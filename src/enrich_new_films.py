"""
Phase 4: enrich the newly-added (source == 'best_picture_nominee') films with
the same derived data every existing Criterion film has, using this
project's existing approved sources and rules -- not a new ad hoc scrape.

  - actor_filmographies.csv / actor_names.csv: replicates the exact rule
    from ReelWrangling/scripts/criterion_imdb_duckdb_enrichment.sql section
    13/14 (category IN ('actor','actress','self'), joined from
    title.principals.tsv / name.basics.tsv), restricted to the new tconsts.
    This is what the shared-actor clustering graph is built from.
  - imdb_genres.csv: replicates extract_imdb_genres.py's join against
    title.basics.tsv, restricted to the new tconsts.
  - title_name_translations.csv: replicates section 15 of the same SQL file
    (best US/English aka, falling back to title.basics primaryTitle).
  - data/film_color.csv: reuses build_film_color.py's Wikidata lookup,
    restricted to tconsts not already present in the file (adds new films
    without re-querying ~1,746 already-resolved ones).

All of these are additive merges into the existing checked-in CSVs -- no
existing row for an existing film is modified.

    python3 enrich_new_films.py
"""

import csv
import sys
import time
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).parent.parent
DATA_DIR = REPO_ROOT / "data"
IMDB_RAW_DIR = Path("/Users/friana/ReelWrangling/data/imdb")

TITLE_PRINCIPALS_TSV = IMDB_RAW_DIR / "title.principals.tsv"
NAME_BASICS_TSV = IMDB_RAW_DIR / "name.basics.tsv"
TITLE_BASICS_TSV = IMDB_RAW_DIR / "title.basics.tsv"
TITLE_AKAS_TSV = IMDB_RAW_DIR / "title.akas.tsv"

CANONICAL_CSV = DATA_DIR / "criterion_basic_info.csv"
ACTOR_FILMOGRAPHIES_CSV = DATA_DIR / "actor_filmographies.csv"
ACTOR_NAMES_CSV = DATA_DIR / "actor_names.csv"
IMDB_GENRES_CSV = DATA_DIR / "imdb_genres.csv"
TITLE_TRANSLATIONS_CSV = DATA_DIR / "title_name_translations.csv"
FILM_COLOR_CSV = DATA_DIR / "film_color.csv"


def new_tconsts():
    with CANONICAL_CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    tconsts = sorted({r["imdb_tconst"] for r in rows if r.get("source") == "best_picture_nominee"})
    return tconsts


def enrich_actor_credits(con, tconsts):
    con.execute("CREATE OR REPLACE TABLE new_tconst(tconst VARCHAR)")
    con.executemany("INSERT INTO new_tconst VALUES (?)", [(t,) for t in tconsts])

    con.execute(f"""
        CREATE OR REPLACE TABLE title_principals AS
        SELECT tconst, nconst, category
        FROM read_csv('{TITLE_PRINCIPALS_TSV}', delim='\t', header=True, quote='', nullstr='\\N', all_varchar=True)
        WHERE tconst IN (SELECT tconst FROM new_tconst)
    """)
    con.execute(f"""
        CREATE OR REPLACE TABLE new_filmographies AS
        SELECT DISTINCT nconst AS actor_nconst, tconst AS title_tconst
        FROM title_principals
        WHERE category IN ('actor', 'actress', 'self')
    """)
    new_rows = con.execute("SELECT actor_nconst, title_tconst FROM new_filmographies").fetchall()

    con.execute(f"""
        CREATE OR REPLACE TABLE name_basics AS
        SELECT nconst, primaryName
        FROM read_csv('{NAME_BASICS_TSV}', delim='\t', header=True, quote='', nullstr='\\N', all_varchar=True)
        WHERE nconst IN (SELECT DISTINCT actor_nconst FROM new_filmographies)
    """)
    new_name_rows = con.execute("SELECT nconst, primaryName FROM name_basics").fetchall()

    existing_filmo = set()
    with ACTOR_FILMOGRAPHIES_CSV.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            existing_filmo.add((row["actor_nconst"], row["title_tconst"]))
    added_filmo = [(a, t) for a, t in new_rows if (a, t) not in existing_filmo]
    with ACTOR_FILMOGRAPHIES_CSV.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator='\n')
        writer.writerows(added_filmo)

    existing_actors = set()
    with ACTOR_NAMES_CSV.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            existing_actors.add(row["actor_nconst"])
    added_names = [(n, name) for n, name in new_name_rows if n not in existing_actors]
    with ACTOR_NAMES_CSV.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator='\n')
        writer.writerows(added_names)

    films_with_cast = {t for _, t in new_rows}
    print(f"actor_filmographies.csv: +{len(added_filmo):,} rows "
          f"({len(films_with_cast):,}/{len(tconsts):,} new films have >=1 cast credit)")
    print(f"actor_names.csv: +{len(added_names):,} actors")
    no_cast = [t for t in tconsts if t not in films_with_cast]
    if no_cast:
        print(f"  {len(no_cast)} new films have NO actor/actress/self credit in title.principals.tsv "
              f"(will fall to hiddenGems in the viz, same as any existing Criterion film with no cast data): "
              f"{no_cast[:10]}{'...' if len(no_cast) > 10 else ''}")


def enrich_genres(con, tconsts):
    df = con.execute(f"""
        SELECT DISTINCT nt.tconst AS imdb_tconst, b.genres
        FROM new_tconst nt
        JOIN read_csv('{TITLE_BASICS_TSV}', delim='\t', header=True, quote='', nullstr='\\N', all_varchar=True) b
          ON b.tconst = nt.tconst
    """).df()
    df["genres"] = df["genres"].fillna("")

    existing = set()
    with IMDB_GENRES_CSV.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            existing.add(row["imdb_tconst"])
    new_rows = [(r.imdb_tconst, r.genres) for r in df.itertuples(index=False) if r.imdb_tconst not in existing]
    with IMDB_GENRES_CSV.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator='\n')
        writer.writerows(new_rows)
    print(f"imdb_genres.csv: +{len(new_rows):,} rows")


def enrich_title_translations(con, tconsts):
    con.execute(f"""
        CREATE OR REPLACE TABLE title_basics_new AS
        SELECT tconst, primaryTitle
        FROM read_csv('{TITLE_BASICS_TSV}', delim='\t', header=True, quote='', nullstr='\\N', all_varchar=True)
        WHERE tconst IN (SELECT tconst FROM new_tconst)
    """)
    con.execute(f"""
        CREATE OR REPLACE TABLE title_akas_en_new AS
        SELECT DISTINCT titleId AS tconst, title, region, language
        FROM read_csv('{TITLE_AKAS_TSV}', delim='\t', header=True, quote='', nullstr='\\N', all_varchar=True)
        WHERE titleId IN (SELECT tconst FROM new_tconst)
          AND (region = 'US' OR language = 'en')
          AND (attributes IS NULL OR attributes != 'segment title')
    """)
    con.execute("""
        CREATE OR REPLACE TABLE best_english_aka_new AS
        SELECT tconst, title AS english_title
        FROM (
            SELECT tconst, title,
                   row_number() OVER (
                       PARTITION BY tconst ORDER BY (region = 'US') DESC, (language = 'en') DESC
                   ) AS rnk
            FROM title_akas_en_new
        ) WHERE rnk = 1
    """)
    df = con.execute("""
        SELECT nt.tconst AS title_tconst,
               COALESCE(bea.english_title, tb.primaryTitle) AS english_title
        FROM new_tconst nt
        LEFT JOIN best_english_aka_new bea ON bea.tconst = nt.tconst
        LEFT JOIN title_basics_new tb ON tb.tconst = nt.tconst
    """).df()

    existing = set()
    with TITLE_TRANSLATIONS_CSV.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            existing.add(row["title_tconst"])
    new_rows = [(r.title_tconst, r.english_title) for r in df.itertuples(index=False) if r.title_tconst not in existing]
    with TITLE_TRANSLATIONS_CSV.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator='\n')
        writer.writerows(new_rows)
    print(f"title_name_translations.csv: +{len(new_rows):,} rows")


def enrich_color(tconsts):
    """Only fetch tconsts not already in film_color.csv -- avoids re-querying
    Wikidata for the ~1,746 films already resolved."""
    import requests

    existing = {}
    with FILM_COLOR_CSV.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            existing[row["imdb_tconst"]] = row
    missing = [t for t in tconsts if t not in existing]
    if not missing:
        print("film_color.csv: no new tconsts to fetch")
        return

    SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
    USER_AGENT = "ReelClusters/1.0 (personal research project; contact: neville@rayze.xyz)"
    BATCH_SIZE = 300
    QUERY_TEMPLATE = """
    SELECT ?imdbID ?colorLabel WHERE {{
      VALUES ?imdbID {{ {ids} }}
      ?film wdt:P345 ?imdbID .
      OPTIONAL {{ ?film wdt:P462 ?color }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
    }}
    """

    def classify(label):
        if label is None:
            return None
        label = label.lower()
        if "black-and-white" in label or "black and white" in label:
            return False
        if "color" in label or "colour" in label:
            return True
        return None

    labels = {}
    for i in range(0, len(missing), BATCH_SIZE):
        batch = missing[i:i + BATCH_SIZE]
        ids = " ".join(f'"{t}"' for t in batch)
        query = QUERY_TEMPLATE.format(ids=ids)
        resp = requests.get(
            SPARQL_ENDPOINT, params={"query": query, "format": "json"},
            headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"}, timeout=30,
        )
        resp.raise_for_status()
        for b in resp.json()["results"]["bindings"]:
            tconst = b["imdbID"]["value"]
            label = b.get("colorLabel", {}).get("value")
            if tconst not in labels or labels[tconst] is None:
                labels[tconst] = label
        print(f"  color lookup {min(i + BATCH_SIZE, len(missing))}/{len(missing)}")
        time.sleep(1)

    n_color = n_bw = n_unresolved = 0
    new_rows = []
    for t in missing:
        label = labels.get(t)
        is_color = classify(label)
        if is_color is True:
            n_color += 1
        elif is_color is False:
            n_bw += 1
        else:
            n_unresolved += 1
        new_rows.append((t, label or "", "" if is_color is None else str(is_color).lower()))

    with FILM_COLOR_CSV.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator='\n')
        writer.writerows(new_rows)
    print(f"film_color.csv: +{len(new_rows):,} rows ({n_color} color, {n_bw} black-and-white, {n_unresolved} unresolved)")


def main():
    if not TITLE_PRINCIPALS_TSV.exists():
        sys.exit(f"{TITLE_PRINCIPALS_TSV} not found -- run on a machine with the ReelWrangling sibling repo checked out.")

    tconsts = new_tconsts()
    print(f"Enriching {len(tconsts):,} newly-added films\n")

    con = duckdb.connect()
    enrich_actor_credits(con, tconsts)
    enrich_genres(con, tconsts)
    enrich_title_translations(con, tconsts)
    con.close()

    enrich_color(tconsts)


if __name__ == "__main__":
    main()
