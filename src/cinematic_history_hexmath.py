"""
Self-contained hex geometry for the Criterion Over Time video only.

Deliberately NOT imported from hex_grid.py: this project must not depend on
(or risk being affected by future changes to) any shared source file, so the
handful of pure-math formulas needed here (all well-known pointy-top axial
hex formulas, not proprietary logic) are duplicated locally instead.
Positions themselves still come only from data/cinematic_history_hex_snapshot.json
(the frozen extract of site/explore.html) -- this module supplies math, not data.
"""

import numpy as np

S3 = np.sqrt(3)


def axial_to_pixel(q, r, size=1.0):
    return size * (S3 * q + S3 / 2 * r), size * (3 / 2 * r)


def hex_neighbors(q, r):
    return [(q + 1, r), (q - 1, r), (q, r + 1), (q, r - 1), (q + 1, r - 1), (q - 1, r + 1)]


def hex_corners(cx, cy, size=1.0):
    angles = np.radians(30 + np.arange(6) * 60)   # pointy-top: first corner at 30 deg
    return np.column_stack([cx + size * np.cos(angles), cy + size * np.sin(angles)])


# Pointy-top: neighbor direction -> shared corner indices
EDGE_CORNERS = {
    (1, 0): (5, 0),
    (-1, 0): (2, 3),
    (0, 1): (0, 1),
    (0, -1): (3, 4),
    (1, -1): (4, 5),
    (-1, 1): (1, 2),
}


def outer_perimeter_segments(grid_hexes, hex_set, size=1.0):
    """Corner-pair segments for every hex edge that faces fully outside the
    grid (no neighbor in that direction exists in hex_set) -- traces the
    grid's true stepped honeycomb silhouette, not a bounding box. Segments
    are unordered/unstitched; the renderer draws them as independent line
    segments (a LineCollection), which doesn't require stitching into a
    single closed path."""
    segs = []
    for q, r in grid_hexes:
        cx, cy = axial_to_pixel(q, r, size)
        corners = hex_corners(cx, cy, size)
        for (dq, dr), (ci1, ci2) in EDGE_CORNERS.items():
            if (q + dq, r + dr) not in hex_set:
                segs.append((tuple(corners[ci1]), tuple(corners[ci2])))
    return segs
