"""
Best Picture winner poster resolution for the "Reeling Through the Years"
video's right-hand panel (every poster in POSTER_SOURCE_DIR is a Best
Picture winner -- see build_best_picture_winners.py / get_poster.py in the
sibling repo). Reads ONLY the already-downloaded poster files in the
sibling ReelWrangling repo's data/posters/ directory (never downloads,
generates, or renames anything). Filenames there are
"<ceremonyYear>_<slug>_<tmdbId>.<ext>".

2026-08-17: re-keyed by the film's own criterion_year (looked up in
db/criterion_graph.duckdb) instead of the Oscar ceremony year baked into
the filename. The ceremony happens up to ~2 years after a film's actual
release (e.g. "1929_wings..." for *Wings*, a 1927 film) -- keying by
ceremony year meant the poster/gold-border showed up years after that
film's own hex had already filled in cinematic_history_schedule.py (which
schedules everything by criterion_year). Keying by criterion_year instead
makes the poster, its hex's gold border, and its dedicated "Best Picture
winner" row all land in the exact same year -- see cinematic_history_
animation.py/cinematic_history_schedule.py.

A ceremony-year file with more than one match, or whose tconst/criterion_year
can't be resolved, is left with no poster on screen and reported back to the
caller rather than guessed at -- same "never guess" policy as before, just
applied at the (now two-step) resolution.
"""

import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

import duckdb

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import cinematic_history_config as cfg  # noqa: E402

DB_PATH = cfg.REPO_ROOT / "db" / "criterion_graph.duckdb"
DETAILS_CSV_PATH = cfg.REPO_ROOT / "data" / "best_picture_winner_details.csv"

FILENAME_YEAR_RE = re.compile(r"^(\d{4})_")
# "<ceremonyYear>_<slug>_<tmdbId>.<ext>" -- exactly get_poster.py's own
# `filename = f"{year_seg}_{slug}_{tmdb_id}{ext}"` naming, read back out.
FILENAME_YEAR_TMDB_RE = re.compile(r"^(\d{4})_.*_(\d+)\.\w+$")

# Read-only source of the (ceremonyYear, tmdbId) -> imdbId mapping these
# posters were downloaded from -- same sibling-repo, same "read only, never
# generated here" boundary as POSTER_SOURCE_DIR itself. Used only to attach
# the exact imdb_tconst a displayed poster represents (for the golden
# poster-hex border and the criterion_year re-keying), never to select/
# download/rename a poster file.
POSTER_QUERY_CSV_PATH = cfg.REPO_ROOT.parent / "ReelWrangling" / "data" / "output" / "query.csv"


def load_poster_tconsts():
    """-> {(ceremony_year_str, tmdb_id_str): imdb_tconst}."""
    mapping = {}
    if not POSTER_QUERY_CSV_PATH.exists():
        return mapping
    with POSTER_QUERY_CSV_PATH.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            year, tmdb, imdb = row.get("ceremonyYear"), row.get("tmdbId"), row.get("imdbId")
            if year and tmdb and imdb:
                mapping[(year, tmdb)] = imdb
    return mapping


def load_criterion_years(tconsts):
    """tconst -> int criterion_year, for exactly the given tconsts (the
    same year cinematic_history_schedule.py's build_reveal_events() buckets
    that film's own hex-fill event under)."""
    if not tconsts:
        return {}
    con = duckdb.connect(str(DB_PATH), read_only=True)
    df = con.execute("""
        SELECT imdb_tconst, criterion_year FROM (
            SELECT imdb_tconst, criterion_year,
                   row_number() OVER (
                       PARTITION BY imdb_tconst ORDER BY confidence_score DESC NULLS LAST
                   ) AS rn
            FROM criterion_basic_info WHERE imdb_tconst IN ({})
        ) WHERE rn = 1
    """.format(",".join(f"'{t}'" for t in tconsts))).df()
    con.close()
    return {t: int(y) for t, y in zip(df["imdb_tconst"], df["criterion_year"]) if y is not None}


def load_director_by_tconst(tconsts):
    if not tconsts:
        return {}
    con = duckdb.connect(str(DB_PATH), read_only=True)
    df = con.execute("""
        SELECT imdb_tconst, criterion_director FROM (
            SELECT imdb_tconst, criterion_director,
                   row_number() OVER (
                       PARTITION BY imdb_tconst ORDER BY confidence_score DESC NULLS LAST
                   ) AS rn
            FROM criterion_basic_info WHERE imdb_tconst IN ({})
        ) WHERE rn = 1
    """.format(",".join(f"'{t}'" for t in tconsts))).df()
    con.close()
    return dict(zip(df["imdb_tconst"], df["criterion_director"]))


def load_winner_details():
    """tconst -> {studio, release_date}, from data/best_picture_winner_
    details.csv (built by build_best_picture_details.py, TMDB-sourced --
    neither field exists anywhere else in this project's own data)."""
    details = {}
    if not DETAILS_CSV_PATH.exists():
        return details
    with DETAILS_CSV_PATH.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("studio") and row.get("release_date"):
                details[row["imdb_tconst"]] = dict(studio=row["studio"], release_date=row["release_date"])
    return details


def build_poster_index(end_year=None):
    """-> dict(resolved={year: Path}, resolved_tconst={year: imdb_tconst},
    details={year: {director, studio, release_date}}, ambiguous={key: [...]},
    missing=[year, ...], unkeyed=[(ceremony_year, filename), ...]).

    `year` throughout is the film's own criterion_year (see module
    docstring), not the ceremony year. `ambiguous` holds both a ceremony
    year with more than one matching file, and a criterion_year that two
    different ceremony-year posters would otherwise collide on (both left
    blank on screen rather than guessed at). `unkeyed` is a resolved poster
    whose tconst has no criterion_year in the DB -- doesn't happen for any
    of the current winners, handled for correctness."""
    end_year = end_year if end_year is not None else cfg.END_YEAR
    by_ceremony_year = defaultdict(list)
    if cfg.POSTER_SOURCE_DIR.is_dir():
        for f in sorted(cfg.POSTER_SOURCE_DIR.iterdir()):
            m = FILENAME_YEAR_RE.match(f.name)
            if m and f.is_file():
                by_ceremony_year[int(m.group(1))].append(f)

    ambiguous = {}
    candidates = []  # (ceremony_year, path) -- exactly one file for that ceremony year
    for cy, files in by_ceremony_year.items():
        if len(files) == 1:
            candidates.append((cy, files[0]))
        else:
            ambiguous[cy] = sorted(f.name for f in files)

    tconst_by_key = load_poster_tconsts()
    resolved_by_ceremony = {}  # ceremony_year -> (tconst, path)
    for cy, path in candidates:
        m = FILENAME_YEAR_TMDB_RE.match(path.name)
        if m:
            tconst = tconst_by_key.get((str(cy), m.group(2)))
            if tconst:
                resolved_by_ceremony[cy] = (tconst, path)

    criterion_years = load_criterion_years([t for t, _ in resolved_by_ceremony.values()])

    by_final_year = defaultdict(list)  # criterion_year -> [(ceremony_year, tconst, path)]
    unkeyed = []
    for cy, (tconst, path) in resolved_by_ceremony.items():
        year = criterion_years.get(tconst)
        if year is None:
            unkeyed.append((cy, path.name))
        else:
            by_final_year[year].append((cy, tconst, path))

    resolved = {}
    resolved_tconst = {}
    for year, entries in by_final_year.items():
        if len(entries) == 1:
            _, tconst, path = entries[0]
            resolved[year] = path
            resolved_tconst[year] = tconst
        else:
            ambiguous[year] = sorted(f"{path.name} (ceremony {cy})" for cy, _, path in entries)

    poster_start_year = min(resolved) if resolved else cfg.POSTER_START_YEAR
    missing = [y for y in range(poster_start_year, end_year + 1)
               if y not in resolved and y not in ambiguous]

    winner_details = load_winner_details()
    director_by_tconst = load_director_by_tconst(list(resolved_tconst.values()))
    details = {}
    for year, tconst in resolved_tconst.items():
        d = winner_details.get(tconst, {})
        details[year] = dict(director=director_by_tconst.get(tconst),
                              studio=d.get("studio"), release_date=d.get("release_date"))

    return dict(resolved=resolved, resolved_tconst=resolved_tconst, details=details,
                ambiguous=ambiguous, missing=missing, unkeyed=unkeyed)


def main():
    idx = build_poster_index()
    print(f"Poster source: {cfg.POSTER_SOURCE_DIR}")
    print(f"Resolved years (keyed by criterion_year): {len(idx['resolved'])}")
    if idx["ambiguous"]:
        print(f"\nAmbiguous ({len(idx['ambiguous'])}) -- left blank on screen, not guessed:")
        for y, names in sorted(idx["ambiguous"].items()):
            print(f"  {y}: {names}")
    if idx["unkeyed"]:
        print(f"\nUnkeyed posters -- resolved tconst has no criterion_year ({len(idx['unkeyed'])}):")
        for cy, name in idx["unkeyed"]:
            print(f"  ceremony {cy}: {name}")
    if idx["missing"]:
        print(f"\nMissing years ({len(idx['missing'])}):")
        print(f"  {idx['missing']}")


if __name__ == "__main__":
    main()
