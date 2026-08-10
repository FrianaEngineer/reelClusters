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
from matplotlib.collections import LineCollection, PolyCollection
from matplotlib.colors import to_rgba

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import cinematic_history_config as cfg  # noqa: E402
import cinematic_history_schedule as sched  # noqa: E402
from cinematic_history_hexmath import (  # noqa: E402
    axial_to_pixel, hex_corners, outer_perimeter_segments, EDGE_CORNERS,
)
from cinematic_history_posters import build_poster_index  # noqa: E402

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

FADE_IN_FRAMES_S = cfg.ITEM_FADE_IN_SECONDS

# axes-fraction y where the graph/right-panel area ends and the persistent
# header band begins (see build_figure()'s ylim extension).
HEADER_BOTTOM = 1 - cfg.TOP_HEADER_FRAC

# Row typography -- 3 rows now (was 5, see cfg.TOP_N_FILMS), so each gets
# meaningfully more room, including up to 2 lines for a long title (see
# wrap_title()).
ROW_TITLE_FONTSIZE_PX = 23
ROW_CREDIT_FONTSIZE_PX = 13
HEADING_FONTSIZE_PX = 21
TITLE_LINE_GAP_FRAC = 0.039     # axes-fraction gap between a title's line 1 and line 2
CREDIT_GAP_1LINE_FRAC = 0.050   # credit's y-offset below the row's own top when its title is 1 line
CREDIT_GAP_2LINE_FRAC = 0.089   # ...when the title is 2 lines (keeps it clear of the title's 2nd line)

YEAR_Y = HEADER_BOTTOM - 0.028
HEADING_Y = HEADER_BOTTOM - 0.108
ROW_TOP_START = HEADER_BOTTOM - 0.195
ROW_SLOT_HEIGHT = 0.150   # per-row vertical budget -- generous enough for a 2-line title + credit line
SWATCH_MARKERSIZE_PT = 15
SWATCH_TEXT_INSET = 0.038   # how far right of the panel's left edge the title/credit text starts (leaves room for the swatch)

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


def fit_credit_line(director, country, connections, max_chars):
    """"Director – Country – N connections", truncating the COUNTRY first
    (with an ellipsis) if the full line doesn't fit, keeping the director
    and the connection count intact -- only truncating the director too, as
    an absolute last resort, if a director name alone is longer than the
    whole budget. Never truncates the connection count."""
    conn_text = f"{connections} connection" if connections == 1 else f"{connections} connections"
    # criterion_director/criterion_country can come through as a pandas/
    # duckdb NaN float for a missing value, not None -- coerce defensively
    # rather than trust upstream always hands back a clean str-or-None.
    director = director if isinstance(director, str) else ""
    country = country if isinstance(country, str) else ""

    def join(parts):
        return " – ".join(p for p in parts if p)

    full = join([director, country, conn_text])
    if len(full) <= max_chars:
        return full

    if country:
        c = country
        while c and len(join([director, c, conn_text])) > max_chars:
            c = c[:-1]
        c = c.rstrip()
        if c != country:
            c = (c[:-1].rstrip() + "…") if len(c) > 1 else "…"
        result = join([director, c, conn_text])
        if len(result) <= max_chars or not director:
            return result

    # Still too long -- either there was no country to shed in the first
    # place, or the director name alone (with country already dropped) is
    # still over budget. Drop the country entirely and truncate the
    # director instead, as a last resort.
    d = director
    while d and len(join([d, conn_text])) > max_chars:
        d = d[:-1]
    d = d.rstrip()
    if d != director:
        d = (d[:-1].rstrip() + "…") if len(d) > 1 else "…"
    return join([d, conn_text])


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
    # centered on the FULL frame width, visible frame 1 through the final
    # frame (alpha never changes) -- see cfg.MAIN_TITLE_TEXT.
    header_text = ax.text(0.5, 1 - cfg.TOP_HEADER_FRAC / 2, cfg.MAIN_TITLE_TEXT, transform=ax.transAxes,
                           fontsize=cfg.MAIN_TITLE_FONTSIZE_PX / px_per_pt, fontweight="bold",
                           color=cfg.MAIN_TITLE_COLOR, va="center", ha="center", zorder=20, alpha=1.0)

    year_text = ax.text(panel_x0, YEAR_Y, "", transform=ax.transAxes,
                         fontsize=40 / px_per_pt, fontweight="bold", color=cfg.YEAR_TEXT_COLOR,
                         va="top", ha="left", zorder=10)

    heading_text = ax.text(panel_x0, HEADING_Y, "", transform=ax.transAxes,
                            fontsize=HEADING_FONTSIZE_PX / px_per_pt, fontweight="bold",
                            color=cfg.YEAR_TEXT_COLOR, va="top", ha="left", zorder=10)

    rows = []
    for i in range(cfg.TOP_N_FILMS):
        top = row_top(i)
        x = panel_x0 + SWATCH_TEXT_INSET
        swatch, = ax.plot([panel_x0 + 0.012], [top - 0.020], marker=(6, 0, 0),
                           markersize=SWATCH_MARKERSIZE_PT, markerfacecolor="none",
                           markeredgecolor="#000000", markeredgewidth=0.6 / px_per_pt,
                           transform=ax.transAxes, linestyle="none", zorder=11, alpha=0.0)
        title_l1 = ax.text(x, top, "", transform=ax.transAxes,
                            fontsize=ROW_TITLE_FONTSIZE_PX / px_per_pt, fontweight="bold",
                            color=cfg.CARD_TITLE_COLOR, va="top", ha="left", zorder=10, alpha=0.0)
        title_l2 = ax.text(x, top - TITLE_LINE_GAP_FRAC, "", transform=ax.transAxes,
                            fontsize=ROW_TITLE_FONTSIZE_PX / px_per_pt, fontweight="bold",
                            color=cfg.CARD_TITLE_COLOR, va="top", ha="left", zorder=10, alpha=0.0)
        credit = ax.text(x, top - CREDIT_GAP_1LINE_FRAC, "", transform=ax.transAxes,
                          fontsize=ROW_CREDIT_FONTSIZE_PX / px_per_pt,
                          color=cfg.CARD_TEXT_COLOR, va="top", ha="left", zorder=10, alpha=0.0)
        rows.append(dict(swatch=swatch, title_l1=title_l1, title_l2=title_l2, credit=credit, top=top, x=x))

    # Sized/positioned to clear the last row's own worst case (a 2-line
    # title) with a safety gap, then kept low in the panel near the bottom.
    poster_box_y0 = 0.02
    last_row_bottom = row_top(cfg.TOP_N_FILMS - 1) - CREDIT_GAP_2LINE_FRAC
    poster_box_height = max(0.16, min(0.30, last_row_bottom - poster_box_y0 - 0.03))
    poster_ax = ax.inset_axes([panel_x0, poster_box_y0, panel_x1 - panel_x0, poster_box_height],
                               transform=ax.transAxes)
    poster_ax.set_facecolor(cfg.BACKGROUND_COLOR)
    poster_ax.axis("off")
    for spine in poster_ax.spines.values():
        spine.set_visible(False)

    # Completed-cluster labels (2026-08-08 restyle): one (potentially
    # multi-line) Text per cluster, in DATA coordinates (matching hex
    # placement, NOT the axes-fraction right panel), positioned/sized/
    # colored/wrapped exactly as read off explore.html by
    # cinematic_history_layout_snapshot.py (cluster_labels_data). Starts at
    # alpha=0; render()'s update() fades each one in once its cluster is
    # complete (schedule's cluster_complete_frames) and never hides it again.
    cluster_label_lines = {}
    for cluster_id, data in cluster_labels_data.items():
        color = cfg.CLUSTER_LABEL_ON_DARK_COLOR if data["on_dark"] else cfg.CLUSTER_LABEL_ON_LIGHT_COLOR
        fontsize_pt = data["fontsize"] * pts_per_data_unit
        stroke_fx = ([patheffects.withStroke(linewidth=fontsize_pt * 0.09,
                                              foreground=cfg.CLUSTER_LABEL_STROKE_COLOR)]
                     if data["on_dark"] else None)
        artists = []
        for line in data["lines"]:
            t = ax.text(line["x"], line["y"], line["text"], fontsize=fontsize_pt, fontweight="bold",
                         color=color, va="center", ha="center", zorder=12, alpha=0.0,
                         path_effects=stroke_fx)
            artists.append(t)
        cluster_label_lines[cluster_id] = artists

    return dict(header_text=header_text, year_text=year_text, heading_text=heading_text,
                rows=rows, poster_ax=poster_ax, cluster_label_lines=cluster_label_lines)


def set_rows(layers, rows_state):
    """rows_state: up to cfg.TOP_N_FILMS dicts (title, director, country,
    connections, swatch_color, alpha), in reveal order. Any row slot beyond
    len(rows_state) is hidden."""
    for i, row in enumerate(layers["rows"]):
        if i < len(rows_state):
            r = rows_state[i]
            lines = wrap_title(r["title"], TITLE_MAX_CHARS)
            l1 = lines[0] if lines else ""
            l2 = lines[1] if len(lines) > 1 else ""
            credit_text = fit_credit_line(r["director"], r["country"], r["connections"], CREDIT_MAX_CHARS)

            row["title_l1"].set_text(l1)
            row["title_l1"].set_alpha(r["alpha"])
            row["title_l2"].set_text(l2)
            row["title_l2"].set_alpha(r["alpha"] if l2 else 0.0)
            credit_gap = CREDIT_GAP_2LINE_FRAC if l2 else CREDIT_GAP_1LINE_FRAC
            row["credit"].set_position((row["x"], row["top"] - credit_gap))
            row["credit"].set_text(credit_text)
            row["credit"].set_alpha(r["alpha"])
            row["swatch"].set_alpha(r["alpha"])
            if r["swatch_color"] is not None:
                row["swatch"].set_markerfacecolor(r["swatch_color"])
        else:
            row["title_l1"].set_alpha(0.0)
            row["title_l2"].set_alpha(0.0)
            row["credit"].set_alpha(0.0)
            row["swatch"].set_alpha(0.0)


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

    poster_index = build_poster_index()["resolved"]

    fig_data = build_figure(schedule["grid_hexes"], schedule["hex_set"], schedule["hex_cluster_map"], dpi)
    fig, ax = fig_data["fig"], fig_data["ax"]
    hex_coll, hex_index, facecolors = fig_data["hex_coll"], fig_data["hex_index"], fig_data["facecolors"]
    px_per_pt, poster_border_lc = fig_data["px_per_pt"], fig_data["poster_border_lc"]
    layers = build_text_layers(ax, px_per_pt, fig_data["pts_per_data_unit"], schedule["cluster_labels"])

    cluster_complete_frames = schedule["cluster_complete_frames"]
    label_fade_frames = max(1, round(fps * cfg.CLUSTER_LABEL_FADE_IN_SECONDS))

    # Smoother year/heading/row/poster transitions (2026-08-08 restyle) --
    # lookahead fade multipliers layered on top of the schedule's own
    # per-frame content (what shows when is unchanged; this only smooths how
    # a change reads on screen). See cfg.YEAR_HEADING_FADE_SECONDS etc.
    year_heading_keys = [(f["phase"], f["year"]) for f in frames]
    year_heading_mult = compute_fade_multipliers(
        year_heading_keys, max(1, round(fps * cfg.YEAR_HEADING_FADE_SECONDS)))
    row_fade_out_mult = compute_fade_out_multipliers(
        year_heading_keys, max(1, round(fps * cfg.ROW_FADE_OUT_SECONDS)))
    poster_keys = [poster_index.get(f["year"]) if f["year"] is not None else None for f in frames]
    poster_mult = compute_fade_multipliers(poster_keys, max(1, round(fps * cfg.POSTER_FADE_SECONDS)))

    poster_state = {"year": object(), "img": None}   # sentinel that can never equal a real year or None-first-frame
    shown_poster_hexes = set()   # every (q, r) that has ever had a golden poster border -- accumulates, never cleared

    def update_poster(year):
        if year == poster_state["year"]:
            return
        poster_state["year"] = year
        layers["poster_ax"].cla()
        layers["poster_ax"].set_facecolor(cfg.BACKGROUND_COLOR)
        layers["poster_ax"].axis("off")
        path = None
        if year is not None and year >= cfg.POSTER_START_YEAR:
            path = poster_index.get(year)
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

        # Completed-cluster labels: fade in once, stay forever -- never
        # reset by phase or by the right panel's own fades.
        for cluster_id, complete_frame in cluster_complete_frames.items():
            frames_since = i - complete_frame
            alpha = 0.0 if frames_since < 0 else min(1.0, frames_since / label_fade_frames)
            for artist in layers["cluster_label_lines"][cluster_id]:
                artist.set_alpha(alpha)

        yh_mult = year_heading_mult[i]
        if frame["phase"] == "title":
            layers["year_text"].set_alpha(0.0)
            layers["heading_text"].set_alpha(0.0)
            set_rows(layers, [])
        else:
            layers["year_text"].set_alpha((1.0 if frame["year"] else 0.0) * yh_mult)
            layers["year_text"].set_text(str(frame["year"]) if frame["year"] else "")
            layers["heading_text"].set_alpha((1.0 if frame["heading"] else 0.0) * yh_mult)
            layers["heading_text"].set_text(frame["heading"] or "")
            row_mult = row_fade_out_mult[i]
            faded_rows = [dict(r, alpha=r["alpha"] * row_mult) for r in frame["rows"]]
            set_rows(layers, faded_rows)

        update_poster(frame["year"])
        if poster_state["img"] is not None:
            poster_state["img"].set_alpha(poster_mult[i])

        artists = [hex_coll, poster_border_lc, layers["header_text"], layers["year_text"], layers["heading_text"]]
        for row in layers["rows"]:
            artists.extend([row["swatch"], row["title_l1"], row["title_l2"], row["credit"]])
        for lines in layers["cluster_label_lines"].values():
            artists.extend(lines)
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
