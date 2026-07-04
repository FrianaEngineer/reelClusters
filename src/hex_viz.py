"""
Hexagonal grid visualization of Criterion Collection film clusters.

Layout rules:
  - One hexagon per film
  - Color = cluster (nominal palette)
  - Large/dense clusters at center, small clusters + hiddenGems at periphery
  - Cluster boundaries drawn as white lines
  - Inter-cluster proximity derived from cross-cluster edge counts via MDS
"""

import duckdb
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon
from matplotlib.collections import PatchCollection, LineCollection
import matplotlib.patches as mpatches
from sklearn.manifold import MDS
from collections import defaultdict
import heapq
from pathlib import Path

DB_PATH  = Path(__file__).parent.parent / "db" / "criterion_graph.duckdb"
OUT_PATH = Path(__file__).parent.parent / "output" / "hex_cluster_grid.png"

S3 = np.sqrt(3)

# ── Hex math (flat-top axial coords) ─────────────────────────────────────────

def axial_to_pixel(q, r, size=1.0):
    return size * 1.5 * q, size * (S3/2 * q + S3 * r)

def cube_dist(q, r):
    return max(abs(q), abs(r), abs(q + r))

def hex_neighbors(q, r):
    return [(q+1,r),(q-1,r),(q,r+1),(q,r-1),(q+1,r-1),(q-1,r+1)]

def hex_corners(cx, cy, size=1.0):
    angles = np.radians(np.arange(6) * 60)
    return np.column_stack([cx + size * np.cos(angles),
                            cy + size * np.sin(angles)])

# Flat-top neighbor direction → which two corner indices form the shared edge
EDGE_CORNERS = {
    ( 1,  0): (0, 5),
    ( 1, -1): (5, 4),
    ( 0, -1): (4, 3),
    (-1,  0): (3, 2),
    (-1,  1): (2, 1),
    ( 0,  1): (1, 0),
}

# ── 1. Load data ──────────────────────────────────────────────────────────────
print("Loading data...")
con = duckdb.connect(str(DB_PATH))

ca_df = con.execute("SELECT cluster_id, imdb_tconst FROM cluster_assignments").df()

# Internal / external edges per cluster
stats_df = con.execute("""
    WITH es AS (
        SELECT ca_a.cluster_id AS ca, ca_b.cluster_id AS cb, count(*) AS n
        FROM movie_edges me
        JOIN cluster_assignments ca_a ON ca_a.imdb_tconst = me.movie_a
        JOIN cluster_assignments ca_b ON ca_b.imdb_tconst = me.movie_b
        GROUP BY 1, 2
    )
    SELECT
        grp.cluster_id,
        count(DISTINCT grp.imdb_tconst) AS size,
        coalesce((SELECT sum(n) FROM es WHERE ca = grp.cluster_id AND cb = grp.cluster_id), 0) AS internal,
        coalesce((SELECT sum(n) FROM es WHERE (ca = grp.cluster_id OR cb = grp.cluster_id) AND ca != cb), 0) AS external
    FROM cluster_assignments grp
    GROUP BY grp.cluster_id
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
cluster_size  = ca_df.groupby('cluster_id').size().to_dict()
stats         = stats_df.set_index('cluster_id').to_dict('index')

internal_ratio = {}
for cid, s in stats.items():
    ie, ee = s['internal'], s['external']
    internal_ratio[cid] = ie / (ie + ee) if (ie + ee) > 0 else 0.0

centrality = {c: cluster_size[c] * internal_ratio.get(c, 0) for c in cluster_size}

PERIPHERY = {'hiddenGems'}
large_clusters = sorted([c for c in cluster_size if c not in PERIPHERY],
                        key=lambda c: centrality[c], reverse=True)
small_clusters = [c for c in cluster_size if c in PERIPHERY]

n_large = sum(cluster_size[c] for c in large_clusters)
n_small = sum(cluster_size[c] for c in small_clusters)
N_TOTAL = n_large + n_small
print(f"Films: {N_TOTAL}  |  core clusters: {len(large_clusters)} ({n_large} films)  "
      f"|  periphery (hiddenGems): {n_small} films")

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

mds     = MDS(n_components=2, dissimilarity='precomputed', random_state=42, normalized_stress='auto')
mds_xy  = mds.fit_transform(dist_mat)
mds_xy -= mds_xy.mean(axis=0)

# ── 4. Generate hex grid ──────────────────────────────────────────────────────
print("Generating hex grid...")
R         = 26
all_hexes = [(q, r) for q in range(-R, R+1) for r in range(-R, R+1)
             if cube_dist(q, r) <= R]
all_hexes.sort(key=lambda h: (cube_dist(h[0], h[1]), h[0], h[1]))
grid_hexes = all_hexes[:N_TOTAL]
hex_set    = set(grid_hexes)

# Border hexes: at least one neighbor missing from grid
border_hexes   = [h for h in grid_hexes
                  if any(n not in hex_set for n in hex_neighbors(h[0], h[1]))]
interior_hexes = [h for h in grid_hexes if h not in set(border_hexes)]

# Sort: border outer-first, interior inner-first
border_hexes.sort(key=lambda h: -cube_dist(h[0], h[1]))
interior_hexes.sort(key=lambda h: cube_dist(h[0], h[1]))

print(f"Border: {len(border_hexes)}  |  Interior: {len(interior_hexes)}  "
      f"|  Small films needing border: {n_small}")

# If not enough border hexes, pull from outermost interior
while len(border_hexes) < n_small and interior_hexes:
    border_hexes.append(interior_hexes.pop())
    border_hexes.sort(key=lambda h: -cube_dist(h[0], h[1]))

# ── 5. Assign hexes to clusters ───────────────────────────────────────────────
print("Assigning hexes to clusters...")
hex_cluster       = {}
cluster_remaining = {c: cluster_size[c] for c in cluster_size}

# Phase A: border hexes → small clusters (outermost first)
small_queue = []
for c in small_clusters:
    small_queue.extend([c] * cluster_size[c])

for i, h in enumerate(border_hexes):
    if i < len(small_queue):
        hex_cluster[h] = small_queue[i]
        cluster_remaining[small_queue[i]] -= 1

# Phase B: interior hexes → large clusters via seeded BFS
#   Seed position = MDS-derived pixel mapped into hex grid pixel space
int_px = np.array([axial_to_pixel(q, r) for q, r in interior_hexes])
px_range  = int_px.max(axis=0) - int_px.min(axis=0)
mds_range = np.abs(mds_xy).max(axis=0)
mds_range[mds_range == 0] = 1
scale   = px_range * 0.40 / mds_range
mds_scaled = mds_xy * scale  # centered at 0,0

# Map each large cluster to its target pixel in hex space
lc_target = {c: mds_scaled[lc_idx[c]] for c in large_clusters}

# Pixel lookup for all interior hexes
int_px_map = {h: np.array(axial_to_pixel(h[0], h[1])) for h in interior_hexes}
available  = set(interior_hexes) - set(hex_cluster)

# Find seed hex (closest unoccupied interior hex to MDS target)
used_seeds = set()
seeds      = {}
for c in large_clusters:
    target  = lc_target[c]
    best    = min((h for h in available if h not in used_seeds),
                  key=lambda h: np.linalg.norm(int_px_map[h] - target))
    seeds[c]   = best
    used_seeds.add(best)

# Simultaneous BFS growth — min-heap: (dist_from_seed, tie_breaker, cluster, hex)
heap = []
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

# Second pass: assign remaining interior hexes by adjacency (not MDS distance)
# — this preserves connectivity by only attaching to already-assigned neighbours
remaining_interior = sorted(
    [h for h in interior_hexes if h not in hex_cluster],
    key=lambda h: cube_dist(h[0], h[1])
)
for h in remaining_interior:
    adj_with_cap = [
        hex_cluster[nb] for nb in hex_neighbors(h[0], h[1])
        if nb in hex_cluster
        and hex_cluster[nb] in large_clusters
        and cluster_remaining.get(hex_cluster[nb], 0) > 0
    ]
    if adj_with_cap:
        c = max(set(adj_with_cap), key=lambda c: cluster_remaining.get(c, 0))
    else:
        c = max((c for c in large_clusters if cluster_remaining.get(c, 0) > 0),
                key=lambda c: cluster_remaining.get(c, 0),
                default=large_clusters[0])
    hex_cluster[h] = c
    cluster_remaining[c] = max(0, cluster_remaining.get(c, 0) - 1)

print(f"  Assigned {len(hex_cluster)} / {N_TOTAL} hexes")

# ── Post-processing: fix any disconnected cluster fragments ───────────────────
from collections import deque

def get_components(cid):
    cluster_hexes = {h for h, c in hex_cluster.items() if c == cid}
    visited, components = set(), []
    for start in cluster_hexes:
        if start in visited:
            continue
        comp, q = set(), deque([start])
        while q:
            h = q.popleft()
            if h in visited or h not in cluster_hexes:
                continue
            visited.add(h); comp.add(h)
            for nb in hex_neighbors(h[0], h[1]):
                if nb in cluster_hexes and nb not in visited:
                    q.append(nb)
        components.append(comp)
    return components

for iteration in range(10):
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
            # Reassign each hex in this fragment to its most common adjacent cluster
            for h in comp:
                adj = [hex_cluster.get(nb) for nb in hex_neighbors(h[0], h[1])
                       if nb in hex_set and hex_cluster.get(nb) != c]
                adj = [a for a in adj if a is not None]
                new_c = max(set(adj), key=adj.count) if adj else large_clusters[0]
                hex_cluster[h] = new_c
    if not any_fixed:
        break

n_frags = sum(len(get_components(c)) - 1 for c in large_clusters)
print(f"  Remaining fragments after connectivity fix: {n_frags}")

# ── 6. Color palette ──────────────────────────────────────────────────────────
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
GAP      = 0.94   # shrink each hex slightly so gaps appear between them

fig, ax = plt.subplots(figsize=(26, 26), facecolor='#12121f')
ax.set_aspect('equal')
ax.axis('off')

# Draw hexagons
patches_by_cluster = defaultdict(list)
for h in grid_hexes:
    cx, cy  = axial_to_pixel(h[0], h[1], HEX_SIZE)
    c       = hex_cluster.get(h, large_clusters[0])
    corners = hex_corners(cx, cy, HEX_SIZE * GAP)
    poly    = Polygon(corners, closed=True)
    patches_by_cluster[c].append(poly)

for c, patches in patches_by_cluster.items():
    pc = PatchCollection(patches, facecolor=color_map[c], edgecolor='none')
    ax.add_collection(pc)

# Draw cluster boundaries
boundary_segs = []
for h in grid_hexes:
    q, r    = h
    c1      = hex_cluster.get(h)
    cx, cy  = axial_to_pixel(q, r, HEX_SIZE)
    corners = hex_corners(cx, cy, HEX_SIZE)
    for (dq, dr), (ci1, ci2) in EDGE_CORNERS.items():
        nb = (q + dq, r + dr)
        c2 = hex_cluster.get(nb)
        if nb in hex_set and c2 is not None and c2 != c1:
            boundary_segs.append([corners[ci1], corners[ci2]])

lc_col = LineCollection(boundary_segs, colors='#12121f', linewidths=1.8)
ax.add_collection(lc_col)

# ── 8. Legend ─────────────────────────────────────────────────────────────────
legend_handles = []
legend_order = large_clusters + ['hiddenGems']
for c in legend_order:
    label = c.replace('_', ' ').title()
    legend_handles.append(
        mpatches.Patch(facecolor=color_map.get(c, '#888888'),
                       edgecolor='#444444', linewidth=0.5,
                       label=f"{label}  ({cluster_size.get(c, 0)})"))

leg = ax.legend(handles=legend_handles, loc='lower right', fontsize=11,
                framealpha=0.85, facecolor='#1e1e35', labelcolor='white',
                edgecolor='#555', ncol=2, handlelength=1.2,
                borderpad=0.8, labelspacing=0.5)

ax.set_title('Criterion Collection — Actor Co-occurrence Clusters\n'
             'Each hexagon = one film  ·  Color = cluster  ·  '
             'White lines = cluster boundaries',
             color='white', fontsize=15, pad=16, linespacing=1.6)

# Fit view
all_px = [axial_to_pixel(q, r, HEX_SIZE) for q, r in grid_hexes]
xs, ys = zip(*all_px)
margin = HEX_SIZE * 2.5
ax.set_xlim(min(xs) - margin, max(xs) + margin)
ax.set_ylim(min(ys) - margin, max(ys) + margin)

plt.tight_layout(pad=0.5)
plt.savefig(str(OUT_PATH), dpi=150, bbox_inches='tight',
            facecolor=fig.get_facecolor())
print(f"Saved → {OUT_PATH}")
