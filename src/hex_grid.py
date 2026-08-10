"""
Shared hex-grid geometry and cluster-to-hex assignment for the Criterion
Collection hex visualization. hex_viz.py (static PNG) and hex_svg.py
(interactive SVG for the website) both build on top of this so the two
renderers can never drift out of sync with each other.
"""

import re
import heapq
from collections import Counter, defaultdict, deque
from pathlib import Path

import duckdb
import numpy as np
from sklearn.manifold import MDS

from cluster_colors import COLOR_MAP

DB_PATH = Path(__file__).parent.parent / "db" / "criterion_graph.duckdb"

S3 = np.sqrt(3)

# ── Hex math (pointy-top axial coords) ───────────────────────────────────────
# Pointy-top gives clean horizontal rows -> fits 16:9 naturally

def axial_to_pixel(q, r, size=1.0):
    return size * (S3 * q + S3 / 2 * r), size * (3 / 2 * r)


def hex_neighbors(q, r):
    return [(q + 1, r), (q - 1, r), (q, r + 1), (q, r - 1), (q + 1, r - 1), (q - 1, r + 1)]


def hex_corners(cx, cy, size=1.0):
    angles = np.radians(30 + np.arange(6) * 60)   # pointy-top: first corner at 30 deg
    return np.column_stack([cx + size * np.cos(angles),
                             cy + size * np.sin(angles)])


# Pointy-top: neighbor direction -> shared corner indices
EDGE_CORNERS = {
    (1, 0): (5, 0),
    (-1, 0): (2, 3),
    (0, 1): (0, 1),
    (0, -1): (3, 4),
    (1, -1): (4, 5),
    (-1, 1): (1, 2),
}


DISPLAY_NAME_OVERRIDES = {}


def display_name(cluster_id):
    """cluster_id -> readable label, handling both snake_case and camelCase."""
    if cluster_id in DISPLAY_NAME_OVERRIDES:
        return DISPLAY_NAME_OVERRIDES[cluster_id]
    s = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', cluster_id)
    return s.replace('_', ' ').title()


class HexGrid:
    def __init__(self, grid_hexes, hex_cluster, hex_set, large_clusters,
                 cluster_size, color_map, hex_film, hidden_gems_outer):
        self.grid_hexes = grid_hexes
        self.hex_cluster = hex_cluster
        self.hex_set = hex_set
        self.large_clusters = large_clusters
        self.cluster_size = cluster_size
        self.hex_film = hex_film
        self.color_map = color_map
        # The subset of hiddenGems hexes that sit on the grid's true outer
        # edge (as opposed to the ring just inside it) -- lets a renderer
        # give the two rings different shading.
        self.hidden_gems_outer = hidden_gems_outer


def build_hex_grid():
    # ── 1. Load data ──────────────────────────────────────────────────────
    con = duckdb.connect(str(DB_PATH))

    ca_df = con.execute("SELECT cluster_id, imdb_tconst FROM cluster_assignments").df()

    # Films not in the graph (no actor credits OR no shared actors with other
    # films) -- added as hiddenGems for visualization only, not persisted to DB
    no_actor_df = con.execute("""
        SELECT imdb_tconst FROM criterion_basic_info
        WHERE imdb_tconst NOT IN (SELECT imdb_tconst FROM cluster_assignments)
    """).df()
    n_no_actor = len(no_actor_df)

    # One year per film (criterion_basic_info can hold multiple candidate-match
    # rows per imdb_tconst; keep the highest-confidence one), used below to
    # place older films toward each cluster's center and newer ones toward
    # its edge.
    year_by_tconst = con.execute("""
        SELECT imdb_tconst, criterion_year FROM (
            SELECT imdb_tconst, criterion_year,
                   row_number() OVER (
                       PARTITION BY imdb_tconst ORDER BY confidence_score DESC NULLS LAST
                   ) AS rn
            FROM criterion_basic_info
        ) WHERE rn = 1
    """).df().set_index('imdb_tconst')['criterion_year'].to_dict()

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

    # ── 2. Cluster properties ──────────────────────────────────────────────
    cluster_size = ca_df.groupby('cluster_id').size().to_dict()
    # Add the no-actor films to hiddenGems size (viz only)
    cluster_size['hiddenGems'] = cluster_size.get('hiddenGems', 0) + n_no_actor

    stats = stats_df.set_index('cluster_id').to_dict('index')
    internal_ratio = {}
    for cid, s in stats.items():
        ie, ee = s['internal'], s['external']
        internal_ratio[cid] = ie / (ie + ee) if (ie + ee) > 0 else 0.0

    centrality = {c: cluster_size[c] * internal_ratio.get(c, 0) for c in cluster_size}

    PERIPHERY = {'hiddenGems'}
    large_clusters = sorted([c for c in cluster_size if c not in PERIPHERY],
                             key=lambda c: centrality[c], reverse=True)

    n_large = sum(cluster_size[c] for c in large_clusters)
    n_small = cluster_size['hiddenGems']
    N_TOTAL = n_large + n_small

    # ── 3. MDS layout for large clusters ───────────────────────────────────
    n_lc = len(large_clusters)
    lc_idx = {c: i for i, c in enumerate(large_clusters)}

    edge_mat = np.zeros((n_lc, n_lc))
    for _, row in cross_df.iterrows():
        ia = lc_idx.get(row['ca'], -1)
        ib = lc_idx.get(row['cb'], -1)
        if ia >= 0 and ib >= 0:
            edge_mat[ia, ib] += row['n']
            edge_mat[ib, ia] += row['n']

    max_e = edge_mat.max() or 1
    dist_mat = 1.0 - edge_mat / max_e
    np.fill_diagonal(dist_mat, 0)

    mds = MDS(n_components=2, dissimilarity='precomputed',
              random_state=42, normalized_stress='auto')
    mds_xy = mds.fit_transform(dist_mat)
    mds_xy -= mds_xy.mean(axis=0)

    # ── 4. Generate 16:9 rectangular hex grid (pointy-top) ─────────────────
    area_needed = N_TOTAL / 0.385
    PH = np.sqrt(area_needed / (16 / 9)) * 1.05   # slight oversize so we can trim
    PW = PH * (16 / 9)

    def rect_priority(q, r):
        px, py = axial_to_pixel(q, r)
        return max(abs(px) / (PW / 2), abs(py) / (PH / 2))

    all_hexes = []
    Q_MAX = int(PW / S3) + 3
    R_MAX = int(PH / 1.5) + 3
    for q in range(-Q_MAX, Q_MAX + 1):
        for r in range(-R_MAX, R_MAX + 1):
            px, py = axial_to_pixel(q, r)
            if abs(px) <= PW / 2 + S3 / 2 and abs(py) <= PH / 2 + 1.0:
                all_hexes.append((q, r))

    all_hexes.sort(key=lambda h: rect_priority(h[0], h[1]))
    grid_hexes = all_hexes[:N_TOTAL]
    hex_set = set(grid_hexes)

    # Hidden Gems is meant to form a ring exactly 2 hexes thick all the way
    # around the grid: depth0 is every hex touching the outside of the grid
    # (the true outer edge), depth1 is every hex one hex-step further in.
    # These are picked by actual hex adjacency (BFS-style), not the
    # continuous rect_priority distance used elsewhere -- rect_priority is a
    # Chebyshev-ish approximation that doesn't line up with discrete hex
    # rings near corners, which was why the old border-fill (below, now
    # replaced) ended up 3 hexes deep in some corners and only 1 deep along
    # some flat edges.
    depth0 = [h for h in grid_hexes
              if any(n not in hex_set for n in hex_neighbors(h[0], h[1]))]
    depth0_set = set(depth0)
    depth1 = [h for h in grid_hexes
              if h not in depth0_set
              and any(n in depth0_set for n in hex_neighbors(h[0], h[1]))]

    # The real hiddenGems film count essentially never divides evenly against
    # depth0+depth1's combined size, so there's always a little shortfall
    # (too few films to double-ring the whole perimeter) or overflow (too
    # many). Sorting depth1 by y position before slicing concentrates that
    # remainder along one edge (the bottom) instead of scattering it
    # unevenly around the ring.
    depth1.sort(key=lambda h: -axial_to_pixel(h[0], h[1])[1])

    n_depth1_needed = n_small - len(depth0)
    gems_ring = list(depth0) + depth1[:max(0, n_depth1_needed)]

    if len(gems_ring) < n_small:
        # n_small exceeds a full 2-hex ring -- extend inward one more
        # hex-step, same idea as the old fallback: pull whichever remaining
        # hexes sit closest to the border first.
        deeper = [h for h in grid_hexes if h not in depth0_set and h not in set(depth1)]
        deeper.sort(key=lambda h: rect_priority(h[0], h[1]))
        while len(gems_ring) < n_small and deeper:
            gems_ring.append(deeper.pop())

    # ── 5. Assign hexes to clusters ─────────────────────────────────────────
    hex_cluster = {}
    cluster_remaining = {c: cluster_size[c] for c in cluster_size}

    for h in gems_ring[:n_small]:
        hex_cluster[h] = 'hiddenGems'
        cluster_remaining['hiddenGems'] -= 1

    # This exact set of hexes is Hidden Gems' outer frame around the whole
    # grid -- rebalance_counts() below must never hand any of these to a
    # needy named cluster, or that cluster starts showing up ON the border.
    hidden_gems_frame = set(gems_ring[:n_small])
    hidden_gems_outer = depth0_set & hidden_gems_frame

    interior_hexes = [h for h in grid_hexes if h not in hidden_gems_frame]

    int_px_map = {h: np.array(axial_to_pixel(h[0], h[1])) for h in interior_hexes}
    available = set(interior_hexes) - set(hex_cluster)

    int_px = np.array(list(int_px_map.values()))
    px_range = int_px.max(axis=0) - int_px.min(axis=0)
    mds_range = np.abs(mds_xy).max(axis=0)
    mds_range[mds_range == 0] = 1
    mds_scaled = mds_xy * (px_range * 0.40 / mds_range)

    lc_target = {c: mds_scaled[lc_idx[c]] for c in large_clusters}

    # A prior hand-requested layout swap applied to 'bergman_scandinavian'
    # and 'transatlantic_auteur_cinema'. Neither cluster ID exists after the
    # 2026-07-31 rebuild (see data/cluster_naming_report.md) -- their
    # replacements (scandinavian_bergman_circle; transatlantic_auteur_cinema
    # folded into european_art_cinema) use their plain data-driven MDS
    # position instead, since no fresh swap was requested for this layout.

    used_seeds = set()
    seeds = {}
    for c in large_clusters:
        best = min((h for h in available if h not in used_seeds),
                   key=lambda h: np.linalg.norm(int_px_map[h] - lc_target[c]))
        seeds[c] = best
        used_seeds.add(best)

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

    # ── Post-processing: fix disconnected fragments, preserve counts ───────
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
                visited.add(h)
                comp.add(h)
                for nb in hex_neighbors(h[0], h[1]):
                    if nb in ch and nb not in visited:
                        q.append(nb)
            comps.append(comp)
        return comps

    def fix_fragments():
        """Reassign any disconnected minority fragment of a cluster to
        whichever neighboring cluster majority-borders it, so every named
        cluster renders as one contiguous blob. This alone can leave a
        cluster's hex count off from its real film count -- a fragment
        given away doesn't come back -- which rebalance_counts() below
        corrects; the two are run in alternation until both are stable."""
        changed = False
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
            if any_fixed:
                changed = True
            else:
                break
        return changed

    def rebalance_counts():
        """Move hexes one at a time from clusters with more hexes than real
        films (surplus) to clusters with fewer (deficit), until every
        cluster's hex count matches cluster_size exactly. Each move takes a
        surplus hex that's adjacent to the deficit cluster's own region (so
        the deficit cluster stays contiguous while growing) and, among those,
        the one closest to the deficit cluster's centroid -- reading as a
        boundary nibble rather than a random jump. Hidden Gems' own outer
        frame (hidden_gems_frame) is never a donor -- otherwise a needy named
        cluster could nibble straight through the ring that's supposed to
        surround the whole grid and end up sitting on the outer edge itself.
        Any OTHER hiddenGems hex (one it only picked up via fix_fragments
        absorbing a stray named-cluster fragment) can still be given back."""
        changed = False
        final_counts = Counter(hex_cluster.values())
        deficits = {c: cluster_size.get(c, 0) - final_counts.get(c, 0) for c in cluster_size}

        def centroid_of(cid):
            pts = [axial_to_pixel(h[0], h[1]) for h, hc in hex_cluster.items() if hc == cid]
            return np.array(pts).mean(axis=0) if pts else np.zeros(2)

        centroids = {c: centroid_of(c) for c in cluster_size}

        def is_available_donor(h, hc):
            return deficits.get(hc, 0) < 0 and h not in hidden_gems_frame

        for _ in range(len(grid_hexes)):
            needy = [c for c, d in deficits.items() if d > 0]
            if not needy:
                break
            c = max(needy, key=lambda cc: deficits[cc])
            candidates = [h for h, hc in hex_cluster.items()
                          if is_available_donor(h, hc)
                          and any(hex_cluster.get(nb) == c for nb in hex_neighbors(h[0], h[1]))]
            if not candidates:
                candidates = [h for h, hc in hex_cluster.items() if is_available_donor(h, hc)]
                if not candidates:
                    break
            best = min(candidates,
                       key=lambda h: np.linalg.norm(np.array(axial_to_pixel(h[0], h[1])) - centroids[c]))
            donor = hex_cluster[best]
            hex_cluster[best] = c
            deficits[c] -= 1
            deficits[donor] += 1
            changed = True
        return changed

    for _ in range(5):
        f_changed = fix_fragments()
        r_changed = rebalance_counts()
        if not f_changed and not r_changed:
            break
    # The alternation above can still end mid-cycle on a rebalance_counts()
    # pass that pulled a stray hex or two away from its cluster's main body
    # again (to fix a count deficit) without re-fragmenting anything else
    # enough to trigger another fix_fragments() pass. One last fragment-only
    # pass (no matching rebalance after it) cleans that up; the count drift
    # it can introduce is at most a hex or two, which contiguity is worth.
    fix_fragments()

    # ── Assign each hex to one specific film ────────────────────────────────
    # Pure presentation metadata (doesn't affect layout/geometry above): lets
    # hex_svg.py style a hex by that exact film's own attributes (e.g. its
    # color/black-and-white status), not just its cluster's. Within each
    # cluster, films are ordered oldest-first and hexes are ordered by
    # distance from that cluster's own centroid (closest first); pairing the
    # two puts older films toward the center of their cluster's region and
    # newer films toward its outer edge. rebalance_counts() above guarantees
    # every cluster's final hex count matches its real film count exactly, so
    # this can just be a straight per-cluster zip -- no cross-cluster
    # leftover pool needed.
    def year_sort_key(tconst):
        try:
            return (0, int(year_by_tconst.get(tconst)))
        except (TypeError, ValueError):
            return (1, 0)   # unknown year -- treat as newest, sort last

    cluster_films = defaultdict(list)
    for _, row in ca_df.iterrows():
        cluster_films[row['cluster_id']].append(row['imdb_tconst'])
    cluster_films['hiddenGems'].extend(no_actor_df['imdb_tconst'].tolist())
    for films in cluster_films.values():
        films.sort(key=year_sort_key)

    cluster_hexes = defaultdict(list)
    for h, c in hex_cluster.items():
        cluster_hexes[c].append(h)
    for c, hexes_c in cluster_hexes.items():
        pts = np.array([axial_to_pixel(h[0], h[1]) for h in hexes_c])
        centroid = pts.mean(axis=0)
        dists = np.linalg.norm(pts - centroid, axis=1)
        cluster_hexes[c] = [hexes_c[i] for i in np.argsort(dists, kind='stable')]

    hex_film = {}
    for c, films_c in cluster_films.items():
        hex_film.update(zip(cluster_hexes.get(c, []), films_c))

    return HexGrid(
        grid_hexes=grid_hexes,
        hex_cluster=hex_cluster,
        hex_set=hex_set,
        large_clusters=large_clusters,
        cluster_size=cluster_size,
        color_map=COLOR_MAP,
        hex_film=hex_film,
        hidden_gems_outer=hidden_gems_outer,
    )
