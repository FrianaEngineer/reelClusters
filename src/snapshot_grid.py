"""
Rebuilds a hex_grid.HexGrid from data/cinematic_history_hex_snapshot.json --
the frozen layout the Criterion Over Time video animates.

Why this exists: hex_grid.py derives the map from whatever the film data
currently says, and the data has moved on since that snapshot was taken
(three clusters have different film counts now), so no amount of re-running
the layout reproduces the map the video uses. Feeding the snapshot's own
hex->cluster assignment into hex_svg.build_svg() gives site/explore.html the
video's exact map, while colors, the Best Picture borders and the cluster
names still come from current code and data.

This supplies POSITIONS ONLY. It does not touch how anything is painted.
"""

import json
from pathlib import Path

from cluster_colors import COLOR_MAP
from hex_grid import HexGrid

SNAPSHOT_PATH = Path(__file__).parent.parent / "data" / "cinematic_history_hex_snapshot.json"
PERIPHERY = {"hiddenGems"}


def load():
    snap = json.loads(SNAPSHOT_PATH.read_text())
    hexes = snap["hexes"]

    # File order is preserved so the emitted <a> blocks come out in the same
    # cluster order the snapshot was written in.
    grid_hexes = [(h["q"], h["r"]) for h in hexes]
    hex_cluster = {(h["q"], h["r"]): h["cluster_id"] for h in hexes}
    hex_film = {(h["q"], h["r"]): h["tconst"] for h in hexes if h["tconst"]}
    hidden_gems_outer = {(h["q"], h["r"]) for h in hexes if h["is_hidden_gems_outer"]}

    cluster_size = {}
    for h in hexes:
        cluster_size[h["cluster_id"]] = cluster_size.get(h["cluster_id"], 0) + 1

    # Same ordering rule hex_grid.py uses for its own large_clusters list
    # (largest first); only min/max of cluster_size feed label sizing, so this
    # ordering affects nothing but the fallback for an unassigned hex.
    large_clusters = sorted((c for c in cluster_size if c not in PERIPHERY),
                            key=lambda c: (-cluster_size[c], c))

    return HexGrid(grid_hexes=grid_hexes, hex_cluster=hex_cluster,
                   hex_set=set(grid_hexes), large_clusters=large_clusters,
                   cluster_size=cluster_size, color_map=COLOR_MAP,
                   hex_film=hex_film, hidden_gems_outer=hidden_gems_outer)


# Per-cluster multiplier on the snapshot's own label font size, for
# site/explore.html. The snapshot's sizes come from a shrink-to-fit pass that
# stops at the first size clearing the cluster, which leaves a few labels
# smaller than the room they actually have. Each value is the largest multiple
# whose real rendered text -- measured in the browser via getBBox(), not
# estimated from a character-width constant -- still sits entirely on its own
# cluster's hexes, with a safety margin applied. Re-measure with
# src/explore_label_fit.py if the snapshot or the names change.
#
# Positions are untouched: only the font size changes, and hex_svg's label
# emit derives line spacing from the font size and re-centers on the same
# anchor, so a multi-line label grows about its own center.
LABEL_SCALE = {
    'soviet_cinema':                1.52,   # 1.00 -> 1.52 data units
    'classic_japanese_cinema':      1.99,   # 1.34 -> 2.67
    'golden_age_hollywood_british': 1.63,   # 1.47 -> 2.40
    # Deliberately short of this one's 2.21x ceiling: at the ceiling it
    # would be the largest label on the map, ahead of clusters several
    # times its size. 2.10 sits between Scandinavian Bergman Circle and
    # Modern American Cinema, which is where its hex count belongs.
    'japanese_new_wave_genre':      1.42,   # 1.48 -> 2.10
}


def load_labels(scale=None):
    """{cluster_id: (x, y, fontsize, [line, ...])} straight from the snapshot's
    own cluster_labels -- the video's label placement and sizing. y is the
    block's center, matching what hex_svg.build_svg(labels=...) expects.

    scale: optional {cluster_id: multiplier}; defaults to LABEL_SCALE."""
    scale = LABEL_SCALE if scale is None else scale
    snap = json.loads(SNAPSHOT_PATH.read_text())
    out = {}
    for cluster_id, d in snap["cluster_labels"].items():
        ys = [ln["y"] for ln in d["lines"]]
        out[cluster_id] = (d["lines"][0]["x"], (max(ys) + min(ys)) / 2,
                           d["fontsize"] * scale.get(cluster_id, 1.0),
                           [ln["text"] for ln in d["lines"]])
    return out
