"""
Builds a frozen, video-only snapshot of the hex layout currently displayed by
site/explore.html, and assigns each cluster's real films to that exact,
unchanged set of hex positions.

Why this exists (do not delete/bypass it): build_hex_grid() computes a fresh
hex-to-cluster layout from scratch, and a since-fixed bug in it meant that
computation wasn't reproducible run-to-run -- re-running it after the fix
produces a *different*, though equally valid, cluster layout than the one
already baked into the live site/explore.html (~22% of hexes land in a
different cluster). Regenerating the live site to match the fixed algorithm
was explicitly ruled out (out of scope, changes what's already published) --
so the cinematic-history video must instead reuse EXACTLY the layout already
on screen at site/explore.html, not recompute one.

What IS and ISN'T recoverable from site/explore.html:
  - Hex position, which cluster owns it, and its exact displayed fill color
    (base color / darkened black-and-white variant / hiddenGems outer-white
    vs inner-gray ring) -- all literally present in the SVG and extracted
    here exactly as shown.
  - Axial (q, r) coordinates -- not stored in the SVG (only pixel corner
    points survive), so reconstructed here from the pixel geometry itself by
    matching the same six fixed neighbor-offset vectors hex_grid.py's own
    (read-only, unmodified) axial_to_pixel() defines. This recovers a fully
    self-consistent axial grid for the *same physical layout* (up to an
    arbitrary rotation/origin choice in the (q, r) labeling, which has no
    visual or functional effect) -- needed so this project's own,
    Criterion-Over-Time-specific geometry helpers (outer-border tracing,
    adjacency) have integer coordinates to work with, without touching
    hex_grid.py itself. verify_geometry_equivalence() below re-derives pixel
    positions from these reconstructed coordinates and checks them against
    the original parsed centroids to confirm the reconstruction didn't
    introduce a labeling error (e.g. an accidental reflection).
  - WHICH SPECIFIC FILM sits in which hex -- never encoded in the SVG at all
    (a hex only carries its fill color, not a film id), so this is
    reconstructed rather than read: oldest-to-newest films are paired with
    nearest-to-farthest-from-centroid hexes, the same rule hex_grid.py
    documents, applied only to this cluster's already-fixed set of live hex
    positions. A film's cluster membership is unaffected either way -- that
    always comes straight from the cluster_assignments table, never from the
    geometry algorithm. What this reconstruction does NOT guarantee is
    reproducing which exact hex any one SPECIFIC same-year cluster-mate
    landed on in whatever now-unrecoverable run originally built the live
    site -- that pairing was never persisted anywhere (only the aggregate
    fill pattern survives, not per-hex film identity), so ties among
    same-year films within a cluster get a new, deterministic tie-break here
    rather than reproducing an untraceable old one. This is a narrative
    (which card is attached to which hex) concern only, not a visual one:
    every hex's PERMANENT displayed color, once revealed, is taken directly
    from the fill this module reads off the live SVG -- never recomputed from
    whichever film ends up narratively attached to it -- so the final frame
    still matches site/explore.html exactly regardless of this ambiguity.
"""

import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import duckdb
import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from hex_grid import S3  # noqa: E402
from cluster_colors import COLOR_MAP  # noqa: E402

# Criterion-Over-Time-specific constant (matches hex_svg.py's own page
# background literal) -- not read from cluster_colors.py, which this project
# must not modify.
PAGE_BACKGROUND_COLOR = "#12121f"

REPO_ROOT = SCRIPT_DIR.parent
EXPLORE_HTML_PATH = REPO_ROOT / "site" / "explore.html"
DB_PATH = REPO_ROOT / "db" / "criterion_graph.duckdb"
SNAPSHOT_PATH = REPO_ROOT / "data" / "cinematic_history_hex_snapshot.json"

HEX_SIZE = 1.0
SVG_NS = "{http://www.w3.org/2000/svg}"

# Neighbor direction -> pixel offset in the SVG's flipped (y-down) frame.
# hex_grid.axial_to_pixel() gives offsets in the ORIGINAL y-up frame; hex_svg's
# flip() maps (x, y) -> (x - x_min, y_max - y), an isometry whose effect on any
# displacement is simply (dx, dy) -> (dx, -dy). These are that transform
# applied to axial_to_pixel(*direction, HEX_SIZE) for each of the 6 directions.
_FLIPPED_OFFSETS = {
    (1, 0):  (S3, 0.0),
    (-1, 0): (-S3, 0.0),
    (0, 1):  (S3 / 2, -1.5),
    (0, -1): (-S3 / 2, 1.5),
    (1, -1): (S3 / 2, 1.5),
    (-1, 1): (-S3 / 2, -1.5),
}
_MATCH_TOL = 0.05   # SVG coordinates are printed to 2 decimals


def parse_explore_svg(path=EXPLORE_HTML_PATH):
    """-> (hexes, cluster_labels).

    hexes: list of dicts {cluster_id, fill, centroid (x, y), points}.
    cluster_labels: {cluster_id: {x, y, fontsize, on_dark, lines}} -- the
    exact <text>/<tspan> markup hex_svg.py wrote for that cluster's on-graph
    label (position, size, color class, wrapped line text), still in the raw
    SVG (flipped, y-down) pixel frame at this point.
    """
    html = path.read_text()
    svg_text = re.search(r"(<svg.*</svg>)", html, re.S).group(1)
    root = ET.fromstring(svg_text)

    hexes = []
    cluster_labels = {}
    for a in root.findall(f"{SVG_NS}a"):
        cluster_id = a.get("href").removeprefix("clusters/").removesuffix(".html")
        g = a.find(f"{SVG_NS}g")
        if g is None:
            text = a.find(f"{SVG_NS}text")
            if text is not None:
                cls = text.get("class", "")
                lines = [(ts.text or "") for ts in text.findall(f"{SVG_NS}tspan")]
                cluster_labels[cluster_id] = dict(
                    x=float(text.get("x")), y=float(text.get("y")),
                    fontsize=float(text.get("font-size")),
                    on_dark="on-dark" in cls, lines=lines,
                )
            continue   # this <a> wraps a <text> label, not a hex group
        for poly in g.findall(f"{SVG_NS}polygon"):
            pts = [tuple(map(float, p.split(","))) for p in poly.get("points").split()]
            cx = sum(p[0] for p in pts) / len(pts)
            cy = sum(p[1] for p in pts) / len(pts)
            hexes.append(dict(cluster_id=cluster_id, fill=poly.get("fill"), centroid=(cx, cy)))
    return hexes, cluster_labels


def reconstruct_axial_coords(hexes):
    """Assigns a self-consistent (q, r) to every parsed hex by BFS-matching
    the six known neighbor-offset vectors against actual pixel centroids.
    Mutates each hex dict in place, adding "qr"."""
    by_round = {}
    for i, h in enumerate(hexes):
        key = (round(h["centroid"][0], 2), round(h["centroid"][1], 2))
        by_round[key] = i

    def find_neighbor(cx, cy, offset):
        target = (cx + offset[0], cy + offset[1])
        # Exact-key lookup first (matches the vast majority instantly);
        # fall back to a small local search only if rounding landed on a
        # neighboring bucket.
        key = (round(target[0], 2), round(target[1], 2))
        if key in by_round:
            return by_round[key]
        for i, h in enumerate(hexes):
            if abs(h["centroid"][0] - target[0]) < _MATCH_TOL and abs(h["centroid"][1] - target[1]) < _MATCH_TOL:
                return i
        return None

    assigned = {0: (0, 0)}
    hexes[0]["qr"] = (0, 0)
    frontier = [0]
    while frontier:
        i = frontier.pop()
        cx, cy = hexes[i]["centroid"]
        q, r = hexes[i]["qr"]
        for (dq, dr), offset in _FLIPPED_OFFSETS.items():
            j = find_neighbor(cx, cy, offset)
            if j is not None and j not in assigned:
                assigned[j] = (q + dq, r + dr)
                hexes[j]["qr"] = (q + dq, r + dr)
                frontier.append(j)

    missing = [i for i in range(len(hexes)) if i not in assigned]
    if missing:
        raise RuntimeError(
            f"reconstruct_axial_coords: {len(missing)}/{len(hexes)} hexes unreachable by "
            f"BFS neighbor-matching -- the grid may not be edge-connected, or a coordinate "
            f"didn't round-trip through the 2-decimal SVG precision as expected."
        )
    qrs = [h["qr"] for h in hexes]
    if len(set(qrs)) != len(qrs):
        raise RuntimeError("reconstruct_axial_coords: produced duplicate (q, r) coordinates.")
    return hexes


def _axial_to_pixel(q, r, size=1.0):
    """Local copy of hex_grid.py's axial_to_pixel formula -- duplicated
    rather than imported so this verification step depends on nothing but
    the (unchangeable) math itself, not on any shared module staying
    exactly as it is today."""
    return size * (S3 * q + S3 / 2 * r), size * (3 / 2 * r)


# hex_svg.py pads its bounding box by its own MARGIN=1.5 constant before
# computing x_min/y_max for flip() -- read-only knowledge of that module's
# math, not a dependency on it staying unchanged.
_SVG_MARGIN = 1.5


def compute_flip_bounds(hexes):
    """-> (x_min, y_max) of the ORIGINAL (unflipped) frame's bounding box,
    padded by hex_svg.py's own MARGIN -- the exact two numbers its flip()
    translation uses. Shared by verify_geometry_equivalence() (forward flip
    check) and invert_flip() (recovering original-frame coordinates for
    anything else parsed out of the SVG's flipped frame, e.g. cluster
    label anchors)."""
    orig_px = [_axial_to_pixel(*h["qr"]) for h in hexes]
    xs = [p[0] for p in orig_px]
    ys = [p[1] for p in orig_px]
    return min(xs) - _SVG_MARGIN, max(ys) + _SVG_MARGIN


def invert_flip(pt, x_min, y_max):
    """Inverse of hex_svg.py's flip(): (x, y) -> (x - x_min, y_max - y).
    Recovers an original-(unflipped)-frame point from an SVG-frame one."""
    x, y = pt
    return x + x_min, y_max - y


def verify_geometry_equivalence(hexes):
    """Confirms reconstruct_axial_coords() didn't introduce a labeling error
    (e.g. an accidental reflection across one axis, which would still pass
    the pure-adjacency BFS check but silently mirror the layout). Re-derives
    each hex's pixel position from its reconstructed (q, r) alone via the
    formula above, applies the same flip (reflection + translation) used to
    go from hex_grid.py's y-up frame to the SVG's frame, and checks that the
    result lines up with the centroid actually parsed from the live SVG --
    for every single hex, not a sample.

    Returns a dict report: {ok, max_error, mean_error, mismatches}."""
    # axial_to_pixel(q, r) in the ORIGINAL (unflipped) frame:
    orig_px = {i: _axial_to_pixel(*h["qr"]) for i, h in enumerate(hexes)}
    x_min, y_max = compute_flip_bounds(hexes)

    def flip(pt):
        x, y = pt
        return x - x_min, y_max - y

    mismatches = []
    errors = []
    for i, h in enumerate(hexes):
        predicted = flip(orig_px[i])
        actual = h["centroid"]
        err = ((predicted[0] - actual[0]) ** 2 + (predicted[1] - actual[1]) ** 2) ** 0.5
        errors.append(err)
        if err > _MATCH_TOL:
            mismatches.append(dict(index=i, qr=h["qr"], predicted=predicted, actual=actual, error=err))

    return dict(
        ok=(len(mismatches) == 0),
        hex_count=len(hexes),
        max_error=max(errors) if errors else None,
        mean_error=(sum(errors) / len(errors)) if errors else None,
        mismatches=mismatches,
    )


def load_cluster_films(con):
    """cluster_id -> [imdb_tconst, ...] sorted oldest-first, exactly the same
    rule (including the tconst tie-break) as hex_grid.py's cluster_films."""
    ca_df = con.execute(
        "SELECT cluster_id, imdb_tconst FROM cluster_assignments ORDER BY cluster_id, imdb_tconst"
    ).df()
    no_actor_df = con.execute("""
        SELECT imdb_tconst FROM criterion_basic_info
        WHERE imdb_tconst NOT IN (SELECT imdb_tconst FROM cluster_assignments)
        ORDER BY imdb_tconst
    """).df()
    year_by_tconst = con.execute("""
        SELECT imdb_tconst, criterion_year FROM (
            SELECT imdb_tconst, criterion_year,
                   row_number() OVER (
                       PARTITION BY imdb_tconst ORDER BY confidence_score DESC NULLS LAST
                   ) AS rn
            FROM criterion_basic_info
        ) WHERE rn = 1
    """).df().set_index("imdb_tconst")["criterion_year"].to_dict()

    def year_sort_key(tconst):
        try:
            return (0, int(year_by_tconst.get(tconst)), tconst)
        except (TypeError, ValueError):
            return (1, 0, tconst)

    from collections import defaultdict
    cluster_films = defaultdict(list)
    for _, row in ca_df.iterrows():
        cluster_films[row["cluster_id"]].append(row["imdb_tconst"])
    cluster_films["hiddenGems"].extend(no_actor_df["imdb_tconst"].tolist())
    for films in cluster_films.values():
        films.sort(key=year_sort_key)
    return cluster_films


def assign_films_to_snapshot_hexes(hexes, cluster_films):
    """Within each cluster's already-fixed (from the live snapshot) set of
    hexes, pair oldest-to-newest films with nearest-to-centroid-to-farthest
    hexes -- the same pairing rule hex_grid.py documents, applied only to
    positions the snapshot already says belong to that cluster.

    Returns (hex_film, unplaced_films): if the DB now has more films in a
    cluster than the live snapshot has hexes for it (data has moved since
    explore.html was last built -- e.g. a film's cluster assignment changed),
    the extra films are reported as unplaced rather than guessed onto some
    other cluster's hex, which would paint them the wrong color."""
    by_cluster = {}
    for h in hexes:
        by_cluster.setdefault(h["cluster_id"], []).append(h)

    hex_film = {}
    unplaced_films = []
    for c, films_c in cluster_films.items():
        hexes_c = by_cluster.get(c, [])
        if not hexes_c:
            unplaced_films.extend((c, tconst) for tconst in films_c)
            continue
        pts = np.array([h["centroid"] for h in hexes_c])
        centroid = pts.mean(axis=0)
        dists = np.linalg.norm(pts - centroid, axis=1)
        order = np.argsort(dists, kind="stable")
        ordered_hexes = [hexes_c[i] for i in order]
        for h, tconst in zip(ordered_hexes, films_c):
            hex_film[h["qr"]] = tconst
        if len(films_c) > len(ordered_hexes):
            unplaced_films.extend((c, tconst) for tconst in films_c[len(ordered_hexes):])
    return hex_film, unplaced_films


FILM_COLOR_CSV = REPO_ROOT / "data" / "film_color.csv"


def load_film_color():
    """tconst -> True/False, exactly as hex_svg.py's own load_film_color()
    reads it (duplicated here rather than imported, same rationale as the
    rest of this module's read-only duplication of upstream math/logic) --
    entries with an unresolved is_color status are simply absent, so a
    caller's plain dict.get(tconst) defaults missing/unresolved films to
    None, matching hex_svg.py's `fill if film_is_color.get(tconst) else
    darken(fill)` (a None also takes the darken/black-and-white branch)."""
    import csv
    is_color = {}
    if not FILM_COLOR_CSV.exists():
        return is_color
    with FILM_COLOR_CSV.open(newline="") as f:
        for row in csv.DictReader(f):
            if row["is_color"] == "true":
                is_color[row["imdb_tconst"]] = True
            elif row["is_color"] == "false":
                is_color[row["imdb_tconst"]] = False
    return is_color


def load_titles(con, tconsts):
    if not tconsts:
        return {}
    df = con.execute("""
        SELECT imdb_tconst, title FROM (
            SELECT imdb_tconst, title,
                   row_number() OVER (
                       PARTITION BY imdb_tconst ORDER BY confidence_score DESC NULLS LAST
                   ) AS rn
            FROM criterion_basic_info
            WHERE imdb_tconst IN ({})
        ) WHERE rn = 1
    """.format(",".join(f"'{t}'" for t in tconsts))).df()
    return dict(zip(df["imdb_tconst"], df["title"]))


def build_snapshot():
    hexes, raw_cluster_labels = parse_explore_svg()
    reconstruct_axial_coords(hexes)
    geometry_check = verify_geometry_equivalence(hexes)
    if not geometry_check["ok"]:
        raise RuntimeError(
            f"verify_geometry_equivalence failed: {len(geometry_check['mismatches'])} hex(es) "
            f"didn't round-trip through the reconstructed (q, r) coordinates -- refusing to "
            f"write a snapshot that doesn't provably reproduce site/explore.html's geometry. "
            f"First mismatch: {geometry_check['mismatches'][0]}"
        )

    # Cluster label anchors/lines are exact facts read off the live SVG
    # (position, font-size, wrapped line text, on-dark/on-light color class)
    # -- only their COORDINATE FRAME needs converting, from the SVG's
    # flipped (y-down) pixel frame into the same original (y-up) frame this
    # project's own axial_to_pixel() draws hexes in. Each raw line's exact
    # SVG y (start_y + i*line_gap, line_gap = fontsize*1.2, mirroring
    # hex_svg.py's own tspan dy stacking) is inverted individually rather
    # than inverting once and re-deriving offsets, so this never has to
    # assume anything about hex_svg.py's line-stacking formula beyond what's
    # already externally visible in the SVG's own printed coordinates.
    x_min, y_max = compute_flip_bounds(hexes)
    cluster_labels = {}
    for cluster_id, lbl in raw_cluster_labels.items():
        line_gap = lbl["fontsize"] * 1.2
        line_positions = []
        for i in range(len(lbl["lines"])):
            svg_y = lbl["y"] + i * line_gap
            ox, oy = invert_flip((lbl["x"], svg_y), x_min, y_max)
            line_positions.append(dict(text=lbl["lines"][i], x=ox, y=oy))
        cluster_labels[cluster_id] = dict(
            fontsize=lbl["fontsize"], on_dark=lbl["on_dark"], lines=line_positions,
        )

    con = duckdb.connect(str(DB_PATH), read_only=True)
    cluster_films = load_cluster_films(con)
    hex_film, unplaced_films = assign_films_to_snapshot_hexes(hexes, cluster_films)
    unplaced_titles = load_titles(con, [tconst for _, tconst in unplaced_films])
    con.close()

    film_is_color = load_film_color()
    hidden_gems_white = COLOR_MAP["hiddenGems"]

    hex_records = []
    for h in hexes:
        q, r = h["qr"]
        cluster_id = h["cluster_id"]
        fill = h["fill"]
        is_hidden_gems_outer = None
        if cluster_id == "hiddenGems":
            is_hidden_gems_outer = (fill.upper() == hidden_gems_white.upper())
        tconst = hex_film.get((q, r))
        hex_records.append(dict(q=q, r=r, cluster_id=cluster_id, fill=fill,
                                 is_hidden_gems_outer=is_hidden_gems_outer,
                                 tconst=tconst,
                                 is_color=film_is_color.get(tconst) if tconst else None))

    total_films_placed = sum(1 for h in hex_records if h["tconst"])
    total_films_expected = sum(len(v) for v in cluster_films.values())
    unfilled_hex_records = [h for h in hex_records if h["tconst"] is None]

    snapshot = dict(
        source="site/explore.html",
        source_hex_count=len(hexes),
        hex_size=HEX_SIZE,
        page_background_color=PAGE_BACKGROUND_COLOR,
        color_map=COLOR_MAP,
        hexes=hex_records,
        cluster_labels=cluster_labels,
        total_films_placed=total_films_placed,
        total_films_expected=total_films_expected,
        unplaced_films=[dict(cluster_id=c, tconst=t, title=unplaced_titles.get(t))
                         for c, t in unplaced_films],
        unfilled_hexes=[dict(q=h["q"], r=h["r"], cluster_id=h["cluster_id"], fill=h["fill"])
                        for h in unfilled_hex_records],
        geometry_verification=dict(ok=geometry_check["ok"],
                                    hex_count=geometry_check["hex_count"],
                                    max_error=geometry_check["max_error"],
                                    mean_error=geometry_check["mean_error"]),
    )
    return snapshot


def main():
    snapshot = build_snapshot()
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(json.dumps(snapshot, indent=1))

    from collections import Counter
    per_cluster = Counter(h["cluster_id"] for h in snapshot["hexes"])
    white = sum(1 for h in snapshot["hexes"] if h["cluster_id"] == "hiddenGems" and h["is_hidden_gems_outer"])
    gray = sum(1 for h in snapshot["hexes"] if h["cluster_id"] == "hiddenGems" and not h["is_hidden_gems_outer"])

    print(f"Saved -> {SNAPSHOT_PATH}")
    print(f"\nTotal extracted hexes: {snapshot['source_hex_count']}")
    print("Hexes per cluster:")
    for c, n in sorted(per_cluster.items()):
        print(f"  {c:30s} {n}")
    print(f"\nhiddenGems white (outer ring) hexes: {white}")
    print(f"hiddenGems gray (inner ring) hexes:  {gray}")
    print(f"\nGeometry verification: ok={snapshot['geometry_verification']['ok']} "
          f"max_error={snapshot['geometry_verification']['max_error']:.6f} "
          f"mean_error={snapshot['geometry_verification']['mean_error']:.6f} "
          f"(tolerance {_MATCH_TOL})")
    print(f"\nFilms placed: {snapshot['total_films_placed']} / expected {snapshot['total_films_expected']}")
    if snapshot["unplaced_films"]:
        print(f"\nUnplaced films ({len(snapshot['unplaced_films'])}):")
        for f in snapshot["unplaced_films"]:
            print(f"  {f['tconst']}  \"{f['title']}\"  (cluster: {f['cluster_id']})")
    if snapshot["unfilled_hexes"]:
        print(f"\nUnfilled hexes ({len(snapshot['unfilled_hexes'])}):")
        for h in snapshot["unfilled_hexes"]:
            print(f"  (q={h['q']}, r={h['r']})  cluster: {h['cluster_id']}  fill: {h['fill']}")


if __name__ == "__main__":
    main()
