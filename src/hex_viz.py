"""
Hexagonal grid visualization of Criterion Collection film clusters.
16:9 landscape layout. One hexagon per film.
"""

import duckdb
import numpy as np
import textwrap
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon
from matplotlib.collections import PatchCollection, LineCollection
from sklearn.manifold import MDS
from collections import defaultdict, deque
import heapq
from pathlib import Path

DB_PATH  = Path(__file__).parent.parent / "db" / "criterion_graph.duckdb"
OUT_PATH = Path(__file__).parent.parent / "output" / "hex_cluster_grid.png"

S3 = np.sqrt(3)

# ── Hex math (pointy-top axial coords) ───────────────────────────────────────
# Pointy-top gives clean horizontal rows → fits 16:9 naturally

def axial_to_pixel(q, r, size=1.0):
    return size * (S3 * q + S3/2 * r), size * (3/2 * r)

def cube_dist(q, r):
    return max(abs(q), abs(r), abs(q + r))

def hex_neighbors(q, r):
    return [(q+1,r),(q-1,r),(q,r+1),(q,r-1),(q+1,r-1),(q-1,r+1)]

def hex_corners(cx, cy, size=1.0):
    angles = np.radians(30 + np.arange(6) * 60)   # pointy-top: first corner at 30°
    return np.column_stack([cx + size * np.cos(angles),
                            cy + size * np.sin(angles)])

# Pointy-top: neighbor direction → shared corner indices
EDGE_CORNERS = {
    ( 1,  0): (5, 0),
    (-1,  0): (2, 3),
    ( 0,  1): (0, 1),
    ( 0, -1): (3, 4),
    ( 1, -1): (4, 5),
    (-1,  1): (1, 2),
}

def contrast_color(hex_color):
    r = int(hex_color[1:3], 16) / 255
    g = int(hex_color[3:5], 16) / 255
    b = int(hex_color[5:7], 16) / 255
    lum = 0.299*r + 0.587*g + 0.114*b
    return '#000000' if lum > 0.45 else '#FFFFFF'

# ── 1. Load data ──────────────────────────────────────────────────────────────
print("Loading data...")
con = duckdb.connect(str(DB_PATH))

ca_df = con.execute("SELECT cluster_id, imdb_tconst FROM cluster_assignments").df()

# Films not in the graph (no actor credits OR no shared actors with other films)
# — added as hiddenGems for visualization only, not persisted to DB
no_actor_df = con.execute("""
    SELECT imdb_tconst FROM criterion_basic_info
    WHERE imdb_tconst NOT IN (SELECT imdb_tconst FROM cluster_assignments)
""").df()
n_no_actor = len(no_actor_df)

stats_df = con.execute("""
    WITH es AS (
        SELECT ca_a.cluster_id AS ca, ca_b.cluster_id AS cb, count(*) AS n
        FROM movie_edges me
        JOIN cluster_assignments ca_a ON ca_a.imdb_tconst = me.movie_a
        JOIN cluster_assignments ca_b ON ca_b.imdb_tconst = me.movie_b
        GROUP BY 1, 2
    )
    SELECT
        c.cluster_id,
        count(DISTINCT c.imdb_tconst) AS size,
        coalesce((SELECT sum(n) FROM es WHERE ca = c.cluster_id AND cb = c.cluster_id), 0) AS internal,
        coalesce((SELECT sum(n) FROM es WHERE (ca = c.cluster_id OR cb = c.cluster_id) AND ca != cb), 0) AS external
    FROM cluster_assignments c
    GROUP BY c.cluster_id
""").df()

cross_df = con.execute("""
    SELECT ca_a.cluster_id AS ca, ca_b.cluster_id AS cb, count(*) AS n
    FROM movie_edges me
    JOIN cluster_assignments ca_a ON ca_a.imdb_tconst = me.movie_a
    JOIN cluster_assignments ca_b ON ca_b.imdb_tconst = me.movie_b
    WHERE ca_a.cluster_id != ca_b.cluster_id
    GROUP BY 1, 2
""").df()

con.close()

# ── 2. Cluster properties ─────────────────────────────────────────────────────
cluster_size = ca_df.groupby('cluster_id').size().to_dict()
# Add the no-actor films to hiddenGems size (viz only)
cluster_size['hiddenGems'] = cluster_size.get('hiddenGems', 0) + n_no_actor

stats = stats_df.set_index('cluster_id').to_dict('index')
internal_ratio = {}
for cid, s in stats.items():
    ie, ee = s['internal'], s['external']
    internal_ratio[cid] = ie / (ie + ee) if (ie + ee) > 0 else 0.0

centrality = {c: cluster_size[c] * internal_ratio.get(c, 0) for c in cluster_size}

PERIPHERY       = {'hiddenGems'}
large_clusters  = sorted([c for c in cluster_size if c not in PERIPHERY],
                         key=lambda c: centrality[c], reverse=True)
small_clusters  = [c for c in cluster_size if c in PERIPHERY]

n_large  = sum(cluster_size[c] for c in large_clusters)
n_small  = cluster_size['hiddenGems']
N_TOTAL  = n_large + n_small
print(f"Films: {N_TOTAL}  |  core: {n_large}  |  hiddenGems (incl. {n_no_actor} no-actor): {n_small}")

# ── 3. MDS layout for large clusters ─────────────────────────────────────────
print("Running MDS...")
n_lc   = len(large_clusters)
lc_idx = {c: i for i, c in enumerate(large_clusters)}

edge_mat = np.zeros((n_lc, n_lc))
for _, row in cross_df.iterrows():
    ia = lc_idx.get(row['ca'], -1)
    ib = lc_idx.get(row['cb'], -1)
    if ia >= 0 and ib >= 0:
        edge_mat[ia, ib] += row['n']
        edge_mat[ib, ia] += row['n']

max_e    = edge_mat.max() or 1
dist_mat = 1.0 - edge_mat / max_e
np.fill_diagonal(dist_mat, 0)

mds    = MDS(n_components=2, dissimilarity='precomputed',
             random_state=42, normalized_stress='auto')
mds_xy = mds.fit_transform(dist_mat)
mds_xy -= mds_xy.mean(axis=0)

# ── 4. Generate 16:9 rectangular hex grid (pointy-top) ───────────────────────
print("Generating hex grid...")

# For pointy-top: pixel_y = 3/2 * r  →  rows are clean horizontal bands
# Target: ~N_TOTAL hexes in 16:9 pixel rectangle
# Hex packing density ≈ 1 / (√3 * 1.5) ≈ 0.385 hexes/unit²
# For N hexes: area ≈ N / 0.385; with 16:9 → H ≈ sqrt(area/1.778), W = H*1.778
area_needed = N_TOTAL / 0.385
PH = np.sqrt(area_needed / (16/9)) * 1.05   # slight oversize so we can trim
PW = PH * (16/9)

def rect_priority(q, r):
    """Normalized Chebyshev distance from center in 16:9 space (0=center, 1=edge)."""
    px, py = axial_to_pixel(q, r)
    return max(abs(px) / (PW/2), abs(py) / (PH/2))

all_hexes = []
Q_MAX = int(PW / S3) + 3
R_MAX = int(PH / 1.5) + 3
for q in range(-Q_MAX, Q_MAX + 1):
    for r in range(-R_MAX, R_MAX + 1):
        px, py = axial_to_pixel(q, r)
        if abs(px) <= PW/2 + S3/2 and abs(py) <= PH/2 + 1.0:
            all_hexes.append((q, r))

# Sort innermost-first in 16:9 normalized space, take exactly N_TOTAL
all_hexes.sort(key=lambda h: rect_priority(h[0], h[1]))
grid_hexes = all_hexes[:N_TOTAL]
hex_set    = set(grid_hexes)

# Border = has at least one neighbor outside the grid
border_hexes   = [h for h in grid_hexes
                  if any(n not in hex_set for n in hex_neighbors(h[0], h[1]))]
interior_hexes = [h for h in grid_hexes if h not in set(border_hexes)]

# Sort border outer-first, interior inner-first (in 16:9 normalized space)
border_hexes.sort(key=lambda h: -rect_priority(h[0], h[1]))
interior_hexes.sort(key=lambda h: rect_priority(h[0], h[1]))

print(f"Grid: {len(grid_hexes)} hexes  |  border: {len(border_hexes)}  |  interior: {len(interior_hexes)}")
print(f"hiddenGems needs: {n_small}")

while len(border_hexes) < n_small and interior_hexes:
    border_hexes.append(interior_hexes.pop())
    border_hexes.sort(key=lambda h: -rect_priority(h[0], h[1]))

# ── 5. Assign hexes to clusters ───────────────────────────────────────────────
print("Assigning hexes to clusters...")
hex_cluster       = {}
cluster_remaining = {c: cluster_size[c] for c in cluster_size}

# Phase A: border → hiddenGems
for h in border_hexes[:n_small]:
    hex_cluster[h] = 'hiddenGems'
    cluster_remaining['hiddenGems'] -= 1

# Phase B: interior → large clusters via MDS-seeded BFS
int_px_map = {h: np.array(axial_to_pixel(h[0], h[1])) for h in interior_hexes}
available  = set(interior_hexes) - set(hex_cluster)

# Scale MDS to interior pixel range
int_px    = np.array(list(int_px_map.values()))
px_range  = int_px.max(axis=0) - int_px.min(axis=0)
mds_range = np.abs(mds_xy).max(axis=0)
mds_range[mds_range == 0] = 1
mds_scaled = mds_xy * (px_range * 0.40 / mds_range)

lc_target  = {c: mds_scaled[lc_idx[c]] for c in large_clusters}

used_seeds = set()
seeds      = {}
for c in large_clusters:
    best = min((h for h in available if h not in used_seeds),
               key=lambda h: np.linalg.norm(int_px_map[h] - lc_target[c]))
    seeds[c] = best
    used_seeds.add(best)

heap    = []
in_heap = set()
for c, seed in seeds.items():
    hex_cluster[seed] = c
    cluster_remaining[c] -= 1
    in_heap.add(seed)
    for nb in hex_neighbors(seed[0], seed[1]):
        if nb in available and nb not in in_heap:
            d = np.linalg.norm(int_px_map.get(nb, np.array(axial_to_pixel(*nb))) - lc_target[c])
            heapq.heappush(heap, (d, large_clusters.index(c), c, nb))
            in_heap.add(nb)

while heap:
    d, _, c, h = heapq.heappop(heap)
    if h in hex_cluster or cluster_remaining.get(c, 0) <= 0:
        continue
    hex_cluster[h] = c
    cluster_remaining[c] -= 1
    for nb in hex_neighbors(h[0], h[1]):
        if nb in available and nb not in hex_cluster:
            nd = np.linalg.norm(int_px_map.get(nb, np.array(axial_to_pixel(*nb))) - lc_target[c])
            heapq.heappush(heap, (nd, large_clusters.index(c), c, nb))

# Second pass: adjacency-based fill for stragglers
remaining = sorted([h for h in interior_hexes if h not in hex_cluster],
                   key=lambda h: rect_priority(h[0], h[1]))
for h in remaining:
    adj_cap = [hex_cluster[nb] for nb in hex_neighbors(h[0], h[1])
               if nb in hex_cluster and hex_cluster.get(nb) in large_clusters
               and cluster_remaining.get(hex_cluster[nb], 0) > 0]
    if adj_cap:
        c = max(set(adj_cap), key=lambda c: cluster_remaining.get(c, 0))
    else:
        c = max((c for c in large_clusters if cluster_remaining.get(c, 0) > 0),
                key=lambda c: cluster_remaining.get(c, 0), default=large_clusters[0])
    hex_cluster[h] = c
    cluster_remaining[c] = max(0, cluster_remaining.get(c, 0) - 1)

print(f"  Assigned {len(hex_cluster)} / {N_TOTAL}")

# ── Post-processing: fix disconnected fragments ───────────────────────────────
def get_components(cid):
    ch = {h for h, c in hex_cluster.items() if c == cid}
    visited, comps = set(), []
    for start in ch:
        if start in visited:
            continue
        comp, q = set(), deque([start])
        while q:
            h = q.popleft()
            if h in visited or h not in ch:
                continue
            visited.add(h); comp.add(h)
            for nb in hex_neighbors(h[0], h[1]):
                if nb in ch and nb not in visited:
                    q.append(nb)
        comps.append(comp)
    return comps

for _ in range(10):
    any_fixed = False
    for c in large_clusters:
        comps = get_components(c)
        if len(comps) <= 1:
            continue
        any_fixed = True
        largest = max(comps, key=len)
        for comp in comps:
            if comp is largest:
                continue
            for h in comp:
                adj = [hex_cluster.get(nb) for nb in hex_neighbors(h[0], h[1])
                       if nb in hex_set and hex_cluster.get(nb) != c]
                adj = [a for a in adj if a]
                hex_cluster[h] = max(set(adj), key=adj.count) if adj else large_clusters[0]
    if not any_fixed:
        break

print(f"  Fragments remaining: {sum(len(get_components(c))-1 for c in large_clusters)}")

# ── 6. Color map ──────────────────────────────────────────────────────────────
color_map = {
    'hiddenGems':               '#FFFFFF',
    'european_art_cinema':      '#7B1E3A',
    'japanese_cinema':          '#1D3557',
    'anglophone_classic':       '#457B9D',
    'american_independent':     '#F4A261',
    'hong_kong_taiwan_cinema':  '#E63946',
    'bergman_scandinavian':     '#5E6472',
    'new_german_cinema':        '#2A9D8F',
    'czech_new_wave':           '#B56576',
    'soviet_cinema':            '#9D0208',
    'satyajit_ray_indian':      '#F77F00',
    'youssef_chahine_egyptian': '#8D6E63',
}

# ── 7. Draw ───────────────────────────────────────────────────────────────────
print("Drawing...")
HEX_SIZE = 1.0
GAP      = 0.95

fig, ax = plt.subplots(figsize=(32, 18), facecolor='#12121f')
ax.set_aspect('equal')
ax.axis('off')

# Hexagon fills grouped by cluster (faster rendering)
by_cluster = defaultdict(list)
for h in grid_hexes:
    cx, cy  = axial_to_pixel(h[0], h[1], HEX_SIZE)
    corners = hex_corners(cx, cy, HEX_SIZE * GAP)
    by_cluster[hex_cluster.get(h, large_clusters[0])].append(Polygon(corners, closed=True))

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

# ── 8. Cluster labels ─────────────────────────────────────────────────────────
all_named = large_clusters + ['hiddenGems']
min_size  = min(cluster_size[c] for c in large_clusters)
max_size  = max(cluster_size[c] for c in large_clusters)

for c in all_named:
    col = color_map.get(c, '#888888')
    txt_col = contrast_color(col)

    # Font size proportional to sqrt of cluster area
    fsize = 7 + 10 * np.sqrt(max(0, cluster_size[c] - min_size) / (max_size - min_size))
    fsize = max(6.5, min(fsize, 18))

    cluster_hexes = [h for h, cl in hex_cluster.items() if cl == c]
    if not cluster_hexes:
        continue

    pixels = np.array([axial_to_pixel(h[0], h[1], HEX_SIZE) for h in cluster_hexes])

    if c == 'hiddenGems':
        # Place label at top center of the border band
        top_hexes = sorted(cluster_hexes, key=lambda h: -axial_to_pixel(h[0], h[1])[1])[:12]
        top_px    = np.array([axial_to_pixel(h[0], h[1]) for h in top_hexes])
        lx, ly    = top_px[:, 0].mean(), top_px[:, 1].max() + 0.5
    else:
        centroid  = pixels.mean(axis=0)
        # Pick the hex closest to centroid within the cluster
        dists     = np.linalg.norm(pixels - centroid, axis=1)
        lx, ly    = pixels[np.argmin(dists)]

    label   = c.replace('_', ' ').title()
    wrapped = '\n'.join(textwrap.wrap(label, width=11))

    ax.text(lx, ly, wrapped,
            ha='center', va='center',
            color=txt_col,
            fontsize=fsize,
            fontweight='bold',
            linespacing=1.25,
            multialignment='center',
            alpha=0.92)

# Fit view tightly to grid
all_px = np.array([axial_to_pixel(q, r, HEX_SIZE) for q, r in grid_hexes])
margin = HEX_SIZE * 1.5
ax.set_xlim(all_px[:,0].min() - margin, all_px[:,0].max() + margin)
ax.set_ylim(all_px[:,1].min() - margin, all_px[:,1].max() + margin)

plt.tight_layout(pad=0)
plt.savefig(str(OUT_PATH), dpi=150, bbox_inches='tight',
            facecolor=fig.get_facecolor())
print(f"Saved → {OUT_PATH}")
