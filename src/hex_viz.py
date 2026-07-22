"""
Hexagonal grid visualization of Criterion Collection film clusters.
16:9 landscape layout. One hexagon per film.
"""

import numpy as np
import textwrap
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon
from matplotlib.collections import PatchCollection, LineCollection
import matplotlib.patheffects as pe
from pathlib import Path

from hex_grid import build_hex_grid, axial_to_pixel, hex_corners, hex_neighbors, EDGE_CORNERS, display_name

OUT_PATH = Path(__file__).parent.parent / "output" / "hex_cluster_grid.png"

print("Building hex grid...")
grid = build_hex_grid()
grid_hexes      = grid.grid_hexes
hex_cluster     = grid.hex_cluster
hex_set         = grid.hex_set
large_clusters  = grid.large_clusters
cluster_size    = grid.cluster_size
color_map       = grid.color_map

print(f"Grid: {len(grid_hexes)} hexes")

# ── Draw ──────────────────────────────────────────────────────────────────────
print("Drawing...")
HEX_SIZE = 1.0
GAP      = 0.95

fig, ax = plt.subplots(figsize=(32, 18), facecolor='#12121f')
ax.set_aspect('equal')
ax.axis('off')

# Hexagon fills grouped by cluster (faster rendering)
by_cluster = {}
for h in grid_hexes:
    cx, cy  = axial_to_pixel(h[0], h[1], HEX_SIZE)
    corners = hex_corners(cx, cy, HEX_SIZE * GAP)
    by_cluster.setdefault(hex_cluster.get(h, large_clusters[0]), []).append(Polygon(corners, closed=True))

for c, patches in by_cluster.items():
    ax.add_collection(PatchCollection(patches,
                                      facecolor=color_map.get(c, '#888888'),
                                      edgecolor='none'))

# Cluster boundary lines
boundary_segs = []
for h in grid_hexes:
    q, r = h
    c1      = hex_cluster.get(h)
    cx, cy  = axial_to_pixel(q, r, HEX_SIZE)
    corners = hex_corners(cx, cy, HEX_SIZE)
    for (dq, dr), (ci1, ci2) in EDGE_CORNERS.items():
        nb = (q+dq, r+dr)
        c2 = hex_cluster.get(nb)
        if nb in hex_set and c2 is not None and c2 != c1:
            boundary_segs.append([corners[ci1], corners[ci2]])

ax.add_collection(LineCollection(boundary_segs, colors='#12121f', linewidths=1.6))

# ── Cluster labels ────────────────────────────────────────────────────────────
all_named = large_clusters + ['hiddenGems']
min_size  = min(cluster_size[c] for c in large_clusters)
max_size  = max(cluster_size[c] for c in large_clusters)

# Uniform label size, matching what european_art_cinema would get under the old
# size-by-cluster-area formula, scaled up a bit for legibility.
FSIZE = 7 + 10 * np.sqrt(max(0, cluster_size['european_art_cinema'] - min_size) / (max_size - min_size))
FSIZE = max(6.5, min(FSIZE, 18)) * 1.3

# Grid's vertical midpoint, used to tell the top border band apart from the bottom one
grid_y_mid = (max(axial_to_pixel(q, r)[1] for q, r in grid_hexes)
              + min(axial_to_pixel(q, r)[1] for q, r in grid_hexes)) / 2

# Manual nudges for labels whose auto-placed position reads poorly against their
# cluster's actual shape (found by inspection, not derivable from the geometry alone).
LABEL_OFFSETS = {
    'european_art_cinema': (0, -3.0),   # push down, out of the way of neighboring clusters
    'anglophone_classic':  (2.5, 0),    # push right, toward the cluster's visual center
}

for c in all_named:
    txt_col = 'black' if c == 'hiddenGems' else 'white'

    cluster_hexes = [h for h, cl in hex_cluster.items() if cl == c]
    if not cluster_hexes:
        continue

    pixels = np.array([axial_to_pixel(h[0], h[1], HEX_SIZE) for h in cluster_hexes])

    if c == 'hiddenGems':
        # Center horizontally on the top row, then vertically on the full thickness of
        # the top border band at that column (not just the single outermost row), so the
        # label sits in the middle of the band rather than hugging its top edge.
        top_y   = max(axial_to_pixel(h[0], h[1])[1] for h in cluster_hexes)
        top_row = [h for h in cluster_hexes if abs(axial_to_pixel(h[0], h[1])[1] - top_y) < 1e-6]
        lx      = np.mean([axial_to_pixel(h[0], h[1])[0] for h in top_row])
        band    = [h for h in cluster_hexes
                   if axial_to_pixel(h[0], h[1])[1] > grid_y_mid
                   and abs(axial_to_pixel(h[0], h[1])[0] - lx) < np.sqrt(3) * 1.5]
        ly      = np.mean([axial_to_pixel(h[0], h[1])[1] for h in band])
    else:
        centroid  = pixels.mean(axis=0)
        # Pick the hex closest to centroid within the cluster
        dists     = np.linalg.norm(pixels - centroid, axis=1)
        lx, ly    = pixels[np.argmin(dists)]

    dx, dy = LABEL_OFFSETS.get(c, (0, 0))
    lx += dx
    ly += dy

    label   = display_name(c)
    wrapped = '\n'.join(textwrap.wrap(label, width=11, break_long_words=False))

    txt = ax.text(lx, ly, wrapped,
                  ha='center', va='center',
                  color=txt_col,
                  fontsize=FSIZE,
                  fontweight='bold',
                  linespacing=1.25,
                  multialignment='center',
                  alpha=0.92)
    if txt_col == 'white':
        txt.set_path_effects([pe.withStroke(linewidth=3.2, foreground='black')])

# Fit view tightly to grid
all_px = np.array([axial_to_pixel(q, r, HEX_SIZE) for q, r in grid_hexes])
margin = HEX_SIZE * 1.5
ax.set_xlim(all_px[:,0].min() - margin, all_px[:,0].max() + margin)
ax.set_ylim(all_px[:,1].min() - margin, all_px[:,1].max() + margin)

plt.tight_layout(pad=0)
plt.savefig(str(OUT_PATH), dpi=150, bbox_inches='tight',
            facecolor=fig.get_facecolor())
print(f"Saved -> {OUT_PATH}")
