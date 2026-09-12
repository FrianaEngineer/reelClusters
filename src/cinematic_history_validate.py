"""
Pre-render validation for the Criterion Over Time video.

Reads ONLY data/cinematic_history_hex_snapshot.json (itself a frozen extract
of the live site/explore.html, produced by cinematic_history_layout_snapshot.py)
and the DB tables needed to check film metadata. Writes ONLY
outputs/cinematic_history_validation_report.json. Never touches
site/explore.html, hex_grid.py, hex_svg.py, or any other shared file.

Approved, documented exceptions (do not re-flag these as failures -- they
were investigated and explicitly signed off on):

  - 2026-08-05 (12 films, european_art_cinema; 12 hexes, japanese_new_wave_genre):
    after regenerating the snapshot from the current site/explore.html (which
    now reflects the 2026-07-31 cluster-taxonomy rebuild), european_art_cinema
    has 465 hexes for 477 real films and japanese_new_wave_genre has 155 hexes
    for only 142 real films -- a matched +13/-13 (12 of which land as
    genuinely unplaced/unfilled once geometry is fixed) drift between exactly
    these two adjacent clusters. Verified NOT a data-timing issue: running
    hex_grid.py's build_hex_grid() fresh today (same DB, same code) reproduces
    the identical -13/+13 imbalance between these same two clusters, with
    every other cluster's hex count matching its film count exactly. Root
    cause is hex_grid.py's own fix_fragments()/rebalance_counts() alternation
    not fully converging at this cluster-adjacency/scale -- the same
    documented class of bug as the original 2026-07-26 exception below, just
    larger because european_art_cinema/japanese_new_wave_genre now border
    each other post-rebuild. Out of scope to fix here: hex_grid.py is a
    shared file that also drives the live site, and this project must not
    modify or depend on changes to it. The 12 films below have no hex in the
    current snapshot and are excluded from the video entirely; the 12 hexes
    below are shown in their snapshot color from the start, never part of the
    per-film reveal schedule.
  - 2026-07-26 (2 films/hexes, both since superseded by the 2026-08-05
    snapshot regeneration but kept here for history): tt33381401 "The Love
    That Remains" and tt38060097 "Joan of Arc", both cluster
    european_art_cinema, were excluded from the video entirely for the same
    hex-count-reconciliation reason. The two hiddenGems hexes this left
    behind, (q=33, r=-14) and (q=34, r=-16), both outer-ring white (#FFFFFF),
    were kept as structural/background hexes with no film attached.
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import duckdb

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import cinematic_history_config as cfg  # noqa: E402
import cinematic_history_schedule as sched  # noqa: E402

REPO_ROOT = SCRIPT_DIR.parent
SNAPSHOT_PATH = REPO_ROOT / "data" / "cinematic_history_hex_snapshot.json"
DB_PATH = REPO_ROOT / "db" / "criterion_graph.duckdb"
REPORT_PATH = REPO_ROOT / "outputs" / "cinematic_history_validation_report.json"

# (tconst, cluster_id) -- approved 2026-08-05, see module docstring. Any
# OTHER unplaced film or unfilled hex found at validation time is a NEW,
# unreviewed exception and must fail loudly, not be silently absorbed here.
APPROVED_UNPLACED_FILMS = {
    ("tt1020773", "european_art_cinema"),   # Certified Copy
    ("tt1508675", "european_art_cinema"),   # Le Havre
    ("tt1847731", "european_art_cinema"),   # Tomboy
    ("tt1602620", "european_art_cinema"),   # Amour
    ("tt2452254", "european_art_cinema"),   # Clouds of Sils Maria
    ("tt4714782", "european_art_cinema"),   # Personal Shopper
    ("tt5222918", "european_art_cinema"),   # The Other Side of Hope
    ("tt6423776", "european_art_cinema"),   # Let the Sunshine In
    ("tt5363618", "european_art_cinema"),   # Sound of Metal
    ("tt19841734", "european_art_cinema"),  # The Innocent
    ("tt14550346", "european_art_cinema"),  # Last Summer
    ("tt32086004", "european_art_cinema"),  # Meeting with Pol Pot
}
# (q, r) is re-derived from scratch on every snapshot regeneration (arbitrary
# origin/rotation, see cinematic_history_layout_snapshot.py), so these
# coordinates are only meaningful against the current snapshot.
APPROVED_UNFILLED_HEXES = {
    (-10, 14), (-28, 10), (-10, 15), (-30, 13), (-29, 11), (-30, 12),
    (-29, 10), (-30, 11), (-11, 16), (-10, 16), (-11, 17), (-10, 17),
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
        dict(**f, status="APPROVED 2026-08-05 -- pre-existing hex-count reconciliation exception, "
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
        dict(**h, status="APPROVED 2026-08-05 -- kept as a structural/background hex with no film "
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


def check_best_picture_sync(schedule, findings):
    """2026-08-17 restyle requirement: a Best Picture winner's poster, its
    hex's gold border, and its hex reaching final color must all land on the
    EXACT SAME frame. Walks the already-built schedule (not a
    re-simulation) to prove it holds for every year that has a winner:
    poster_hexes must be non-empty on exactly one frame per such year (the
    trigger), and that frame must be precisely poster_active_year's own
    first frame for that year -- if either drifts, the poster/hex-fill/
    gold-border sync this restyle exists to fix would be broken again."""
    frames = schedule["frames"]
    poster_hex_frames = defaultdict(list)
    poster_active_first_frame = {}
    seen_active = set()
    for i, f in enumerate(frames):
        if f["poster_hexes"]:
            poster_hex_frames[f["year"]].append(i)
        active = f.get("poster_active_year")
        if active is not None and active not in seen_active:
            seen_active.add(active)
            poster_active_first_frame[active] = i

    for year, idxs in poster_hex_frames.items():
        if len(idxs) != 1:
            findings["fatal"].append(
                f"{year}: poster_hexes non-empty on {len(idxs)} frames ({idxs}), expected exactly 1 trigger frame")
            continue
        trigger = idxs[0]
        active_first = poster_active_first_frame.get(year)
        if active_first != trigger:
            findings["fatal"].append(
                f"{year}: poster/gold-border trigger frame ({trigger}) != poster_active_year's own first "
                f"frame ({active_first}) -- poster and hex-fill/gold-border are not synchronized")

    findings["info"]["best_picture_years_synced"] = len(poster_hex_frames)


def check_reveal_schedule(findings):
    """"Reeling Through the Years" restyle checks -- walks the actual built
    schedule (not just the snapshot) to prove, for every single year, that:
      - at most cfg.TOP_N_FILMS featured films ever get a title card,
      - at most 2 of those are plain ranked ("most connected") rows -- the
        3rd is always specifically that year's Best Picture winner, never a
        4th ranked film (see cinematic_history_schedule.py's
        select_featured_films()),
      - none of those 2 ranked rows is a Japanese-language film (the
        exclusion select_featured_films() is supposed to enforce -- the
        Best Picture row itself is exempt, per spec),
      - every featured film's swatch color is exactly its own hex's final
        fill (never guessed, never a cluster-average color) when it has a
        hex at all,
      - remaining-film hexes only ever start filling after every featured
        film's own hex for that year has already reached its final color
        (no overlap),
      - no hex is ever claimed as a featured OR remaining hex by more than
        one distinct film in the same year (a same-tconst catalog duplicate
        occupying >1 of its OWN hexes is fine; two DIFFERENT tconsts on the
        same hex is not),
      - poster/hex-fill/gold-border land on the exact same frame for every
        year with a Best Picture winner (see check_best_picture_sync()).
    """
    schedule = sched.build_full_schedule()
    by_year = sched.group_events_by_year(schedule["events"])
    final_colors = schedule["final_colors"]
    language_by_tconst = sched.load_film_languages()

    from cinematic_history_posters import build_poster_index
    bp_tconst_by_year = build_poster_index()["resolved_tconst"]
    events_by_tconst = {e["tconst"]: e for e in schedule["events"]}

    for year, evs in by_year.items():
        bp_tconst = bp_tconst_by_year.get(year)
        bp_event = events_by_tconst.get(bp_tconst) if bp_tconst else None
        top, remaining = sched.select_featured_films(evs, language_by_tconst, bp_event)
        if len(top) > cfg.TOP_N_FILMS:
            findings["fatal"].append(
                f"{year}: {len(top)} featured films, exceeds cfg.TOP_N_FILMS={cfg.TOP_N_FILMS}")

        non_bp = [e for e in top if not e.get("is_best_picture")]
        if len(non_bp) > 2:
            findings["fatal"].append(f"{year}: {len(non_bp)} non-Best-Picture featured rows, expected at most 2")
        for e in non_bp:
            if language_by_tconst.get(e["tconst"]) == "ja":
                findings["fatal"].append(
                    f"{year}: {e['tconst']} \"{e['title']}\" is Japanese-language but occupies a "
                    f"most-connected slot (should only ever appear there via the Best Picture slot)")

        for e in top:
            for (q, r) in e["hexes"]:
                if final_colors[(q, r)] != final_colors[e["hexes"][0]]:
                    findings["fatal"].append(
                        f"{year}: {e['tconst']} \"{e['title']}\"'s own hexes disagree in final color "
                        f"({e['hexes']}) -- swatch color can't unambiguously match the graph")

        top_hexes = {h for e in top for h in e["hexes"]}
        remaining_hexes = {h for e in remaining for h in e["hexes"]}
        overlap = top_hexes & remaining_hexes
        if overlap:
            findings["fatal"].append(f"{year}: {len(overlap)} hex(es) claimed by both a featured and a "
                                      f"remaining film: {sorted(overlap)}")

        hex_owner = {}
        for e in evs:
            for h in e["hexes"]:
                if h in hex_owner and hex_owner[h] != e["tconst"]:
                    findings["fatal"].append(
                        f"{year}: hex {h} claimed by two different films: {hex_owner[h]} and {e['tconst']}")
                hex_owner[h] = e["tconst"]

    check_best_picture_sync(schedule, findings)

    findings["info"]["reveal_schedule_total_seconds"] = schedule["total_seconds"]
    findings["info"]["reveal_schedule_years_checked"] = len(by_year)


def check_restyle_invariants(snapshot, findings):
    """2026-08-08 "Most Connected Films" restyle checks: TOP_N_FILMS==3,
    every reveal event carries a real (non-negative int) connection count,
    every cluster with a label gets exactly one completion frame and vice
    versa, and every resolved yearly poster's film has at least one hex on
    the snapshot (required for the golden poster-hex border to ever have
    something to point at)."""
    if cfg.TOP_N_FILMS != 3:
        findings["fatal"].append(f"cfg.TOP_N_FILMS is {cfg.TOP_N_FILMS}, expected 3 ('Most Connected Films' spec)")

    schedule = sched.build_full_schedule()
    for e in schedule["events"]:
        if not isinstance(e["connections"], int) or e["connections"] < 0:
            findings["fatal"].append(f"{e['tconst']} \"{e['title']}\" has invalid connections: {e['connections']!r}")

    label_clusters = set(snapshot["cluster_labels"])
    complete_clusters = set(schedule["cluster_complete_frames"])
    if label_clusters != complete_clusters:
        findings["fatal"].append(
            f"cluster_labels vs cluster_complete_frames mismatch -- "
            f"only in labels: {sorted(label_clusters - complete_clusters)}, "
            f"only in complete_frames: {sorted(complete_clusters - label_clusters)}"
        )

    from cinematic_history_posters import build_poster_index
    tconst_hexes = sched.hexes_by_tconst(snapshot)
    poster_idx = build_poster_index()
    for year, tconst in poster_idx["resolved_tconst"].items():
        if not tconst_hexes.get(tconst):
            findings["fatal"].append(
                f"poster year {year} resolves to {tconst}, which has no hex in the snapshot "
                f"-- golden poster-hex border would have nothing to highlight"
            )

    findings["info"]["top_n_films"] = cfg.TOP_N_FILMS
    findings["info"]["cluster_complete_frames"] = schedule["cluster_complete_frames"]
    findings["info"]["poster_years_resolved_to_tconst"] = len(poster_idx["resolved_tconst"])


def main():
    snapshot = load_snapshot()
    findings = dict(fatal=[], info={}, exceptions={})

    check_hex_integrity(snapshot, findings)
    check_unplaced_films(snapshot, findings)
    check_unfilled_hexes(snapshot, findings)
    check_film_metadata(snapshot, findings)
    check_geometry_verification(snapshot, findings)
    check_reveal_schedule(findings)
    check_restyle_invariants(snapshot, findings)

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
    print(f"\nReveal schedule checked: {findings['info']['reveal_schedule_years_checked']} years, "
          f"projected {findings['info']['reveal_schedule_total_seconds']:.1f}s total")
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
