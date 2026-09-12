"""
Extracts Best Picture *winners* (as opposed to nominees) from the IMDb list
export already used for the Reeling Through the Years video and writes them
to data/best_picture_winners.csv, so the hex grid can gold-border each
winner's hexagon.

data/raw/imdb_best_picture_nominees_raw.csv covers all nominees; winners are
distinguished only by their Description field reading "Oscar winner <year>"
(blank for a plain nominee) -- that field is dropped by
ingest_best_picture_csv.py / merge_best_picture_films.py, so it has to be
read off the raw file directly rather than the normalized/merged tables.

Re-run any time the raw best-picture CSV changes:
    python3 build_best_picture_winners.py
"""

import csv
import re
from pathlib import Path

RAW_CSV = Path(__file__).parent.parent / "data" / "raw" / "imdb_best_picture_nominees_raw.csv"
OUT_CSV = Path(__file__).parent.parent / "data" / "best_picture_winners.csv"

WINNER_RE = re.compile(r"^Oscar winner (\d{4})$")


def main():
    with RAW_CSV.open(newline="") as f:
        rows = list(csv.DictReader(f))

    winners = []
    for row in rows:
        m = WINNER_RE.match(row.get("Description", "").strip())
        if m:
            winners.append((row["Const"].strip(), row["Title"].strip(), m.group(1)))

    with OUT_CSV.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["imdb_tconst", "title", "oscar_year"])
        for tconst, title, year in winners:
            writer.writerow([tconst, title, year])

    print(f"Saved {len(winners)} Best Picture winners -> {OUT_CSV}")


if __name__ == "__main__":
    main()
