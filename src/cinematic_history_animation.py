"""
Criterion Over Time renderer.

Consumes ONLY cinematic_history_schedule.py's build_full_schedule() output
(itself sourced only from data/cinematic_history_hex_snapshot.json + the DB,
never from build_hex_grid()) and cinematic_history_config.py. Draws the hex
grid with hex_svg.py's exact visual language (dark background, per-hex black
stroke) plus a new continuous outer-perimeter border, and a small crossfading
film-info card holding up to ABSOLUTE_MAX_BATCH_SIZE rows (one per film in
the current batch). Writes a SILENT MP4 -- audio is muxed in a separate
stage (cinematic_history_audio_mix.py) so a test/draft render never has to
pay for the audio pipeline too.

Never imports hex_grid.py or hex_svg.py. Never writes outside outputs/.
"""

import argparse
import shutil
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.animation as animation
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.patches import FancyBboxPatch, Polygon

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import cinematic_history_config as cfg  # noqa: E402
import cinematic_history_schedule as sched  # noqa: E402
from cinematic_history_hexmath import axial_to_pixel, hex_corners, outer_perimeter_segments  # noqa: E402

FIGURE_WIDTH_IN = 16
FIGURE_HEIGHT_IN = 9
HEX_SIZE = 1.0
HEX_GAP = 0.95
CARD_BAND_FRAC = 0.24   # fraction of the frame height reserved for the film-info card


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


def truncate_title(text, width=52):
    """Single line, not wrapped -- the row layout gives the title exactly
    one line above the director/country line, so a wrapped second line
    would overlap it. Long titles get an ellipsis instead."""
    text = text or ""
    if len(text) <= width:
        return text
    return text[:width - 1].rstrip() + "…"


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
    # The top needs its own, much larger margin -- the year label sits above
    # the grid at a fixed axes-fraction (transAxes) position, and a plain
    # 2.0-unit margin (same as the other 3 sides) turned out to leave less
    # than a single text-line's worth of clearance once the card band and
    # the equal-aspect-ratio letterboxing are factored in, so the label
    # visually collided with the grid's own top row.
    top_margin = HEX_SIZE * 7.0
    x_min, x_max = min(xs) - margin, max(xs) + margin
    y_min, y_max = min(ys) - margin, max(ys) + top_margin
    # Reserve a band below the grid for the film-info card, WITHOUT shrinking
    # or shifting the grid itself -- extending ylim downward keeps the grid's
    # own scale/position perfectly stable frame to frame (spec: "the graph
    # must remain centered," "scale and position must remain stable").
    band_height = (y_max - y_min) * CARD_BAND_FRAC / (1 - CARD_BAND_FRAC)
    ax.set_xlim(x_min, x_max)
    ax.set_ylim(y_min - band_height, y_max)

    segs = outer_perimeter_segments(grid_hexes, hex_set, size=HEX_SIZE)
    lc = LineCollection(segs, colors=cfg.OUTER_BORDER_COLOR,
                         linewidths=cfg.OUTER_BORDER_WIDTH_PX / px_per_pt,
                         capstyle="round", joinstyle="round", zorder=3)
    ax.add_collection(lc)

    return fig, ax, patches, px_per_pt


def build_text_layers(ax, px_per_pt, n_slots):
    year_text = ax.text(0.02, 0.98, "", transform=ax.transAxes,
                         fontsize=30 / px_per_pt, fontweight="bold", color="#ffffff",
                         va="top", ha="left", zorder=10)
    title_text = ax.text(0.5, 0.56, "", transform=ax.transAxes,
                          fontsize=56 / px_per_pt, fontweight="bold", color="#ffffff",
                          va="center", ha="center", zorder=10, alpha=0.0)
    subtitle_text = ax.text(0.5, 0.46, "", transform=ax.transAxes,
                             fontsize=20 / px_per_pt, color="#dddddd",
                             va="center", ha="center", zorder=10, alpha=0.0)

    card_plate = FancyBboxPatch((0.025, 0.015), 0.95, CARD_BAND_FRAC - 0.03,
                                 transform=ax.transAxes,
                                 boxstyle="round,pad=0.006,rounding_size=0.012",
                                 facecolor=cfg.CARD_SURFACE_COLOR, edgecolor="none",
                                 zorder=8, alpha=0.0)
    ax.add_patch(card_plate)

    def make_row_group():
        row_h = (CARD_BAND_FRAC - 0.05) / n_slots
        rows = []
        for i in range(n_slots):
            y_top = 0.015 + (CARD_BAND_FRAC - 0.03) - i * row_h
            tt = ax.text(0.055, y_top, "", transform=ax.transAxes,
                         fontsize=24 / px_per_pt, fontweight="bold", color="#111111",
                         va="top", ha="left", zorder=9, alpha=0.0, linespacing=1.0)
            dt = ax.text(0.055, y_top - row_h * 0.46, "", transform=ax.transAxes,
                         fontsize=cfg.CARD_DIRECTOR_FONTSIZE_PX / px_per_pt, color=cfg.CARD_TEXT_COLOR,
                         va="top", ha="left", zorder=9, alpha=0.0)
            ct = ax.text(0.60, y_top - row_h * 0.46, "", transform=ax.transAxes,
                         fontsize=cfg.CARD_COUNTRY_FONTSIZE_PX / px_per_pt, color=cfg.CARD_TEXT_COLOR,
                         va="top", ha="left", zorder=9, alpha=0.0)
            rows.append((tt, dt, ct))
        return rows

    out_rows = make_row_group()
    in_rows = make_row_group()
    return dict(year_text=year_text, title_text=title_text, subtitle_text=subtitle_text,
                card_plate=card_plate, out_rows=out_rows, in_rows=in_rows)


def set_card_slot(triples, card_state):
    if card_state is None:
        for tt, dt, ct in triples:
            tt.set_alpha(0.0)
            dt.set_alpha(0.0)
            ct.set_alpha(0.0)
        return 0.0
    rows, alpha = card_state["rows"], card_state["alpha"]
    for i, (tt, dt, ct) in enumerate(triples):
        if i < len(rows):
            r = rows[i]
            tt.set_text(truncate_title(r["title"]))
            tt.set_alpha(alpha)
            dt.set_text(r["director"] or "")
            dt.set_alpha(alpha)
            ct.set_text(r["country"] or "")
            ct.set_alpha(alpha)
        else:
            tt.set_alpha(0.0)
            dt.set_alpha(0.0)
            ct.set_alpha(0.0)
    return alpha


def render(schedule, output_path, dpi, frame_slice=None):
    frames = schedule["frames"]
    if frame_slice is not None:
        frames = frames[frame_slice]
    fps = schedule["fps"]

    fig, ax, patches, px_per_pt = build_figure(schedule["grid_hexes"], schedule["hex_set"], dpi)
    # Size the card for however many rows batches actually use (observed
    # max, clamped to the configured hard cap as a defensive ceiling) --
    # not the generic cap itself, so a typical 1-2-film batch doesn't sit in
    # a mostly-empty 4-row card.
    n_slots = max(1, min(schedule["max_batch_size"], cfg.ABSOLUTE_MAX_BATCH_SIZE))
    layers = build_text_layers(ax, px_per_pt, n_slots)

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
            layers["year_text"].set_text(frame["year"] or "")

        a_out = set_card_slot(layers["out_rows"], frame["card_out"])
        a_in = set_card_slot(layers["in_rows"], frame["card_in"])
        layers["card_plate"].set_alpha(min(0.94, max(a_out, a_in)) * 0.94)

        artists = (list(patches.values()) + [layers["year_text"], layers["title_text"],
                   layers["subtitle_text"], layers["card_plate"]])
        for tt, dt, ct in layers["out_rows"] + layers["in_rows"]:
            artists.extend([tt, dt, ct])
        return artists

    anim = animation.FuncAnimation(fig, update, frames=len(frames), blit=False)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    writer = resolve_ffmpeg_writer(fps)
    print(f"Rendering {len(frames)} frames ({len(frames) / fps:.1f}s) -> {output_path} ...")
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
