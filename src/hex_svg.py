"""
Interactive SVG rendering of the hex cluster grid, for the project website's
home page. Each cluster's hexes are wrapped in a single <a>, so hovering
highlights the whole region and clicking navigates to that cluster's page.
Built on the same hex_grid assignment as hex_viz.py so the two never drift
out of sync with each other.
"""

import csv
import textwrap
from pathlib import Path
from xml.sax.saxutils import escape

import numpy as np

from hex_grid import build_hex_grid, axial_to_pixel, hex_corners, EDGE_CORNERS, display_name

OUT_PATH = Path(__file__).parent.parent / "site" / "hex_grid.svg"
FILM_COLOR_CSV = Path(__file__).parent.parent / "data" / "film_color.csv"

HEX_SIZE = 1.0
GAP      = 0.95
MARGIN   = 1.5

# fit_label() shrinks a cluster label to fit the room its own hexes have; for
# very small clusters that room can be tiny, which used to shrink text down
# to near-illegibility (~0.4-0.5). Clamp to a legible floor instead and let a
# label that still can't fit spill slightly into a neighboring cluster's
# color -- the white-on-dark/black-on-light label styling (paint-order:
# stroke, in the <style> block below) keeps it readable regardless of what's
# behind it, so a little overflow reads far better than tiny text.
MIN_LABEL_FSIZE = 1.0

# Every hex gets a plain black border. A film's color/black-and-white status
# (see build_film_color.py) instead tints the fill: black-and-white (or
# unresolved -- deliberately treated the same as black-and-white, so an
# unknown film never gets a false "in color" look) renders as a darker shade
# of its cluster's color; confirmed-color films render at the cluster's
# normal color.
HEX_BORDER      = "#000000"
BW_DARKEN_FACTOR = 0.65   # multiply each RGB channel by this for black-and-white films


def darken(hex_color, factor=BW_DARKEN_FACTOR):
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    return f"#{int(r * factor):02x}{int(g * factor):02x}{int(b * factor):02x}"


def load_film_color():
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


def esc(s):
    return escape(str(s))


def page_href(cluster_id):
    return f"clusters/{cluster_id}.html"


def build_svg():
    grid              = build_hex_grid()
    grid_hexes        = grid.grid_hexes
    hex_cluster       = grid.hex_cluster
    hex_set           = grid.hex_set
    large_clusters    = grid.large_clusters
    cluster_size      = grid.cluster_size
    color_map         = grid.color_map
    hex_film          = grid.hex_film
    hidden_gems_outer = grid.hidden_gems_outer
    film_is_color  = load_film_color()

    # All geometry below is computed in the SAME (matplotlib-style, y-up)
    # frame hex_viz.py uses. `flip` is applied only at the very end, to each
    # individual point right as it's written out -- never to a center that
    # then gets more geometry (like corners) built on top of it, since a
    # partial flip part-way through corrupts the shared-corner correspondence
    # that the boundary-line lookup (EDGE_CORNERS) depends on.
    all_px = np.array([axial_to_pixel(q, r, HEX_SIZE) for q, r in grid_hexes])
    x_min, y_min = all_px.min(axis=0) - MARGIN
    x_max, y_max = all_px.max(axis=0) + MARGIN
    W, H = x_max - x_min, y_max - y_min

    def flip(pt):
        x, y = pt
        return x - x_min, y_max - y

    by_cluster = {}
    for h in grid_hexes:
        by_cluster.setdefault(hex_cluster.get(h, large_clusters[0]), []).append(h)

    min_size = min(cluster_size[c] for c in large_clusters)
    max_size = max(cluster_size[c] for c in large_clusters)

    def font_size_for(c):
        if c == 'hiddenGems':
            return 1.5
        t = (cluster_size[c] - min_size) / (max_size - min_size) if max_size > min_size else 0
        return 1.0 + 1.5 * np.sqrt(max(0, t))

    CHAR_W = 0.58   # approx average glyph advance for bold Helvetica, as a fraction of font-size

    def fit_label(pixels, lx, ly, ideal_fsize, label, min_fsize=MIN_LABEL_FSIZE):
        """Shrink font size (and rewrap) until the label fits the room this
        cluster's own hexes actually have AT the label's position -- not its
        overall bounding box, since an irregularly-shaped cluster (e.g.
        squeezed between two neighbors) can be much narrower right where the
        label sits than its footprint elsewhere. Without this, long labels on
        small or narrow clusters visually spill into a neighboring cluster's
        color, since SVG text isn't clipped to the polygon it labels.
        """
        GAP_THRESH = HEX_SIZE * 2.6   # wider than one hex step -> a different arm of the shape

        def contiguous_room(coords, anchor):
            """Room on each side of `anchor` along a 1-D slice of this
            cluster's own hex coordinates, following only the CONTIGUOUS run
            touching the anchor. A big, irregularly-shaped cluster can wrap
            around a neighbor and have another arm of itself at the same
            height (or same column) far away -- a plain min/max over all
            same-row hexes would count that far arm as "room", wildly
            overestimating the space actually available right here.
            """
            xs = np.sort(coords)
            i = np.searchsorted(xs, anchor)
            lo = anchor
            j = i - 1
            while j >= 0 and (lo - xs[j]) < GAP_THRESH:
                lo = xs[j]
                j -= 1
            hi = anchor
            j = i
            while j < len(xs) and (xs[j] - hi) < GAP_THRESH:
                hi = xs[j]
                j += 1
            return anchor - lo + HEX_SIZE, hi - anchor + HEX_SIZE

        def half_height_over(x_half_span):
            # Same idea as half_width_over, transposed: sample several narrow
            # COLUMNS across the label's width and take the min up/down room,
            # rather than pooling every hex in the wide x-band into one
            # contiguous_room call -- that would mix columns whose shape
            # boundary sits at different heights and overestimate room, the
            # same bug half_width_over had to avoid for rows.
            band = pixels[np.abs(pixels[:, 0] - lx) < x_half_span + HEX_SIZE]
            if not len(band):
                return HEX_SIZE
            xs = band[:, 0]
            lo, hi = lx - x_half_span, lx + x_half_span
            rooms = []
            for x0 in np.linspace(lo, hi, 5):
                col = band[np.abs(xs - x0) < HEX_SIZE * 0.9]
                if len(col):
                    up, down = contiguous_room(col[:, 1], ly)
                    rooms.append(min(up, down))
            return min(rooms) if rooms else HEX_SIZE

        MARGIN_FACTOR = 0.82   # extra safety margin, since this is all approximate

        def half_width_over(y_half_span):
            # Room available on EACH side of the (center-anchored) label
            # point, across the whole vertical span the text block would
            # occupy -- not just a slice at its center line, since a
            # multi-line block can reach into a narrower or wider part of the
            # cluster above/below center.
            band = pixels[np.abs(pixels[:, 1] - ly) < y_half_span + HEX_SIZE]
            if not len(band):
                return HEX_SIZE
            ys = band[:, 1]
            lo, hi = ly - y_half_span, ly + y_half_span
            rooms = []
            for y0 in np.linspace(lo, hi, 5):
                row = band[np.abs(ys - y0) < HEX_SIZE * 0.9]
                if len(row):
                    left, right = contiguous_room(row[:, 0], lx)
                    rooms.append(min(left, right))
            return min(rooms) if rooms else HEX_SIZE

        fsize = ideal_fsize
        lines = [label]
        for _ in range(14):
            line_gap = fsize * 1.2
            # Rough pass to estimate block height/line count at this font size.
            probe_half_w = half_width_over(fsize * 1.1 / 2)
            max_chars = max(3, int((2 * probe_half_w * MARGIN_FACTOR) / (fsize * CHAR_W)))
            lines = textwrap.wrap(label, width=max_chars, break_long_words=False) or [label]
            block_h = line_gap * (len(lines) - 1) + fsize * 1.1
            half_w  = half_width_over(block_h / 2)
            half_h  = half_height_over(half_w)
            widest_half = max(len(l) for l in lines) * fsize * CHAR_W / 2
            if widest_half <= half_w * MARGIN_FACTOR and block_h / 2 <= half_h * MARGIN_FACTOR:
                break
            fsize *= 0.88
            if fsize < min_fsize:
                fsize = min_fsize
                break
        return fsize, lines

    # Grid's vertical midpoint in the ORIGINAL frame (matches hex_viz.py),
    # used to place the hiddenGems label on the middle of whichever border
    # band it sits on.
    grid_y_mid = (max(axial_to_pixel(q, r)[1] for q, r in grid_hexes)
                  + min(axial_to_pixel(q, r)[1] for q, r in grid_hexes)) / 2

    # Manual nudges, ported as-is from hex_viz.py (still in the original,
    # unflipped frame -- flip() below applies to the final nudged point).
    # european_art_cinema's region shape/position is essentially unchanged
    # by the 2026-07-31 rebuild, so its nudge is kept. anglophone_classic's
    # successor (golden_age_hollywood_british) and bergman_scandinavian's
    # successor (scandinavian_bergman_circle) cover meaningfully different
    # film counts/shapes now -- their old pixel-tuned nudges were dropped
    # rather than carried forward blindly; re-add here (with the new IDs) if
    # a visual check of site/hex_grid.svg shows a label overrunning its hexes.
    # Each offset below was chosen by brute-force sampling every hex in the
    # cluster as a candidate anchor and picking one of the ones that let
    # fit_label grow closest to the cluster's size-driven ideal font size
    # (font_size_for) without spilling past its own hexes -- not hand-tuned
    # guesses. See git history for the search script.
    LABEL_OFFSETS = {
        # Base (centroid-nearest) anchor sits in a narrow neck of the
        # cluster's shape; row y=-24 (original frame) is a single wide,
        # hole-free run the full width of the cluster's lower body.
        'european_art_cinema': (-0.86, -13.5),
        # Base anchor sits in the cluster's narrowest point; y=-15 is this
        # small, roughly circular cluster's widest row. Still small/enclosed
        # (surrounded by european_art_cinema), so the ceiling here is modest.
        'czech_new_wave': (0.87, 1.5),
        # modern_american_cinema's centroid-nearest anchor lands close to its
        # border with hong_kong_taiwan_cinema (which sits right above it),
        # leaving fit_label so little clearance the label collapses to
        # MIN_LABEL_FSIZE and spills onto hong_kong_taiwan_cinema's hexes.
        # y=24 (original frame) is near the top of the cluster's wide-open
        # upper body, clear of hong_kong_taiwan_cinema below and
        # golden_age_hollywood_british's border to the left -- verified
        # visually against site/hex_grid.svg.
        'modern_american_cinema': (-1.74, 15.0),
    }

    MATCH_FONT_SIZE = {}

    # hong_kong_taiwan_cinema's island shape gives fit_label so little
    # vertical room at any nearby anchor point (tried a spread of manual
    # offsets, all landed on the same floor) that it always bottoms out at
    # MIN_LABEL_FSIZE. Give it a deliberately higher floor instead -- verified
    # separately that the resulting label still doesn't reach a neighboring
    # cluster's hexes. (bergman_scandinavian's old floor override was dropped
    # along with its ID -- see LABEL_OFFSETS comment above.)
    FSIZE_FLOOR_OVERRIDES = {
        'hong_kong_taiwan_cinema': 2.0,
    }

    # fit_label's shrink loop multiplies by 0.88 per step, starting from
    # font_size_for(c)'s "ideal" size. That coarse geometric decay can jump
    # straight past a size that would have fit -- e.g. japanese_new_wave_genre
    # fails at 1.55 (needs 0.852 of vertical room, has 0.82) so the next step
    # is 1.36, even though sizes up to ~1.48 also fit. Feeding a starting
    # ideal_fsize closer to the true boundary (found by fine-stepping fits()
    # at this cluster's real anchor -- see git history) lets the SAME fits()
    # safety check succeed on the first try instead of overshooting down to
    # the next coarse rung. No change to fit_label itself, so no other
    # cluster's size is affected.
    IDEAL_FSIZE_OVERRIDES = {
        'japanese_new_wave_genre': 1.478,
    }

    def base_anchor(c, hexes):
        pixels = np.array([axial_to_pixel(h[0], h[1], HEX_SIZE) for h in hexes])
        centroid = pixels.mean(axis=0)
        dists = np.linalg.norm(pixels - centroid, axis=1)
        lx, ly = pixels[np.argmin(dists)]
        dx, dy = LABEL_OFFSETS.get(c, (0, 0))
        return pixels, lx + dx, ly + dy

    fsize_cache = {}
    for ref_c in set(MATCH_FONT_SIZE.values()):
        pixels, lx, ly = base_anchor(ref_c, by_cluster[ref_c])
        fsize_cache[ref_c], _ = fit_label(pixels, lx, ly, font_size_for(ref_c), display_name(ref_c))

    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W:.1f} {H:.1f}" '
           f'font-family="Helvetica, Arial, sans-serif">']
    svg.append(f'<rect x="0" y="0" width="{W:.1f}" height="{H:.1f}" fill="#12121f"/>')
    svg.append("""
<style>
  a .hex { transition: filter 0.12s ease; }
  a:hover .hex { filter: brightness(1.4); }
  a { cursor: pointer; }
  .label { font-weight: 700; text-anchor: middle; dominant-baseline: central; paint-order: stroke; }
  .label.on-dark { fill: #ffffff; stroke: #000000; stroke-width: 0.11; stroke-linejoin: round; opacity: 0.95; }
  .label.on-light { fill: #000000; opacity: 0.92; }
</style>
""")

    # Hexes and labels are rendered in two separate passes (all hexes, THEN
    # all labels) rather than interleaved per-cluster. A label is allowed to
    # spill outside its own cluster's hexes (see MIN_LABEL_FSIZE above), and
    # with a single interleaved pass, whichever cluster happened to be drawn
    # LATER in dict order would paint its hexes right over an earlier
    # cluster's spilled label text. Drawing every label only after every
    # cluster's hexes are down guarantees labels always end up on top,
    # regardless of draw order or how far a label spills.
    label_info = {}   # c -> (lx, ly, fsize, lines)

    for c, hexes in by_cluster.items():
        fill = color_map.get(c, '#888888')
        pixels = np.array([axial_to_pixel(h[0], h[1], HEX_SIZE) for h in hexes])   # original frame

        if c == 'hiddenGems':
            # The top border is two hex rows thick (outer + inner ring).
            # Averaging across both -- the old approach -- lands ly exactly
            # on the boundary line between them, splitting the label across
            # both rows. Center on the inner row alone instead, so the label
            # sits on one unbroken row of hexes like every other label.
            top_y    = max(pixels[:, 1])
            top_row  = pixels[np.abs(pixels[:, 1] - top_y) < 1e-6]
            lx       = top_row[:, 0].mean()
            inner_y  = top_y - 1.5 * HEX_SIZE
            inner_row = pixels[np.abs(pixels[:, 1] - inner_y) < 1e-6]
            ly       = inner_y if len(inner_row) else top_y
        else:
            centroid = pixels.mean(axis=0)
            dists    = np.linalg.norm(pixels - centroid, axis=1)
            lx, ly   = pixels[np.argmin(dists)]

        dx, dy = LABEL_OFFSETS.get(c, (0, 0))
        lx, ly = lx + dx, ly + dy

        ideal_fsize = fsize_cache.get(MATCH_FONT_SIZE.get(c), font_size_for(c))
        ideal_fsize = IDEAL_FSIZE_OVERRIDES.get(c, ideal_fsize)
        min_fsize = FSIZE_FLOOR_OVERRIDES.get(c, MIN_LABEL_FSIZE)
        fsize, lines = fit_label(pixels, lx, ly, ideal_fsize, display_name(c), min_fsize=min_fsize)
        label_info[c] = (*flip((lx, ly)), fsize, lines)

        svg.append(f'<a href="{esc(page_href(c))}">')
        svg.append('<g>')
        for h in hexes:
            cx, cy  = axial_to_pixel(h[0], h[1], HEX_SIZE)          # original frame
            corners = [flip(p) for p in hex_corners(cx, cy, HEX_SIZE * GAP)]
            pts = " ".join(f"{px:.2f},{py:.2f}" for px, py in corners)
            if c == 'hiddenGems':
                # Position-based, not film-based: the outer ring (the grid's
                # true edge) is white, the inner ring one hex-step in is the
                # same darkened shade used elsewhere for black-and-white
                # films -- reusing that color rather than each hex's own
                # film's color/b&w status, so the two-ring border reads
                # cleanly instead of mixing white/grey by film metadata.
                hex_fill = fill if h in hidden_gems_outer else darken(fill)
            else:
                tconst = hex_film.get(h)
                hex_fill = fill if film_is_color.get(tconst) else darken(fill)
            svg.append(f'<polygon class="hex" points="{pts}" fill="{hex_fill}" '
                       f'stroke="{HEX_BORDER}" stroke-width="0.07"/>')
        svg.append('</g>')
        svg.append('</a>')

    # Cluster boundary lines (drawn on top, not part of any single cluster's <a>).
    # Corners come from the SAME unflipped hex_corners() call as the fills
    # above, so EDGE_CORNERS' shared-corner indices still line up correctly;
    # flip() is applied only to the two endpoints of each finished segment.
    boundary_segs = []
    for h in grid_hexes:
        q, r = h
        c1 = hex_cluster.get(h)
        cx, cy  = axial_to_pixel(q, r, HEX_SIZE)
        corners = hex_corners(cx, cy, HEX_SIZE)
        for (dq, dr), (ci1, ci2) in EDGE_CORNERS.items():
            nb = (q + dq, r + dr)
            c2 = hex_cluster.get(nb)
            if nb in hex_set and c2 is not None and c2 != c1:
                boundary_segs.append((flip(corners[ci1]), flip(corners[ci2])))

    path_d = " ".join(f"M{x1:.2f},{y1:.2f} L{x2:.2f},{y2:.2f}" for (x1, y1), (x2, y2) in boundary_segs)
    # Note: unlike matplotlib's linewidths (fixed points, independent of data
    # scale), SVG stroke-width is in the same user-space units as the geometry
    # -- and a hex here has radius 1.0, so this needs to be a small fraction
    # of that, not the "1.6" that worked for the matplotlib version.
    svg.append(f'<path d="{path_d}" fill="none" stroke="#12121f" stroke-width="0.12" '
               f'stroke-linecap="round" pointer-events="none"/>')

    # Labels last, so every one paints on top of every cluster's hexes and the
    # boundary lines -- see the comment on `label_info` above.
    for c, (lx, ly, fsize, lines) in label_info.items():
        label_cls = 'label on-light' if c == 'hiddenGems' else 'label on-dark'
        line_gap = fsize * 1.2
        start_y = ly - line_gap * (len(lines) - 1) / 2
        svg.append(f'<a href="{esc(page_href(c))}">')
        svg.append(f'<text class="{label_cls}" x="{lx:.2f}" y="{start_y:.2f}" font-size="{fsize:.2f}">')
        for i, line in enumerate(lines):
            dy_attr = '0' if i == 0 else f'{line_gap:.2f}'
            svg.append(f'<tspan x="{lx:.2f}" dy="{dy_attr}">{esc(line)}</tspan>')
        svg.append('</text>')
        svg.append('</a>')

    svg.append('</svg>')
    return '\n'.join(svg)


if __name__ == "__main__":
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(build_svg())
    print(f"Saved -> {OUT_PATH}")
