"""
"Reeling Through the Years: Mapping Cinematic History" renderer.

Consumes ONLY cinematic_history_schedule.py's build_full_schedule() output
(itself sourced only from data/cinematic_history_hex_snapshot.json + the DB,
never from build_hex_grid()) and cinematic_history_config.py. Draws the hex
grid with hex_svg.py's visual language (lighter/thinner interior hex
strokes, a thicker/more-defined continuous outer-perimeter border, plus a
new black outline between adjacent clusters -- see build_figure()) in a
two-column layout: the hex grid on the left under a persistent main-title
header, and a vertical film-info panel on the right holding the current
year, a static "Most Connected Films" heading, up to cfg.TOP_N_FILMS film
rows (each with a small hexagon swatch in that film's cluster color beside
its title/director/country/connections), and the matching yearly poster
(with a golden border on its exact hex). Writes a SILENT MP4 -- audio is
muxed in a separate stage (cinematic_history_audio_mix.py) so a test/draft
render never has to pay for the audio pipeline too.

Never imports hex_grid.py or hex_svg.py. Never writes outside outputs/.
"""

import argparse
import math
import shutil
import sys
import textwrap
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.animation as animation
import matplotlib.patheffects as patheffects
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager
from matplotlib.collections import LineCollection, PolyCollection
from matplotlib.colors import to_rgba
from matplotlib.transforms import Affine2D

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import cinematic_history_config as cfg  # noqa: E402
import cinematic_history_schedule as sched  # noqa: E402
from cinematic_history_hexmath import (  # noqa: E402
    axial_to_pixel, hex_corners, outer_perimeter_segments, EDGE_CORNERS,
)
from cinematic_history_posters import build_poster_index  # noqa: E402


# Period fonts (2026-08-17 restyle): a restrained, readable bold font per
# ~20-year cinematic period (cfg.PERIOD_FONTS), applied only to the film
# title lines and the big year number -- see font_for_year() and set_rows().
# Registered once at import time so every family is available to matplotlib
# by name before any figure is built.
for _start, _end, _family, _filename in cfg.PERIOD_FONTS:
    _font_path = cfg.FONTS_DIR / _filename
    if _font_path.exists():
        font_manager.fontManager.addfont(str(_font_path))


def font_for_year(year):
    if year is not None:
        for start, end, family, _filename in cfg.PERIOD_FONTS:
            if start <= year <= end:
                return family
    return cfg.DEFAULT_FONT_FAMILY

FIGURE_WIDTH_IN = 16
FIGURE_HEIGHT_IN = 9
HEX_SIZE = 1.0
HEX_GAP = 0.95

# 2026-08-08 "Reeling Through the Years: Mapping Cinematic History" restyle:
# graph made noticeably larger (right panel narrowed further, from 0.32) and
# pushed toward the right edge, with a new header band (cfg.TOP_HEADER_FRAC)
# reserved above the graph for the persistent main title -- see
# build_figure(). The grid itself, and every hex's/label's position within
# it, is completely unchanged; only how much of the frame is reserved around
# it changes.
RIGHT_PANEL_FRAC = 0.24
PANEL_PAD = 0.018
EXTRA_BOTTOM_MARGIN_FRAC = 0.035   # 2026-08-17: extra breathing room below the grid only, see build_figure()

FADE_IN_FRAMES_S = cfg.ITEM_FADE_IN_SECONDS

# axes-fraction y where the graph/right-panel area ends and the persistent
# header band begins (see build_figure()'s ylim extension).
HEADER_BOTTOM = 1 - cfg.TOP_HEADER_FRAC

# Row typography -- 3 rows now (was 5, see cfg.TOP_N_FILMS), so each gets
# meaningfully more room, including up to 2 lines for a long title (see
# wrap_title()).
#
# 2026-08-17 "three-line info block" restyle: each row is exactly title,
# then "Director · Country" tucked close beneath it, then "N connections" on
# its own line -- see set_rows(). Row index 2 (the 3rd/last slot) is, by
# construction of cinematic_history_schedule.py's select_featured_films(),
# ALWAYS either that year's Academy Award Best Picture winner or unused/
# hidden -- never a plain ranked film -- so it alone reserves extra space
# above its title for the "ACADEMY AWARD BEST PICTURE WINNER" label.
ROW_TITLE_FONTSIZE_PX = 23
ROW_CREDIT_FONTSIZE_PX = 13
ROW_LABEL_FONTSIZE_PX = cfg.BEST_PICTURE_LABEL_FONTSIZE_PX
HEADING_FONTSIZE_PX = 21
TITLE_LINE_GAP_FRAC = 0.039              # axes-fraction gap between a title's line 1 and line 2
DIRECTOR_COUNTRY_GAP_1LINE_FRAC = 0.036  # "Director · Country" y-offset below the title when it's 1 line -- tight, per spec
DIRECTOR_COUNTRY_GAP_2LINE_FRAC = 0.075  # ...when the title is 2 lines (keeps it clear of the title's 2nd line)
CONNECTIONS_EXTRA_GAP_FRAC = 0.027       # "N connections" y-offset below the director/country line
BEST_PICTURE_LABEL_DROP_FRAC = 0.031     # row 2 only: how far its title shifts down to make room for the label above it (bumped alongside the larger label fontsize)

HEADING_Y = HEADER_BOTTOM - 0.045   # 2026-08-19: moved up into the space the removed standalone year number left behind (was -0.108)
ROW_TOP_START = HEADER_BOTTOM - 0.095   # 2026-08-19: tightened gap below the heading, per feedback (was -0.195)
ROW_SLOT_HEIGHT = 0.120   # per-row vertical budget -- tightened (was 0.150), still clears a 2-line title + 2 credit lines
SWATCH_MARKERSIZE_PT = 15
SWATCH_TEXT_INSET = 0.038   # how far right of the panel's left edge the title/credit text starts (leaves room for the swatch)
BEST_PICTURE_SWATCH_EDGE_WIDTH_PT = 2.4   # heavier than a normal row's 0.6pt black outline, to read clearly gold
                                          # (2026-09-12: 1.6 -> 2.4, the award ring read too thin at 1080p)

# Clapperboard (2026-08-17 restyle, enlarged 2026-08-19): shares the
# poster's own row, poster narrowed/shifted left to make room for it beside
# -- see build_text_layers().
POSTER_WIDTH_FRAC_OF_BOX = 0.50   # was 0.58 -- gives the clapperboard a bigger share of the row
CLAPPER_GAP_FRAC = 0.014
# 2026-09-08: the clapperboard's own height is capped independently of the
# poster's (was sharing poster_box_height outright, which made it far
# taller than its actual text content needs, per feedback) -- top-aligned
# with the poster, just shorter, so there's a bit of panel background below
# it rather than the board stretching all the way down.
CLAPPER_MAX_HEIGHT_FRAC = 0.20

CHAR_W = 0.56   # approx average glyph advance for bold Helvetica, as a fraction of font-size -- mirrors hex_svg.py's own CHAR_W heuristic for cluster labels


def _char_budget(fontsize_px):
    panel_x0 = 1 - RIGHT_PANEL_FRAC + PANEL_PAD + SWATCH_TEXT_INSET
    panel_x1 = 1 - PANEL_PAD
    text_width_px = (panel_x1 - panel_x0) * cfg.RESOLUTION[0]
    return max(6, int(text_width_px / (fontsize_px * CHAR_W)))


TITLE_MAX_CHARS = _char_budget(ROW_TITLE_FONTSIZE_PX)
CREDIT_MAX_CHARS = _char_budget(ROW_CREDIT_FONTSIZE_PX)


def resolve_ffmpeg_writer(fps, bitrate=8000):
    if shutil.which("ffmpeg") and animation.FFMpegWriter.isAvailable():
        return animation.FFMpegWriter(fps=fps, codec="libx264", bitrate=bitrate,
                                       extra_args=["-pix_fmt", "yuv420p"])
    try:
        import imageio_ffmpeg
        matplotlib.rcParams["animation.ffmpeg_path"] = imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        pass
    if animation.FFMpegWriter.isAvailable():
        return animation.FFMpegWriter(fps=fps, codec="libx264", bitrate=bitrate,
                                       extra_args=["-pix_fmt", "yuv420p"])
    sys.exit("ERROR: no usable ffmpeg found (checked PATH and the imageio_ffmpeg-bundled binary).")


def row_top(i):
    return ROW_TOP_START - i * ROW_SLOT_HEIGHT


def wrap_title(title, max_chars_per_line):
    """Up to 2 lines, never shrunk to fit (spec: "do not shrink the title
    until it becomes difficult to read"). A title that still wouldn't fit in
    2 lines at this width keeps its 2nd line readable by ending in an
    ellipsis, rather than growing a 3rd line or shrinking the font."""
    title = title or ""
    if not title:
        return [""]
    lines = textwrap.wrap(title, width=max_chars_per_line, break_long_words=False) or [title]
    if len(lines) <= 2:
        return lines
    line1 = lines[0]
    rest = title[len(line1):].strip()
    while len(rest) > max_chars_per_line - 1 and rest:
        rest = rest[:-1]
    return [line1, rest.rstrip() + "…"]


def fit_director_country_line(director, country, max_chars):
    """"Director · Country" on its own line, truncating the COUNTRY first
    (with an ellipsis) if it doesn't fit, keeping the director intact --
    only truncating the director too, as an absolute last resort, if the
    director name alone is longer than the whole budget."""
    # criterion_director/criterion_country can come through as a pandas/
    # duckdb NaN float for a missing value, not None -- coerce defensively
    # rather than trust upstream always hands back a clean str-or-None.
    director = director if isinstance(director, str) else ""
    country = country if isinstance(country, str) else ""

    def join(parts):
        return " · ".join(p for p in parts if p)

    full = join([director, country])
    if len(full) <= max_chars or not full:
        return full

    if country:
        c = country
        while c and len(join([director, c])) > max_chars:
            c = c[:-1]
        c = c.rstrip()
        if c != country:
            c = (c[:-1].rstrip() + "…") if len(c) > 1 else "…"
        result = join([director, c])
        if len(result) <= max_chars or not director:
            return result

    d = director
    while d and len(d) > max_chars:
        d = d[:-1]
    d = d.rstrip()
    if d != director:
        d = (d[:-1].rstrip() + "…") if len(d) > 1 else "…"
    return d


def connections_line(connections):
    """"N connections" -- never truncated (always short)."""
    return f"{connections} connection" if connections == 1 else f"{connections} connections"


def hex_outline_segments(q, r, size_factor=HEX_GAP):
    """Closed 6-edge loop tracing one hex's own VISIBLE outline (same
    size_factor as the fill hexes, so it doesn't touch neighboring hexes) --
    used for the golden poster-hex border."""
    cx, cy = axial_to_pixel(q, r, HEX_SIZE)
    corners = hex_corners(cx, cy, HEX_SIZE * size_factor)
    return [(tuple(corners[i]), tuple(corners[(i + 1) % 6])) for i in range(6)]


def compute_fade_multipliers(keys, window_frames):
    """Trapezoid alpha multiplier per frame index: ramps 0->1 over
    `window_frames` after `keys` changes, holds at 1, then ramps 1->0 over
    `window_frames` before `keys` changes again -- except the FINAL run of
    identical keys (nothing plays after it, so there's nothing to fade out
    into) never fades out."""
    n = len(keys)
    if n == 0 or window_frames <= 0:
        return [1.0] * n
    run_remaining = [0] * n
    run_remaining[-1] = 1
    for i in range(n - 2, -1, -1):
        run_remaining[i] = run_remaining[i + 1] + 1 if keys[i] == keys[i + 1] else 1
    since_start = [0] * n
    since_start[0] = 1
    for i in range(1, n):
        since_start[i] = since_start[i - 1] + 1 if keys[i] == keys[i - 1] else 1
    mult = [1.0] * n
    for i in range(n):
        has_successor = (i + run_remaining[i]) < n
        fade_out = 1.0 if not has_successor else min(1.0, run_remaining[i] / window_frames)
        fade_in = min(1.0, since_start[i] / window_frames)
        mult[i] = min(fade_in, fade_out)
    return mult


def compute_fade_out_multipliers(keys, window_frames):
    """Same idea as compute_fade_multipliers(), but fade-out only (no
    fade-in ramp) -- used for the film rows, whose own entrance already has
    its own staggered per-row fade-in from the schedule."""
    n = len(keys)
    if n == 0 or window_frames <= 0:
        return [1.0] * n
    run_remaining = [0] * n
    run_remaining[-1] = 1
    for i in range(n - 2, -1, -1):
        run_remaining[i] = run_remaining[i + 1] + 1 if keys[i] == keys[i + 1] else 1
    mult = [1.0] * n
    for i in range(n):
        has_successor = (i + run_remaining[i]) < n
        mult[i] = 1.0 if not has_successor else min(1.0, run_remaining[i] / window_frames)
    return mult


def build_figure(grid_hexes, hex_set, hex_cluster_map, dpi):
    px_per_pt = dpi / 72.0
    fig = plt.figure(figsize=(FIGURE_WIDTH_IN, FIGURE_HEIGHT_IN), facecolor=cfg.BACKGROUND_COLOR)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_facecolor(cfg.BACKGROUND_COLOR)
    ax.set_aspect("equal")
    ax.axis("off")

    # A single PolyCollection for all ~2300+ hexes -- see the original
    # design note this project has always used: per-hex Patch objects would
    # each pay their own per-object Agg draw overhead on EVERY frame, which
    # is the actual render-time bottleneck at this frame count.
    hex_index = {(q, r): i for i, (q, r) in enumerate(grid_hexes)}
    all_corners = [hex_corners(*axial_to_pixel(q, r, HEX_SIZE), HEX_SIZE * HEX_GAP) for q, r in grid_hexes]
    facecolors = np.tile(to_rgba(cfg.BACKGROUND_COLOR), (len(grid_hexes), 1))
    hex_coll = PolyCollection(all_corners, facecolors=facecolors, edgecolors=cfg.HEX_STROKE_COLOR,
                               linewidths=cfg.HEX_STROKE_WIDTH_PX / px_per_pt, zorder=2)
    ax.add_collection(hex_coll)

    all_px = [axial_to_pixel(q, r, HEX_SIZE) for q, r in grid_hexes]
    xs = [p[0] for p in all_px]
    ys = [p[1] for p in all_px]
    margin = HEX_SIZE * 1.3
    x_min, x_max = min(xs) - margin, max(xs) + margin
    y_min, y_max = min(ys) - margin, max(ys) + margin

    # 2026-08-17: a bit of extra room below the grid ONLY (not top/sides) so
    # the whole header+grid+panel composition reads as vertically centered
    # in the frame rather than the grid crashing right to the bottom edge --
    # per spec, moves the visuals slightly upward without touching the
    # header/title (already sized for the reel above) or horizontal centering.
    y_min -= (y_max - y_min) * EXTRA_BOTTOM_MARGIN_FRAC

    # Reserve the right-hand info-panel column (x) and the top header band
    # (y) by extending xlim/ylim, WITHOUT shrinking or shifting the grid
    # itself -- the grid's own data still only occupies [x_min, x_max] x
    # [y_min, y_max], so panel/header content (placed via transAxes at
    # x >= 1-RIGHT_PANEL_FRAC / y >= 1-cfg.TOP_HEADER_FRAC) can never be
    # drawn over it.
    panel_width = (x_max - x_min) * RIGHT_PANEL_FRAC / (1 - RIGHT_PANEL_FRAC)
    header_height = (y_max - y_min) * cfg.TOP_HEADER_FRAC / (1 - cfg.TOP_HEADER_FRAC)
    ax.set_xlim(x_min, x_max + panel_width)
    ax.set_ylim(y_min, y_max + header_height)

    # Black outline around every individual cluster's own shape (2026-08-08
    # restyle). explore.html itself only separates adjacent clusters with a
    # background-colored gap (see hex_svg.py's boundary_segs, stroke=page
    # background) -- this project draws that exact same adjacency as a real
    # black line instead, so every cluster's silhouette is legible even
    # before any of its hexes are filled in (the opening frame) and stays
    # legible for the rest of the video. Corners come from the SAME
    # unflipped hex_corners() geometry as the hex fills above.
    boundary_segs = []
    for (q, r) in grid_hexes:
        c1 = hex_cluster_map.get((q, r))
        cx, cy = axial_to_pixel(q, r, HEX_SIZE)
        corners = hex_corners(cx, cy, HEX_SIZE)
        for (dq, dr), (ci1, ci2) in EDGE_CORNERS.items():
            nb = (q + dq, r + dr)
            c2 = hex_cluster_map.get(nb)
            if nb in hex_set and c2 is not None and c2 != c1:
                boundary_segs.append((tuple(corners[ci1]), tuple(corners[ci2])))
    boundary_lc = LineCollection(boundary_segs, colors=cfg.CLUSTER_BOUNDARY_COLOR,
                                  linewidths=cfg.CLUSTER_BOUNDARY_WIDTH_PX / px_per_pt,
                                  capstyle="round", joinstyle="round", zorder=3)
    ax.add_collection(boundary_lc)

    segs = outer_perimeter_segments(grid_hexes, hex_set, size=HEX_SIZE)
    lc = LineCollection(segs, colors=cfg.OUTER_BORDER_COLOR,
                         linewidths=cfg.OUTER_BORDER_WIDTH_PX / px_per_pt,
                         capstyle="round", joinstyle="round", zorder=4)
    ax.add_collection(lc)

    # Golden poster-hex border (2026-08-08 restyle; 2026-08-09 made
    # persistent) -- empty until the first poster is on screen; set_segments()
    # is called in render()'s update() whenever a NEW poster hex appears,
    # each time re-drawn for the full accumulated set of every hex that has
    # ever had a poster shown, so borders never disappear once earned.
    poster_border_lc = LineCollection([], colors=cfg.POSTER_HEX_BORDER_COLOR,
                                       linewidths=cfg.POSTER_HEX_BORDER_WIDTH_PX / px_per_pt,
                                       capstyle="round", joinstyle="round", zorder=5)
    ax.add_collection(poster_border_lc)

    xlim = ax.get_xlim()
    # Physical figure width in points (72pt/inch) is dpi-independent, so this
    # "data units -> matplotlib text points" scale factor is too -- see
    # cinematic_history_layout_snapshot.py's cluster_labels for the
    # data-unit font sizes this converts.
    pts_per_data_unit = FIGURE_WIDTH_IN * 72.0 / (xlim[1] - xlim[0])

    return dict(fig=fig, ax=ax, hex_coll=hex_coll, hex_index=hex_index, facecolors=facecolors,
                px_per_pt=px_per_pt, poster_border_lc=poster_border_lc, pts_per_data_unit=pts_per_data_unit)


def build_text_layers(ax, px_per_pt, pts_per_data_unit, cluster_labels_data):
    panel_x0 = 1 - RIGHT_PANEL_FRAC + PANEL_PAD
    panel_x1 = 1 - PANEL_PAD

    # Persistent main title (2026-08-08 restyle): its own header space,
    # visible frame 1 through the final frame (alpha never changes) -- see
    # cfg.MAIN_TITLE_TEXT. 2026-08-19: centered on the GRAPH area only (0 to
    # 1-RIGHT_PANEL_FRAC), not the full frame -- centering on the whole
    # frame put it noticeably right of the graph's own center (the right
    # panel skews the frame's true center away from the graph), and once
    # off-center it also collided with the reel (now living to the right of
    # it, roughly on the same row). Positioned near the BOTTOM of the header
    # band (not its vertical center) so the reel has clear room above it,
    # within the same band, without the two overlapping.
    title_x = (1 - RIGHT_PANEL_FRAC) / 2
    header_text = ax.text(title_x, HEADER_BOTTOM + cfg.MAIN_TITLE_Y_ABOVE_HEADER_BOTTOM_FRAC, cfg.MAIN_TITLE_TEXT,
                           transform=ax.transAxes, fontsize=cfg.MAIN_TITLE_FONTSIZE_PX / px_per_pt,
                           fontweight="bold", color=cfg.MAIN_TITLE_COLOR, va="center", ha="center",
                           zorder=20, alpha=1.0)

    # 2026-08-19: the standalone year number above this heading was removed
    # -- the film reel (top-right, see build_reel()) now carries the
    # current year on its own, so repeating it here was redundant.
    heading_text = ax.text(panel_x0, HEADING_Y, "", transform=ax.transAxes,
                            fontsize=HEADING_FONTSIZE_PX / px_per_pt, fontweight="bold",
                            color=cfg.YEAR_TEXT_COLOR, va="top", ha="left", zorder=10)

    rows = []
    # See module docstring / cinematic_history_schedule.py's
    # select_featured_films(): the 3rd row is always either that year's Best
    # Picture winner or unused -- never a plain ranked film -- so it alone
    # reserves label space above its title and gets a gold (not black)
    # swatch outline.
    BEST_PICTURE_ROW_INDEX = 2
    for i in range(cfg.TOP_N_FILMS):
        top = row_top(i)
        is_bp_slot = (i == BEST_PICTURE_ROW_INDEX)
        title_y = (top - BEST_PICTURE_LABEL_DROP_FRAC) if is_bp_slot else top
        x = panel_x0 + SWATCH_TEXT_INSET

        bp_label = None
        if is_bp_slot:
            bp_label = ax.text(x, top, "", transform=ax.transAxes,
                                fontsize=ROW_LABEL_FONTSIZE_PX / px_per_pt, fontweight="bold",
                                color=cfg.BEST_PICTURE_LABEL_COLOR, va="top", ha="left", zorder=10, alpha=0.0)

        swatch_edge_color = cfg.POSTER_HEX_BORDER_COLOR if is_bp_slot else "#000000"
        swatch_edge_width = BEST_PICTURE_SWATCH_EDGE_WIDTH_PT if is_bp_slot else 0.6
        swatch, = ax.plot([panel_x0 + 0.012], [title_y - 0.020], marker=(6, 0, 0),
                           markersize=SWATCH_MARKERSIZE_PT, markerfacecolor="none",
                           markeredgecolor=swatch_edge_color, markeredgewidth=swatch_edge_width / px_per_pt,
                           transform=ax.transAxes, linestyle="none", zorder=11, alpha=0.0)
        title_l1 = ax.text(x, title_y, "", transform=ax.transAxes,
                            fontsize=ROW_TITLE_FONTSIZE_PX / px_per_pt, fontweight="bold",
                            color=cfg.CARD_TITLE_COLOR, va="top", ha="left", zorder=10, alpha=0.0)
        title_l2 = ax.text(x, title_y - TITLE_LINE_GAP_FRAC, "", transform=ax.transAxes,
                            fontsize=ROW_TITLE_FONTSIZE_PX / px_per_pt, fontweight="bold",
                            color=cfg.CARD_TITLE_COLOR, va="top", ha="left", zorder=10, alpha=0.0)
        director_country = ax.text(x, title_y - DIRECTOR_COUNTRY_GAP_1LINE_FRAC, "", transform=ax.transAxes,
                                    fontsize=ROW_CREDIT_FONTSIZE_PX / px_per_pt,
                                    color=cfg.CARD_TEXT_COLOR, va="top", ha="left", zorder=10, alpha=0.0)
        connections_text_artist = ax.text(x, title_y - DIRECTOR_COUNTRY_GAP_1LINE_FRAC - CONNECTIONS_EXTRA_GAP_FRAC,
                                           "", transform=ax.transAxes, fontsize=ROW_CREDIT_FONTSIZE_PX / px_per_pt,
                                           color=cfg.CARD_TEXT_COLOR, va="top", ha="left", zorder=10, alpha=0.0)
        rows.append(dict(swatch=swatch, title_l1=title_l1, title_l2=title_l2,
                          director_country=director_country, connections=connections_text_artist,
                          bp_label=bp_label, top=top, title_y=title_y, x=x))

    # Sized/positioned to clear the last row's own worst case (a 2-line
    # title, plus its label) with a safety gap, then kept low in the panel
    # near the bottom. 2026-08-17: narrowed/shifted left (from the full
    # panel width) to make room for the clapperboard beside it -- see
    # CLAPPER_GAP_FRAC/POSTER_WIDTH_FRAC_OF_BOX below.
    poster_box_y0 = 0.02
    last_title_y = row_top(cfg.TOP_N_FILMS - 1) - BEST_PICTURE_LABEL_DROP_FRAC
    last_row_bottom = last_title_y - DIRECTOR_COUNTRY_GAP_2LINE_FRAC - CONNECTIONS_EXTRA_GAP_FRAC
    poster_box_height = max(0.16, min(0.30, last_row_bottom - poster_box_y0 - 0.03))
    panel_width = panel_x1 - panel_x0
    poster_box_width = panel_width * POSTER_WIDTH_FRAC_OF_BOX
    poster_ax = ax.inset_axes([panel_x0, poster_box_y0, poster_box_width, poster_box_height],
                               transform=ax.transAxes)
    poster_ax.set_facecolor(cfg.BACKGROUND_COLOR)
    poster_ax.axis("off")
    for spine in poster_ax.spines.values():
        spine.set_visible(False)

    # Clapperboard: own (shorter) height, top-aligned with the poster --
    # see CLAPPER_MAX_HEIGHT_FRAC.
    clapper_height = min(poster_box_height, CLAPPER_MAX_HEIGHT_FRAC)
    clapper_y0 = poster_box_y0 + poster_box_height - clapper_height
    clapper_x0 = panel_x0 + poster_box_width + CLAPPER_GAP_FRAC
    clapper_box = (clapper_x0, clapper_y0, panel_x1 - clapper_x0, clapper_height)

    # Cluster labels (2026-08-17 restyle: always-on from frame 1): one
    # (potentially multi-line) Text per cluster, in DATA coordinates
    # (matching hex placement, NOT the axes-fraction right panel),
    # positioned/sized/colored/wrapped exactly as read off explore.html by
    # cinematic_history_layout_snapshot.py (cluster_labels_data). Per spec,
    # every cluster name must already be visible in its permanent position
    # at 0:00, not animated in later -- alpha=1.0 from creation, never
    # changed after (see render()'s update(), which no longer touches these).
    cluster_label_lines = {}
    for cluster_id, data in cluster_labels_data.items():
        color = cfg.CLUSTER_LABEL_ON_DARK_COLOR if data["on_dark"] else cfg.CLUSTER_LABEL_ON_LIGHT_COLOR
        scale = cfg.CLUSTER_LABEL_SCALE.get(cluster_id, 1.0)
        fontsize_pt = data["fontsize"] * pts_per_data_unit * scale
        stroke_fx = ([patheffects.withStroke(linewidth=fontsize_pt * 0.09,
                                              foreground=cfg.CLUSTER_LABEL_STROKE_COLOR)]
                     if data["on_dark"] else None)
        # The snapshot's per-line y values were spaced for the snapshot's own
        # font size (line_gap = fontsize * 1.2). Scaling the font without
        # scaling that gap would run a multi-line label's lines into each
        # other, so each line's offset from the block's center is scaled by
        # the same factor, keeping the block centered where it already sits.
        ys = [line["y"] for line in data["lines"]]
        y_mid = (max(ys) + min(ys)) / 2
        artists = []
        for line in data["lines"]:
            y = y_mid + (line["y"] - y_mid) * scale
            t = ax.text(line["x"], y, line["text"], fontsize=fontsize_pt, fontweight="bold",
                         color=color, va="center", ha="center", zorder=12, alpha=1.0,
                         path_effects=stroke_fx)
            artists.append(t)
        cluster_label_lines[cluster_id] = artists

    return dict(header_text=header_text, heading_text=heading_text,
                rows=rows, poster_ax=poster_ax, clapper_box=clapper_box,
                cluster_label_lines=cluster_label_lines)


def set_rows(layers, rows_state, period_font=None):
    """rows_state: up to cfg.TOP_N_FILMS dicts (title, director, country,
    connections, swatch_color, is_best_picture, alpha), in reveal order. Any
    row slot beyond len(rows_state) is hidden. Row index 2 is always either
    that year's Best Picture winner or unused (see build_text_layers()) --
    its "ACADEMY AWARD BEST PICTURE WINNER" label fades with the rest of
    that slot's content.

    period_font: family name for the title lines only (see font_for_year())
    -- every row shown together is always from the SAME schedule year (top-2
    + that year's Best Picture winner), so one family covers the whole call.
    None leaves the title's font family untouched (used for the title-phase
    all-hidden call, where it doesn't matter)."""
    for i, row in enumerate(layers["rows"]):
        if i < len(rows_state):
            r = rows_state[i]
            lines = wrap_title(r["title"], TITLE_MAX_CHARS)
            l1 = lines[0] if lines else ""
            l2 = lines[1] if len(lines) > 1 else ""
            director_country_text = fit_director_country_line(r["director"], r["country"], CREDIT_MAX_CHARS)
            connections_text = connections_line(r["connections"])

            if period_font is not None:
                row["title_l1"].set_fontfamily(period_font)
                row["title_l2"].set_fontfamily(period_font)
            row["title_l1"].set_text(l1)
            row["title_l1"].set_alpha(r["alpha"])
            row["title_l2"].set_text(l2)
            row["title_l2"].set_alpha(r["alpha"] if l2 else 0.0)
            dc_gap = DIRECTOR_COUNTRY_GAP_2LINE_FRAC if l2 else DIRECTOR_COUNTRY_GAP_1LINE_FRAC
            dc_y = row["title_y"] - dc_gap
            row["director_country"].set_position((row["x"], dc_y))
            row["director_country"].set_text(director_country_text)
            row["director_country"].set_alpha(r["alpha"])
            row["connections"].set_position((row["x"], dc_y - CONNECTIONS_EXTRA_GAP_FRAC))
            row["connections"].set_text(connections_text)
            row["connections"].set_alpha(r["alpha"])
            row["swatch"].set_alpha(r["alpha"])
            row["swatch"].set_markerfacecolor(r["swatch_color"] if r["swatch_color"] is not None else "none")
            if row["bp_label"] is not None:
                row["bp_label"].set_text(cfg.BEST_PICTURE_LABEL_TEXT)
                row["bp_label"].set_alpha(r["alpha"])
        else:
            row["title_l1"].set_alpha(0.0)
            row["title_l2"].set_alpha(0.0)
            row["director_country"].set_alpha(0.0)
            row["connections"].set_alpha(0.0)
            row["swatch"].set_alpha(0.0)
            if row["bp_label"] is not None:
                row["bp_label"].set_alpha(0.0)


# ── Film reel + year display (2026-08-19 restyle) ───────────────────────────
# Right side of the header, roughly on the title's own row. A continuously
# spinning disc with a straight (no bend/curve) black film strip emerging
# directly from its rim, carrying the current year. Positions here are
# FIGURE INCHES (fig.dpi_scale_trans: origin bottom-left of the whole
# FIGURE_WIDTH_IN x FIGURE_HEIGHT_IN figure, y up), not axes-fraction -- the
# figure is 16:9, not square, so a "circle" drawn with equal x/y radius in
# transAxes fractions would render as an ellipse; inches share one physical
# scale in both directions, giving true circles for the hub/rim/sprockets
# regardless of dpi.
REEL_CENTER_X_IN = 12.6
REEL_CENTER_Y_IN = 7.85
REEL_OUTER_RADIUS_IN = 0.46
REEL_HUB_RADIUS_IN = 0.095
REEL_SPOKE_HOLE_RADIUS_IN = 0.07
REEL_SPOKE_HOLE_DIST_IN = 0.29

# Real-film-strip proportions: wide cell (room for a 4-digit year with
# margin), sprockets confined to a thin top/bottom margin, cells butt
# directly against each other (no gap) so the strip reads as one continuous
# piece, never separate blocks.
STRIP_CELL_WIDTH_IN = 1.05
STRIP_CELL_HEIGHT_IN = 0.52
STRIP_PITCH_IN = STRIP_CELL_WIDTH_IN   # zero gap between cells
STRIP_SPROCKET_MARGIN_FRAC = 0.15   # fraction of cell height reserved for perforations, top and bottom each
STRIP_SPROCKET_COUNT = 7            # per edge

# Disc on the left of the assembly, film feeds RIGHTWARD out from behind it.
# STRIP_ORIGIN_X_IN is the disc's own RIM (not its center) -- a cell's LEFT
# EDGE is clamped to never sit left of this, so no part of any cell can ever
# poke out past the wheel (half the cell width is wider than the disc's
# radius, so anchoring at the center alone wouldn't be enough).
STRIP_ORIGIN_X_IN = REEL_CENTER_X_IN + REEL_OUTER_RADIUS_IN
STRIP_VISIBLE_RIGHT_IN = 15.8   # near the frame's right edge
STRIP_POOL_SIZE = 9


def reel_year_slot(year):
    """Integer world-slot index for `year` along the strip -- None (the
    title-phase pseudo-slot) is slot 0; consecutive years are always
    (1 + cfg.REEL_BLANK_CELLS_BETWEEN_YEARS) slots apart, so that many blank
    cells sit physically between one year's cell and the next, every time."""
    spacing = 1 + cfg.REEL_BLANK_CELLS_BETWEEN_YEARS
    if year is None:
        return 0
    return spacing * (year - cfg.START_YEAR + 1)


def _smoothstep(t):
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return t * t * (3 - 2 * t)


def compute_reel_scroll(frames, fps):
    """-> numpy float array, one world-slot position per frame (see
    reel_year_slot()), using the SCHEDULE'S OWN real per-year frame
    boundaries as landmarks -- never a fixed/arbitrary duration, so it can't
    drift across the video's full length.

    Two eased phases per year, NOT one spline/line across the whole gap: a
    SETTLE phase (the bulk of that year's own duration) where the cell
    drifts only a small, fixed distance (cfg.REEL_SETTLE_DRIFT_IN)
    regardless of how long the year is on screen -- so it stays inside the
    visible/legible window and never disappears before that year's own
    films are done revealing -- followed by a short, fixed-duration
    TRANSITION phase (cfg.REEL_TRANSITION_SECONDS, clamped to whatever time
    a thin/empty year actually has) where it sweeps the rest of the way to
    the next slot (showing several blank cells pass) and lands exactly on
    the real transition frame. Both phases ease with a smoothstep, and each
    one's own velocity is 0 at both of its endpoints, so consecutive phases
    (settle -> transition, and one year's transition -> the next year's
    settle) always meet at matching (zero) velocity -- continuous
    everywhere, no abrupt speed changes, while never holding at a literal,
    sustained standstill."""
    n = len(frames)
    landmarks = [(None, 0)]
    prev_year = None
    for i, f in enumerate(frames):
        y = f["year"]
        if y is not None and y != prev_year:
            landmarks.append((y, i))
        prev_year = y

    settle_drift_slots = cfg.REEL_SETTLE_DRIFT_IN / STRIP_PITCH_IN
    transition_frames_desired = max(1, round(cfg.REEL_TRANSITION_SECONDS * fps))
    scroll = np.empty(n, dtype=float)
    for idx, (year_a, frame_a) in enumerate(landmarks):
        slot_a = reel_year_slot(year_a)
        if idx + 1 >= len(landmarks):
            scroll[frame_a:n] = slot_a
            continue
        year_b, frame_b = landmarks[idx + 1]
        slot_b = reel_year_slot(year_b)
        gap = frame_b - frame_a
        transition_frames = min(transition_frames_desired, gap)
        settle_frames = gap - transition_frames
        settle_target = slot_a + min(settle_drift_slots, (slot_b - slot_a) * 0.3)

        for t in range(frame_a, frame_a + settle_frames):
            frac = _smoothstep((t - frame_a + 1) / max(1, settle_frames))
            scroll[t] = slot_a + (settle_target - slot_a) * frac
        for t in range(frame_a + settle_frames, frame_b):
            frac = _smoothstep((t - (frame_a + settle_frames) + 1) / max(1, transition_frames))
            scroll[t] = settle_target + (slot_b - settle_target) * frac
    return scroll


def compute_reel_year_start_frames(frames):
    """-> {year: first_frame_index}, for the year-fade-in timer (see
    update_reel()) -- a separate, TIME-based reveal, not tied to position,
    since the settle phase above deliberately only drifts a tiny fixed
    distance regardless of how long it lasts."""
    start_frame = {}
    prev_year = None
    for i, f in enumerate(frames):
        y = f["year"]
        if y is not None and y != prev_year:
            start_frame[y] = i
        prev_year = y
    return start_frame


def build_reel(fig, px_per_pt):
    """Creates every reel/film-strip artist once; update_reel() repositions
    them every frame. Added to `ax` (not the bare Figure) so they share its
    zorder/paint order with everything else -- ax already spans the whole
    figure (see build_figure()), so figure-inches coordinates here are never
    clipped."""
    ax = fig.axes[0]
    tr = fig.dpi_scale_trans

    strip_cells = []
    for _ in range(STRIP_POOL_SIZE):
        rect = plt.Rectangle((0, 0), STRIP_CELL_WIDTH_IN, STRIP_CELL_HEIGHT_IN,
                              facecolor=cfg.REEL_FILM_STRIP_COLOR, edgecolor="none",
                              transform=tr, zorder=30, alpha=0.0)
        ax.add_patch(rect)
        holes = []
        for _ in range(STRIP_SPROCKET_COUNT * 2):
            h = plt.Rectangle((0, 0), 0.045, STRIP_CELL_HEIGHT_IN * STRIP_SPROCKET_MARGIN_FRAC * 0.55,
                               facecolor=cfg.REEL_SPROCKET_COLOR, edgecolor="none",
                               transform=tr, zorder=31, alpha=0.0)
            ax.add_patch(h)
            holes.append(h)
        year_text = ax.text(0, 0, "", transform=tr, ha="center", va="center",
                             fontsize=25 / px_per_pt, fontweight="bold",
                             color=cfg.REEL_YEAR_TEXT_COLOR, zorder=32, alpha=0.0)
        strip_cells.append(dict(rect=rect, holes=holes, year_text=year_text))

    # Reel disc drawn ABOVE the strip (higher zorder) so the strip visibly
    # emerges from behind it, not merely beside it.
    rim = plt.Circle((REEL_CENTER_X_IN, REEL_CENTER_Y_IN), REEL_OUTER_RADIUS_IN,
                      facecolor=cfg.BACKGROUND_COLOR, edgecolor=cfg.REEL_FILM_STRIP_COLOR,
                      linewidth=3.0, transform=tr, zorder=40)
    ax.add_patch(rim)
    spokes = []
    for _ in range(cfg.REEL_SPOKE_COUNT):
        line, = ax.plot([0, 0], [0, 0], color=cfg.REEL_FILM_STRIP_COLOR, linewidth=5.5,
                         solid_capstyle="round", transform=tr, zorder=41)
        spokes.append(line)
    spoke_holes = []
    for _ in range(cfg.REEL_SPOKE_COUNT):
        hole = plt.Circle((0, 0), REEL_SPOKE_HOLE_RADIUS_IN, facecolor=cfg.BACKGROUND_COLOR,
                           edgecolor=cfg.REEL_FILM_STRIP_COLOR, linewidth=1.3, transform=tr, zorder=42)
        ax.add_patch(hole)
        spoke_holes.append(hole)
    hub = plt.Circle((REEL_CENTER_X_IN, REEL_CENTER_Y_IN), REEL_HUB_RADIUS_IN,
                      facecolor=cfg.REEL_FILM_STRIP_COLOR, edgecolor="none", transform=tr, zorder=43)
    ax.add_patch(hub)

    return dict(strip_cells=strip_cells, rim=rim, spokes=spokes, spoke_holes=spoke_holes, hub=hub)


def update_reel(reel_layers, frame_index, scroll, fps, active_year, active_year_start_frame):
    S = scroll[frame_index]
    active_slot = reel_year_slot(active_year) if active_year is not None else None
    # Visible range is one-sided (m <= S only -- m > S is still behind the
    # disc), so the pool covers S downward, not centered on S.
    base_m = int(np.floor(S)) - (STRIP_POOL_SIZE - 3)

    sprocket_h = STRIP_CELL_HEIGHT_IN * STRIP_SPROCKET_MARGIN_FRAC * 0.55
    inset = STRIP_CELL_WIDTH_IN * 0.10
    usable = STRIP_CELL_WIDTH_IN - 2 * inset
    xs_offsets = [-usable / 2 + usable * k / (STRIP_SPROCKET_COUNT - 1) for k in range(STRIP_SPROCKET_COUNT)]
    y_in = REEL_CENTER_Y_IN   # perfectly straight -- no bend/curve

    for pool_i, cell in enumerate(reel_layers["strip_cells"]):
        m = base_m + pool_i
        # A slot's natural LEFT EDGE crosses the disc's rim the instant S
        # reaches it, then moves right (away from the disc) as S keeps
        # increasing. The very next slot in line is ALREADY partially past
        # the rim before its own "natural" left edge clears it -- clipped
        # to start exactly at the rim (a growing sliver) instead of hidden
        # outright, so the strip stays flush against the disc with no gap.
        x_left_natural = STRIP_ORIGIN_X_IN + (S - m) * STRIP_PITCH_IN
        x_right_natural = x_left_natural + STRIP_CELL_WIDTH_IN
        fully_emerged = x_left_natural >= STRIP_ORIGIN_X_IN
        if x_right_natural <= STRIP_ORIGIN_X_IN or x_left_natural > STRIP_VISIBLE_RIGHT_IN:
            cell["rect"].set_alpha(0.0)
            for h in cell["holes"]:
                h.set_alpha(0.0)
            cell["year_text"].set_alpha(0.0)
            continue

        draw_left = max(x_left_natural, STRIP_ORIGIN_X_IN)
        draw_right = min(x_right_natural, STRIP_VISIBLE_RIGHT_IN)
        cell["rect"].set_xy((draw_left, y_in - STRIP_CELL_HEIGHT_IN / 2))
        cell["rect"].set_width(draw_right - draw_left)
        cell["rect"].set_alpha(1.0)

        x_in = x_left_natural + STRIP_CELL_WIDTH_IN / 2   # true center, meaningful once fully emerged
        if fully_emerged:
            top_y = y_in + STRIP_CELL_HEIGHT_IN / 2 - sprocket_h - STRIP_CELL_HEIGHT_IN * 0.03
            bot_y = y_in - STRIP_CELL_HEIGHT_IN / 2 + STRIP_CELL_HEIGHT_IN * 0.03
            for k in range(STRIP_SPROCKET_COUNT):
                cell["holes"][k].set_xy((x_in + xs_offsets[k] - 0.0225, top_y))
                cell["holes"][k].set_alpha(1.0)
                cell["holes"][STRIP_SPROCKET_COUNT + k].set_xy((x_in + xs_offsets[k] - 0.0225, bot_y))
                cell["holes"][STRIP_SPROCKET_COUNT + k].set_alpha(1.0)
        else:
            for h in cell["holes"]:
                h.set_alpha(0.0)

        if m == active_slot and fully_emerged:
            # Gradual reveal: the year starts invisible right as it emerges
            # and fades up to full opacity over a short, fixed TIME window
            # -- not distance, since the settle phase only drifts a tiny
            # fixed distance regardless of how long it lasts.
            fade_in_frames = max(1, round(cfg.REEL_YEAR_FADE_IN_SECONDS * fps))
            reveal = (frame_index - active_year_start_frame) / fade_in_frames
            reveal = 0.0 if reveal < 0.0 else (1.0 if reveal > 1.0 else reveal)
            cell["year_text"].set_text(str(active_year))
            cell["year_text"].set_position((x_in, y_in))
            cell["year_text"].set_alpha(reveal)
        else:
            cell["year_text"].set_alpha(0.0)

    angle = (frame_index / fps) * cfg.REEL_ROTATION_DEGREES_PER_SECOND
    n_spokes = cfg.REEL_SPOKE_COUNT
    for k, spoke in enumerate(reel_layers["spokes"]):
        a = math.radians(angle + k * (360.0 / n_spokes))
        dx, dy = math.cos(a), math.sin(a)
        spoke.set_data([REEL_CENTER_X_IN + dx * REEL_HUB_RADIUS_IN, REEL_CENTER_X_IN + dx * (REEL_OUTER_RADIUS_IN - 0.05)],
                        [REEL_CENTER_Y_IN + dy * REEL_HUB_RADIUS_IN, REEL_CENTER_Y_IN + dy * (REEL_OUTER_RADIUS_IN - 0.05)])
    for k, hole in enumerate(reel_layers["spoke_holes"]):
        a = math.radians(angle + k * (360.0 / n_spokes) + (360.0 / n_spokes) / 2)
        hole.center = (REEL_CENTER_X_IN + math.cos(a) * REEL_SPOKE_HOLE_DIST_IN,
                       REEL_CENTER_Y_IN + math.sin(a) * REEL_SPOKE_HOLE_DIST_IN)


# ── Clapperboard (2026-08-17 restyle) ───────────────────────────────────────
# Shares the poster's own row (see build_text_layers()'s narrowed poster_ax
# + clapper_box), showing whichever film's poster is currently on screen:
# director (from the DB), studio + full release date (TMDB-sourced, see
# build_best_picture_details.py / cinematic_history_posters.py's `details`).


def format_release_date(date_str):
    """"1927-08-12" -> "August 12, 1927"; blank/unparseable input -> ""."""
    if not date_str:
        return ""
    try:
        from datetime import datetime
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%B %-d, %Y")
    except (ValueError, TypeError):
        return date_str


def _clapper_char_budget(width_in, fontsize_px):
    avail_px = width_in * (cfg.RESOLUTION[0] / FIGURE_WIDTH_IN)
    return max(6, int(avail_px / (fontsize_px * CHAR_W)))


# Dynamic vertical layout (see update_clapperboard()): a director/studio
# name that wraps to a 2nd line pushes everything below it down instead of
# a name ever being cut off with an ellipsis.
CLAPPER_LABEL_LINE_H_IN = 0.125
CLAPPER_VALUE_LINE_H_IN = 0.145
CLAPPER_SECTION_GAP_IN = 0.06   # around each separating rule


def build_clapperboard(fig, px_per_pt, box):
    """box: (x0_frac, y0_frac, w_frac, h_frac) in transAxes fraction (from
    build_text_layers()'s clapper_box, alongside the poster it shares a row
    with) -- converted to figure-inches here for the same true-rectangle/
    consistent-dpi reasons as build_reel()."""
    ax = fig.axes[0]
    tr = fig.dpi_scale_trans
    x0_frac, y0_frac, w_frac, h_frac = box
    x0_in, y0_in = x0_frac * FIGURE_WIDTH_IN, y0_frac * FIGURE_HEIGHT_IN
    w_in, h_in = w_frac * FIGURE_WIDTH_IN, h_frac * FIGURE_HEIGHT_IN
    bar_h_in = min(0.26, h_in * 0.16)

    body = plt.Rectangle((x0_in, y0_in), w_in, h_in - bar_h_in - 0.03,
                          facecolor=cfg.CLAPPERBOARD_BODY_COLOR, edgecolor=cfg.CLAPPERBOARD_STRIPE_LIGHT,
                          linewidth=0.8, transform=tr, zorder=30, alpha=0.0)
    ax.add_patch(body)

    # The clapper "stick"/arm -- hinged at its bottom-left corner (where it
    # meets the body) and rotated OPEN by cfg.CLAPPERBOARD_OPEN_ANGLE_DEG,
    # rather than sitting flat/closed on top of the body.
    hinge_x, hinge_y = x0_in, y0_in + h_in - bar_h_in
    # A hatched patch does NOT honour set_alpha(): matplotlib strokes the
    # hatch lines at full opacity regardless, so the striped bar stayed
    # visible over the empty background for the whole pre-1927 stretch of
    # the video (before any Best Picture poster exists) even though every
    # other clapperboard artist was correctly at alpha 0. Its opacity is
    # driven through RGBA face/edge colours instead -- which the hatch does
    # honour -- with set_alpha pinned to None so it can't re-enter the
    # broken path, plus set_visible() as a hard off switch. See
    # update_clapperboard().
    bar = plt.Rectangle((x0_in, hinge_y), w_in, bar_h_in,
                         hatch="////", linewidth=0.0, zorder=31)
    bar.set_alpha(None)
    bar.set_facecolor(to_rgba(cfg.CLAPPERBOARD_STRIPE_DARK, 0.0))
    bar.set_edgecolor(to_rgba(cfg.CLAPPERBOARD_STRIPE_LIGHT, 0.0))
    bar.set_visible(False)
    bar.set_transform(Affine2D().rotate_deg_around(hinge_x, hinge_y, cfg.CLAPPERBOARD_OPEN_ANGLE_DEG) + tr)
    ax.add_patch(bar)

    text_x = x0_in + w_in * 0.10
    sep_x0, sep_x1 = x0_in + w_in * 0.08, x0_in + w_in * 0.92
    label_fontsize_pt = cfg.CLAPPERBOARD_LABEL_FONTSIZE_PX / px_per_pt
    value_fontsize_pt = cfg.CLAPPERBOARD_VALUE_FONTSIZE_PX / px_per_pt
    top_y = hinge_y - 0.11   # hinge_y, not the rotated bar's own extent -- opening the bar only ever lifts it away from the body, never lower

    def mk_text(fontsize_pt):
        return ax.text(text_x, 0, "", transform=tr, fontsize=fontsize_pt, fontweight="bold",
                        color=cfg.CLAPPERBOARD_TEXT_COLOR, va="top", ha="left", zorder=32, alpha=0.0)

    director_label = mk_text(label_fontsize_pt)
    director_label.set_text("DIRECTOR")
    director_l1 = mk_text(value_fontsize_pt)
    director_l2 = mk_text(value_fontsize_pt)
    studio_label = mk_text(label_fontsize_pt)
    studio_label.set_text("STUDIO")
    studio_l1 = mk_text(value_fontsize_pt)
    studio_l2 = mk_text(value_fontsize_pt)
    date_value = mk_text(value_fontsize_pt)

    sep1, = ax.plot([], [], color=cfg.CLAPPERBOARD_TEXT_COLOR, linewidth=0.8, alpha=0.0, transform=tr, zorder=32)
    sep2, = ax.plot([], [], color=cfg.CLAPPERBOARD_TEXT_COLOR, linewidth=0.8, alpha=0.0, transform=tr, zorder=32)

    max_chars = _clapper_char_budget(w_in * 0.84, cfg.CLAPPERBOARD_VALUE_FONTSIZE_PX)

    return dict(body=body, bar=bar, director_label=director_label, director_l1=director_l1, director_l2=director_l2,
                studio_label=studio_label, studio_l1=studio_l1, studio_l2=studio_l2, date_value=date_value,
                sep1=sep1, sep2=sep2, max_chars=max_chars, text_x=text_x, sep_x0=sep_x0, sep_x1=sep_x1, top_y=top_y)


def update_clapperboard(c, details, alpha):
    all_artists = (c["body"], c["bar"], c["director_label"], c["director_l1"], c["director_l2"],
                   c["studio_label"], c["studio_l1"], c["studio_l2"], c["date_value"], c["sep1"], c["sep2"])
    visible = alpha > 0.0
    for a in all_artists:
        if a is not c["bar"]:
            a.set_alpha(alpha)
        a.set_visible(visible)
    # The hatched bar fades through its own RGBA colours -- set_alpha() is a
    # no-op on a hatch (see build_clapperboard()).
    c["bar"].set_facecolor(to_rgba(cfg.CLAPPERBOARD_STRIPE_DARK, alpha))
    c["bar"].set_edgecolor(to_rgba(cfg.CLAPPERBOARD_STRIPE_LIGHT, alpha))
    if not visible:
        return

    details = details or {}
    # wrap_title() already does exactly what's needed here: up to 2 lines,
    # ellipsis only as an absolute last resort -- never a silent truncation
    # of a name that would otherwise fit on a 2nd line.
    director_lines = wrap_title(details.get("director") or "", c["max_chars"])
    studio_lines = wrap_title(details.get("studio") or "", c["max_chars"])

    x = c["text_x"]
    y = c["top_y"]

    c["director_label"].set_position((x, y))
    y -= CLAPPER_LABEL_LINE_H_IN
    c["director_l1"].set_text(director_lines[0] if director_lines else "")
    c["director_l1"].set_position((x, y))
    y -= CLAPPER_VALUE_LINE_H_IN
    if len(director_lines) > 1:
        c["director_l2"].set_text(director_lines[1])
        c["director_l2"].set_position((x, y))
        c["director_l2"].set_alpha(alpha)
        y -= CLAPPER_VALUE_LINE_H_IN
    else:
        c["director_l2"].set_alpha(0.0)

    y -= CLAPPER_SECTION_GAP_IN * 0.5
    c["sep1"].set_data([c["sep_x0"], c["sep_x1"]], [y, y])
    y -= CLAPPER_SECTION_GAP_IN * 0.5

    c["studio_label"].set_position((x, y))
    y -= CLAPPER_LABEL_LINE_H_IN
    c["studio_l1"].set_text(studio_lines[0] if studio_lines else "")
    c["studio_l1"].set_position((x, y))
    y -= CLAPPER_VALUE_LINE_H_IN
    if len(studio_lines) > 1:
        c["studio_l2"].set_text(studio_lines[1])
        c["studio_l2"].set_position((x, y))
        c["studio_l2"].set_alpha(alpha)
        y -= CLAPPER_VALUE_LINE_H_IN
    else:
        c["studio_l2"].set_alpha(0.0)

    y -= CLAPPER_SECTION_GAP_IN * 0.5
    c["sep2"].set_data([c["sep_x0"], c["sep_x1"]], [y, y])
    y -= CLAPPER_SECTION_GAP_IN * 0.5

    c["date_value"].set_text(format_release_date(details.get("release_date")))
    c["date_value"].set_position((x, y))


_POSTER_IMAGE_CACHE = {}
# Source posters are ~500x750px; the panel only ever displays one at roughly
# 140x210px (constrained by the panel's own box height, not the image's
# native resolution -- see poster_ax's inset_axes call above). Every frame
# during a poster's ~10s+ on-screen run redraws it at full canvas res
# (blit=False repaints the whole figure every frame), so resampling a
# 500x750 source down to display size on EVERY one of those frames was a
# real, measured render-time cost across the video's ~97 poster years.
# Downsampling once here, to comfortably above actual display size rather
# than to the exact pixel count, keeps it sharp while cutting that per-frame
# resampling cost by roughly 5x.
POSTER_CACHE_MAX_SIZE = (220, 330)


def load_poster_image(path):
    if path not in _POSTER_IMAGE_CACHE:
        from PIL import Image
        with Image.open(path) as im:
            im.thumbnail(POSTER_CACHE_MAX_SIZE, Image.LANCZOS)
            _POSTER_IMAGE_CACHE[path] = np.asarray(im.convert("RGB"))
    return _POSTER_IMAGE_CACHE[path]


def render(schedule, output_path, dpi, frame_slice=None):
    frames = schedule["frames"]
    fps = schedule["fps"]

    poster_full_index = build_poster_index()
    poster_index = poster_full_index["resolved"]
    poster_details = poster_full_index["details"]

    fig_data = build_figure(schedule["grid_hexes"], schedule["hex_set"], schedule["hex_cluster_map"], dpi)
    fig, ax = fig_data["fig"], fig_data["ax"]
    hex_coll, hex_index, facecolors = fig_data["hex_coll"], fig_data["hex_index"], fig_data["facecolors"]
    px_per_pt, poster_border_lc = fig_data["px_per_pt"], fig_data["poster_border_lc"]
    layers = build_text_layers(ax, px_per_pt, fig_data["pts_per_data_unit"], schedule["cluster_labels"])
    reel_layers = build_reel(fig, px_per_pt)
    reel_scroll = compute_reel_scroll(frames, fps)
    reel_year_start_frames = compute_reel_year_start_frames(frames)
    clapper_layers = build_clapperboard(fig, px_per_pt, layers["clapper_box"])

    # Smoother year/heading/row/poster transitions (2026-08-08 restyle) --
    # lookahead fade multipliers layered on top of the schedule's own
    # per-frame content (what shows when is unchanged; this only smooths how
    # a change reads on screen). See cfg.YEAR_HEADING_FADE_SECONDS etc.
    year_heading_keys = [(f["phase"], f["year"]) for f in frames]
    year_heading_mult = compute_fade_multipliers(
        year_heading_keys, max(1, round(fps * cfg.YEAR_HEADING_FADE_SECONDS)))
    row_fade_out_mult = compute_fade_out_multipliers(
        year_heading_keys, max(1, round(fps * cfg.ROW_FADE_OUT_SECONDS)))
    # poster_active_year (from cinematic_history_schedule.py) is the sticky
    # "which year's Best Picture winner is currently on screen" field, set
    # exactly on the frame that winner's own hex(es) finish popping to final
    # color -- NOT frame["year"] (which would swap the poster in the instant
    # a new year starts, potentially well before or after that winner's own
    # reveal, the sync bug this restyle fixes). See cinematic_history_
    # posters.py's build_poster_index() docstring for the matching re-key.
    poster_keys = [f.get("poster_active_year") for f in frames]
    poster_mult = compute_fade_multipliers(poster_keys, max(1, round(fps * cfg.POSTER_FADE_SECONDS)))

    poster_state = {"year": object(), "img": None}   # sentinel that can never equal a real year or None-first-frame
    shown_poster_hexes = set()   # every (q, r) that has ever had a golden poster border -- accumulates, never cleared

    def update_poster(active_year):
        if active_year == poster_state["year"]:
            return
        poster_state["year"] = active_year
        layers["poster_ax"].cla()
        layers["poster_ax"].set_facecolor(cfg.BACKGROUND_COLOR)
        layers["poster_ax"].axis("off")
        path = poster_index.get(active_year) if active_year is not None else None
        poster_state["img"] = layers["poster_ax"].imshow(load_poster_image(path)) if path is not None else None

    def update(i):
        frame = frames[i]
        if frame["color_diffs"]:
            for (q, r), color in frame["color_diffs"].items():
                facecolors[hex_index[(q, r)]] = to_rgba(color)
            hex_coll.set_facecolors(facecolors)

        # Golden poster-hex border: every hex that has EVER had a poster
        # displayed on it accumulates into shown_poster_hexes and keeps its
        # border for the rest of the video -- persists, never replaced or
        # cleared, so it's additive rather than wholesale-swapped per poster.
        new_hexes = set(frame["poster_hexes"]) - shown_poster_hexes
        if new_hexes:
            shown_poster_hexes.update(new_hexes)
            segs = []
            for (q, r) in shown_poster_hexes:
                segs.extend(hex_outline_segments(q, r))
            poster_border_lc.set_segments(segs)

        yh_mult = year_heading_mult[i]
        if frame["phase"] == "title":
            layers["heading_text"].set_alpha(0.0)
            set_rows(layers, [])
        else:
            period_font = font_for_year(frame["year"])
            layers["heading_text"].set_alpha((1.0 if frame["heading"] else 0.0) * yh_mult)
            layers["heading_text"].set_text(frame["heading"] or "")
            row_mult = row_fade_out_mult[i]
            faded_rows = [dict(r, alpha=r["alpha"] * row_mult) for r in frame["rows"]]
            set_rows(layers, faded_rows, period_font=period_font)

        active_year = frame.get("poster_active_year")
        update_poster(active_year)
        clapper_alpha = poster_mult[i] if active_year is not None else 0.0
        if poster_state["img"] is not None:
            poster_state["img"].set_alpha(poster_mult[i])
        update_clapperboard(clapper_layers, poster_details.get(active_year), clapper_alpha)

        reel_year = frame["year"]
        update_reel(reel_layers, i, reel_scroll, fps, reel_year, reel_year_start_frames.get(reel_year, 0))

        artists = [hex_coll, poster_border_lc, layers["header_text"], layers["heading_text"]]
        for row in layers["rows"]:
            artists.extend([row["swatch"], row["title_l1"], row["title_l2"],
                             row["director_country"], row["connections"]])
            if row["bp_label"] is not None:
                artists.append(row["bp_label"])
        for lines in layers["cluster_label_lines"].values():
            artists.extend(lines)
        artists.extend([reel_layers["rim"], reel_layers["hub"], *reel_layers["spokes"], *reel_layers["spoke_holes"]])
        for cell in reel_layers["strip_cells"]:
            artists.extend([cell["rect"], cell["year_text"], *cell["holes"]])
        artists.extend([clapper_layers["body"], clapper_layers["bar"], clapper_layers["director_label"],
                         clapper_layers["director_l1"], clapper_layers["director_l2"],
                         clapper_layers["studio_label"], clapper_layers["studio_l1"], clapper_layers["studio_l2"],
                         clapper_layers["date_value"], clapper_layers["sep1"], clapper_layers["sep2"]])
        return artists

    frame_indices = range(len(frames))
    if frame_slice is not None:
        frame_indices = range(len(frames))[frame_slice]

    anim = animation.FuncAnimation(fig, update, frames=frame_indices, blit=False)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    writer = resolve_ffmpeg_writer(fps)
    print(f"Rendering {len(frame_indices)} frames -> {output_path} ...")
    anim.save(str(output_path), writer=writer, dpi=dpi)
    plt.close(fig)
    print("Done.")


def main():
    parser = argparse.ArgumentParser(
        description="Render the Reeling Through the Years: Mapping Cinematic History video (silent master).")
    parser.add_argument("--output", default=str(cfg.OUTPUT_DIR / "cinematic_history_silent.mp4"))
    parser.add_argument("--dpi", type=int, default=120)
    parser.add_argument("--start-frame", type=int, default=0)
    parser.add_argument("--end-frame", type=int, default=None)
    args = parser.parse_args()

    print("Building schedule...")
    schedule = sched.build_full_schedule()
    print(f"Total: {len(schedule['frames'])} frames "
          f"({schedule['total_seconds']:.1f}s / {schedule['total_seconds'] / 60:.2f} min) at {schedule['fps']} fps")

    frame_slice = slice(args.start_frame, args.end_frame)
    render(schedule, args.output, args.dpi, frame_slice)


if __name__ == "__main__":
    main()
