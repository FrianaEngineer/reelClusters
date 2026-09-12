"""
Builds the mini shared-actor graph grid on site/clusters/hiddenGems.html: one
card per raw Louvain community that fell under MIN_NAMED_CLUSTER_SIZE and got
folded into hiddenGems by src/cluster.py.

Replaces the "Community 23", "Community 15" numeric headings that
src/build_small_cluster_analysis.py emits with a hand-authored descriptive
title per pocket, and draws each pocket's actual shared-actor subgraph so the
shape of the connection is visible rather than only described in prose.

Titles are keyed by anchor films rather than by Louvain's numeric community
id: that numbering is not stable across reruns (see src/cluster.py), but a
pocket that survives a rerun keeps its films. A community whose anchors no
longer both appear falls back to the same director/country label
build_small_cluster_analysis.py derives, and prints a warning.
"""

from collections import Counter

import networkx as nx
import numpy as np
import pandas as pd

from cluster import build_graph, run_louvain, MIN_NAMED_CLUSTER_SIZE

# (title, two anchor film titles). A community is given the title when BOTH
# anchors are among its films. Authored against the 2026-07-31
# post-Best-Picture-import run; see output/small_cluster_analysis.md.
POCKET_TITLES = [
    ("The Romanian New Wave",          "The Death of Mr. Lazarescu", "Police, Adjective"),
    ("Jia Zhangke's China",            "Xiao Wu", "Platform"),
    ("Sembène's Senegal",              "Black Girl", "Xala"),
    ("The L.A. Rebellion",             "Killer of Sheep", "Daughters of the Dust"),
    ("The Iranian New Wave",           "Where Is the Friend’s House?", "Chess of the Wind"),
    ("Sorrentino's Italy",             "The Great Beauty", "Gomorrah"),
    ("The Kazakh New Wave",            "Revenge", "The Fall of Otrar"),
    ("Pedro Costa's Fontainhas",       "Ossos", "In Vanda’s Room"),
    ("Mészáros's Diary Trilogy",       "Diary for My Children", "Diary for My Lovers"),
    ("Lino Brocka's Manila",           "Insiang", "Bona"),
    ("The Yugoslav Black Wave",        "WR: Mysteries of the Organism", "Man Is Not a Bird"),
    ("Alexander Payne's Sad Comedies", "Sideways", "The Holdovers"),
    ("Lina Rodriguez's Migrations",    "Señoritas", "So Much Tenderness"),
    ("Babenco's Brazilian Streets",    "Pixote", "King of the Night"),
    ("Bahrani's New York Hustle",      "Man Push Cart", "Chop Shop"),
    ("Detour to Winnipeg",             "Detour", "My Winnipeg"),
    ("Haugerud's Oslo Diptych",        "Dreams", "Love"),
    ("Eisenstein's Historical Epics",  "Alexander Nevsky", "Ivan the Terrible, Part I"),
    ("New Mexican Realism",            "Dos Estaciones", "Tótem"),
    ("Norman's Race Films",            "The Flying Ace", "Regeneration"),
    ("Dunham's Early Mumblecore",      "Creative Nonfiction", "Tiny Furniture"),
    ("Black British Cinema",           "Pressure", "The Passion of Remembrance"),
    ("Bresson's Late Films",           "The Trial of Joan of Arc", "The Devil, Probably"),
    ("Mexican Political Thrillers",    "Highway Patrolman", "Canoa: A Shameful Memory"),
    ("Mexican Gothic, 1934",           "Dos monjes", "The Phantom of the Monastery"),
    ("Black Women's Independent Cinema", "Alma’s Rainbow", "Naked Acts"),
    ("Korean Contemporary Masters",    "Poetry", "Parasite"),
    ("Sean Baker's Early Work",        "Four Letter Words", "Prince of Broadway"),
    ("1970s American Underground",     "Eraserhead", "Bushman"),
    ("Outside the Studio System",      "Night of the Living Dead", "Losing Ground"),
    ("Turkish Social Realism",         "Dry Summer", "Law of the Border"),
    ("European Migrant Dramas",        "Tori and Lokita", "Dheepan"),
    ("The Feminist Avant-Garde",       "Born in Flames", "Seduction: The Cruel Woman"),
    ("Eisenstein's Revolutionary Silents", "Strike", "Battleship Potemkin"),
    ("Early Cronenberg",               "Stereo", "Crimes of the Future"),
    ("Kleber Mendonça Filho's Brazil", "Bacurau", "The Secret Agent"),
]

# Card drawing geometry, in the mini-graph's own viewBox units.
VIEW_W, VIEW_H = 200.0, 132.0
PAD = 18.0


def load_basic(con):
    """One row per film, preferring the Criterion-sourced row over the Best
    Picture import row for the 14 films that carry both."""
    return con.execute("""
        SELECT imdb_tconst, title, criterion_director, criterion_year, criterion_country
        FROM (
            SELECT *, row_number() OVER (
                PARTITION BY imdb_tconst
                ORDER BY (source = 'best_picture_nominee') ASC, confidence_score DESC NULLS LAST
            ) AS rn
            FROM criterion_basic_info
        ) WHERE rn = 1
    """).df().set_index("imdb_tconst")


def auto_label(members, basic):
    """The director/country fallback label, same rule as
    build_small_cluster_analysis.py's."""
    size = len(members)
    directors, countries = Counter(), Counter()
    for t in members:
        if t in basic.index:
            d, c = basic.loc[t, "criterion_director"], basic.loc[t, "criterion_country"]
            if pd.notna(d):
                directors[d] += 1
            if pd.notna(c):
                countries[c] += 1
    bits = []
    top_director = directors.most_common(1)
    if top_director and top_director[0][1] >= max(2, size // 2):
        bits.append(top_director[0][0])
    if countries:
        top_country, top_count = countries.most_common(1)[0]
        if len(countries) == 1 and top_count >= max(2, size // 2):
            bits.append(top_country + " cinema")
    return " / ".join(bits) if bits else "Mixed"


def meta_line(members, basic):
    """'9 films · Cristi Puiu · Romania' -- the top director and country by
    film count, each shown only when it covers at least half the pocket."""
    size = len(members)
    directors, countries = Counter(), Counter()
    for t in members:
        if t in basic.index:
            d, c = basic.loc[t, "criterion_director"], basic.loc[t, "criterion_country"]
            if pd.notna(d):
                directors[d] += 1
            if pd.notna(c):
                countries[c] += 1
    bits = [f"{size} films"]
    for counter in (directors, countries):
        if counter:
            name, n = counter.most_common(1)[0]
            if n >= max(2, size / 2):
                bits.append(name)
    return " · ".join(bits)


def layout(sub):
    """Spring layout scaled into the card viewBox. Both axes are scaled by the
    same factor so the graph keeps its own proportions instead of being
    stretched to the card's aspect ratio."""
    # 23 of the 36 pockets are isolated 2-film pairs, and spring_layout puts
    # every one of them on the same steep diagonal. Draw those flat and
    # centered instead -- same information, and it reads as a deliberate
    # "these two, nothing else" rather than 23 identical slanted lines.
    if sub.number_of_nodes() == 2:
        a, b = sorted(sub.nodes())
        return {a: (VIEW_W / 2 - 42, VIEW_H / 2), b: (VIEW_W / 2 + 42, VIEW_H / 2)}

    pos = nx.spring_layout(sub, seed=42, weight="shared_actors")

    # Rotate onto principal axes so the layout's longest dimension runs across
    # the card's long side. Without this, an elongated pocket (the 9-film
    # Romanian one, the 6-film Senegalese one) that spring_layout happens to
    # draw vertically gets squeezed into a narrow column with the card's width
    # unused, since both axes share one scale factor below.
    nodes = list(pos)
    pts = np.array([pos[n] for n in nodes], dtype=float)
    pts -= pts.mean(axis=0)
    if len(nodes) > 2:
        _u, _s, vt = np.linalg.svd(pts, full_matrices=False)
        pts = pts @ vt.T
    pos = {n: (float(x), float(y)) for n, (x, y) in zip(nodes, pts)}

    xs = [p[0] for p in pos.values()]
    ys = [p[1] for p in pos.values()]
    span_x, span_y = max(xs) - min(xs), max(ys) - min(ys)
    avail_w, avail_h = VIEW_W - 2 * PAD, VIEW_H - 2 * PAD
    scale = min(avail_w / span_x if span_x > 1e-9 else avail_w,
                avail_h / span_y if span_y > 1e-9 else avail_h)
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    return {n: ((x - cx) * scale + VIEW_W / 2, (y - cy) * scale + VIEW_H / 2)
            for n, (x, y) in pos.items()}


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def card_html(title, members, sub, basic):
    pos = layout(sub)
    parts = [f'<svg class="gem-graph" viewBox="0 0 {VIEW_W:g} {VIEW_H:g}" '
             f'role="img" aria-label="{esc(title)} shared-actor graph">']
    for u, v, data in sub.edges(data=True):
        x1, y1 = pos[u]
        x2, y2 = pos[v]
        width = 0.7 + 0.35 * min(data.get("shared_actors", 1), 8)
        parts.append(f'<line class="gem-edge" x1="{x1:.1f}" y1="{y1:.1f}" '
                     f'x2="{x2:.1f}" y2="{y2:.1f}" stroke-width="{width:.2f}"/>')
    for n in sorted(sub.nodes(), key=lambda t: sub.degree(t)):
        x, y = pos[n]
        r = 3.4 + 1.15 * (sub.degree(n) ** 0.5)
        film = basic.loc[n, "title"] if n in basic.index else n
        year = (int(basic.loc[n, "criterion_year"])
                if n in basic.index and pd.notna(basic.loc[n, "criterion_year"]) else None)
        label = f"{film} ({year})" if year else str(film)
        # No <title> child: the page's own styled tooltip reads data-film, and
        # a <title> would stack the browser's native tooltip on top of it.
        parts.append(f'<circle class="gem-node" cx="{x:.1f}" cy="{y:.1f}" '
                     f'r="{r:.2f}" data-film="{esc(label)}" role="img" '
                     f'aria-label="{esc(label)}" tabindex="0"></circle>')
    parts.append("</svg>")
    return (f'<article class="gem-card">\n'
            f'  <h3 class="gem-card-title">{esc(title)}</h3>\n'
            f'  <p class="gem-card-meta">{esc(meta_line(members, basic))}</p>\n'
            f'  ' + "".join(parts) + "\n</article>")


def build_grid(con):
    """Returns (grid_html, stats), where stats feeds the narrative paragraph
    above the grid on the Hidden Gems page. Every number in that prose is
    computed here rather than written by hand, so it can't drift away from the
    partition the cards are drawn from."""
    G = build_graph(con)
    partition = run_louvain(G)
    basic = load_basic(con)

    by_anchor = {}
    for title, a, b in POCKET_TITLES:
        by_anchor[frozenset((a, b))] = title

    sizes = Counter(partition.values())
    small_ids = [cid for cid, s in sizes.items() if s < MIN_NAMED_CLUSTER_SIZE]

    pockets = []
    for cid in small_ids:
        members = [t for t, c in partition.items() if c == cid]
        titles = {basic.loc[t, "title"] for t in members if t in basic.index}
        name = next((n for anchors, n in by_anchor.items() if anchors <= titles), None)
        if name is None:
            name = auto_label(members, basic)
            print(f"  ! community {cid} matched no authored title, using {name!r}")
        pockets.append((name, members, G.subgraph(members)))

    pockets.sort(key=lambda p: (-len(p[1]), p[0]))

    # Self-contained: not one credited actor shared with any film outside the
    # pocket, which is exactly why Louvain never merged it into a bigger
    # community in the first place.
    self_contained = 0
    for _name, members, sub in pockets:
        member_set = set(members)
        external = sum(1 for t in members for nbr in G[t] if nbr not in member_set)
        if external == 0:
            self_contained += 1

    multi = [p for p in pockets if len(p[1]) >= 3]
    director_led = country_led = 0
    for _name, members, _sub in multi:
        directors, countries = Counter(), Counter()
        for t in members:
            if t in basic.index:
                d, c = basic.loc[t, "criterion_director"], basic.loc[t, "criterion_country"]
                if pd.notna(d):
                    directors[d] += 1
                if pd.notna(c):
                    countries[c] += 1
        if directors and directors.most_common(1)[0][1] >= max(2, len(members) // 2):
            director_led += 1
        if len(countries) == 1:
            country_led += 1

    stats = {
        "n_pockets": len(pockets),
        "n_films": sum(len(p[1]) for p in pockets),
        "n_self_contained": self_contained,
        "n_multi": len(multi),
        "n_director_led": director_led,
        "n_country_led": country_led,
        "n_pairs": sum(1 for p in pockets if len(p[1]) == 2),
        "largest_name": pockets[0][0],
        "largest_size": len(pockets[0][1]),
    }

    cards = "\n".join(card_html(n, m, s, basic) for n, m, s in pockets)
    return f'<div class="gem-grid">\n{cards}\n</div>', stats
