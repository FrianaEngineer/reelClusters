"""
Finds the largest safe value for each entry of
cinematic_history_config.CLUSTER_LABEL_SCALE: how much a cluster label on the
video's hex map can be enlarged before its text stops sitting entirely on its
OWN cluster's hexes.

explore.html's label sizes (frozen into data/cinematic_history_hex_snapshot.json)
come from a shrink-to-fit pass that stops at the first size that clears the
cluster -- which can land well under what the cluster actually has room for.
This measures the real thing instead of estimating from a character-width
constant: every line is laid out with matplotlib at the video's own figure
size and dpi, its rendered extent is read back, and every point of that
extent is tested against the nearest hex center's cluster id.

    python3 cinematic_history_label_fit.py                  # report all clusters
    python3 cinematic_history_label_fit.py soviet_cinema    # just these

Findings are printed, never written: paste the ones you want into
CLUSTER_LABEL_SCALE by hand, so the video's labels are never resized as a
silent side effect of running this.
"""

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import cinematic_history_config as cfg  # noqa: E402
import cinematic_history_schedule as sched  # noqa: E402
from cinematic_history_hexmath import axial_to_pixel  # noqa: E402
from cinematic_history_animation import (  # noqa: E402
    FIGURE_WIDTH_IN, HEX_SIZE, build_figure)

# Sampling density across a line's rendered bounding box. The test is "is this
# point on one of my own hexes", so it needs enough points to catch a corner
# poking into a neighbor, not just the centre line.
SAMPLES_X, SAMPLES_Y = 24, 6


def hex_lookup(snapshot):
    centers, owners = [], []
    for h in snapshot["hexes"]:
        centers.append(axial_to_pixel(h["q"], h["r"], HEX_SIZE))
        owners.append(h["cluster_id"])
    return np.array(centers), np.array(owners)


def owner_at(points, centers, owners):
    """Cluster id of the hex whose center is nearest each point. A point
    outside the grid entirely still resolves to the nearest hex, which is the
    conservative answer here: it will not match the label's own cluster
    unless that cluster really does reach it."""
    d = ((points[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
    return owners[d.argmin(axis=1)]


def fits(cluster_id, data, scale, ax, fig, centers, owners, pts_per_data_unit):
    ys = [ln["y"] for ln in data["lines"]]
    y_mid = (max(ys) + min(ys)) / 2
    fontsize_pt = data["fontsize"] * pts_per_data_unit * scale

    probes = []
    for ln in data["lines"]:
        y = y_mid + (ln["y"] - y_mid) * scale
        t = ax.text(ln["x"], y, ln["text"], fontsize=fontsize_pt, fontweight="bold",
                    va="center", ha="center")
        fig.canvas.draw()
        bb = t.get_window_extent(fig.canvas.get_renderer())
        (x0, y0), (x1, y1) = ax.transData.inverted().transform(bb.get_points())
        t.remove()
        gx, gy = np.meshgrid(np.linspace(x0, x1, SAMPLES_X), np.linspace(y0, y1, SAMPLES_Y))
        probes.append(np.column_stack([gx.ravel(), gy.ravel()]))

    pts = np.vstack(probes)
    return bool((owner_at(pts, centers, owners) == cluster_id).all())


def main():
    wanted = sys.argv[1:]
    snapshot = sched.load_snapshot()
    centers, owners = hex_lookup(snapshot)

    # The real figure builder, not a copy of its extent math: the labels must
    # be measured in exactly the axes the video draws them in.
    grid_hexes = [(h["q"], h["r"]) for h in snapshot["hexes"]]
    hex_set = set(grid_hexes)
    hex_cluster_map = {(h["q"], h["r"]): h["cluster_id"] for h in snapshot["hexes"]}
    fig_data = build_figure(grid_hexes, hex_set, hex_cluster_map, dpi=120)
    fig, ax = fig_data["fig"], fig_data["ax"]
    pts_per_data_unit = fig_data["pts_per_data_unit"]

    labels = snapshot["cluster_labels"]
    for cluster_id in (wanted or sorted(labels)):
        data = labels[cluster_id]
        ok_at_1 = fits(cluster_id, data, 1.0, ax, fig, centers, owners, pts_per_data_unit)
        if not ok_at_1:
            print(f"{cluster_id:32} already spills at scale 1.0 -- leave it alone")
            continue
        lo, hi = 1.0, 3.0
        for _ in range(14):
            mid = (lo + hi) / 2
            ok = fits(cluster_id, data, mid, ax, fig, centers, owners, pts_per_data_unit)
            if ok:
                lo = mid
            else:
                hi = mid
        # Back off the measured boundary: the sampled grid can miss a glyph
        # overhang of a fraction of a hex, and the label carries a stroke.
        safe = round(lo * 0.94, 2)
        print(f"{cluster_id:32} snapshot {data['fontsize']:.2f}  max {lo:.2f}x  -> suggested {safe:.2f}x")
    plt.close(fig)


if __name__ == "__main__":
    main()
