"""
Builds the static project website: an interactive hex-grid home page and one
page per cluster embedding its existing network visualization plus a
data-grounded description. Run after any of the viz scripts so the site
picks up the latest SVGs/assignment.

    python3 build_site.py
"""

import json
import shutil
from pathlib import Path
from xml.sax.saxutils import escape

import duckdb
import markdown as md_lib

import hex_svg
from hex_grid import DB_PATH, display_name
from cluster_colors import COLOR_MAP

SITE_DIR     = Path(__file__).parent.parent / "site"
OUTPUT_DIR   = Path(__file__).parent.parent / "output"
CLUSTERS_DIR = SITE_DIR / "clusters"
ASSETS_DIR   = SITE_DIR / "assets"
ANALYSIS_MD  = OUTPUT_DIR / "small_cluster_analysis.md"

# Clusters that use cluster_ring_viz.py's degree-banded ellipse view instead
# of the shared-actor network graph -- the seven largest/densest named
# clusters after the 2026-07-31 rebuild, whose force-directed graphs would be
# too dense to read as edges. The remaining four (small enough that a plain
# shared-actor graph stays legible) use cluster_graph_viz.py instead. See
# data/cluster_naming_report.md.
RING_CLUSTERS = {"european_art_cinema", "classic_japanese_cinema",
                  "golden_age_hollywood_british", "modern_american_cinema",
                  "japanese_new_wave_genre", "hong_kong_taiwan_cinema",
                  "scandinavian_bergman_circle"}

NAMED_CLUSTERS = [
    "modern_american_cinema", "european_art_cinema",
    "golden_age_hollywood_british",
    "classic_japanese_cinema", "japanese_new_wave_genre",
    "hong_kong_taiwan_cinema", "scandinavian_bergman_circle",
    "czech_new_wave", "silent_era_comedy", "soviet_cinema",
    "satyajit_ray_indian",
]

# Hand-authored, data-grounded blurbs. Numbers/tables on the page itself are
# computed live from the DB below so they can't drift out of sync with this
# prose -- these just supply the qualitative read a query can't.
# Rewritten for the 2026-07-31 Best Picture nominee import (619 IMDb films
# merged in, 591 genuinely new; see data/cluster_naming_report.md for the
# full per-cluster evidence this prose is grounded in). Two of the ten
# pre-rebuild clusters (youssef_chahine_egyptian, transatlantic_auteur_cinema)
# no longer exist as distinct Louvain communities -- both folded into
# european_art_cinema this run. Country-of-origin stats are only quoted for
# the subset of a cluster's films that actually carry a criterion_country
# value: most of the newly-added Best Picture films don't have that field
# yet, so modern_american_cinema and golden_age_hollywood_british -- which
# absorbed most of the new films -- call this out explicitly rather than
# implying full coverage.
BLURBS = {
    "modern_american_cinema": (
        "The Collection's largest cluster after this rebuild, and its most "
        "heterogeneous: mainstream awards-season filmmaking (Spielberg, Scorsese, "
        "Eastwood) alongside the American independent and art-house tradition "
        "(Cassavetes, Jarmusch, Lynch) that used to sit in a smaller cluster of its "
        "own. Once the 2026 Best Picture nominee import added hundreds of largely "
        "American films to the shared-actor network, it pulled both halves of "
        "American cinema into one connected community.",

        "498 films spanning 1954 to 2025 (median 1997). Steven Spielberg (14 films) "
        "and Martin Scorsese (11) are its most prolific directors, followed by Jim "
        "Jarmusch, Francis Ford Coppola, Mike Leigh, David Lynch, Clint Eastwood, and "
        "John Cassavetes at 5 each -- no single filmmaker dominates the way they do "
        "in several of the Collection's smaller clusters. Mostly a color-era cluster "
        "(426 color films to 39 black-and-white, 33 unresolved). Only 203 of its 498 "
        "films carry a recorded country of origin -- most of the 2026 import doesn't "
        "have that field yet -- but of those, the large majority are American, with "
        "a British minority.",

        "So densely interconnected, at this size, that a shared-actor edge graph "
        "would read as a solid mass -- shown here grouped by connection count "
        "instead. Hub films (28, with 21 or more connections) are the connective "
        "tissue tying the cluster together; Mid-level films (234, with 7–20 "
        "connections) carry a solid share of those connections; Peripheral films "
        "(236, with fewer than 7 connections), nearly half the cluster, are tied "
        "in more loosely, often through a single shared actor.",
    ),
    "european_art_cinema": (
        "The Collection's broadest continental-European arthouse cluster -- French "
        "New Wave and its descendants (Truffaut, Rivette, Godard, Malle), Italian "
        "and Spanish art cinema, Eastern European auteurs, and Youssef Chahine's "
        "Egyptian filmography, which formed its own small cluster before this "
        "rebuild but now reads as part of the same connected community -- bound "
        "together less by any single movement than by decades of overlapping casts "
        "across the postwar European arthouse circuit.",

        "477 films spanning 1916 to 2024 (median 1970). Rainer Werner Fassbinder (19 "
        "films) and Youssef Chahine (18) are its most prolific directors, followed "
        "by Carlos Saura, François Truffaut, and Bertrand Tavernier. Of the 462 "
        "films with a recorded country, France accounts for the largest single "
        "share (260), with Italy, Germany, Spain, and Egypt following. "
        "Black-and-white and color are close to evenly split (239 color to 213 "
        "black-and-white, 25 unresolved) -- black-and-white films cluster in the "
        "mid-century core, while color productions spread from the 1960s onward.",

        "So densely interconnected that a shared-actor edge graph reads as a solid "
        "mass -- shown here grouped by connection count instead. Hub films (23, "
        "with 25 or more connections) are the true connective tissue, like Mr. "
        "Klein and The Phantom of Liberty; Mid-level films (211, with 10–24 "
        "connections) carry a solid share of those connections; Peripheral films "
        "(243, with fewer than 10 connections), the largest group, are tied in "
        "more loosely, often through a single shared actor or one-off "
        "international production.",
    ),
    "golden_age_hollywood_british": (
        "Classic British and American studio-era cinema -- Hitchcock, David Lean, "
        "William Wyler, John Ford, and George Stevens -- absorbed most of the 2026 "
        "Best Picture import's classic-era winners, from Wuthering Heights and "
        "Rebecca to Mr. Smith Goes to Washington and Lawrence of Arabia, reinforcing "
        "rather than diluting its identity as the studio-era English-language star "
        "system. (Chaplin's own silent-era work split out into a separate cluster "
        "this rebuild -- see Silent-Era Comedy below.)",

        "467 films spanning 1913 to 2015 (median 1946). William Wyler and David Lean "
        "(13 films each) lead, followed by Alfred Hitchcock and John Ford (10 each), "
        "George Stevens, Henry King, and Frank Capra. Of the 208 films with a "
        "recorded country of origin -- most new Best Picture titles don't carry "
        "that field yet -- British productions edge out American (115 to 79). "
        "Predominantly black-and-white (324 films to 136 in color, 7 unresolved), "
        "reflecting the era it's centered on.",

        "Grown from 250 to 467 films this rebuild, with its own fresh connection-"
        "count thresholds. Hub films (30, with 32 or more connections) are the "
        "studio-era regulars who tie the whole cluster together; Mid-level films "
        "(203, with 15–31 connections) share a solid number of those connections; "
        "Peripheral films (234, with fewer than 15 connections) are the loosest "
        "members, still part of the same star system but linked in by only a "
        "handful of shared cast.",
    ),
    "classic_japanese_cinema": (
        "Classical Japanese studio cinema -- Ozu and Naruse's shomin-geki family "
        "dramas, Kinoshita's melodramas, Kurosawa and Kobayashi's period and social "
        "films -- built on the stock-company acting culture that carries the same "
        "faces across hundreds of films from different directors and studios. This "
        "rebuild split what was previously one large Japanese Cinema cluster into "
        "this classical/studio-drama half and a separate genre/New-Wave-leaning half "
        "(see Japanese New Wave & Genre Cinema below).",

        "216 films spanning 1929 to 1998 (median 1956), almost entirely Japanese "
        "productions (210 of 216). Keisuke Kinoshita (35 films) and Yasujiro Ozu "
        "(32) lead, followed by Akira Kurosawa (22), Ishiro Honda (16), Mikio Naruse "
        "(15), and Masaki Kobayashi (12). Predominantly black-and-white (137 films "
        "to 53 in color, 26 unresolved), reflecting the classical studio era -- "
        "roughly the 1930s through the early 1960s -- this cluster is centered on.",

        "A smaller, much denser core than the old Japanese Cinema cluster it "
        "descends from: the median film here has 44.5 connections. Hub films (10, "
        "with 84 or more connections) -- led by The Bad Sleep Well at 122 "
        "connections -- are the studio system's most connected stars and "
        "directors; Mid-level films (98, with 45–83 connections) still carry "
        "heavy connections; Peripheral films (108, with fewer than 45 "
        "connections) are comparatively loose ties, still substantial by any "
        "other cluster's standard.",
    ),
    "japanese_new_wave_genre": (
        "The other half of the pre-rebuild Japanese Cinema cluster: samurai and "
        "genre action (Kenji Misumi's Zatoichi series, chanbara swordplay) alongside "
        "the Japanese New Wave (Oshima, Shinoda, Imamura, Suzuki) -- two sensibilities "
        "that share enough cast to form one graph community, but separated cleanly "
        "from the classical studio-drama cluster above once the larger, denser "
        "post-import network gave Louvain enough signal to resolve the distinction.",

        "142 films spanning 1937 to 2008 (median 1968), almost entirely Japanese "
        "(140 of 142). Kenji Misumi and Nagisa Oshima (13 films each) lead, followed "
        "by Masahiro Shinoda (12), Juzo Itami (9), and Shohei Imamura and Seijun "
        "Suzuki (8 each). Color is closer to a majority here than in Classic "
        "Japanese Cinema (60 color to 41 black-and-white, 41 unresolved), reflecting "
        "its later center of gravity.",

        "Hub films (7, with 41 or more connections) -- led by Zatoichi's "
        "Conspiracy and Harakiri -- are the small, tightly-connected core; "
        "Mid-level films (65, with 22–40 connections) still carry real weight; "
        "Peripheral films (70, with fewer than 22 connections) make up about half "
        "the cluster.",
    ),
    "hong_kong_taiwan_cinema": (
        "Hong Kong action and New Taiwanese Cinema sharing one cluster -- John Woo "
        "and Jackie Chan's genre filmmaking alongside Wong Kar-wai, Edward Yang, and "
        "Hou Hsiao-hsien's arthouse work, connected by a Hong Kong/Taiwan industry "
        "whose actors moved fluidly between the two scenes.",

        "82 films spanning 1967 to 2025. Of the 79 films with a recorded country, "
        "the split is roughly 63 Hong Kong to 13 Taiwan. The commercial and arthouse "
        "halves read very differently on screen -- Woo's bullet ballets and Chan's "
        "stunt-driven comedies against Wong's saturated color and Yang and Hou's "
        "austere long takes -- but action choreographers, ensemble stars, and "
        "repertory actors cut across both. Virtually the entire cluster is in color "
        "(66 color films to just 1 black-and-white, 15 unresolved).",

        "Small but dense: the typical film here has about as many connections as "
        "in the Collection's biggest ring clusters, despite the much smaller film "
        "count. Hub films (19, with 20 or more connections) -- led by The Eagle "
        "Shooting Heroes and Days of Being Wild -- form a genuinely large, "
        "tightly-connected core; Mid-level films (36, with 8–19 connections) "
        "still carry real weight; Peripheral films (27, with fewer than 8 "
        "connections) are close to, but not, the majority.",
    ),
    "scandinavian_bergman_circle": (
        "Ingmar Bergman's filmography is the dense core of this cluster almost by "
        "himself, surrounded by the wider Swedish and Scandinavian tradition he grew "
        "out of -- Sjöström, Molander, Widerberg -- plus, via actress Ingrid "
        "Bergman's own international career, several 1940s Hollywood pictures "
        "(Casablanca, Gaslight, For Whom the Bell Tolls) that share cast with his "
        "Scandinavian repertory company rather than with the classic-Hollywood "
        "cluster they'd otherwise sit in.",

        "80 films spanning 1917 to 2011, with Ingmar Bergman alone accounting for "
        "31 of them -- more than four times his nearest peer. Of the 71 films with "
        "a recorded country, Sweden accounts for the large majority (58), with "
        "Denmark, France, and Italy contributing a handful each, reflecting the "
        "Ingrid Bergman Hollywood pictures pulled in by shared cast. Mostly "
        "black-and-white (64 films to 15 in color, 1 unresolved).",

        "One of the densest small clusters in the Collection. Hub films (23, with "
        "25 or more connections) are Bergman's own most-connected work -- Autumn "
        "Sonata and Brink of Life among them -- plus the Ingrid Bergman Hollywood "
        "pictures; Mid-level films (38, with 10–24 connections) are still solidly "
        "tied in; Peripheral films (19, with fewer than 10 connections) are the "
        "loosest members, mostly the wider Scandinavian tradition around him.",
    ),
    "czech_new_wave": (
        "The Czechoslovak New Wave of the 1960s -- Forman, Chytilová, Vláčil, Menzel "
        "-- a small, almost entirely self-contained national cinema with a tight "
        "recurring cast and very little cast overlap outside Czechoslovakia. "
        "Untouched in size by the 2026 Best Picture import -- none of the 619 "
        "imported films landed here.",

        "36 films running 1958 to 1987, almost all Czechoslovak productions (35 of "
        "36). No single director dominates the way Bergman or Kinoshita do "
        "elsewhere in the Collection -- Vláčil (5 films), Chytilová (4), Forman "
        "(3), and Menzel (2) each contribute a handful, and the cluster holds "
        "together through a shared pool of actors working across the state-run film "
        "industry of the era rather than one director's repertory company.",

        "Shown as a shared-actor network: nodes are films, and a line between two "
        "films means they share at least one credited actor. Even the most "
        "connected films here -- The Cassandra Cat, The Unfortunate Bridegroom, and "
        "Courage for Every Day, all with around 10-12 connections -- are far less "
        "centrally linked than the hubs of the Collection's bigger clusters, which "
        "fits a small national cinema working with a correspondingly small acting "
        "pool. Hover a film for its year and connection count; click through to "
        "watch it on Criterion.",
    ),
    "silent_era_comedy": (
        "A new cluster in the 2026 rebuild: silent-and-into-sound American slapstick "
        "comedy, centered on Charlie Chaplin's own filmography alongside the Harold "
        "Lloyd collaborators (Newmeyer, Taylor, Bruckman, Wilde) and Buster Keaton "
        "-- distinct enough from the broader Golden Age Hollywood & British "
        "cluster's dramas and prestige pictures to form its own connected community "
        "once the larger post-import network gave Louvain enough signal to resolve "
        "it.",

        "27 films spanning 1921 to 1957 (median 1928), almost entirely American (26 "
        "of 27). Chaplin (10 films) is the largest single share but not a majority "
        "-- Clyde Bruckman and the Newmeyer/Taylor/Wilde circle of Harold Lloyd "
        "collaborators together outnumber him. Entirely black-and-white (all 27 "
        "films), true to its silent-and-early-sound center of gravity even though a "
        "few members (Chaplin's Limelight, 1952) run later.",

        "Shown as a shared-actor network given its size. The Milky Way, The Great "
        "Dictator, and Movie Crazy are among its most-connected films. Hover a film "
        "for its year and connection count; click through to watch it on Criterion.",
    ),
    "soviet_cinema": (
        "Soviet and post-Soviet cinema centered on Kira Muratova and Andrei "
        "Tarkovsky, with Bondarchuk, Klimov, and Shepitko filling out a cluster that "
        "stays almost entirely within the former Soviet Union's own production and "
        "acting circles. Untouched in size by the 2026 Best Picture import -- none "
        "of the 619 imported films landed here.",

        "24 films running 1957 to 2004, mostly credited to the Soviet Union itself "
        "(20 of 24), with a few later Ukrainian and Russian productions extending "
        "the cluster past 1991. Muratova (7 films) and Tarkovsky (5) anchor it, "
        "followed by Bondarchuk (4), with Kalatozov and Shepitko contributing a "
        "couple each -- a small enough cast of directors that individual careers, "
        "more than any single movement, hold the cluster together.",

        "Shown as a shared-actor network given its small size. Mirror, Stalker, and "
        "Andrei Rublev -- all Tarkovsky -- share the highest connection count (6 "
        "each), with Solaris and Ivan's Childhood close behind at 5. Hover a film "
        "for its year and connection count; click through to watch it on "
        "Criterion.",
    ),
    "satyajit_ray_indian": (
        "Built around Satyajit Ray's own filmography, the towering figure of "
        "Bengali and Indian art cinema in the Collection, with Ritwik Ghatak's "
        "Bengali cinema and a handful of other Indian and Indian-adjacent films "
        "connected in by shared cast. Untouched in size by the 2026 Best Picture "
        "import -- none of the 619 imported films landed here.",

        "18 films spanning 1955 to 1994, 15 of them Ray's own -- from Apur Sansar "
        "and Devi in the early 1960s through later work like The Home and the World "
        "in the 1980s. The cluster is small enough that it holds together almost "
        "entirely on the strength of Ray's own recurring collaborators rather than "
        "a broader movement or national scene.",

        "Shown as a shared-actor network of individual films rather than grouped by "
        "connection count, given its small size. Devi (14 connections) is the "
        "clear hub; Apur Sansar and The Elephant God follow at 9 each. Hover a "
        "film for its year and connection count; click through to watch it on "
        "Criterion.",
    ),
}


def esc(s):
    return escape(str(s))


def blurb_html(cluster_id):
    """BLURBS entries are either a single string (one paragraph) or a tuple of
    paragraph strings, so a cluster needing a longer, multi-paragraph
    description doesn't force every other cluster's blurb to be split up too."""
    blurb = BLURBS.get(cluster_id, "")
    paragraphs = (blurb,) if isinstance(blurb, str) else blurb
    return "\n".join(f'<p class="blurb">{esc(p)}</p>' for p in paragraphs)


def cluster_stats(con, cluster_id):
    """Deduped per-film stats for one cluster (criterion_basic_info can hold
    multiple candidate-match rows per imdb_tconst; keep the highest-confidence
    one, same rule cluster_graph_viz.py uses)."""
    df = con.execute("""
        WITH best AS (
            SELECT c.imdb_tconst, b.title, b.criterion_year, b.criterion_director, b.criterion_country,
                   row_number() OVER (
                       PARTITION BY c.imdb_tconst ORDER BY b.confidence_score DESC NULLS LAST
                   ) AS rn
            FROM cluster_assignments c
            JOIN criterion_basic_info b ON b.imdb_tconst = c.imdb_tconst
            WHERE c.cluster_id = ?
        )
        SELECT imdb_tconst, title, criterion_year, criterion_director, criterion_country
        FROM best WHERE rn = 1
    """, [cluster_id]).df()

    directors = (df["criterion_director"].dropna().value_counts().head(6))
    countries = (df["criterion_country"].dropna().value_counts().head(5))
    return {
        "n_films": len(df),
        "year_min": int(df["criterion_year"].min()) if len(df) else None,
        "year_max": int(df["criterion_year"].max()) if len(df) else None,
        "directors": list(directors.items()),
        "countries": list(countries.items()),
    }


def hub_films(con, cluster_id, n=4):
    """Top-n films by internal (within-cluster) shared-actor degree, each also
    annotated with its external degree (shared-actor edges to films in a
    different cluster, including the hiddenGems bucket). Ranking is by
    internal degree only, unchanged -- external is additional context, not a
    second sort key."""
    df = con.execute("""
        WITH film_edges AS (
            SELECT movie_a AS m, movie_b AS other FROM movie_edges
            UNION ALL
            SELECT movie_b AS m, movie_a AS other FROM movie_edges
        ),
        joined AS (
            SELECT fe.m, ca.cluster_id AS cluster_m, cb.cluster_id AS cluster_other
            FROM film_edges fe
            JOIN cluster_assignments ca ON ca.imdb_tconst = fe.m
            JOIN cluster_assignments cb ON cb.imdb_tconst = fe.other
            WHERE ca.cluster_id = ?
        ),
        deg AS (
            SELECT m AS imdb_tconst,
                   count(*) FILTER (WHERE cluster_other = cluster_m) AS internal_degree,
                   count(*) FILTER (WHERE cluster_other != cluster_m) AS external_degree
            FROM joined
            GROUP BY m
        ),
        best AS (
            SELECT imdb_tconst, title, criterion_year,
                   row_number() OVER (
                       PARTITION BY imdb_tconst ORDER BY confidence_score DESC NULLS LAST
                   ) AS rn
            FROM criterion_basic_info
        )
        SELECT d.imdb_tconst, b.title, b.criterion_year, d.internal_degree, d.external_degree
        FROM deg d
        JOIN best b ON b.imdb_tconst = d.imdb_tconst AND b.rn = 1
        ORDER BY d.internal_degree DESC
        LIMIT ?
    """, [cluster_id, n]).df()
    return list(df.itertuples(index=False))


PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — Criterion Clusters</title>
<link rel="stylesheet" href="../style.css">
</head>
<body>
<div class="page">
  <a class="back-link" href="../explore.html">&larr; All clusters</a>
  <header class="cluster-header" style="border-color:{color}">
    <span class="swatch" style="background:{color}"></span>
    <div>
      <h1>{title}</h1>
      <p class="stat-line">{stat_line}</p>
    </div>
  </header>

  <div class="cluster-body">
    <div class="main">
      <div class="viz-card">
        {viz_embed}
      </div>
      <div class="stats-row">
        {hub_section}
        {directors_section}
        {countries_section}
      </div>
    </div>
    <div class="side">
      <section>
        <h2>About this cluster</h2>
        {blurb}
      </section>
    </div>
  </div>
</div>
</body>
</html>
"""


def table_html(heading, rows, value_label):
    if not rows:
        return ""
    items = "".join(
        f'<tr><td>{esc(name)}</td><td>{count}</td></tr>' for name, count in rows
    )
    return f"""
      <section>
        <h2>{esc(heading)}</h2>
        <table class="stat-table">
          <thead><tr><th>{esc(heading)}</th><th>{esc(value_label)}</th></tr></thead>
          <tbody>{items}</tbody>
        </table>
      </section>"""


def hub_films_html(rows):
    if not rows:
        return ""
    items = "".join(
        f'<li><span class="film-title">{esc(r.title)}</span> '
        f'<span class="film-year">({int(r.criterion_year)})</span> '
        f'<span class="film-degree">{r.internal_degree} internal &middot; '
        f'{r.external_degree} external links</span></li>'
        for r in rows
    )
    return f"""
      <section>
        <h2>Most connected films</h2>
        <ol class="hub-list">{items}</ol>
      </section>"""


# Populated by build_cluster_page (cluster_id -> the same top-6 director
# names shown in that cluster's "Top directors" table) and flushed to
# site/assets/top-directors.js by write_top_directors_js, so the "Explore
# Directors by Cluster" tab can filter down to the same names without
# re-deriving them (and risking drift) from the raw per-film director field.
TOP_DIRECTORS = {}


def write_top_directors_js():
    js = (
        "// Generated by src/build_site.py -- do not hand-edit.\n"
        "// cluster_id -> top-6 director names for that cluster's \"Top directors\"\n"
        "// table (site/clusters/<id>.html), used by directors-tab.js to filter\n"
        "// the \"Explore Directors by Cluster\" tab down to the same names.\n"
        f"window.TOP_DIRECTORS = {json.dumps(TOP_DIRECTORS, ensure_ascii=False)};\n"
    )
    (ASSETS_DIR / "top-directors.js").write_text(js)


def build_cluster_page(con, cluster_id):
    stats = cluster_stats(con, cluster_id)
    hubs  = hub_films(con, cluster_id)
    color = COLOR_MAP.get(cluster_id, "#888888")
    title = display_name(cluster_id)
    TOP_DIRECTORS[cluster_id] = [name for name, _count in stats["directors"]]

    if cluster_id in RING_CLUSTERS:
        svg_name = f"{cluster_id}_rings.svg"
    else:
        svg_name = f"{cluster_id}_graph.svg"
    shutil.copyfile(OUTPUT_DIR / svg_name, ASSETS_DIR / svg_name)
    svg_rel = f"../assets/{svg_name}"
    viz_embed = (f'<object type="image/svg+xml" data="{esc(svg_rel)}" '
                 f'class="cluster-viz" aria-label="{esc(title)} shared-actor network"></object>')

    stat_line = f"{stats['n_films']} films"
    if stats["year_min"] is not None:
        stat_line += f" &middot; {stats['year_min']}&ndash;{stats['year_max']}"

    html = PAGE_TEMPLATE.format(
        title=esc(title),
        color=color,
        stat_line=stat_line,
        viz_embed=viz_embed,
        blurb=blurb_html(cluster_id),
        hub_section=hub_films_html(hubs),
        directors_section=table_html("Top directors", stats["directors"], "Films"),
        countries_section=table_html("Top countries", stats["countries"], "Films"),
    )
    (CLUSTERS_DIR / f"{cluster_id}.html").write_text(html)


HIDDEN_GEMS_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hidden Gems — Criterion Clusters</title>
<link rel="stylesheet" href="../style.css">
</head>
<body>
<div class="page">
  <a class="back-link" href="../explore.html">&larr; All clusters</a>
  <header class="cluster-header" style="border-color:#5a5a5a">
    <span class="swatch" style="background:#FFFFFF;border:1px solid #5a5a5a"></span>
    <div>
      <h1>Hidden Gems</h1>
      <p class="stat-line">{stat_line}</p>
    </div>
  </header>

  <div class="cluster-body single-column">
    <section>
      <p class="blurb">
        The periphery bucket: films with no shared-actor connection to any of the
        ten named clusters above, plus {n_no_actor} films with no actor credits
        data at all. Far from uniform -- within it are dozens of small,
        tightly-connected pockets that are each coherent on their own (usually a
        single director's filmography or a specific national cinema) but too
        small individually to place on the hex grid. The analysis below profiles
        the largest of those pockets.
      </p>
    </section>
    <section class="markdown-body">
      {analysis_html}
    </section>
  </div>
</div>
</body>
</html>
"""


def build_hidden_gems_page(con):
    # hiddenGems has no on-page "Top directors" table (it's a text-only
    # small-cluster analysis, not a per-cluster stats page), but the same
    # top-6-by-film-count rule from cluster_stats still applies for the
    # "Explore Directors by Cluster" tab's filtering.
    stats = cluster_stats(con, "hiddenGems")
    TOP_DIRECTORS["hiddenGems"] = [name for name, _count in stats["directors"]]

    df = con.execute("""
        SELECT count(*) AS n FROM cluster_assignments WHERE cluster_id = 'hiddenGems'
    """).df()
    n_assigned = int(df["n"].iloc[0])
    n_no_actor = con.execute("""
        SELECT count(*) FROM criterion_basic_info
        WHERE imdb_tconst NOT IN (SELECT imdb_tconst FROM cluster_assignments)
    """).fetchone()[0]

    analysis_md = ANALYSIS_MD.read_text()
    # Drop the '!!!' typo-markers left in a couple of headings in the source doc.
    analysis_md = analysis_md.replace("!!!!!!!!!!", "").replace("!!!!!!!!!", "")
    analysis_html = md_lib.markdown(analysis_md, extensions=["tables"])

    html = HIDDEN_GEMS_TEMPLATE.format(
        stat_line=f"{n_assigned + n_no_actor} films ({n_assigned} in small clusters, {n_no_actor} with no actor data)",
        n_no_actor=n_no_actor,
        analysis_html=analysis_html,
    )
    (CLUSTERS_DIR / "hiddenGems.html").write_text(html)


EXPLORE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Explore the Clusters — Criterion Clusters</title>
<link rel="stylesheet" href="style.css">
</head>
<body class="home-page">
<div class="page">
  <a class="back-link" href="index.html">&larr; Home</a>
  <header class="home-header">
    <h1>Criterion Collection: Shared-Actor Clusters</h1>
    <p class="subtitle">
      Every hexagon is one film in the Collection -- Criterion titles plus the
      2026 Academy Best Picture nominee import -- grouped by shared cast into
      {n_clusters} clusters. Hover a region to preview it, click to explore
      that cluster's network and read more.
    </p>
  </header>
  <div class="hex-wrap">
    {hex_svg}
  </div>
</div>
</body>
</html>
"""


def build_explore():
    svg_markup = hex_svg.build_svg()
    html = EXPLORE_TEMPLATE.format(n_clusters=len(NAMED_CLUSTERS) + 1, hex_svg=svg_markup)
    (SITE_DIR / "explore.html").write_text(html)


LANDING_SECTIONS = [
    {
        "id": "cinematic-history",
        "modifier": "history",
        "href": "cinematic-history.html",
        "kicker": "01 — Context",
        "title": "Criterion Over Time",
        "body": (
            "The movements, studios, and eras behind the clusters — how each "
            "one fits into the broader story of film."
        ),
        "cta": "Read the history",
        "media": "assets/cinematic_history_poster.jpg",
        "scroll_cue": True,
    },
    {
        "id": "explore",
        "modifier": "explore",
        "href": "explore.html",
        "kicker": "02 — Interactive",
        "title": "Explore the Clusters",
        "body": (
            "Every film in the Collection -- Criterion titles plus the 2026 "
            "Academy Best Picture nominee import -- grouped into {n_clusters} "
            "hexagonal clusters by shared cast. Hover a region to preview it, "
            "click to explore that cluster's network."
        ),
        "cta": "Open the map",
        "media": "hex_grid.svg",
        "scroll_cue": False,
    },
    {
        "id": "find-your-film",
        "modifier": "find-your-film",
        "href": "recommendations.html",
        "kicker": "03 — Personalized",
        "title": "Find Your Film",
        "body": (
            "Not sure what to watch? Tell us what you're in the mood for, "
            "and we'll search the collection for films that match your taste."
        ),
        "cta": "Meet your next favorite film",
        "media": "assets/find_your_film_hero.svg",
        "scroll_cue": False,
    },
    {
        "id": "movie-map",
        "modifier": "map",
        "href": "movie-map.html",
        "kicker": "04 — Directors",
        "title": "Explore Directors by Cluster",
        "body": (
            "Every director in the collection, grouped by the cluster their "
            "films belong to."
        ),
        "cta": "Explore by director",
        "media": False,
        "scroll_cue": False,
    },
    {
        "id": "methodology",
        "modifier": "methodology",
        "href": "methodology.html",
        "kicker": "05 — The Data",
        "title": "Methodology",
        "body": (
            "How the clusters were built: cast-overlap graphs, community "
            "detection, and the judgment calls behind them."
        ),
        "cta": "Read the methodology",
        "media": "assets/methodology_sankey_hero.png",
        "scroll_cue": False,
    },
]

LANDING_HERO_TEMPLATE = """  <section class="landing-hero landing-hero--{modifier}" id="{id}">
    {media}
    <div class="landing-hero-scrim"></div>
    <div class="landing-hero-content">
      <p class="landing-hero-kicker">{kicker}</p>
      <h2>{title}</h2>
      <p class="landing-hero-body">{body}</p>
      <span class="landing-hero-cta">{cta} &rarr;</span>
    </div>
    <a class="landing-hero-stretch" href="{href}" aria-label="{title}"></a>{scroll_cue}
  </section>
"""

LANDING_SCROLL_CUE = """
    <span class="landing-scroll-cue" aria-hidden="true">Scroll<svg viewBox="0 0 24 24" width="14" height="14"><path d="M4 8 L12 16 L20 8" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></span>"""

LANDING_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Criterion Collection: Shared-Actor Clusters</title>
<link rel="stylesheet" href="style.css">
</head>
<body class="landing-page">
<a class="landing-brand" href="#top">Criterion Clusters</a>
<main class="landing-scroll" id="top">
{sections}  <footer class="landing-footer" id="footer">
    <div class="landing-footer-inner">
      <p class="landing-footer-brand">Criterion Collection: Shared-Actor Clusters</p>
      <nav class="landing-footer-links">
        <a href="cinematic-history.html">Criterion Over Time</a>
        <a href="explore.html">Explore the Clusters</a>
        <a href="recommendations.html">Find Your Film</a>
        <a href="movie-map.html">Explore Directors by Cluster</a>
        <a href="methodology.html">Methodology</a>
      </nav>
    </div>
  </footer>
</main>
</body>
</html>
"""


def build_landing():
    n_clusters = len(NAMED_CLUSTERS) + 1
    sections = ""
    for sec in LANDING_SECTIONS:
        media = (f'<img class="landing-hero-media" src="{sec["media"]}" alt="">'
                  if sec.get("media") else "")
        scroll_cue = LANDING_SCROLL_CUE if sec["scroll_cue"] else ""
        sections += LANDING_HERO_TEMPLATE.format(
            id=sec["id"],
            modifier=sec["modifier"],
            href=sec["href"],
            kicker=sec["kicker"],
            title=esc(sec["title"]),
            body=esc(sec["body"].format(n_clusters=n_clusters)),
            cta=esc(sec["cta"]),
            media=media,
            scroll_cue=scroll_cue,
        )
    html = LANDING_TEMPLATE.format(sections=sections)
    (SITE_DIR / "index.html").write_text(html)


PLACEHOLDER_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — Criterion Clusters</title>
<link rel="stylesheet" href="style.css">
</head>
<body>
<div class="page">
  <a class="back-link" href="index.html">&larr; Home</a>
  <header class="placeholder-header">
    <p class="placeholder-kicker">{kicker}</p>
    <h1>{title}</h1>
  </header>
  <p class="placeholder-note">Coming soon.</p>
</div>
</body>
</html>
"""


def build_placeholder_pages():
    # "movie-map" (site/movie-map.html, the "Explore Directors by Cluster"
    # tab) is hand-built -- see directors-tab.js/director-utils.js -- not a
    # stub, so it's excluded here the same as the other fully-built pages.
    for sec in LANDING_SECTIONS:
        if sec["id"] in ("explore", "cinematic-history", "methodology", "find-your-film", "movie-map"):
            continue
        html = PLACEHOLDER_TEMPLATE.format(
            title=esc(sec["title"]),
            kicker=esc(sec["kicker"]),
        )
        (SITE_DIR / sec["href"]).write_text(html)


CINEMATIC_HISTORY_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Criterion Over Time — Criterion Clusters</title>
<link rel="stylesheet" href="style.css">
</head>
<body>
<div class="page">
  <a class="back-link" href="index.html">&larr; Home</a>
  <header class="placeholder-header">
    <p class="placeholder-kicker">01 — Context</p>
    <h1>Criterion Over Time</h1>
  </header>
  <p class="placeholder-note">
    Every film's hexagon, filling in by release year, oldest to newest --
    watch the clusters take shape as the Collection grows.
  </p>
  <div class="cinematic-video-wrap">
    <video class="cinematic-video" controls loop playsinline
           poster="assets/cinematic_history_poster.jpg">
      <source src="assets/cinematic_history.mp4" type="video/mp4">
      Your browser does not support embedded video. Download it here:
      <a href="assets/cinematic_history.mp4">cinematic_history.mp4</a>.
    </video>
  </div>
</div>
</body>
</html>
"""


ANIMATION_DIR = Path(__file__).parent.parent / "outputs"


def build_cinematic_history():
    video_src = ANIMATION_DIR / "cinematic_history.mp4"
    if video_src.exists():
        shutil.copyfile(video_src, ASSETS_DIR / "cinematic_history.mp4")
    if not (ASSETS_DIR / "cinematic_history_poster.jpg").exists():
        print("  (no cinematic_history_poster.jpg in site/assets yet -- "
              "extract one with ffmpeg, e.g. from outputs/cinematic_history.mp4)")
    (SITE_DIR / "cinematic-history.html").write_text(CINEMATIC_HISTORY_TEMPLATE)


METHODOLOGY_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Methodology — Criterion Clusters</title>
<link rel="stylesheet" href="style.css">
</head>
<body>
<div class="page">
  <a class="back-link" href="index.html">&larr; Home</a>
  <header class="placeholder-header">
    <p class="placeholder-kicker">05 — The Data</p>
    <h1>Methodology</h1>
  </header>

  <div class="sankey-card">
    <iframe class="sankey-embed" src="assets/criterion_pipeline_sankey.html"
            title="Criterion-to-IMDb matching pipeline" loading="lazy"></iframe>
  </div>

  <div class="cluster-body single-column">
    <section class="markdown-body">
      <p>This project began by building a cleaned Criterion-to-IMDb dataset that
      could support graph-based clustering and film analysis. The original
      Criterion Collection records were enriched with IMDb metadata using a
      DuckDB SQL pipeline. The pipeline loaded Criterion data, IMDb title files,
      IMDb crew files, actor filmographies, actor names, and title translations
      (for titles in languages other than English). Since Criterion and IMDb do
      not always have identical titles, the matching process uses fuzzy
      matching instead of only relying on exact title matches.</p>

      <p>In order to improve match accuracy, the pipeline used a two part
      matching strategy. The first path searched for candidates using director
      and year because films with slightly different titles can still be
      confidently matched when the director and year agree. The second path
      acted as a fallback by searching based on how similar titles were and a
      small year window. Each candidate match received a weighted confidence
      score based on title similarity, director similarity, and year
      similarity. Title similarity was weighted most heavily, followed by
      director similarity and then year similarity. This helped handle cases
      where a film title differed slightly between Criterion and IMDb, while
      still preventing weak or unrelated matches.</p>

      <p>Each candidate match was scored using a weighted confidence formula
      with three components: title similarity, director similarity, and year
      similarity. Title similarity was calculated between the cleaned
      Criterion title and IMDb title. Director similarity was calculated
      between the cleaned Criterion director name and IMDb director name. Year
      similarity was scored separately: an exact year match received 1.0, a
      one-year difference received 0.5, a two-year difference received 0.25,
      and anything outside that range received 0.</p>

      <pre class="formula">weighted_score = 0.50 * title_sim + 0.35 * director_sim + 0.15 * year_sim</pre>

      <p>In other words, title similarity made up 50% of the match decision,
      director similarity made up 35%, and year similarity made up 15%. This
      allowed the pipeline to still match films with slightly different titles
      when the director and year strongly supported the match, while also
      lowering the score for films with weak title, director, or year
      evidence.</p>

      <p>Several cleaning steps were added to reduce false matches. Text was
      standardized by lowercasing, removing accents, and stripping punctuation
      so that names and titles could be compared more fairly. IMDb alternate
      titles marked as &ldquo;segment title&rdquo; were excluded because they
      caused anthology films to be incorrectly matched to individual segment
      records. Ambiguous matches were not automatically corrected unless the
      evidence was very strong. Instead, films with low confidence, close
      runner-up scores, exact ties, or no match were separated into manual
      review files.</p>

      <p>For the clustering project, the dataset was narrowed to only
      unambiguous feature-length movies. Records were kept only if they were
      IMDb title type movie, had a runtime of at least 60 minutes, and had a
      confidence score of at least 85. This removed short films, videos, TV
      movies, TV specials, and uncertain matches from the main clustering
      dataset. The full raw data stayed in the original ReelWrangling project
      while the new reelClusters repository contained only the filtered data
      needed for graph analysis.</p>

      <p>The graph was created by having each movie as a node, and an edge was
      created between two movies if they shared at least one actor. The edge
      weight represented the number of actors shared by the two movies. The
      main file used to build the graph was <code>actor_filmographies.csv</code>,
      which connects actors to IMDb title IDs. Actor names were joined from
      <code>actor_names.csv</code>, and film metadata such as title, director,
      year, runtime, and match confidence came from
      <code>criterion_basic_info.csv</code>.</p>

      <p>On 2026-07-31, 619 films from an Academy Best Picture nominee IMDb
      list (620 raw rows, one exact duplicate) were merged into this same
      dataset. Each row was matched against the existing Criterion records by
      exact IMDb ID first; 28 were already present as Criterion titles and
      were left as single records, and 591 were genuinely new. Cast, genre,
      release-date, and black-and-white/color data for the new films was
      pulled from the same IMDb source files the original pipeline used. The
      merge, deduplication audit, and enrichment steps are reproducible
      scripts (<code>src/ingest_best_picture_csv.py</code>,
      <code>src/merge_best_picture_films.py</code>,
      <code>src/enrich_new_films.py</code>), and the full accounting -- every
      incoming row's match decision -- is in
      <code>data/dedup_audit.csv</code>.</p>

      <p>After filtering and the Best Picture merge, the dataset contained
      2,366 movie records covering 2,337 distinct films (1,746 from Criterion,
      591 newly added). The actor co-occurrence graph contained 2,170
      connected movie nodes and 18,799 shared-actor edges. Some films did not
      appear in the graph because they either had no IMDb actor credits or
      had actors who did not appear in any other film in the dataset. These
      disconnected films were treated separately as hidden gems rather than
      forcing them into clusters.</p>

      <p>Then, groups of films that were strongly connected through shared
      actors were identified. Louvain clustering was used because the graph
      size was manageable and the method works well for finding communities in
      weighted networks, with a fixed random seed (42) so the result is
      reproducible. Communities smaller than 15 films were folded into Hidden
      Gems rather than given their own page. The resulting clusters were
      reviewed and named from scratch based on the films inside each one --
      no name was carried over automatically from a previous run -- producing
      Modern American Cinema, European Art Cinema, Golden Age Hollywood &amp;
      British Cinema, Classic Japanese Cinema, Japanese New Wave &amp; Genre
      Cinema, Hong Kong &amp; Taiwan Cinema, Scandinavian Cinema &amp; the
      Bergman Circle, Czech New Wave, Silent-Era Comedy, Soviet Cinema, and
      Satyajit Ray &amp; Indian Cinema. The full evidence behind each name --
      film counts, year ranges, leading directors and genres, and
      alternatives considered -- is in
      <code>data/cluster_naming_report.md</code>.</p>

      <p>Finally, the graph results were exported for analysis and
      visualization. Cluster assignments were written back into the DuckDB
      database and exported into CSV files, with one CSV per cluster. Small or
      disconnected films were placed into a hidden gems folder. A hex-grid
      visualization was also created where each movie was represented as its
      own hexagon, grouped by cluster, with hidden gems placed around the
      outside. This made the final clustering easier to interpret visually
      while still preserving the graph-based structure of the analysis.</p>
    </section>
  </div>
</div>
</body>
</html>
"""


def build_methodology():
    (SITE_DIR / "methodology.html").write_text(METHODOLOGY_TEMPLATE)


def main():
    CLUSTERS_DIR.mkdir(parents=True, exist_ok=True)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH))

    print("Building landing page...")
    build_landing()

    print("Building explore page + hex grid...")
    build_explore()

    print("Building placeholder pages...")
    build_placeholder_pages()

    print("Building cinematic history page...")
    build_cinematic_history()

    print("Building methodology page...")
    build_methodology()

    for cluster_id in NAMED_CLUSTERS:
        print(f"Building {cluster_id}...")
        build_cluster_page(con, cluster_id)

    print("Building hiddenGems...")
    build_hidden_gems_page(con)

    write_top_directors_js()

    con.close()
    print(f"Done. Open {SITE_DIR / 'index.html'}")


if __name__ == "__main__":
    main()
