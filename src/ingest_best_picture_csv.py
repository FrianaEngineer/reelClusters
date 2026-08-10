"""
Phase 2 ingestion for the Best Picture nominees IMDb list export.

Reads data/raw/imdb_best_picture_nominees_raw.csv (an untouched copy of the
supplied ReelWrangling CSV -- see that file's header comment / git history
for provenance) and produces a normalized, validated intermediate table:
data/raw/imdb_best_picture_nominees_normalized.csv

This step does NOT decide what's a duplicate of an existing Criterion film --
that's merge_best_picture_films.py. This step only:
  1. validates each row structurally (IMDb ID format, URL/Const agreement,
     numeric/date parsing, title type),
  2. deduplicates exact repeated Const values *within* the incoming CSV,
  3. normalizes genres/directors into this project's existing list-ish CSV
     conventions,
  4. carries source row position through as provenance.

Missing values are preserved as empty/NaN -- never coerced to 0 or "Unknown".

    python3 ingest_best_picture_csv.py
"""

import csv
import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
RAW_CSV = REPO_ROOT / "data" / "raw" / "imdb_best_picture_nominees_raw.csv"
NORMALIZED_CSV = REPO_ROOT / "data" / "raw" / "imdb_best_picture_nominees_normalized.csv"
VALIDATION_ERRORS_CSV = REPO_ROOT / "data" / "raw" / "imdb_best_picture_nominees_validation_errors.csv"
ROW_DISPOSITIONS_CSV = REPO_ROOT / "data" / "raw" / "imdb_best_picture_nominees_row_dispositions.csv"

TCONST_RE = re.compile(r"^tt\d+$")
URL_TCONST_RE = re.compile(r"/title/(tt\d+)/")
SUPPORTED_TITLE_TYPES = {"Movie"}


class RowError(Exception):
    def __init__(self, position, field, message):
        self.position = position
        self.field = field
        self.message = message
        super().__init__(f"row {position} field {field}: {message}")


def parse_int(value, field, position):
    value = (value or "").strip()
    if value == "":
        return None
    try:
        return int(value)
    except ValueError:
        raise RowError(position, field, f"expected integer, got {value!r}")


def parse_float(value, field, position):
    value = (value or "").strip()
    if value == "":
        return None
    try:
        return float(value)
    except ValueError:
        raise RowError(position, field, f"expected float, got {value!r}")


def parse_date(value, field, position):
    """IMDb release dates are sometimes only known to month or year
    precision -- YYYY, YYYY-MM, and YYYY-MM-DD are all accepted and stored
    verbatim (not padded/guessed to a fake day), since this project has no
    full-date field to require finer precision than the source provides."""
    value = (value or "").strip()
    if value == "":
        return None
    if not re.match(r"^\d{4}(-\d{2}(-\d{2})?)?$", value):
        raise RowError(position, field, f"expected YYYY, YYYY-MM, or YYYY-MM-DD, got {value!r}")
    return value


def normalize_genres(value):
    """'Drama, Romance' -> 'Drama,Romance' -- matches data/imdb_genres.csv's
    no-space comma convention (see extract_imdb_genres.py output)."""
    parts = [g.strip() for g in (value or "").split(",") if g.strip()]
    return ",".join(parts)


def normalize_directors(value):
    """'Frank Borzage, Jane Doe' -> ['Frank Borzage', 'Jane Doe'], preserving
    each name as written. Joined with ', ' to match criterion_director's
    existing free-text style when a film has one director; multi-director
    films keep all names."""
    parts = [d.strip() for d in (value or "").split(",") if d.strip()]
    return parts


def validate_and_normalize_row(row, position):
    const = (row["Const"] or "").strip()
    if not TCONST_RE.match(const):
        raise RowError(position, "Const", f"not a valid tt-prefixed IMDb ID: {const!r}")

    url = (row["URL"] or "").strip()
    url_match = URL_TCONST_RE.search(url)
    url_tconst = url_match.group(1) if url_match else None
    if url_tconst is None:
        raise RowError(position, "URL", f"could not extract tconst from URL: {url!r}")
    if url_tconst != const:
        raise RowError(position, "URL", f"URL tconst {url_tconst!r} disagrees with Const {const!r}")

    title_type = (row["Title Type"] or "").strip()
    if title_type not in SUPPORTED_TITLE_TYPES:
        raise RowError(position, "Title Type", f"unsupported title type: {title_type!r}")

    title = (row["Title"] or "").strip()
    original_title = (row["Original Title"] or "").strip()
    if not title:
        raise RowError(position, "Title", "blank title")

    year = parse_int(row["Year"], "Year", position)
    runtime = parse_int(row["Runtime (mins)"], "Runtime (mins)", position)
    rating = parse_float(row["IMDb Rating"], "IMDb Rating", position)
    votes = parse_int(row["Num Votes"], "Num Votes", position)
    release_date = parse_date(row["Release Date"], "Release Date", position)

    directors = normalize_directors(row["Directors"])
    if not directors:
        raise RowError(position, "Directors", "no directors listed")

    genres = normalize_genres(row["Genres"])

    return {
        "source_position": position,
        "imdb_tconst": const,
        "title": title,
        "original_title": original_title,
        "year": year,
        "release_date": release_date or "",
        "runtime_minutes": runtime,
        "imdb_rating": rating,
        "num_votes": votes,
        "genres": genres,
        "directors": "; ".join(directors),
        "title_type": title_type,
        "source_url": url,
    }


def main():
    with RAW_CSV.open(newline="", encoding="utf-8") as f:
        raw_rows = list(csv.DictReader(f))

    errors = []
    normalized = []
    seen_tconst_first_position = {}
    duplicate_in_csv = []
    dispositions = []

    for i, row in enumerate(raw_rows, start=1):
        position = row.get("Position", str(i)) or str(i)
        raw_title = (row.get("Title") or "").strip()
        raw_const = (row.get("Const") or "").strip()
        raw_year = (row.get("Year") or "").strip()
        try:
            record = validate_and_normalize_row(row, position)
        except RowError as e:
            errors.append({"position": e.position, "field": e.field, "message": e.message})
            dispositions.append({
                "source_position": position, "imdb_id": raw_const, "title": raw_title,
                "year": raw_year, "decision": "rejected_invalid",
                "detail": f"{e.field}: {e.message}",
            })
            continue

        tconst = record["imdb_tconst"]
        if tconst in seen_tconst_first_position:
            duplicate_in_csv.append((position, tconst, record["title"]))
            dispositions.append({
                "source_position": position, "imdb_id": tconst, "title": record["title"],
                "year": raw_year, "decision": "duplicate_in_csv",
                "detail": f"duplicate of row {seen_tconst_first_position[tconst]} (same Const)",
            })
            continue
        seen_tconst_first_position[tconst] = position
        normalized.append(record)
        dispositions.append({
            "source_position": position, "imdb_id": tconst, "title": record["title"],
            "year": raw_year, "decision": "ok", "detail": "",
        })

    NORMALIZED_CSV.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "source_position", "imdb_tconst", "title", "original_title", "year",
        "release_date", "runtime_minutes", "imdb_rating", "num_votes",
        "genres", "directors", "title_type", "source_url",
    ]
    with NORMALIZED_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(normalized)

    with VALIDATION_ERRORS_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["position", "field", "message"])
        writer.writeheader()
        writer.writerows(errors)

    with ROW_DISPOSITIONS_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["source_position", "imdb_id", "title", "year", "decision", "detail"])
        writer.writeheader()
        writer.writerows(dispositions)

    print(f"Read {len(raw_rows):,} raw rows from {RAW_CSV}")
    print(f"Validation errors: {len(errors):,} -> {VALIDATION_ERRORS_CSV}")
    print(f"Duplicate Const within CSV (kept first occurrence): {len(duplicate_in_csv):,}")
    for pos, tconst, title in duplicate_in_csv:
        print(f"  row {pos}: {tconst} {title!r} (duplicate of an earlier row)")
    print(f"Normalized unique incoming films: {len(normalized):,} -> {NORMALIZED_CSV}")


if __name__ == "__main__":
    main()
