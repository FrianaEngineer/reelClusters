"""
One-time extraction of real IMDb genre tags for this project's film set.

criterion_basic_info.csv carries imdb_tconst but was never joined against
IMDb's genres field -- the raw IMDb title.basics.tsv dump lives in the sibling
ReelWrangling project (this project only ever pulled in the filtered
Criterion/IMDb match output, see methodology.html), so genres were simply not
present here yet.

This script re-derives data/imdb_genres.csv from that sibling repo's raw
dump. It is NOT part of build_site.py's regular pipeline (that dump isn't
checked into this repo, and won't exist on another machine) -- it only needs
re-running if the film set changes and the checked-in CSV needs refreshing.
Everything downstream (build_recommendation_data.py) reads the checked-in
CSV, not this script.

    python3 extract_imdb_genres.py
"""

from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).parent.parent
CRITERION_BASIC_INFO = REPO_ROOT / "data" / "criterion_basic_info.csv"
OUT_PATH = REPO_ROOT / "data" / "imdb_genres.csv"

# Sibling project -- see reelClusters project memory / methodology.html for
# why the raw IMDb dumps live there and not here.
TITLE_BASICS_TSV = Path("/Users/friana/ReelWrangling/data/imdb/title.basics.tsv")


def main():
    if not TITLE_BASICS_TSV.exists():
        raise SystemExit(
            f"{TITLE_BASICS_TSV} not found -- this script only runs on a "
            "machine with the ReelWrangling sibling repo checked out."
        )

    con = duckdb.connect()
    df = con.execute(
        """
        SELECT DISTINCT c.imdb_tconst, b.genres
        FROM read_csv_auto(?) c
        JOIN read_csv_auto(?, delim='\t', header=True, quote='') b
          ON b.tconst = c.imdb_tconst
        """,
        [str(CRITERION_BASIC_INFO), str(TITLE_BASICS_TSV)],
    ).df()

    # IMDb's null marker for a handful of rows with no genre tags at all.
    df["genres"] = df["genres"].replace(r"^\\N$", "", regex=True).fillna("")
    df.to_csv(OUT_PATH, index=False)
    print(f"Wrote {len(df):,} rows to {OUT_PATH}")


if __name__ == "__main__":
    main()
