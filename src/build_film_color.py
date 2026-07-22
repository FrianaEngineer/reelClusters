"""
Looks up each film's color / black-and-white status from Wikidata (joined by
IMDb ID via property P345) and writes it to data/film_color.csv, so the hex
grid can color each hexagon's border by its own film's status.

criterion.com and imdb.com both return 403 for scripted requests (confirmed
directly, and already noted in build_criterion_links.py) -- there's no
per-page scraping route. Wikidata's public SPARQL query service is open and
built for exactly this kind of bulk lookup instead.

Coverage is necessarily partial: well-known titles are reliably tagged with
a P462 (color) value, but many of the more obscure films in these clusters
(small national cinemas, single-director filmographies) are not. Unmatched
films get an empty color_label/is_color and hex_svg.py treats them as
black-and-white (the safe default -- no false "color" borders). Films with
no resolved value are printed at the end for manual follow-up.

Re-run any time criterion_basic_info changes:
    python3 build_film_color.py
"""

import csv
import time
from pathlib import Path

import duckdb
import requests

from hex_grid import DB_PATH

OUT_CSV = Path(__file__).parent.parent / "data" / "film_color.csv"
SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
BATCH_SIZE = 300
USER_AGENT = "ReelClusters/1.0 (personal research project; contact: neville@rayze.xyz)"

QUERY_TEMPLATE = """
SELECT ?imdbID ?colorLabel WHERE {{
  VALUES ?imdbID {{ {ids} }}
  ?film wdt:P345 ?imdbID .
  OPTIONAL {{ ?film wdt:P462 ?color }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}}
"""


def load_tconsts():
    con = duckdb.connect(str(DB_PATH), read_only=True)
    df = con.execute("SELECT DISTINCT imdb_tconst FROM criterion_basic_info").df()
    con.close()
    return sorted(df["imdb_tconst"].tolist())


def classify(label):
    """Wikidata's P462 label text -> True (color) / False (b&w) / None
    (unrecognized -- left unresolved rather than guessed)."""
    if label is None:
        return None
    label = label.lower()
    if "black-and-white" in label or "black and white" in label:
        return False
    if "color" in label or "colour" in label:
        return True
    return None


def fetch_batch(tconsts):
    ids = " ".join(f'"{t}"' for t in tconsts)
    query = QUERY_TEMPLATE.format(ids=ids)
    for attempt in range(2):
        try:
            resp = requests.get(
                SPARQL_ENDPOINT,
                params={"query": query, "format": "json"},
                headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"},
                timeout=30,
            )
            resp.raise_for_status()
            break
        except requests.RequestException:
            if attempt == 1:
                raise
            time.sleep(3)

    rows = {}
    for b in resp.json()["results"]["bindings"]:
        tconst = b["imdbID"]["value"]
        label = b.get("colorLabel", {}).get("value")
        # A film can have more than one P462 binding (e.g. a part-color print);
        # keep the first informative label seen rather than overwrite it with None.
        if tconst not in rows or rows[tconst] is None:
            rows[tconst] = label
    return rows


def main():
    tconsts = load_tconsts()
    print(f"Looking up color/B&W for {len(tconsts)} films...")

    labels = {}
    for i in range(0, len(tconsts), BATCH_SIZE):
        batch = tconsts[i:i + BATCH_SIZE]
        labels.update(fetch_batch(batch))
        print(f"  {min(i + BATCH_SIZE, len(tconsts))}/{len(tconsts)}")
        time.sleep(1)   # polite pacing on a shared public endpoint

    unresolved = []
    n_color = n_bw = 0
    with OUT_CSV.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["imdb_tconst", "color_label", "is_color"])
        for t in tconsts:
            label = labels.get(t)
            is_color = classify(label)
            if is_color is True:
                n_color += 1
            elif is_color is False:
                n_bw += 1
            else:
                unresolved.append(t)
            writer.writerow([t, label or "", "" if is_color is None else str(is_color).lower()])

    print(f"Saved -> {OUT_CSV}")
    print(f"  {n_color} color, {n_bw} black-and-white, {len(unresolved)} unresolved (treated as black-and-white)")
    if unresolved:
        print("\nUnresolved imdb_tconst (no Wikidata color match -- review manually if needed):")
        con = duckdb.connect(str(DB_PATH), read_only=True)
        df = con.execute("SELECT imdb_tconst, title, criterion_year FROM criterion_basic_info").df()
        con.close()
        df = df[df["imdb_tconst"].isin(unresolved)].drop_duplicates(subset="imdb_tconst").sort_values("title")
        for _, row in df.iterrows():
            year = "" if row["criterion_year"] != row["criterion_year"] else f" ({int(row['criterion_year'])})"
            print(f"  {row['imdb_tconst']}  {row['title']}{year}")


if __name__ == "__main__":
    main()
