"""
Cinematic History: animates the Criterion Collection hex grid, filling in
hexes in chronological order (by criterion_year) from oldest to newest.

Reuses the existing hex-grid geometry, cluster assignment, and film-to-hex
mapping from hex_grid.py verbatim -- this script only adds a reveal timeline
and renders it. Film metadata (title, year, director) is looked up from
criterion_graph.duckdb by IMDb tconst, never joined by title.
"""

import argparse
import shutil
import sys
import textwrap
from collections import defaultdict
from pathlib import Path

import duckdb
import matplotlib
matplotlib.use("Agg")
import matplotlib.animation as animation
import matplotlib.colors as mcolors
import matplotlib.patheffects as patheffects
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from hex_grid import axial_to_pixel, build_hex_grid, hex_corners
from cluster_colors import contrast_text_color

DB_PATH = SCRIPT_DIR.parent / "db" / "criterion_graph.duckdb"
OUTPUT_DIR = SCRIPT_DIR.parent / "outputs"

# ── Visual constants ──────────────────────────────────────────────────────
BACKGROUND_COLOR = "#8A8A8A"
HEX_EDGE_COLOR = "#111111"
FIGURE_WIDTH = 16
FIGURE_HEIGHT = 9
OUTPUT_DPI = 120
FPS = 30
MAX_TITLES_PER_FRAME = 11

# Films pop in strictly one at a time, never overlapping: each film's hex(es)
# fade in over HEX_POP_SECONDS, then hold on screen (already faded in, title
# already in the panel) for READ_HOLD_SECONDS before the next film starts --
# that dedicated pause per title is what gives each one real reading time.
HEX_POP_SECONDS = 0.15
READ_HOLD_SECONDS = 0.35

HEX_SIZE = 1.0
HEX_GAP = 0.95

INTRO_SECONDS = 2.5
OUTRO_SECONDS = 2.5

TITLE_WRAP_WIDTH = 34
TITLE_MAX_LINES = 2
CREDIT_LINE_MAX_CHARS = 68


# ── Metadata ──────────────────────────────────────────────────────────────

def load_metadata(con):
    """One highest-confidence metadata row per imdb_tconst, matching the
    same selection logic hex_grid.py already uses for criterion_year."""
    df = con.execute("""
        SELECT * FROM (
            SELECT
                imdb_tconst,
                title,
                criterion_year,
                criterion_director,
                criterion_country,
                confidence_score,
                row_number() OVER (
                    PARTITION BY imdb_tconst ORDER BY confidence_score DESC NULLS LAST
                ) AS rn
            FROM criterion_basic_info
        ) WHERE rn = 1
    """).df()
    return df.set_index("imdb_tconst").to_dict("index")


def format_credit_line(director, country, max_chars=CREDIT_LINE_MAX_CHARS):
    """Combines director + country into the one small line shown under a
    title. Truncated (not wrapped) past max_chars -- unlike the title itself,
    losing the tail of a long multi-director credit list is an acceptable
    trade-off for keeping the panel layout simple; this only affects a
    handful of films with many co-directors."""
    parts = [p for p in (director, country) if isinstance(p, str) and p]
    line = "  ·  ".join(parts)
    if len(line) <= max_chars:
        return line
    return line[: max_chars - 1].rstrip() + "…"


def build_hex_records(grid, meta):
    """(q, r) -> dict(tconst, title, credit_line, year, cluster, color)."""
    records = {}
    missing = []
    for h, tconst in grid.hex_film.items():
        cluster = grid.hex_cluster.get(h)
        color = grid.color_map.get(cluster, "#888888")
        row = meta.get(tconst)
        if row is None:
            missing.append(tconst)
            title, director, country, year = tconst, None, None, None
        else:
            title, director, country, year = (row["title"], row["criterion_director"],
                                                row["criterion_country"], row["criterion_year"])
            try:
                year = int(year)
            except (TypeError, ValueError):
                year = None
        records[h] = dict(tconst=tconst, title=title,
                           credit_line=format_credit_line(director, country),
                           year=year, cluster=cluster, color=color,
                           outline=contrast_text_color(color))
    return records, missing


def wrap_title(text, width=TITLE_WRAP_WIDTH, max_lines=TITLE_MAX_LINES):
    """Wraps a title onto up to `max_lines` lines instead of truncating it to
    one -- long Criterion titles (alternate/subtitle-style names especially)
    would otherwise lose real words to a trailing ellipsis."""
    text = text or ""
    lines = textwrap.wrap(text, width=width, break_long_words=False) or [""]
    if len(lines) <= max_lines:
        return lines
    kept = lines[:max_lines]
    last = kept[-1].rstrip()
    if len(last) > width - 1:
        last = last[: width - 1].rstrip()
    kept[-1] = last + "…"
    return kept


# ── Reveal schedule ───────────────────────────────────────────────────────

def blend(c1, c2, t):
    r1, g1, b1 = mcolors.to_rgb(c1)
    r2, g2, b2 = mcolors.to_rgb(c2)
    return (r1 + (r2 - r1) * t, g1 + (g2 - g1) * t, b1 + (b2 - b1) * t)


def paginate(entries, page_size):
    if not entries:
        return [[]]
    return [entries[i:i + page_size] for i in range(0, len(entries), page_size)]


def group_films_by_tconst(hexes_this_year, records):
    """Groups hexes sharing the same tconst (a handful of films land on more
    than one hex -- see hex_grid.py's hiddenGems assignment) into a single
    reveal event, sorted title A-Z so hex pop order matches panel order."""
    by_tconst = {}
    for h in hexes_this_year:
        rec = records[h]
        entry = by_tconst.setdefault(rec["tconst"], dict(
            sort_title=rec["title"] or "", title_lines=wrap_title(rec["title"]),
            color=rec["color"], outline=rec["outline"],
            credit_line=rec["credit_line"], hexes=[],
        ))
        entry["hexes"].append(h)
    films = list(by_tconst.values())
    films.sort(key=lambda f: f["sort_title"])
    return films


def build_page_frames(page_films, year_label, year_total, revealed_before_page,
                       page_label, pop_frames, hold_frames):
    """One page's worth of frames: films pop in strictly one at a time --
    each one fades in over `pop_frames`, then holds fully visible (with its
    title already sitting in the panel) for `hold_frames` before the next
    film's hex starts fading -- no two films ever fade in at once."""
    per_film = max(1, pop_frames + hold_frames)
    total_frames = per_film * len(page_films) if page_films else 1

    frames = []
    for f in range(total_frames):
        film_idx = min(f // per_film, len(page_films) - 1) if page_films else 0
        local_f = f - film_idx * per_film
        color_diffs = {}
        if page_films and local_f < pop_frames:
            t = (local_f + 1) / pop_frames
            for h in page_films[film_idx]["hexes"]:
                color_diffs[h] = blend(BACKGROUND_COLOR, page_films[film_idx]["color"], t)
        visible = page_films[:film_idx + 1]
        frames.append(dict(
            year_label=year_label,
            title_card=None,
            panel_entries=[dict(title_lines=v["title_lines"], color=v["color"],
                                 outline=v["outline"], credit_line=v["credit_line"])
                           for v in visible],
            year_total=year_total,
            revealed_so_far=revealed_before_page + len(visible),
            page_label=page_label,
            color_diffs=color_diffs,
        ))
    return frames


def build_year_pages(hexes_this_year, records, year_label, max_titles,
                      pop_frames, hold_frames):
    """One year's (or 'Unknown Year' block's) worth of animation frames,
    across as many pages of up to `max_titles` films as it takes."""
    films = group_films_by_tconst(hexes_this_year, records)
    pages = paginate(films, max_titles)
    year_total = len(films)

    frames = []
    revealed_before = 0
    for page_idx, page in enumerate(pages):
        page_label = f"page {page_idx + 1} of {len(pages)}" if len(pages) > 1 else ""
        frames.extend(build_page_frames(
            page, year_label, year_total, revealed_before, page_label,
            pop_frames, hold_frames,
        ))
        revealed_before += len(page)
    return frames


def build_schedule(records, fps, max_titles, pop_frames, hold_frames, start_year, end_year):
    year_to_hexes = defaultdict(list)
    for h, rec in records.items():
        year_to_hexes[rec["year"]].append(h)

    known_years = sorted(y for y in year_to_hexes if y is not None)
    unknown_hexes = year_to_hexes.get(None, [])

    pre_years = [y for y in known_years if start_year is not None and y < start_year]
    active_years = [y for y in known_years
                    if (start_year is None or y >= start_year)
                    and (end_year is None or y <= end_year)]

    schedule = []

    # Intro: full gray grid + title card; hexes from years before --start-year
    # (if any) are already-told story and appear instantly, not faded in.
    intro_frames = max(1, round(INTRO_SECONDS * fps))
    pre_hex_colors = {h: records[h]["color"] for y in pre_years for h in year_to_hexes[y]}
    min_y = known_years[0] if known_years else None
    max_y = known_years[-1] if known_years else None
    for i in range(intro_frames):
        schedule.append(dict(
            year_label="",
            title_card=("CRITERION COLLECTION", f"A Cinematic History, {min_y}–{max_y}"),
            panel_entries=[],
            year_total=0,
            revealed_so_far=0,
            page_label="",
            color_diffs=pre_hex_colors if i == 0 else {},
        ))

    for year in active_years:
        schedule.extend(build_year_pages(
            year_to_hexes[year], records, str(year), max_titles,
            pop_frames, hold_frames,
        ))

    if unknown_hexes and end_year is None:
        schedule.extend(build_year_pages(
            unknown_hexes, records, "Unknown Year", max_titles,
            pop_frames, hold_frames,
        ))

    # Outro: hold on the final year's content so the video doesn't cut abruptly.
    outro_frames = max(1, round(OUTRO_SECONDS * fps))
    last = schedule[-1] if schedule else None
    for _ in range(outro_frames):
        if last is not None:
            schedule.append(dict(**{**last, "color_diffs": {}}))

    return schedule


# ── FFmpeg resolution ─────────────────────────────────────────────────────

def resolve_ffmpeg_writer(fps):
    if shutil.which("ffmpeg") and animation.FFMpegWriter.isAvailable():
        return animation.FFMpegWriter(fps=fps, codec="libx264", bitrate=8000,
                                       extra_args=["-pix_fmt", "yuv420p"])
    try:
        import imageio_ffmpeg
        matplotlib.rcParams["animation.ffmpeg_path"] = imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        pass
    if animation.FFMpegWriter.isAvailable():
        return animation.FFMpegWriter(fps=fps, codec="libx264", bitrate=8000,
                                       extra_args=["-pix_fmt", "yuv420p"])
    sys.exit(
        "ERROR: No usable FFmpeg executable found. Install FFmpeg (e.g. "
        "`brew install ffmpeg`) or ensure imageio-ffmpeg is installed "
        "(`pip install imageio-ffmpeg`)."
    )


# ── Rendering ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Animate the Criterion hex grid chronologically.")
    parser.add_argument("--output", default=str(OUTPUT_DIR / "cinematic_history.mp4"))
    parser.add_argument("--fps", type=int, default=FPS)
    parser.add_argument("--dpi", type=int, default=OUTPUT_DPI)
    parser.add_argument("--start-year", type=int, default=None)
    parser.add_argument("--end-year", type=int, default=None)
    parser.add_argument("--hex-pop-seconds", type=float, default=HEX_POP_SECONDS,
                         help="Seconds for a single film's hex(es) to fade in.")
    parser.add_argument("--read-hold-seconds", type=float, default=READ_HOLD_SECONDS,
                         help="Dedicated read-time pause after each film pops in, before the next one starts.")
    parser.add_argument("--preview", action="store_true",
                         help="Also export a low-res GIF preview alongside the MP4.")
    args = parser.parse_args()

    if args.start_year is not None and args.end_year is not None and args.start_year > args.end_year:
        sys.exit("ERROR: --start-year must be <= --end-year.")

    if not DB_PATH.exists():
        sys.exit(f"ERROR: database not found at {DB_PATH}")

    print("Building hex grid...")
    grid = build_hex_grid()
    print(f"Hexes: {len(grid.grid_hexes)}  Film assignments: {len(grid.hex_film)}")

    print("Loading film metadata from DuckDB...")
    con = duckdb.connect(str(DB_PATH), read_only=True)
    meta = load_metadata(con)
    con.close()

    records, missing = build_hex_records(grid, meta)

    print("Building reveal schedule...")
    pop_frames = max(1, round(args.fps * args.hex_pop_seconds))
    hold_frames = max(1, round(args.fps * args.read_hold_seconds))
    schedule = build_schedule(records, args.fps, MAX_TITLES_PER_FRAME,
                               pop_frames, hold_frames, args.start_year, args.end_year)
    duration_s = len(schedule) / args.fps
    print(f"Total frames: {len(schedule)} ({duration_s:.1f}s / {duration_s / 60:.1f} min at {args.fps}fps)")

    output_path = Path(args.output)

    print("Rendering figure and patches...")
    fig = plt.figure(figsize=(FIGURE_WIDTH, FIGURE_HEIGHT), facecolor=BACKGROUND_COLOR)
    gs = fig.add_gridspec(1, 2, width_ratios=[3, 1.2], wspace=0.02,
                           left=0.01, right=0.99, top=0.98, bottom=0.02)
    ax_grid = fig.add_subplot(gs[0, 0])
    ax_panel = fig.add_subplot(gs[0, 1])

    ax_grid.set_facecolor(BACKGROUND_COLOR)
    ax_panel.set_facecolor(BACKGROUND_COLOR)
    ax_grid.set_aspect("equal")
    ax_grid.axis("off")
    ax_panel.axis("off")

    patches = {}
    for h in grid.grid_hexes:
        cx, cy = axial_to_pixel(h[0], h[1], HEX_SIZE)
        corners = hex_corners(cx, cy, HEX_SIZE * HEX_GAP)
        poly = Polygon(corners, closed=True, facecolor=BACKGROUND_COLOR,
                        edgecolor=HEX_EDGE_COLOR, linewidth=0.6)
        ax_grid.add_patch(poly)
        patches[h] = poly

    all_px = [axial_to_pixel(q, r, HEX_SIZE) for q, r in grid.grid_hexes]
    xs = [p[0] for p in all_px]
    ys = [p[1] for p in all_px]
    margin = HEX_SIZE * 1.5
    ax_grid.set_xlim(min(xs) - margin, max(xs) + margin)
    ax_grid.set_ylim(min(ys) - margin, max(ys) + margin)

    year_text = ax_panel.text(0.04, 0.97, "", transform=ax_panel.transAxes,
                               fontsize=44, fontweight="bold", color="#111111",
                               va="top", ha="left")
    subtitle_text = ax_panel.text(0.04, 0.855, "", transform=ax_panel.transAxes,
                                   fontsize=13, color="#222222", va="top", ha="left")

    n_slots = MAX_TITLES_PER_FRAME
    top, bottom = 0.80, 0.03
    step = (top - bottom) / n_slots
    title_texts, director_texts = [], []
    for i in range(n_slots):
        y = top - i * step
        tt = ax_panel.text(0.04, y, "", transform=ax_panel.transAxes,
                            fontsize=13, fontweight="bold", color="white", va="top", ha="left",
                            linespacing=0.95)
        dt = ax_panel.text(0.06, y - step * 0.62, "", transform=ax_panel.transAxes,
                            fontsize=8.5, color="#f2f2f2", style="italic",
                            va="top", ha="left")
        title_texts.append(tt)
        director_texts.append(dt)

    page_text = ax_panel.text(0.04, 0.005, "", transform=ax_panel.transAxes,
                               fontsize=9, color="#1a1a1a", style="italic",
                               va="bottom", ha="left")

    def update(frame_idx):
        frame = schedule[frame_idx]
        for h, color in frame["color_diffs"].items():
            patches[h].set_facecolor(color)

        if frame["title_card"]:
            wrapped = "\n".join(textwrap.wrap(frame["title_card"][0], width=12))
            year_text.set_text(wrapped)
            year_text.set_fontsize(26)
            year_text.set_linespacing(1.15)
            subtitle_text.set_text("\n".join(textwrap.wrap(frame["title_card"][1], width=28)))
        else:
            year_text.set_text(frame["year_label"])
            year_text.set_fontsize(44)
            total = frame["year_total"]
            subtitle_text.set_text(f"{frame['revealed_so_far']} of {total} film"
                                    f"{'s' if total != 1 else ''} revealed")

        entries = frame["panel_entries"]
        for i in range(n_slots):
            if i < len(entries):
                e = entries[i]
                title_texts[i].set_text("\n".join(e["title_lines"]))
                title_texts[i].set_color(e["color"])
                title_texts[i].set_path_effects(
                    [patheffects.withStroke(linewidth=2.6, foreground=e["outline"])])
                director_texts[i].set_text(e["credit_line"])
            else:
                title_texts[i].set_text("")
                director_texts[i].set_text("")
        page_text.set_text(frame["page_label"])

        return (list(patches.values()) + [year_text, subtitle_text, page_text]
                + title_texts + director_texts)

    anim = animation.FuncAnimation(fig, update, frames=len(schedule), blit=False)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    writer = resolve_ffmpeg_writer(args.fps)
    print(f"Saving MP4 to {output_path} ...")
    anim.save(str(output_path), writer=writer, dpi=args.dpi)
    print("MP4 saved.")

    if args.preview:
        gif_path = OUTPUT_DIR / "cinematic_history_preview.gif"
        gif_path.parent.mkdir(parents=True, exist_ok=True)
        print(f"Saving GIF preview to {gif_path} ...")
        gif_writer = animation.PillowWriter(fps=args.fps)
        anim.save(str(gif_path), writer=gif_writer, dpi=min(args.dpi, 80))
        print("GIF preview saved.")

    valid_years = [r["year"] for r in records.values() if r["year"] is not None]
    print("\n=== Summary ===")
    print(f"Films rendered (hex slots): {len(records)}")
    print(f"Missing metadata: {len(missing)}")
    if missing:
        print(f"  tconsts: {missing[:20]}{' ...' if len(missing) > 20 else ''}")
    print(f"Min year: {min(valid_years) if valid_years else 'N/A'}")
    print(f"Max year: {max(valid_years) if valid_years else 'N/A'}")
    print(f"Output: {output_path}")
    if args.preview:
        print(f"Preview GIF: {OUTPUT_DIR / 'cinematic_history_preview.gif'}")


if __name__ == "__main__":
    main()
