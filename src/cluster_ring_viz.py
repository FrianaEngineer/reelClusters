"""
Concentric-ring view of a cluster's films, grouped by internal-edge degree band.
Ring distance from center = degree band (inner = most internally connected).
No edges are drawn -- band membership is the only signal, shown via ring + node size.
"""

import duckdb
import numpy as np
from pathlib import Path
from xml.sax.saxutils import escape

from cluster_colors import COLOR_MAP, contrast_text_color
from cluster_graph_viz import DB_PATH, BG_COLOR, TOOLTIP_BG, TOOLTIP_TEXT, hexagon_points, CRITERION_LINKS

OUT_DIR = Path(__file__).parent.parent / "output"

W, H   = 1600, 900   # 16:9 canvas
CX, CY = W / 2, H / 2 + 50   # pushed down to leave headroom at the top

NODE_R       = 7.0    # uniform for every film, regardless of band
BAND_GAP     = 11.0   # inset so nodes stay clear of the ring-guide boundary lines
ASPECT_X     = 2.0     # rings are ellipses, stretched horizontally to fill the
                       # 16:9 canvas -- radius below is the (unstretched)
                       # vertical/minor semi-axis; the horizontal/major
                       # semi-axis is radius * ASPECT_X. Combined with the
                       # outer band's radius (~380), this puts the ellipse's
                       # edges within ~30-40px of the canvas border on every
                       # side -- CY's headroom push-down (see below) makes
                       # the bottom margin the tightest of the four.
LABEL_OFFSET = 10.0   # labels curve on a slightly larger radius, hovering just
                       # outside their ring instead of sitting on the line itself
LABEL_ASCENT_MARGIN = 14.0   # curved-text glyphs extend outward past their own
                              # baseline radius (ascenders) -- this keeps the
                              # NEXT band's nodes clear of that ink, not just
                              # of the label's nominal baseline offset above

# Per-cluster (min_degree, ring_radius, label) triples -- innermost band first.
# Films are scattered by area throughout each band's annulus (0..r for the
# innermost band), not placed on the ring line itself. Band thresholds AND
# radii are cluster-specific: the radii are sized so each band's node count
# packs comfortably (packing fraction ~0.2-0.3) given its annulus area --
# Japanese Cinema skews far denser (avg degree ~44 vs ~10) so its bands and
# ring sizes both differ substantially from European Art Cinema's. Anglophone
# Classic's degree distribution is nearly the same shape/density as European
# Art Cinema's (avg degree ~9 vs ~10, same 25/10 hub/mid split reads as a
# comparable ~4%/40%/55% hub/mid/peripheral split of a smaller film count), so
# it reuses the same degree thresholds; only the radii shrink, scaled to its
# ~255-vs-432 film count so each band keeps a similar packing density within
# the same 380px outer bound.
CLUSTER_BANDS = {
    "european_art_cinema": [
        (25, 103, "Hub (degree ≥ 25)"),
        (10, 282, "Mid (10–24)"),
        (0,  380, "Peripheral (< 10)"),
    ],
    "japanese_cinema": [
        (75, 139, "Hub (degree ≥ 75)"),
        (25, 298, "Mid (25–74)"),
        (0,  380, "Peripheral (< 25)"),
    ],
    "anglophone_classic": [
        (25, 75,  "Hub (degree ≥ 25)"),
        (10, 243, "Mid (10–24)"),
        (0,  380, "Peripheral (< 10)"),
    ],
}
RINGS_TO_RENDER = ["european_art_cinema", "japanese_cinema", "anglophone_classic"]


def esc(s):
    return escape(str(s))


def load_films_with_internal_degree(con, cluster_id):
    return con.execute("""
        WITH internal_edges AS (
            SELECT me.movie_a, me.movie_b
            FROM movie_edges me
            JOIN cluster_assignments ca ON ca.imdb_tconst = me.movie_a
            JOIN cluster_assignments cb ON cb.imdb_tconst = me.movie_b
            WHERE ca.cluster_id = ? AND cb.cluster_id = ?
        ),
        endpoints AS (
            SELECT movie_a AS m FROM internal_edges
            UNION ALL
            SELECT movie_b AS m FROM internal_edges
        ),
        deg AS (
            SELECT m AS imdb_tconst, count(*) AS degree FROM endpoints GROUP BY m
        ),
        best_match AS (
            SELECT imdb_tconst, title, criterion_year,
                   row_number() OVER (
                       PARTITION BY imdb_tconst ORDER BY confidence_score DESC NULLS LAST
                   ) AS rn
            FROM criterion_basic_info
        )
        SELECT d.imdb_tconst, b.title, b.criterion_year, d.degree
        FROM deg d
        JOIN best_match b ON b.imdb_tconst = d.imdb_tconst AND b.rn = 1
    """, [cluster_id, cluster_id]).df()


def band_for_degree(degree, bands):
    for min_deg, radius, label in bands:
        if degree >= min_deg:
            return min_deg, radius, label


def sample_annulus_no_overlap(rng, cx0, cy0, r_inner, r_outer, n, min_dist, max_attempts=500):
    """n (x, y) absolute points, scattered by area over the annulus
    [r_inner, r_outer) around (cx0, cy0). Rejects candidates closer than
    min_dist to an already-placed point in this band so nodes never overlap
    each other. Labels curve along their own band's boundary radius, which
    BAND_GAP already keeps clear of nodes on both sides, so no separate
    label-avoidance is needed here."""
    r_inner_eff = max(r_inner, 0)
    points = []
    for _ in range(n):
        x = y = 0.0
        for _ in range(max_attempts):
            r = np.sqrt(r_inner_eff ** 2 + rng.random() * (r_outer ** 2 - r_inner_eff ** 2))
            theta = rng.random() * 2 * np.pi
            x, y = cx0 + r * np.cos(theta), cy0 + r * np.sin(theta)
            if all((x - px) ** 2 + (y - py) ** 2 >= min_dist ** 2 for px, py in points):
                break
        points.append((x, y))
    return points


def build_svg(cluster_id, films, bands):
    node_color = COLOR_MAP.get(cluster_id, "#888888")
    bg_color   = BG_COLOR
    text_color = contrast_text_color(bg_color)

    grouped = {min_deg: [] for min_deg, *_ in bands}
    for row in films.itertuples():
        min_deg, *_ = band_for_degree(row.degree, bands)
        grouped[min_deg].append(row)
    for min_deg in grouped:
        grouped[min_deg].sort(key=lambda r: (-r.degree, r.title))

    label_texts = [f"{label} — {len(grouped[min_deg])} films" for min_deg, radius, label in bands]

    # Collect every node's position first (across all bands) so circles and
    # tooltips can each be emitted as one contiguous pass below.
    rng = np.random.default_rng(42)
    min_dist = 2 * NODE_R + 2   # keep circles from touching, not just from overlapping
    all_nodes = []              # (row, cx, cy)
    prev_radius = 0.0
    for min_deg, radius, label in bands:
        rows = grouped[min_deg]
        r_inner = (max(prev_radius + NODE_R + BAND_GAP, prev_radius + LABEL_OFFSET + LABEL_ASCENT_MARGIN)
                   if prev_radius > 0 else 0.0)
        r_outer = radius - NODE_R - BAND_GAP
        offsets = sample_annulus_no_overlap(rng, CX, CY, r_inner, r_outer, len(rows), min_dist)
        # Stretch into the ellipse: points were sampled on a circle of the
        # given (unstretched) radius, so scaling x away from center by
        # ASPECT_X maps that filled circular annulus onto the matching
        # filled elliptical annulus. Since ASPECT_X > 1, this can only
        # increase pairwise distances, so the min_dist guarantee from
        # sampling still holds post-stretch.
        offsets = [(CX + (x - CX) * ASPECT_X, y) for x, y in offsets]
        prev_radius = radius
        all_nodes.extend(zip(rows, offsets))

    # Hovering a node must bring its tooltip above every OTHER node too, not
    # just its own circle -- plain nesting (circle+tooltip in one <g>) fails
    # this because paint order still follows document order, so a
    # later-drawn node's circle can cover an earlier node's tooltip. Fix:
    # draw all circles first, then all tooltips (so tooltips always paint on
    # top), and pair each circle to its own tooltip with a unique id plus the
    # CSS general sibling combinator (`~`), which doesn't require adjacency.
    hover_rules = []
    for row, _ in all_nodes:
        node_id, tip_id = f"n-{row.imdb_tconst}", f"t-{row.imdb_tconst}"
        hover_rules.append(f'#{node_id}:hover ~ #{tip_id} {{ opacity: 1; }}')

    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
           f'viewBox="0 0 {W} {H}" font-family="Helvetica, Arial, sans-serif">']
    svg.append(f"""
<style>
  .node {{ fill: {node_color}; stroke: {bg_color}; stroke-width: 1.5; cursor: pointer; }}
  .node:hover {{ stroke: {text_color}; }}
  .tooltip {{ opacity: 0; pointer-events: none; transition: opacity 0.12s ease; }}
  .tooltip rect {{ fill: {TOOLTIP_BG}; stroke: #ffffff; stroke-opacity: 0.25; }}
  .tooltip text {{ fill: {TOOLTIP_TEXT}; font-size: 15px; font-weight: 600; }}
  .ring-label {{ fill: {text_color}; font-size: 15px; font-weight: 600; opacity: 0.85; }}
  .ring-guide {{ fill: none; stroke: {text_color}; stroke-opacity: 0.9; stroke-width: 1; }}
  {' '.join(hover_rules)}
</style>
""")
    svg.append(f'<rect x="0" y="0" width="{W}" height="{H}" fill="{bg_color}"/>')

    for i, ((min_deg, radius, label), text) in enumerate(zip(bands, label_texts)):
        rx = radius * ASPECT_X
        svg.append(f'<ellipse class="ring-guide" cx="{CX:.1f}" cy="{CY:.1f}" rx="{rx:.1f}" ry="{radius}"/>')
        # Invisible semi-elliptical guide (left point -> top -> right point), on a
        # slightly larger radius than the ring itself, that the label curves
        # along -- so it hovers just above its ring instead of sitting on the
        # line, while the ring itself stays a single unbroken ellipse.
        label_rx = rx + LABEL_OFFSET * ASPECT_X
        label_ry = radius + LABEL_OFFSET
        path_id = f"ring-path-{i}"
        svg.append(f'<path id="{path_id}" d="M {CX - label_rx:.1f} {CY:.1f} '
                    f'A {label_rx} {label_ry} 0 0 1 {CX + label_rx:.1f} {CY:.1f}" fill="none" stroke="none"/>')
        svg.append(f'<text class="ring-label" text-anchor="middle">'
                    f'<textPath href="#{path_id}" xlink:href="#{path_id}" startOffset="50%">'
                    f'{esc(text)}</textPath></text>')

    for row, (cx, cy) in all_nodes:
        node_id = f"n-{row.imdb_tconst}"
        polygon = f'<polygon class="node" points="{hexagon_points(cx, cy, NODE_R)}"/>'
        link = CRITERION_LINKS.get(row.title)
        if link:
            # id has to live on the <a>, not the polygon: the hover-tooltip
            # rule below is a sibling selector (#node:hover ~ #tooltip) that
            # needs the id'd element to still be a direct sibling of the
            # tooltip <g> -- nesting the polygon one level deeper inside <a>
            # doesn't break that, since hovering the polygon still counts as
            # hovering its <a> ancestor.
            svg.append(f'<a id="{node_id}" href="{esc(link)}" target="_blank" rel="noopener">{polygon}</a>')
        else:
            svg.append(f'<polygon id="{node_id}" class="node" points="{hexagon_points(cx, cy, NODE_R)}"/>')

    for row, (cx, cy) in all_nodes:
        tip = f"{row.title} ({int(row.criterion_year)}) · degree {row.degree}"
        tw = max(70, 8.2 * len(tip))
        th = 34
        tx = min(max(cx - tw / 2, 8), W - tw - 8)
        ty = cy - NODE_R - th - 10
        if ty < 10:
            ty = cy + NODE_R + 10

        svg.append(f'''<g id="t-{row.imdb_tconst}" class="tooltip">
  <rect x="{tx:.1f}" y="{ty:.1f}" width="{tw:.1f}" height="{th:.1f}" rx="6"/>
  <text x="{tx + tw / 2:.1f}" y="{ty + th / 2 + 5:.1f}" text-anchor="middle">{esc(tip)}</text>
</g>''')

    svg.append('</svg>')
    return '\n'.join(svg)


if __name__ == "__main__":
    con = duckdb.connect(str(DB_PATH))
    for cluster_id in RINGS_TO_RENDER:
        bands = CLUSTER_BANDS[cluster_id]
        films = load_films_with_internal_degree(con, cluster_id)
        svg_text = build_svg(cluster_id, films, bands)
        out_path = OUT_DIR / f"{cluster_id}_rings.svg"
        out_path.write_text(svg_text)
        print(f"{cluster_id}: {len(films)} films across {len(bands)} bands -> {out_path}")
    con.close()
