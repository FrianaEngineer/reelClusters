"""
Input-validation tests for src/ingest_best_picture_csv.py, plus an
integration check that the actual generated normalized/disposition files are
internally consistent with the raw CSV.
"""

import csv
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

import ingest_best_picture_csv as ing  # noqa: E402


# --- Unit tests on the parsing/validation functions -----------------------

def test_valid_tconst_accepted():
    row = {
        "Const": "tt0018379", "URL": "https://www.imdb.com/title/tt0018379/",
        "Title": "7th Heaven", "Original Title": "7th Heaven", "Year": "1927",
        "Release Date": "1927-10-30", "Runtime (mins)": "110", "IMDb Rating": "7.5",
        "Num Votes": "4713", "Genres": "Drama, Romance", "Directors": "Frank Borzage",
        "Title Type": "Movie",
    }
    rec = ing.validate_and_normalize_row(row, "1")
    assert rec["imdb_tconst"] == "tt0018379"
    assert rec["year"] == 1927
    assert rec["runtime_minutes"] == 110
    assert rec["imdb_rating"] == 7.5


def test_invalid_tconst_format_rejected():
    row = {"Const": "notanid", "URL": "https://www.imdb.com/title/notanid/",
           "Title": "X", "Original Title": "X", "Year": "2000", "Release Date": "",
           "Runtime (mins)": "90", "IMDb Rating": "", "Num Votes": "",
           "Genres": "Drama", "Directors": "Someone", "Title Type": "Movie"}
    with pytest.raises(ing.RowError):
        ing.validate_and_normalize_row(row, "1")


def test_url_tconst_disagreement_rejected():
    row = {"Const": "tt0018379", "URL": "https://www.imdb.com/title/tt9999999/",
           "Title": "X", "Original Title": "X", "Year": "2000", "Release Date": "",
           "Runtime (mins)": "90", "IMDb Rating": "", "Num Votes": "",
           "Genres": "Drama", "Directors": "Someone", "Title Type": "Movie"}
    with pytest.raises(ing.RowError):
        ing.validate_and_normalize_row(row, "1")


def test_unsupported_title_type_rejected():
    row = {"Const": "tt0018379", "URL": "https://www.imdb.com/title/tt0018379/",
           "Title": "X", "Original Title": "X", "Year": "2000", "Release Date": "",
           "Runtime (mins)": "90", "IMDb Rating": "", "Num Votes": "",
           "Genres": "Drama", "Directors": "Someone", "Title Type": "TV Series"}
    with pytest.raises(ing.RowError):
        ing.validate_and_normalize_row(row, "1")


def test_missing_rating_preserved_as_none_not_zero():
    row = {"Const": "tt0019257", "URL": "https://www.imdb.com/title/tt0019257/",
           "Title": "The Patriot", "Original Title": "The Patriot", "Year": "1928",
           "Release Date": "1928-08-01", "Runtime (mins)": "90", "IMDb Rating": "",
           "Num Votes": "500", "Genres": "Drama", "Directors": "Someone", "Title Type": "Movie"}
    rec = ing.validate_and_normalize_row(row, "1")
    assert rec["imdb_rating"] is None  # not 0.0


def test_missing_runtime_preserved_as_none():
    row = {"Const": "tt0018379", "URL": "https://www.imdb.com/title/tt0018379/",
           "Title": "X", "Original Title": "X", "Year": "2000", "Release Date": "",
           "Runtime (mins)": "", "IMDb Rating": "5.0", "Num Votes": "10",
           "Genres": "Drama", "Directors": "Someone", "Title Type": "Movie"}
    rec = ing.validate_and_normalize_row(row, "1")
    assert rec["runtime_minutes"] is None


@pytest.mark.parametrize("date_str", ["1936-02", "1927-10-30", "1936"])
def test_partial_and_full_dates_accepted(date_str):
    row = {"Const": "tt0018379", "URL": "https://www.imdb.com/title/tt0018379/",
           "Title": "X", "Original Title": "X", "Year": "2000", "Release Date": date_str,
           "Runtime (mins)": "90", "IMDb Rating": "5.0", "Num Votes": "10",
           "Genres": "Drama", "Directors": "Someone", "Title Type": "Movie"}
    rec = ing.validate_and_normalize_row(row, "1")
    assert rec["release_date"] == date_str


def test_malformed_date_rejected():
    row = {"Const": "tt0018379", "URL": "https://www.imdb.com/title/tt0018379/",
           "Title": "X", "Original Title": "X", "Year": "2000", "Release Date": "not-a-date",
           "Runtime (mins)": "90", "IMDb Rating": "5.0", "Num Votes": "10",
           "Genres": "Drama", "Directors": "Someone", "Title Type": "Movie"}
    with pytest.raises(ing.RowError):
        ing.validate_and_normalize_row(row, "1")


def test_genre_normalization_matches_existing_no_space_convention():
    assert ing.normalize_genres("Drama, Romance") == "Drama,Romance"
    assert ing.normalize_genres("Comedy") == "Comedy"
    assert ing.normalize_genres("") == ""


def test_multi_director_split_preserves_each_name():
    assert ing.normalize_directors("Fred Newmeyer, Sam Taylor") == ["Fred Newmeyer", "Sam Taylor"]
    assert ing.normalize_directors("Frank Borzage") == ["Frank Borzage"]


# --- Integration checks against the actual generated artifacts ------------

RAW_CSV = REPO_ROOT / "data" / "raw" / "imdb_best_picture_nominees_raw.csv"
NORMALIZED_CSV = REPO_ROOT / "data" / "raw" / "imdb_best_picture_nominees_normalized.csv"
DISPOSITIONS_CSV = REPO_ROOT / "data" / "raw" / "imdb_best_picture_nominees_row_dispositions.csv"
ORIGINAL_CSV = Path("/Users/friana/ReelWrangling/data/imdb/9944c2c8-05e3-400b-bf9f-ac375c33f9aa.csv")


@pytest.mark.skipif(not ORIGINAL_CSV.exists(), reason="original ReelWrangling CSV not available on this machine")
def test_raw_copy_is_byte_identical_to_supplied_csv():
    assert RAW_CSV.read_bytes() == ORIGINAL_CSV.read_bytes()


def test_raw_csv_has_expected_row_count():
    with RAW_CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 620


def test_normalized_csv_has_619_unique_films():
    with NORMALIZED_CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 619
    assert len({r["imdb_tconst"] for r in rows}) == 619


def test_dispositions_cover_every_raw_row_exactly_once():
    with DISPOSITIONS_CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 620
    positions = [r["source_position"] for r in rows]
    assert len(positions) == len(set(positions))


def test_casablanca_duplicate_recorded_as_duplicate_in_csv():
    with DISPOSITIONS_CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    casablanca = [r for r in rows if r["imdb_id"] == "tt0034583"]
    assert len(casablanca) == 2
    decisions = sorted(r["decision"] for r in casablanca)
    assert decisions == ["duplicate_in_csv", "ok"]
