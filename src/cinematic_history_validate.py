"""
Pre-render validation for the Criterion Over Time video.

Reads ONLY data/cinematic_history_hex_snapshot.json (itself a frozen extract
of the live site/explore.html, produced by cinematic_history_layout_snapshot.py)
and the DB tables needed to check film metadata. Writes ONLY
outputs/cinematic_history_validation_report.json. Never touches
site/explore.html, hex_grid.py, hex_svg.py, or any other shared file.

Approved, documented exceptions (do not re-flag these as failures -- they
were investigated and explicitly signed off on):

  - tt33381401 "The Love That Remains" and tt38060097 "Joan of Arc" (2025),
    both cluster european_art_cinema, are excluded from the video entirely.
    Root cause: hex_grid.py's own cluster_size-vs-hex-count reconciliation
    (fix_fragments()/rebalance_counts()) doesn't always converge exactly --
    its own code comment admits the final pass "can still introduce a hex or
    two" of drift. In the live site/explore.html, european_art_cinema has
    430 hexes for 432 real films. This was verified NOT to be a data-timing
    issue: db/criterion_graph.duckdb (mtime 2026-07-18) predates the site
    build that produced explore.html (mtime 2026-07-25) by a week, and both
    films are already correctly classified in that same build's
    films-data.js and european_art_cinema_rings.svg. Neither film has any
    hex or persisted position in the current hex graph, so neither is
    assigned one -- not excluded by guesswork, excluded because no hex for
    them exists.
  - The two hiddenGems hexes this leaves behind, (q=33, r=-14) and
    (q=34, r=-16), both outer-ring white (#FFFFFF), are kept as
    structural/background hexes with no film attached -- shown in their
    snapshot color from the start of the video, never part of the per-film
    reveal schedule.
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import duckdb

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
SNAPSHOT_PATH = REPO_ROOT / "data" / "cinematic_history_hex_snapshot.json"
DB_PATH = REPO_ROOT / "db" / "criterion_graph.duckdb"
REPORT_PATH = REPO_ROOT / "outputs" / "cinematic_history_validation_report.json"

# (tconst, title, cluster_id) -- approved 2026-07-26. Any OTHER unplaced film
# or unfilled hex found at validation time is a NEW, unreviewed exception and
# must fail loudly, not be silently absorbed into this list.
APPROVED_UNPLACED_FILMS = {
    ("tt33381401", "european_art_cinema"),
    ("tt38060097", "european_art_cinema"),
}
APPROVED_UNFILLED_HEXES = {
    (33, -14),
    (34, -16),
}


def load_snapshot():
    if not SNAPSHOT_PATH.exists():
        sys.exit(f"ERROR: {SNAPSHOT_PATH} not found -- run cinematic_history_layout_snapshot.py first.")
    return json.loads(SNAPSHOT_PATH.read_text())


def check_hex_integrity(snapshot, findings):
    hexes = snapshot["hexes"]
    qrs = [(h["q"], h["r"]) for h in hexes]
    dupes = [qr for qr, n in Counter(qrs).items() if n > 1]
    if dupes:
        findings["fatal"].append(f"{len(dupes)} duplicate (q, r) hex coordinate(s) in the snapshot: {dupes[:10]}")

    tconsts = [h["tconst"] for h in hexes if h["tconst"]]
    tconst_hex_count = Counter(tconsts)
    # A film occupying >1 hex is only valid if the DB itself has multiple
    # cluster_assignments rows for that one tconst (the Carlos: Part 1/2/3 /
    # K-ON! style catalog duplicates) -- checked below against the DB, not
    # assumed here.
    findings["info"]["films_on_multiple_hexes"] = {t: n for t, n in tconst_hex_count.items() if n > 1}

    per_cluster = Counter(h["cluster_id"] for h in hexes)
    findings["info"]["hexes_per_cluster"] = dict(sorted(per_cluster.items()))

    white = sum(1 for h in hexes if h["cluster_id"] == "hiddenGems" and h["is_hidden_gems_outer"])
    gray = sum(1 for h in hexes if h["cluster_id"] == "hiddenGems" and h["is_hidden_gems_outer"] is False)
    findings["info"]["hidden_gems_outer_white_hexes"] = white
    findings["info"]["hidden_gems_inner_gray_hexes"] = gray


def check_unplaced_films(snapshot, findings):
    unplaced = snapshot.get("unplaced_films", [])
    unexpected = [f for f in unplaced if (f["tconst"], f["cluster_id"]) not in APPROVED_UNPLACED_FILMS]
    approved_found = [f for f in unplaced if (f["tconst"], f["cluster_id"]) in APPROVED_UNPLACED_FILMS]

    if unexpected:
        findings["fatal"].append(
            f"{len(unexpected)} unplaced film(s) are NOT on the approved exception list -- "
            f"stop and get explicit sign-off before excluding them: {unexpected}"
        )
    missing_approved = APPROVED_UNPLACED_FILMS - {(f["tconst"], f["cluster_id"]) for f in unplaced}
    if missing_approved:
        # Not fatal -- if a future data/site refresh happens to make room for
        # these two, that's a welcome change, just worth surfacing.
        findings["info"]["previously_approved_exceptions_no_longer_present"] = sorted(missing_approved)

    findings["exceptions"]["unplaced_films"] = [
        dict(**f, status="APPROVED 2026-07-26 -- pre-existing hex-count reconciliation exception, "
                          "not a data-timing issue (see module docstring)")
        for f in approved_found
    ]


def check_unfilled_hexes(snapshot, findings):
    unfilled = snapshot.get("unfilled_hexes", [])
    unexpected = [h for h in unfilled if (h["q"], h["r"]) not in APPROVED_UNFILLED_HEXES]
    approved_found = [h for h in unfilled if (h["q"], h["r"]) in APPROVED_UNFILLED_HEXES]

    if unexpected:
        findings["fatal"].append(
            f"{len(unexpected)} unfilled hex(es) are NOT on the approved exception list: {unexpected}"
        )

    findings["exceptions"]["unfilled_hexes"] = [
        dict(**h, status="APPROVED 2026-07-26 -- kept as a structural/background hex with no film "
                          "attached, shown in its snapshot color from the start")
        for h in approved_found
    ]


def check_film_metadata(snapshot, findings):
    tconsts = sorted({h["tconst"] for h in snapshot["hexes"] if h["tconst"]})
    con = duckdb.connect(str(DB_PATH), read_only=True)
    df = con.execute("""
        SELECT * FROM (
            SELECT imdb_tconst, title, criterion_year, criterion_director, criterion_country,
                   row_number() OVER (
                       PARTITION BY imdb_tconst ORDER BY confidence_score DESC NULLS LAST
                   ) AS rn
            FROM criterion_basic_info
            WHERE imdb_tconst IN ({})
        ) WHERE rn = 1
    """.format(",".join(f"'{t}'" for t in tconsts))).df()

    # Cross-check: is every "film occupies >1 hex" case actually backed by
    # >1 raw catalog row for that tconst? Two different tables can cause
    # this, and both are legitimate (not a new snapshot-assignment bug):
    #   - cluster_assignments having >1 row for a tconst (would duplicate it
    #     within a NAMED cluster's film list).
    #   - criterion_basic_info having >1 row for a tconst that has NO
    #     cluster_assignments row at all (e.g. "Carlos: Part 1/2/3", "K-ON!"
    #     under two title variants) -- these feed the no-actor/hiddenGems
    #     path, which has no DISTINCT, so the same tconst is pulled in once
    #     per catalog row and lands on that many hiddenGems hexes. This is
    #     already true of the live site itself (hex_grid.py's own
    #     cluster_films/no_actor_df has the identical characteristic), not
    #     something this snapshot introduced.
    ca_counts = con.execute("""
        SELECT imdb_tconst, count(*) AS n FROM cluster_assignments
        WHERE imdb_tconst IN ({0})
        GROUP BY imdb_tconst HAVING count(*) > 1
    """.format(",".join(f"'{t}'" for t in tconsts))).df()
    cbi_counts = con.execute("""
        SELECT imdb_tconst, count(*) AS n FROM criterion_basic_info
        WHERE imdb_tconst IN ({0})
          AND imdb_tconst NOT IN (SELECT imdb_tconst FROM cluster_assignments)
        GROUP BY imdb_tconst HAVING count(*) > 1
    """.format(",".join(f"'{t}'" for t in tconsts))).df()
    con.close()

    expected_multi = set(ca_counts["imdb_tconst"]) | set(cbi_counts["imdb_tconst"])
    actual_multi = set(findings["info"]["films_on_multiple_hexes"])
    unexplained_multi = actual_multi - expected_multi
    if unexplained_multi:
        findings["fatal"].append(
            f"{len(unexplained_multi)} film(s) occupy multiple hexes with no matching multi-row "
            f"cluster_assignments explanation -- possible new snapshot-assignment bug: {sorted(unexplained_multi)}"
        )

    by_tconst = df.set_index("imdb_tconst").to_dict("index")
    missing_year = [t for t in tconsts if t not in by_tconst or by_tconst[t]["criterion_year"] is None]
    if missing_year:
        findings["fatal"].append(f"{len(missing_year)} placed film(s) have no valid criterion_year: {missing_year}")

    missing_meta = [t for t in tconsts if t not in by_tconst]
    if missing_meta:
        findings["fatal"].append(f"{len(missing_meta)} placed film(s) have no metadata row at all: {missing_meta}")

    findings["info"]["placed_film_count"] = len(tconsts)
    findings["info"]["year_range"] = [
        min(r["criterion_year"] for r in by_tconst.values() if r["criterion_year"] is not None),
        max(r["criterion_year"] for r in by_tconst.values() if r["criterion_year"] is not None),
    ] if by_tconst else None


def check_geometry_verification(snapshot, findings):
    gv = snapshot.get("geometry_verification")
    if not gv or not gv.get("ok"):
        findings["fatal"].append(f"geometry_verification failed or missing in snapshot: {gv}")
    else:
        findings["info"]["geometry_verification"] = gv


def main():
    snapshot = load_snapshot()
    findings = dict(fatal=[], info={}, exceptions={})

    check_hex_integrity(snapshot, findings)
    check_unplaced_films(snapshot, findings)
    check_unfilled_hexes(snapshot, findings)
    check_film_metadata(snapshot, findings)
    check_geometry_verification(snapshot, findings)

    findings["ok"] = (len(findings["fatal"]) == 0)

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(findings, indent=2, default=str))

    print(f"Report -> {REPORT_PATH}\n")
    print(f"Hexes per cluster: {findings['info']['hexes_per_cluster']}")
    print(f"hiddenGems outer/white: {findings['info']['hidden_gems_outer_white_hexes']}  "
          f"inner/gray: {findings['info']['hidden_gems_inner_gray_hexes']}")
    print(f"Placed films: {findings['info']['placed_film_count']}  "
          f"year range: {findings['info']['year_range']}")
    print(f"Geometry verification: {findings['info'].get('geometry_verification')}")
    if findings["info"]["films_on_multiple_hexes"]:
        print(f"Films on multiple hexes (expected -- catalog duplicates): "
              f"{findings['info']['films_on_multiple_hexes']}")
    print(f"\nApproved exceptions:")
    for f in findings["exceptions"]["unplaced_films"]:
        print(f"  UNPLACED FILM: {f['tconst']} \"{f['title']}\" ({f['cluster_id']}) -- {f['status']}")
    for h in findings["exceptions"]["unfilled_hexes"]:
        print(f"  UNFILLED HEX: (q={h['q']}, r={h['r']}) {h['cluster_id']} {h['fill']} -- {h['status']}")

    if findings["fatal"]:
        print(f"\nFATAL ({len(findings['fatal'])}):")
        for f in findings["fatal"]:
            print(f"  - {f}")
        sys.exit(1)
    print("\nValidation OK.")


if __name__ == "__main__":
    main()
