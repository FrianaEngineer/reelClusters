"""
Background image for the "Find Your Film" homepage hero: a honeycomb mosaic
built from this project's own real cluster colors (cluster_colors.COLOR_MAP)
and real cluster sizes (cluster_assignments), not decorative stock art. Each
hex is one random draw from the actual distribution of films across
clusters, echoing the hex-per-film language used by hex_svg.py's
explore-the-clusters grid, but shuffled into an unpositioned texture rather
than the real cluster map -- this is a mood/texture background, not a data
visualization, so it's deliberately not trying to be read as one.

The real color/black-and-white split from data/film_color.csv is reused too
(see hex_svg.py's own darken() convention for the same idea).

    python3 build_find_your_film_hero.py
"""

import csv
import random
from pathlib import Path

import duckdb
import numpy as np

from hex_grid import DB_PATH, axial_to_pixel, hex_corners
from cluster_colors import COLOR_MAP

REPO_ROOT = Path(__file__).parent.parent
FILM_COLOR_CSV = REPO_ROOT / "data" / "film_color.csv"
OUT_PATH = REPO_ROOT / "site" / "assets" / "find_your_film_hero.svg"

CANVAS_W, CANVAS_H = 1600, 900
HEX_SIZE = 18
BW_DARKEN_FACTOR = 0.65
# A hero *background* needs to sit behind readable text under the same
# scrim every other hero uses -- at full saturation, hundreds of small
# bright hexes read as loud confetti (especially near the top, where the
# scrim is thinnest). Dimming every tile toward the site's own dark navy
# keeps the real color identity of each cluster recognizable while reading
# as calm, moody texture rather than a stained-glass window.
GLOBAL_DIM = 0.4
BASE_BG = (0x12, 0x12, 0x1f)
SEED = 42  # fixed, like the MDS/Louvain seeds elsewhere in this project


def darken(hex_color, factor=BW_DARKEN_FACTOR):
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    return f"#{int(r * factor):02x}{int(g * factor):02x}{int(b * factor):02x}"


def dim_toward_bg(hex_color, factor=GLOBAL_DIM):
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    br, bg, bb = BASE_BG
    r = r * factor + br * (1 - factor)
    g = g * factor + bg * (1 - factor)
    b = b * factor + bb * (1 - factor)
    return f"#{int(r):02x}{int(g):02x}{int(b):02x}"


def cluster_weights(con):
    df = con.execute(
        "SELECT cluster_id, count(*) AS n FROM cluster_assignments GROUP BY 1"
    ).df()
    return list(df["cluster_id"]), list(df["n"])


def bw_ratio():
    if not FILM_COLOR_CSV.exists():
        return 0.5
    counts = {"color": 0, "black-and-white": 0}
    with FILM_COLOR_CSV.open(newline="") as f:
        for row in csv.DictReader(f):
            label = row["color_label"]
            if label in counts:
                counts[label] += 1
    total = counts["color"] + counts["black-and-white"]
    return counts["black-and-white"] / total if total else 0.5


def hex_polygon_points(cx, cy, size):
    corners = hex_corners(cx, cy, size)
    return " ".join(f"{x:.2f},{y:.2f}" for x, y in corners)


def build_svg():
    con = duckdb.connect(str(DB_PATH), read_only=True)
    cluster_ids, weights = cluster_weights(con)
    con.close()

    rng = random.Random(SEED)
    bw_frac = bw_ratio()

    step_x = np.sqrt(3) * HEX_SIZE
    step_y = 1.5 * HEX_SIZE

    hexes = []
    row = 0
    y = -HEX_SIZE
    while y < CANVAS_H + HEX_SIZE:
        x_offset = (step_x / 2) if row % 2 else 0
        x = -HEX_SIZE + x_offset
        while x < CANVAS_W + HEX_SIZE:
            cluster_id = rng.choices(cluster_ids, weights=weights, k=1)[0]
            color = COLOR_MAP.get(cluster_id, "#888888")
            if rng.random() < bw_frac:
                color = darken(color)
            color = dim_toward_bg(color)
            hexes.append((x, y, color))
            x += step_x
        y += step_y
        row += 1

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {CANVAS_W} {CANVAS_H}" '
        f'width="{CANVAS_W}" height="{CANVAS_H}">',
        f'<rect width="{CANVAS_W}" height="{CANVAS_H}" fill="#12121f"/>',
    ]
    for cx, cy, color in hexes:
        points = hex_polygon_points(cx, cy, HEX_SIZE * 0.96)
        parts.append(f'<polygon points="{points}" fill="{color}" stroke="#0a0a14" stroke-width="0.6"/>')
    parts.append("</svg>")

    OUT_PATH.write_text("\n".join(parts))
    print(f"Wrote {len(hexes):,} hexes to {OUT_PATH}")


if __name__ == "__main__":
    build_svg()
