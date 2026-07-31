"""
Yearly-poster resolution for the Criterion Over Time video's right-hand
panel. Reads ONLY the already-downloaded poster files in the sibling
ReelWrangling repo's data/posters/ directory (never downloads, generates, or
renames anything). Filenames there are "<year>_<slug>_<id>.<ext>"; a year
resolves to a poster iff exactly one file's name starts with that 4-digit
year.

1915-1928 are intentionally excluded from the video's poster years (per
spec) and are not reported as missing. Any 1929+ year with zero matching
files is "missing"; any year with more than one matching file is
"ambiguous" -- both are left with no poster on screen and are reported back
to the caller rather than guessed at.
"""

import re
import sys
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import cinematic_history_config as cfg  # noqa: E402

FILENAME_YEAR_RE = re.compile(r"^(\d{4})_")


def build_poster_index(end_year=None):
    """-> dict(resolved={year: Path}, ambiguous={year: [filenames]},
    missing=[year, ...]) for years POSTER_START_YEAR..end_year."""
    end_year = end_year if end_year is not None else cfg.END_YEAR
    by_year = defaultdict(list)
    if cfg.POSTER_SOURCE_DIR.is_dir():
        for f in sorted(cfg.POSTER_SOURCE_DIR.iterdir()):
            m = FILENAME_YEAR_RE.match(f.name)
            if m and f.is_file():
                by_year[int(m.group(1))].append(f)

    resolved = {}
    ambiguous = {}
    for y, files in by_year.items():
        if len(files) == 1:
            resolved[y] = files[0]
        else:
            ambiguous[y] = sorted(f.name for f in files)

    missing = [y for y in range(cfg.POSTER_START_YEAR, end_year + 1)
               if y not in resolved and y not in ambiguous]

    return dict(resolved=resolved, ambiguous=ambiguous, missing=missing)


def main():
    idx = build_poster_index()
    print(f"Poster source: {cfg.POSTER_SOURCE_DIR}")
    print(f"Resolved years: {len(idx['resolved'])}")
    if idx["ambiguous"]:
        print(f"\nAmbiguous years ({len(idx['ambiguous'])}) -- left blank on screen, not guessed:")
        for y, names in sorted(idx["ambiguous"].items()):
            print(f"  {y}: {names}")
    if idx["missing"]:
        print(f"\nMissing years from {cfg.POSTER_START_YEAR} onward ({len(idx['missing'])}):")
        print(f"  {idx['missing']}")


if __name__ == "__main__":
    main()
