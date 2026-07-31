"""
Criterion Over Time renderer.

Consumes ONLY cinematic_history_schedule.py's build_full_schedule() output
(itself sourced only from data/cinematic_history_hex_snapshot.json + the DB,
never from build_hex_grid()) and cinematic_history_config.py. Draws the hex
grid with hex_svg.py's exact visual language (per-hex black stroke) plus a
continuous outer-perimeter border, in a two-column layout: the hex grid on
the left, and a vertical film-info panel on the right holding the current
year, a 2-lane rolling film-title/director/country queue, and the matching
yearly poster. Writes a SILENT MP4 -- audio is muxed in a separate stage
(cinematic_history_audio_mix.py) so a test/draft render never has to pay for
the audio pipeline too.

Never imports hex_grid.py or hex_svg.py. Never writes outside outputs/.
"""

import argparse
import shutil
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.animation as animation
import matplotlib.image as mpimg
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.patches import Polygon

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import cinematic_history_config as cfg  # noqa: E402
import cinematic_history_schedule as sched  # noqa: E402
from cinematic_history_hexmath import axial_to_pixel, hex_corners, outer_perimeter_segments  # noqa: E402
from cinematic_history_posters import build_poster_index  # noqa: E402

FIGURE_WIDTH_IN = 16
FIGURE_HEIGHT_IN = 9
HEX_SIZE = 1.0
HEX_GAP = 0.95

# Fraction of the frame's total width reserved for the right-hand info
# panel. The hex grid occupies the remaining (1 - RIGHT_PANEL_FRAC) on the
# left -- panel content lives entirely at x >= 1-RIGHT_PANEL_FRAC in axes
# fraction, so it can never overlap the grid, which only ever occupies data
# coordinates to the left of that boundary (see build_figure).
RIGHT_PANEL_FRAC = 0.36
PANEL_PAD = 0.025   # inset from the panel's own left/right edges

FADE_IN_FRAMES_S = cfg.ITEM_FADE_IN_SECONDS
FADE_OUT_FRAMES_S = cfg.ITEM_FADE_OUT_SECONDS


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


def truncate(text, width):
    """Single line, not wrapped -- long titles/credits get an ellipsis
    instead of clipping into the next line or spilling out of the panel."""
    text = text or ""
    if len(text) <= width:
        return text
    return text[:width - 1].rstrip() + "…"


def truncate_title(text):
    return truncate(text, 36)


def truncate_credit(text):
    return truncate(text, 54)


def build_figure(grid_hexes, hex_set, dpi):
    px_per_pt = dpi / 72.0
    fig = plt.figure(figsize=(FIGURE_WIDTH_IN, FIGURE_HEIGHT_IN), facecolor=cfg.BACKGROUND_COLOR)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_facecolor(cfg.BACKGROUND_COLOR)
    ax.set_aspect("equal")
    ax.axis("off")

    patches = {}
    for (q, r) in grid_hexes:
        cx, cy = axial_to_pixel(q, r, HEX_SIZE)
        corners = hex_corners(cx, cy, HEX_SIZE * HEX_GAP)
        poly = Polygon(corners, closed=True, facecolor=cfg.BACKGROUND_COLOR,
                        edgecolor=cfg.HEX_STROKE_COLOR, linewidth=cfg.HEX_STROKE_WIDTH_PX / px_per_pt,
                        zorder=2)
        ax.add_patch(poly)
        patches[(q, r)] = poly

    all_px = [axial_to_pixel(q, r, HEX_SIZE) for q, r in grid_hexes]
    xs = [p[0] for p in all_px]
    ys = [p[1] for p in all_px]
    margin = HEX_SIZE * 2.0
    x_min, x_max = min(xs) - margin, max(xs) + margin
    y_min, y_max = min(ys) - margin, max(ys) + margin

    # Reserve the right-hand info-panel column by extending xlim, WITHOUT
    # shrinking or shifting the grid itself -- the grid's own data still
    # only occupies [x_min, x_max], so panel content (placed via transAxes
    # at x >= 1-RIGHT_PANEL_FRAC) can never be drawn over it.
    panel_width = (x_max - x_min) * RIGHT_PANEL_FRAC / (1 - RIGHT_PANEL_FRAC)
    ax.set_xlim(x_min, x_max + panel_width)
    ax.set_ylim(y_min, y_max)

    segs = outer_perimeter_segments(grid_hexes, hex_set, size=HEX_SIZE)
    lc = LineCollection(segs, colors=cfg.OUTER_BORDER_COLOR,
                         linewidths=cfg.OUTER_BORDER_WIDTH_PX / px_per_pt,
                         capstyle="round", joinstyle="round", zorder=3)
    ax.add_collection(lc)

    return fig, ax, patches, px_per_pt


def build_text_layers(ax, px_per_pt):
    panel_x0 = 1 - RIGHT_PANEL_FRAC + PANEL_PAD
    panel_x1 = 1 - PANEL_PAD
    panel_center = (panel_x0 + panel_x1) / 2

    year_text = ax.text(panel_x0, 0.95, "", transform=ax.transAxes,
                         fontsize=44 / px_per_pt, fontweight="bold", color=cfg.YEAR_TEXT_COLOR,
                         va="top", ha="left", zorder=10)

    title_text = ax.text(panel_center, 0.62, "", transform=ax.transAxes,
                          fontsize=30 / px_per_pt, fontweight="bold", color=cfg.TITLE_CARD_TEXT_COLOR,
                          va="center", ha="center", zorder=10, alpha=0.0)
    subtitle_text = ax.text(panel_center, 0.52, "", transform=ax.transAxes,
                             fontsize=16 / px_per_pt, color=cfg.TITLE_CARD_SUBTITLE_COLOR,
                             va="center", ha="center", zorder=10, alpha=0.0)

    def make_lane(y_top):
        rows = {}
        for key in ("out", "in"):
            tt = ax.text(panel_x0, y_top, "", transform=ax.transAxes,
                         fontsize=cfg.CARD_TITLE_FONTSIZE_PX / px_per_pt, fontweight="bold",
                         color=cfg.CARD_TITLE_COLOR, va="top", ha="left", zorder=9, alpha=0.0)
            ct = ax.text(panel_x0, y_top - 0.07, "", transform=ax.transAxes,
                         fontsize=cfg.CARD_CREDIT_FONTSIZE_PX / px_per_pt,
                         color=cfg.CARD_TEXT_COLOR, va="top", ha="left", zorder=9, alpha=0.0)
            rows[key] = (tt, ct)
        return rows

    lanes = [make_lane(0.84), make_lane(0.62)]

    poster_ax = ax.inset_axes([panel_x0, 0.04, panel_x1 - panel_x0, 0.40], transform=ax.transAxes)
    poster_ax.set_facecolor(cfg.BACKGROUND_COLOR)
    poster_ax.axis("off")
    for spine in poster_ax.spines.values():
        spine.set_visible(False)

    return dict(year_text=year_text, title_text=title_text, subtitle_text=subtitle_text,
                lanes=lanes, poster_ax=poster_ax)


def clamp01(x):
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)


def set_lane(lane, cur, cur_alpha, prev, prev_alpha):
    tt_in, ct_in = lane["in"]
    tt_out, ct_out = lane["out"]
    if cur is not None:
        tt_in.set_text(truncate_title(cur["title"]))
        tt_in.set_alpha(cur_alpha)
        ct_in.set_text(truncate_credit(cur["credit_line"]))
        ct_in.set_alpha(cur_alpha)
    else:
        tt_in.set_alpha(0.0)
        ct_in.set_alpha(0.0)
    if prev is not None:
        tt_out.set_text(truncate_title(prev["title"]))
        tt_out.set_alpha(prev_alpha)
        ct_out.set_text(truncate_credit(prev["credit_line"]))
        ct_out.set_alpha(prev_alpha)
    else:
        tt_out.set_alpha(0.0)
        ct_out.set_alpha(0.0)


_POSTER_IMAGE_CACHE = {}


def load_poster_image(path):
    if path not in _POSTER_IMAGE_CACHE:
        _POSTER_IMAGE_CACHE[path] = mpimg.imread(str(path))
    return _POSTER_IMAGE_CACHE[path]


def render(schedule, output_path, dpi, frame_slice=None):
    frames = schedule["frames"]
    fps = schedule["fps"]
    item_queue = schedule["item_queue"]
    hold_start_frame = schedule["hold_start_frame"]

    lane_lists = [
        [it for it in item_queue if it["lane"] == 0],
        [it for it in item_queue if it["lane"] == 1],
    ]
    fade_in_frames = max(1, round(fps * FADE_IN_FRAMES_S))
    fade_out_frames = max(1, round(fps * FADE_OUT_FRAMES_S))

    poster_index = build_poster_index()["resolved"]

    fig, ax, patches, px_per_pt = build_figure(schedule["grid_hexes"], schedule["hex_set"], dpi)
    layers = build_text_layers(ax, px_per_pt)

    # One monotonic pointer per lane -- frames are always rendered in
    # strictly increasing order by the movie writer, so each pointer only
    # ever advances, never resets or searches backward.
    lane_ptr = [-1, -1]
    poster_state = {"year": object()}   # sentinel that can never equal a real year or None-first-frame

    def lane_current_prev(lane_idx, frame_i):
        lst = lane_lists[lane_idx]
        p = lane_ptr[lane_idx]
        while p + 1 < len(lst) and lst[p + 1]["entrance_frame"] <= frame_i:
            p += 1
        lane_ptr[lane_idx] = p
        cur = lst[p] if p >= 0 else None
        prev = lst[p - 1] if p >= 1 else None
        return cur, prev, p, len(lst)

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
        if path is not None:
            layers["poster_ax"].imshow(load_poster_image(path))

    def update(i):
        frame = frames[i]
        for (q, r), color in frame["color_diffs"].items():
            patches[(q, r)].set_facecolor(color)

        if frame["phase"] == "title":
            layers["title_text"].set_alpha(1.0)
            layers["title_text"].set_text("CRITERION OVER TIME")
            layers["subtitle_text"].set_alpha(1.0)
            layers["subtitle_text"].set_text("A Cinematic History, 1913–2025")
            layers["year_text"].set_alpha(0.0)
        else:
            layers["title_text"].set_alpha(0.0)
            layers["subtitle_text"].set_alpha(0.0)
            layers["year_text"].set_alpha(1.0 if frame["year"] else 0.0)
            layers["year_text"].set_text(str(frame["year"]) if frame["year"] else "")

        for lane_idx in (0, 1):
            cur, prev, p, lane_len = lane_current_prev(lane_idx, i)
            if cur is not None:
                t_in = i - cur["entrance_frame"]
                cur_alpha = clamp01(t_in / fade_in_frames)
                if p == lane_len - 1 and i >= hold_start_frame:
                    t_hold = i - hold_start_frame
                    cur_alpha = min(cur_alpha, clamp01(1 - t_hold / fade_out_frames))
            else:
                cur_alpha = 0.0
            if prev is not None:
                t_out = i - cur["entrance_frame"]
                prev_alpha = clamp01(1 - t_out / fade_out_frames)
            else:
                prev_alpha = 0.0
            set_lane(layers["lanes"][lane_idx], cur, cur_alpha, prev, prev_alpha)

        update_poster(frame["year"])

        artists = list(patches.values()) + [layers["year_text"], layers["title_text"], layers["subtitle_text"]]
        for lane in layers["lanes"]:
            for tt, ct in lane.values():
                artists.extend([tt, ct])
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
    parser = argparse.ArgumentParser(description="Render the Criterion Over Time video (silent master).")
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
