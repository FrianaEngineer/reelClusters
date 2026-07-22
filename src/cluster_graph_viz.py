"""
Force-directed shared-actor network for Criterion clusters.
Pure SVG + CSS (no JavaScript) so it stays interactive as a standalone file:
hover a node to see its title and year, click a node (where we have a
confirmed real criterion.com URL for it) to open that film's page.
"""

import csv
import duckdb
import networkx as nx
import numpy as np
from pathlib import Path
from xml.sax.saxutils import escape

from cluster_colors import COLOR_MAP, contrast_text_color

DB_PATH = Path(__file__).parent.parent / "db" / "criterion_graph.duckdb"
OUT_DIR = Path(__file__).parent.parent / "output"
CRITERION_LINKS_CSV = Path(__file__).parent.parent / "data" / "criterion_film_links.csv"
CHANNEL_LINKS_CSV   = Path(__file__).parent.parent / "data" / "criterion_channel_links.csv"


def load_criterion_links():
    """title -> film URL, for the subset of films we could match to a real,
    confirmed page -- criterion.com's own catalog first (build_criterion_links.py),
    falling back to the Criterion Channel (verify_channel_links.py) for
    titles not on criterion.com. Both sources are confirmed matches (an exact
    slug hit for criterion.com, a live page with a matching year for the
    Channel); titles with neither are simply absent here -- their nodes
    render without a link rather than guessing."""
    links = {}
    if CHANNEL_LINKS_CSV.exists():
        with open(CHANNEL_LINKS_CSV, newline="") as f:
            links.update({row["title"]: row["channel_url"] for row in csv.DictReader(f)})
    if CRITERION_LINKS_CSV.exists():
        with open(CRITERION_LINKS_CSV, newline="") as f:
            links.update({row["title"]: row["criterion_url"] for row in csv.DictReader(f)})
    return links


CRITERION_LINKS = load_criterion_links()

BG_COLOR = "#dedddc"
# The tooltip is a floating overlay, not part of the page, so it keeps its own
# fixed dark/white styling regardless of the page background above.
TOOLTIP_BG   = "#12121f"
TOOLTIP_TEXT = "#ffffff"
W, H     = 1600, 900   # 16:9 canvas
MARGIN   = 90

# Reference point the density-scaling below is tuned against (the original
# youssef_chahine_egyptian render: 17 nodes, 41 edges, radius 16, opacity 0.45).
REF_NODES, REF_EDGES = 17, 41
REF_NODE_R, REF_EDGE_OPACITY, REF_EDGE_WIDTH = 16, 0.45, 1.5

# The two big clusters already read well from the plain spring layout; leave
# their positions untouched and only reorient the smaller/sparser ones.
SKIP_DENSITY_REORIENT = {"japanese_cinema", "european_art_cinema"}

CLUSTERS_TO_RENDER = [
    "youssef_chahine_egyptian",
    "european_art_cinema",
    "transatlantic_auteur_cinema",
    "hong_kong_taiwan_cinema",
    "bergman_scandinavian",
    "czech_new_wave",
    "satyajit_ray_indian",
    "japanese_cinema",
    "soviet_cinema",
    "anglophone_classic",
]


def load_cluster(con, cluster_id):
    # criterion_basic_info can hold multiple candidate-match rows per imdb_tconst;
    # keep only the highest-confidence one so films aren't double-counted.
    films = con.execute("""
        SELECT imdb_tconst, title, criterion_year FROM (
            SELECT c.imdb_tconst, b.title, b.criterion_year,
                   row_number() OVER (
                       PARTITION BY c.imdb_tconst ORDER BY b.confidence_score DESC NULLS LAST
                   ) AS rn
            FROM cluster_assignments c
            JOIN criterion_basic_info b ON b.imdb_tconst = c.imdb_tconst
            WHERE c.cluster_id = ?
        ) WHERE rn = 1
    """, [cluster_id]).df()

    edges = con.execute("""
        SELECT me.movie_a, me.movie_b
        FROM movie_edges me
        JOIN cluster_assignments ca ON ca.imdb_tconst = me.movie_a
        JOIN cluster_assignments cb ON cb.imdb_tconst = me.movie_b
        WHERE ca.cluster_id = ? AND cb.cluster_id = ?
    """, [cluster_id, cluster_id]).df()
    return films, edges


def layout_to_canvas(pos):
    # Force-directed coordinates have no real-world distances to preserve, so
    # stretch x and y independently to fill the full 16:9 canvas rather than
    # keeping the layout's (often portrait-ish) native aspect ratio.
    xs, ys  = [p[0] for p in pos.values()], [p[1] for p in pos.values()]
    x_range = max(xs) - min(xs) or 1
    y_range = max(ys) - min(ys) or 1
    avail_w, avail_h = W - 2 * MARGIN, H - 2 * MARGIN
    x_scale = avail_w / x_range
    y_scale = avail_h / y_range

    def to_canvas(p):
        x = (p[0] - min(xs)) * x_scale + MARGIN
        y = (p[1] - min(ys)) * y_scale + MARGIN
        return x, H - y   # flip: SVG y grows downward, layout y grows upward

    return {n: to_canvas(p) for n, p in pos.items()}


def esc(s):
    return escape(str(s))


def pull_dense_core_to_center(G, pos):
    """Reflow a spring layout into concentric rings by k-core number: nodes
    embedded in the densest part of the shared-actor network form a ring
    close to the center, while progressively more peripheral (lower-core)
    nodes form wider rings further out. Within each ring, nodes are spaced
    at even angles all the way around the center -- so the periphery doesn't
    clump to whichever side the original spring layout happened to leave it
    on -- but ordered by their original angle first, so nodes that were near
    each other before (e.g. sharing more neighbors) tend to land near each
    other on the ring rather than at arbitrary points around it. The edges
    drawn from `pos` afterward still connect the same node pairs, just from
    these reoriented positions.

    The center is a density-weighted centroid (weight = k-core depth
    squared), not the centroid of all nodes and not just the single deepest
    core. spring_layout already centers its whole output at roughly (0, 0),
    which for small/lopsided graphs can leave the actual dense cluster
    sitting well off to one side of that origin -- and anchoring on only the
    single deepest core is fragile too, since that's sometimes a tiny
    tight-knit clique off to one side rather than the graph's real visual
    mass. Weighting every node's pull on the center by its core depth finds
    the center of gravity of "the generally dense part" instead.
    """
    core = nx.core_number(G)
    min_core, max_core = min(core.values()), max(core.values())
    span = (max_core - min_core) or 1

    weights = {n: (c - min_core + 1) ** 2 for n, c in core.items()}
    wsum = sum(weights.values())
    cx = sum(weights[n] * pos[n][0] for n in G.nodes()) / wsum
    cy = sum(weights[n] * pos[n][1] for n in G.nodes()) / wsum
    max_radius = max(np.hypot(x - cx, y - cy) for x, y in pos.values()) or 1.0

    rings = {}
    for n in G.nodes():
        rings.setdefault(core[n], []).append(n)

    new_pos = {}
    for c, nodes in rings.items():
        density = (c - min_core) / span                # 0 = peripheral, 1 = densest core
        ring_radius = max_radius * (1.0 - 0.8 * density)
        # Order by each node's original angle around the center so nodes
        # that were already near each other stay near each other on the ring.
        ordered = sorted(nodes, key=lambda n: np.arctan2(pos[n][1] - cy, pos[n][0] - cx))
        # Stagger each ring's starting angle so spokes of different rings
        # don't all line up along the same radii.
        offset = c * 2 * np.pi / (max_core + 1)
        for i, n in enumerate(ordered):
            angle = offset + 2 * np.pi * i / len(ordered)
            new_pos[n] = (cx + ring_radius * np.cos(angle), cy + ring_radius * np.sin(angle))
    return new_pos


def hexagon_points(cx, cy, r):
    """Pointy-top hexagon vertices (matches hex_viz.py's orientation) as an
    SVG polygon points string."""
    angles = np.radians(30 + np.arange(6) * 60)
    pts = zip(cx + r * np.cos(angles), cy + r * np.sin(angles))
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)


def build_svg(cluster_id, films, edges):
    G = nx.Graph()
    G.add_nodes_from(films["imdb_tconst"])
    G.add_edges_from(edges[["movie_a", "movie_b"]].itertuples(index=False, name=None))

    n_nodes, n_edges = G.number_of_nodes(), max(G.number_of_edges(), 1)
    pos = nx.spring_layout(G, weight=None, seed=42)
    if cluster_id not in SKIP_DENSITY_REORIENT:
        pos = pull_dense_core_to_center(G, pos)
    coords = layout_to_canvas(pos)
    info   = {row.imdb_tconst: (row.title, int(row.criterion_year)) for row in films.itertuples()}
    node_color = COLOR_MAP.get(cluster_id, "#888888")
    bg_color   = BG_COLOR
    text_color = contrast_text_color(bg_color)
    edge_color = "#000000"

    # Denser clusters get smaller nodes and fainter/thinner edges so the graph
    # doesn't collapse into a solid mass; scaled to match the original
    # Youssef Chahine render (17 nodes / 41 edges) at REF_* above. The opacity
    # floor is lower than width/node_r's floor because avg-degree outliers like
    # japanese_cinema (~44) still washed out into a solid grey mass at 0.05 --
    # every other cluster rendered so far sits well above this floor already,
    # so lowering it doesn't change their appearance.
    node_r       = float(np.clip(REF_NODE_R * np.sqrt(REF_NODES / n_nodes), 3, REF_NODE_R))
    edge_opacity = float(np.clip(REF_EDGE_OPACITY * np.sqrt(REF_EDGES / n_edges), 0.02, REF_EDGE_OPACITY))
    edge_width   = float(np.clip(REF_EDGE_WIDTH * np.sqrt(REF_EDGES / n_edges), 0.35, REF_EDGE_WIDTH))

    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
           f'font-family="Helvetica, Arial, sans-serif">']
    svg.append(f"""
<style>
  .edge {{ stroke: {edge_color}; stroke-opacity: {edge_opacity}; stroke-width: {edge_width}; }}
  .node polygon {{ fill: {node_color}; stroke: {bg_color}; stroke-width: 2; }}
  .node {{ cursor: pointer; }}
  .node:hover polygon {{ stroke: {text_color}; }}
  .tooltip {{ opacity: 0; pointer-events: none; transition: opacity 0.12s ease; }}
  .node:hover .tooltip {{ opacity: 1; }}
  .tooltip rect {{ fill: {TOOLTIP_BG}; stroke: #ffffff; stroke-opacity: 0.25; }}
  .tooltip text {{ fill: {TOOLTIP_TEXT}; font-size: 15px; font-weight: 600; }}
</style>
""")
    svg.append(f'<rect x="0" y="0" width="{W}" height="{H}" fill="{bg_color}"/>')

    svg.append('<g>')
    for a, b in G.edges():
        (x1, y1), (x2, y2) = coords[a], coords[b]
        svg.append(f'<line class="edge" x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}"/>')
    svg.append('</g>')

    for n in G.nodes():
        cx, cy = coords[n]
        title, year = info[n]
        label = f"{title} ({year})"
        tw = max(70, 8.2 * len(label))
        th = 34
        tx = min(max(cx - tw / 2, 8), W - tw - 8)
        ty = cy - node_r - th - 10
        if ty < 10:
            ty = cy + node_r + 10

        node_svg = f'''<g class="node">
  <polygon points="{hexagon_points(cx, cy, node_r)}"/>
  <g class="tooltip">
    <rect x="{tx:.1f}" y="{ty:.1f}" width="{tw:.1f}" height="{th:.1f}" rx="6"/>
    <text x="{tx + tw / 2:.1f}" y="{ty + th / 2 + 5:.1f}" text-anchor="middle">{esc(label)}</text>
  </g>
</g>'''
        link = CRITERION_LINKS.get(title)
        if link:
            node_svg = f'<a href="{esc(link)}" target="_blank" rel="noopener">{node_svg}</a>'
        svg.append(node_svg)

    svg.append('</svg>')
    return '\n'.join(svg)


if __name__ == "__main__":
    con = duckdb.connect(str(DB_PATH))
    for cluster_id in CLUSTERS_TO_RENDER:
        films, edges = load_cluster(con, cluster_id)
        svg_text = build_svg(cluster_id, films, edges)
        out_path = OUT_DIR / f"{cluster_id}_graph.svg"
        out_path.write_text(svg_text)
        print(f"{cluster_id}: {len(films)} films, {len(edges)} edges -> {out_path}")
    con.close()
