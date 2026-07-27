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
from hex_svg import darken, load_film_color

OUT_DIR = Path(__file__).parent.parent / "output"

W, H = 1600, 900   # 16:9 canvas

NODE_R_DEFAULT   = 7.0    # uniform for every film, regardless of band
BAND_GAP         = 11.0   # inset so nodes stay clear of the ring-guide boundary lines
ASPECT_X         = 2.0     # rings are ellipses, stretched horizontally to fill the
                       # 16:9 canvas -- radius below is the (unstretched)
                       # vertical/minor semi-axis; the horizontal/major
                       # semi-axis is radius * ASPECT_X. Combined with the
                       # outer band's radius (~380), this puts the ellipse's
                       # edges within ~30-40px of the canvas border on every
                       # side -- CY's headroom push-down (see below) makes
                       # the bottom margin the tightest of the four.
LABEL_OFFSET     = 10.0   # labels curve on a slightly larger radius, hovering just
                       # outside their ring instead of sitting on the line itself
LABEL_ASCENT_MARGIN_DEFAULT = 14.0   # curved-text glyphs extend outward past their own
                              # baseline radius (ascenders) -- this keeps the
                              # NEXT band's nodes clear of that ink, not just
                              # of the label's nominal baseline offset above

# CY push-down below true vertical center, to leave headroom for the outermost
# band's label. The shared default (50) leaves only ~20px of bottom margin
# against ~120px on top for a 380-radius outer band -- visibly off-center,
# which is what the Anglophone Classic page plan's "center the graph" request
# was about. Left as-is for the other two ring clusters (not part of this
# request); Anglophone Classic gets a much smaller push, just enough headroom
# for its now-larger label font (see LABEL_STYLE_OVERRIDES below).
CY_PUSH_DEFAULT = 50.0
CY_PUSH_OVERRIDES = {
    "anglophone_classic": 14.0,
    "transatlantic_auteur_cinema": 14.0,
    "hong_kong_taiwan_cinema": 14.0,
    "bergman_scandinavian": 14.0,
    "european_art_cinema": 14.0,
    "japanese_cinema": 14.0,
}

# Per-cluster visual overrides so the shared ring-viz code can give every
# ring cluster the same larger, higher-contrast treatment.
NODE_R_OVERRIDES = {
    "anglophone_classic": 12.0,
    "transatlantic_auteur_cinema": 12.0,
    "hong_kong_taiwan_cinema": 12.0,
    "bergman_scandinavian": 12.0,
    # European Art Cinema and Japanese Cinema both have far more films (432
    # and 354) than the other bigger-node clusters, so 12.0 doesn't fit
    # within the fixed 380px outer bound without real node overlap -- 9.5 is
    # the largest radius that still packs every band cleanly for both
    # (verified by checking every node's pairwise distance, not just
    # eyeballing it).
    "european_art_cinema": 9.5,
    "japanese_cinema": 9.5,
}
# Default node border blends into the background (stroke = bg_color) so
# touching nodes read as separated without drawing attention to the border
# itself. The bigger-node clusters get an actual visible-but-slight black
# border instead, so individual films stand out more clearly.
NODE_BORDER_STYLE_OVERRIDES = {
    "anglophone_classic": {"stroke": "#000000", "opacity": 0.55, "width": 1.4},
    "transatlantic_auteur_cinema": {"stroke": "#000000", "opacity": 0.55, "width": 1.4},
    "hong_kong_taiwan_cinema": {"stroke": "#000000", "opacity": 0.55, "width": 1.4},
    "bergman_scandinavian": {"stroke": "#000000", "opacity": 0.55, "width": 1.4},
    "european_art_cinema": {"stroke": "#000000", "opacity": 0.55, "width": 1.4},
    "japanese_cinema": {"stroke": "#000000", "opacity": 0.55, "width": 1.4},
}
LABEL_STYLE_DEFAULT = {"font_size": 15, "font_weight": 600}
LABEL_STYLE_OVERRIDES = {
    "anglophone_classic": {"font_size": 21, "font_weight": 800},
    "transatlantic_auteur_cinema": {"font_size": 21, "font_weight": 800},
    "hong_kong_taiwan_cinema": {"font_size": 21, "font_weight": 800},
    "bergman_scandinavian": {"font_size": 21, "font_weight": 800},
    "european_art_cinema": {"font_size": 21, "font_weight": 800},
    "japanese_cinema": {"font_size": 21, "font_weight": 800},
}
LABEL_ASCENT_MARGIN_OVERRIDES = {
    "anglophone_classic": 19.0,
    "transatlantic_auteur_cinema": 19.0,
    "hong_kong_taiwan_cinema": 19.0,
    "bergman_scandinavian": 19.0,
    "european_art_cinema": 19.0,
    "japanese_cinema": 19.0,
}
RING_GUIDE_STYLE_OVERRIDES = {
    # Darker and thicker than the shared default (which just reuses the
    # cluster's contrast text color at stroke-width 1). Rather than an
    # unrelated fixed color, "darken_factor" darkens the cluster's own node
    # color -- same darken() used for black-and-white nodes below -- so the
    # ring boundaries still read as part of the cluster's own identity while
    # standing out from the larger nodes/labels.
    "anglophone_classic": {"darken_factor": 0.3, "width": 2.6, "opacity": 1.0},
    "transatlantic_auteur_cinema": {"darken_factor": 0.3, "width": 2.6, "opacity": 1.0},
    "hong_kong_taiwan_cinema": {"darken_factor": 0.3, "width": 2.6, "opacity": 1.0},
    "bergman_scandinavian": {"darken_factor": 0.3, "width": 2.6, "opacity": 1.0},
    "european_art_cinema": {"darken_factor": 0.3, "width": 2.6, "opacity": 1.0},
    "japanese_cinema": {"darken_factor": 0.3, "width": 2.6, "opacity": 1.0},
}

# Clusters that distinguish black-and-white from color films by darkening the
# node fill (same rule hex_svg.py uses for the home page's hex grid).
BW_TINT_CLUSTERS = {"anglophone_classic", "transatlantic_auteur_cinema",
                     "hong_kong_taiwan_cinema", "bergman_scandinavian",
                     "european_art_cinema", "japanese_cinema"}

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
    # Radii widened slightly from the original (103, 282) to make room for
    # the bigger 9.5px nodes (see NODE_R_OVERRIDES) at this cluster's much
    # higher per-band film counts (21/182/229) -- verified zero pairwise
    # node-overlaps at these exact radii, not just visually spot-checked.
    "european_art_cinema": [
        (25, 90,  "Hub (degree ≥ 25)"),
        (10, 255, "Mid (10–24)"),
        (0,  380, "Peripheral (< 10)"),
    ],
    # Radii widened slightly from the original (139, 298) for the same
    # reason as European Art Cinema above: the bigger 9.5px nodes need more
    # room for this cluster's per-band counts (44/226/84) -- verified zero
    # pairwise node-overlaps at these exact radii.
    "japanese_cinema": [
        (75, 165, "Hub (degree ≥ 75)"),
        (25, 315, "Mid (25–74)"),
        (0,  380, "Peripheral (< 25)"),
    ],
    "anglophone_classic": [
        (25, 75,  "Hub (degree ≥ 25)"),
        (10, 243, "Mid (10–24)"),
        (0,  380, "Peripheral (< 10)"),
    ],
    # Transatlantic Auteur Cinema's own degree distribution is much sparser
    # (avg internal degree ~4.7, max 20) than the other three ring clusters,
    # so it needs its own thresholds rather than reusing the 25/10 split --
    # at those cutoffs its hub band would be empty (max degree is only 20).
    # Chosen to land on roughly the same hub/mid/peripheral proportions
    # (~6%/31%/63%) as Anglophone Classic's (~4%/37%/59%) so it reads as the
    # same kind of graph despite the different absolute degree range.
    "transatlantic_auteur_cinema": [
        (15, 75,  "Hub (degree ≥ 15)"),
        (5,  230, "Mid (5–14)"),
        (0,  380, "Peripheral (< 5)"),
    ],
    # Hong Kong/Taiwan Cinema is small (79 films) but dense and fairly evenly
    # spread across its whole 1-36 degree range (median 12, not concentrated
    # near either end like the other clusters), with a genuinely large
    # top tier rather than a long thin tail -- closer in shape to Japanese
    # Cinema's dense core than to Anglophone/Transatlantic's skew. Hub/Mid/
    # Peripheral here land at ~23%/46%/32% of the cluster.
    "hong_kong_taiwan_cinema": [
        (20, 100, "Hub (degree ≥ 20)"),
        (8,  250, "Mid (8–19)"),
        (0,  380, "Peripheral (< 8)"),
    ],
    # Bergman Scandinavian is the densest small cluster: mean/median internal
    # degree ~17-18, nearly flat across the whole 1-35 range rather than
    # skewed to either end (Bergman's own repertory company forms the dense
    # core, with the wider Scandinavian tradition around it). Hub/Mid/
    # Peripheral land at ~25%/48%/27% -- band sizes close enough to Hong
    # Kong/Taiwan Cinema's (18/36/25 films) to reuse the same radii.
    "bergman_scandinavian": [
        (25, 100, "Hub (degree ≥ 25)"),
        (10, 250, "Mid (10–24)"),
        (0,  380, "Peripheral (< 10)"),
    ],
}
RINGS_TO_RENDER = ["european_art_cinema", "japanese_cinema", "anglophone_classic",
                   "transatlantic_auteur_cinema", "hong_kong_taiwan_cinema",
                   "bergman_scandinavian"]


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
    film_is_color = load_film_color()

    NODE_R = NODE_R_OVERRIDES.get(cluster_id, NODE_R_DEFAULT)
    CX, CY = W / 2, H / 2 + CY_PUSH_OVERRIDES.get(cluster_id, CY_PUSH_DEFAULT)
    LABEL_ASCENT_MARGIN = LABEL_ASCENT_MARGIN_OVERRIDES.get(cluster_id, LABEL_ASCENT_MARGIN_DEFAULT)
    label_style = {**LABEL_STYLE_DEFAULT, **LABEL_STYLE_OVERRIDES.get(cluster_id, {})}
    guide_override = RING_GUIDE_STYLE_OVERRIDES.get(cluster_id, {})
    guide_stroke = (darken(node_color, guide_override["darken_factor"])
                    if "darken_factor" in guide_override else text_color)
    guide_width  = guide_override.get("width", 1)
    guide_opacity = guide_override.get("opacity", 0.9)
    border_override = NODE_BORDER_STYLE_OVERRIDES.get(cluster_id, {})
    node_stroke = border_override.get("stroke", bg_color)
    node_stroke_opacity = border_override.get("opacity", 1.0)
    node_stroke_width = border_override.get("width", max(1.5, NODE_R * 0.2))

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
  .node {{ stroke: {node_stroke}; stroke-opacity: {node_stroke_opacity}; stroke-width: {node_stroke_width}; cursor: pointer; }}
  .node:hover {{ stroke: {text_color}; stroke-opacity: 1; }}
  .tooltip {{ opacity: 0; pointer-events: none; transition: opacity 0.12s ease; }}
  .tooltip rect {{ fill: {TOOLTIP_BG}; stroke: #ffffff; stroke-opacity: 0.25; }}
  .tooltip text {{ fill: {TOOLTIP_TEXT}; font-size: 22px; font-weight: 600; }}
  .ring-label {{ fill: {text_color}; font-size: {label_style['font_size']}px; font-weight: {label_style['font_weight']}; opacity: 0.9; }}
  .ring-guide {{ fill: none; stroke: {guide_stroke}; stroke-opacity: {guide_opacity}; stroke-width: {guide_width}; }}
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
        # Black-and-white (or unresolved -- treated the same, so an unknown
        # film never gets a false "in color" look) renders as a darker shade
        # of the cluster color; confirmed-color films get the normal cluster
        # color. Same rule hex_svg.py uses for the home page's hex grid.
        is_bw = cluster_id in BW_TINT_CLUSTERS and not film_is_color.get(row.imdb_tconst)
        fill = darken(node_color) if is_bw else node_color
        polygon = f'<polygon class="node" points="{hexagon_points(cx, cy, NODE_R)}" fill="{fill}"/>'
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
            svg.append(f'<polygon id="{node_id}" class="node" points="{hexagon_points(cx, cy, NODE_R)}" fill="{fill}"/>')

    for row, (cx, cy) in all_nodes:
        tip = f"{row.title} ({int(row.criterion_year)}) · degree {row.degree}"
        tw = max(100, 11.9 * len(tip))
        th = 46
        tx = min(max(cx - tw / 2, 8), W - tw - 8)
        ty = cy - NODE_R - th - 10
        if ty < 10:
            ty = cy + NODE_R + 10

        svg.append(f'''<g id="t-{row.imdb_tconst}" class="tooltip">
  <rect x="{tx:.1f}" y="{ty:.1f}" width="{tw:.1f}" height="{th:.1f}" rx="6"/>
  <text x="{tx + tw / 2:.1f}" y="{ty + th / 2 + 7:.1f}" text-anchor="middle">{esc(tip)}</text>
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
