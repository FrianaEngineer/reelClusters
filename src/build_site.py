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
# of the shared-actor network graph. European Art Cinema and Japanese Cinema
# are here because their force-directed graphs are too dense to read as edges
# (millions of overlapping lines); Anglophone Classic, Transatlantic Auteur
# Cinema, Hong Kong/Taiwan Cinema, and Bergman Scandinavian are here by
# choice, for a visual style matching those two.
RING_CLUSTERS = {"european_art_cinema", "japanese_cinema", "anglophone_classic",
                  "transatlantic_auteur_cinema", "hong_kong_taiwan_cinema",
                  "bergman_scandinavian"}

NAMED_CLUSTERS = [
    "youssef_chahine_egyptian", "european_art_cinema",
    "transatlantic_auteur_cinema",
    "hong_kong_taiwan_cinema", "bergman_scandinavian",
    "czech_new_wave", "satyajit_ray_indian", "japanese_cinema", "soviet_cinema",
    "anglophone_classic",
]

# Hand-authored, data-grounded blurbs. Numbers/tables on the page itself are
# computed live from the DB below so they can't drift out of sync with this
# prose -- these just supply the qualitative read a query can't.
BLURBS = {
    "youssef_chahine_egyptian": (
        "Almost entirely the work of one director: nearly every film in this cluster "
        "is Youssef Chahine's own, making it the Collection's most concentrated "
        "single-director grouping. Chahine was Egypt's most prominent filmmaker and "
        "one of Arab cinema's defining figures, working across five decades from "
        "historical epic to intimate autobiography.",

        "The 16 films run 1950 to 1999 and trace his range: star-driven melodrama and "
        "wartime drama in the 1950s (The Blazing Sun, Dark Waters), the historical "
        "epic Saladin the Victorious in 1963, and from the late 1970s on a turn toward "
        "autobiography with the Alexandria films (Alexandria...Why?, Alexandria: "
        "Again and Forever), which fictionalize his own life and career. Egyptian "
        "popular cinema's musical and melodrama traditions run through even his most "
        "personal work.",

        "Because almost the whole cluster is one director's filmography, this is "
        "shown as a shared-actor network rather than degree bands -- the connecting "
        "lines mostly trace actors Chahine cast again and again across his career, "
        "not a shared scene or movement. Hover a film for its year and "
        "internal-connection count; click through to watch it on Criterion.",
    ),
    "european_art_cinema": (
        "The Collection's largest and most heterogeneous cluster -- French New Wave "
        "and its descendants (Godard, Truffaut, Rivette, Varda), Italian and Spanish "
        "art cinema, and Eastern European auteurs, bound together less by any single "
        "movement than by decades of overlapping casts across the postwar European "
        "arthouse circuit.",

        "432 films spanning 1916 to 2025, with a dense core in the postwar decades: "
        "Truffaut and Godard's New Wave, Rivette's long-form experiments, Tavernier's "
        "literary adaptations, Saura's films under and after Franco, Kieślowski's "
        "Polish and French work. Black-and-white and color are close to evenly split "
        "here (192 versus 217 films) -- black-and-white films (the darker tint) "
        "cluster in that mid-century core, while color productions (the lighter tint) "
        "spread from the 1960s onward as the movements it's built from moved into "
        "color and the cluster's reach extended toward the present.",

        "So densely interconnected that a shared-actor edge graph reads as a solid "
        "mass -- shown here as degree bands instead. Hub films (21, degree ≥25) are "
        "the true connective tissue, like Mr. Klein and The Phantom of Liberty; "
        "Mid-level films (182, degree 10–24) carry a solid share of those "
        "connections; Peripheral films (229, degree <10), the largest group, are "
        "tied in more loosely, often through a single shared actor or one-off "
        "international production.",
    ),
    "transatlantic_auteur_cinema": (
        "Independent American cinema (Cassavetes through the Jarmusch/Lynch/Roeg "
        "generation into 21st-century indie film) and New German Cinema (Fassbinder's "
        "prolific ensemble output, Wenders) in a single cluster -- two scenes that read "
        "as separate national cinemas but turn out to share enough cast, once the "
        "Collection's documentaries are excluded from the network, to form one "
        "connected community rather than two.",

        "157 films running 1954 to 2021, dominated by Rainer Werner Fassbinder's "
        "extraordinarily prolific repertory-company output (18 films -- more than the "
        "next several directors combined) alongside Wenders, Jarmusch, and Cassavetes. "
        "About 59% of its films are American, 21% German. Mostly a color-era cluster "
        "(115 color films to 24 black-and-white), reflecting how recently, by "
        "Criterion standards, both scenes were working -- the black-and-white "
        "minority sits mostly at Fassbinder's earliest, cheapest productions.",

        "Its degree distribution is far sparser than Anglophone Classic's or European "
        "Art Cinema's (average internal connections per film: under 5, versus 9–10), "
        "so the bands are proportioned differently here. Hub films (9, degree ≥15) -- "
        "mostly Fassbinder's own repertory-company work like The Third Generation and "
        "The Merchant of Four Seasons -- are the small core tying the cluster "
        "together. Mid-level films (49, degree 5–14) share a handful of connections; "
        "Peripheral films (99, degree <5), the majority, are linked in far more "
        "loosely.",
    ),
    "hong_kong_taiwan_cinema": (
        "Hong Kong action and New Taiwanese Cinema sharing one cluster -- John Woo and "
        "Jackie Chan's genre filmmaking alongside Wong Kar-wai, Edward Yang, and Hou "
        "Hsiao-hsien's arthouse work, connected by a Hong Kong/Taiwan industry whose "
        "actors moved fluidly between the two scenes.",

        "79 films spanning 1967 to 2025, split roughly 63 Hong Kong to 13 Taiwan. The "
        "commercial and arthouse halves read very differently on screen -- Woo's "
        "bullet ballets and Chan's stunt-driven comedies against Wong's saturated "
        "color and Yang and Hou's austere long takes -- but action choreographers, "
        "ensemble stars, and repertory actors cut across both. Virtually the entire "
        "cluster is in color (63 color films to just 1 black-and-white), since almost "
        "none of it predates the color era of Hong Kong and Taiwanese filmmaking.",

        "Small (79 films) but dense: median internal degree is 12, spread fairly "
        "evenly across its 1–36 range rather than skewed to one end, so the bands are "
        "sized differently than in the other ring graphs. Hub films (18, degree ≥20) "
        "-- led by The Eagle Shooting Heroes and Days of Being Wild -- form a "
        "genuinely large, tightly-connected core; Mid-level films (36, degree 8–19) "
        "still carry real weight; Peripheral films (25, degree <8) are the minority "
        "here, not the majority.",
    ),
    "bergman_scandinavian": (
        "Ingmar Bergman's filmography is the dense core of this cluster almost by "
        "himself, surrounded by the wider Swedish and Scandinavian tradition he grew "
        "out of and influenced -- Sjöström, Molander, Widerberg -- plus a scattering "
        "of films that share cast with his repertory company.",

        "71 films spanning 1917 to 2000, with Bergman alone accounting for 31 of them "
        "-- more than four times his nearest peer. Mostly a black-and-white cluster "
        "(59 films to 11 in color), reflecting how much of Bergman's most connected "
        "work (Wild Strawberries, The Seventh Seal, The Magician) belongs to his "
        "1950s-60s black-and-white period; the smaller color group runs later, into "
        "Autumn Sonata and beyond.",

        "The densest small cluster in the Collection: mean and median internal degree "
        "both sit around 17–18, nearly flat across the whole 1–35 range rather than "
        "skewed to either end. Hub films (18, degree ≥25) -- Autumn Sonata, Brink of "
        "Life, The Magician, and Wild Strawberries among them -- are Bergman's own "
        "most-connected work; Mid-level films (34, degree 10–24) are still solidly "
        "tied in; Peripheral films (19, degree <10) are the loosest members, mostly "
        "the wider Scandinavian tradition around him.",
    ),
    "czech_new_wave": (
        "The Czechoslovak New Wave of the 1960s -- Forman, Chytilová, Vláčil, Menzel "
        "-- a small, almost entirely self-contained national cinema with a tight "
        "recurring cast and very little cast overlap outside Czechoslovakia.",

        "36 films running 1958 to 1987, almost all Czechoslovak productions (35 of "
        "36). No single director dominates the way Bergman or Chahine do elsewhere in "
        "the Collection -- Vláčil (5 films), Chytilová (4), Forman (3), and Menzel "
        "(2) each contribute a handful, and the cluster holds together through a "
        "shared pool of actors working across the state-run film industry of the era "
        "rather than one director's repertory company.",

        "Shown as a shared-actor network: nodes are films, and a line between two "
        "films means they share at least one credited actor. Even the most connected "
        "films here -- The Cassandra Cat, The Unfortunate Bridegroom, and Courage for "
        "Every Day, all around 10-12 internal connections -- are far less centrally "
        "linked than the hubs of the Collection's bigger clusters, which fits a small "
        "national cinema working with a correspondingly small acting pool. Hover a "
        "film for its year and connection count; click through to watch it on "
        "Criterion.",
    ),
    "satyajit_ray_indian": (
        "Built around Satyajit Ray's own filmography, the towering figure of Bengali "
        "and Indian art cinema in the Collection, with Ritwik Ghatak's Bengali cinema "
        "and a handful of other Indian and Indian-adjacent films connected in by "
        "shared cast.",

        "18 films spanning 1955 to 1994, 15 of them Ray's own -- from Apur Sansar and "
        "Devi in the early 1960s through later work like The Home and the World in "
        "the 1980s. The cluster is small enough that it holds together almost "
        "entirely on the strength of Ray's own recurring collaborators rather than a "
        "broader movement or national scene.",

        "Shown as a shared-actor network rather than degree bands, given its small "
        "size. Devi (14 internal connections) is the clear hub; Apur Sansar and The "
        "Elephant God follow at 9 each. Hover a film for its year and connection "
        "count; click through to watch it on Criterion.",
    ),
    "japanese_cinema": (
        "The second-largest cluster and the most densely interconnected: classical "
        "Japanese studio cinema across Ozu, Kurosawa, Naruse, Kinoshita, and "
        "Kobayashi, whose stock-company acting culture means the same faces recur "
        "across hundreds of films from different directors and studios.",

        "354 films spanning 1929 to 2008, almost entirely Japanese productions (345 "
        "of 354). Predominantly black-and-white (176 films to 111 in color, plus a "
        "further 67 unresolved and treated the same way) -- the classical studio era "
        "this cluster is built from, roughly the 1930s through the early 1960s, was "
        "shot in black-and-white almost by default; color titles concentrate later, "
        "as the studio system gave way to more independent postwar and New "
        "Wave-adjacent filmmaking.",

        "Like European Art Cinema, too dense to draw as an edge graph -- shown here "
        "as degree bands instead, though on a much larger scale: even its Hub "
        "threshold (degree ≥75) is triple European Art Cinema's. Hub films (44) -- "
        "led by The Bad Sleep Well at a remarkable 122 internal connections -- are "
        "the studio system's most connected stars and directors; Mid-level films "
        "(226, degree 25–74), the clear majority, still carry heavy connections; "
        "Peripheral films (84, degree <25) are comparatively loose ties, still "
        "substantial by any other cluster's standard.",
    ),
    "soviet_cinema": (
        "Soviet and post-Soviet cinema centered on Kira Muratova and Andrei "
        "Tarkovsky, with Bondarchuk, Klimov, and Shepitko filling out a cluster that "
        "stays almost entirely within the former Soviet Union's own production and "
        "acting circles.",

        "24 films running 1957 to 2004, mostly credited to the Soviet Union itself "
        "(20 of 24), with a few later Ukrainian and Russian productions extending the "
        "cluster past 1991. Muratova (7 films) and Tarkovsky (5) anchor it, followed "
        "by Bondarchuk (4), with Kalatozov and Shepitko contributing a couple each -- "
        "a small enough cast of directors that individual careers, more than any "
        "single movement, hold the cluster together.",

        "Shown as a shared-actor network given its small size. Mirror, Stalker, and "
        "Andrei Rublev -- all Tarkovsky -- share the highest internal-connection "
        "count (6 each), with Solaris and Ivan's Childhood close behind at 5. Hover a "
        "film for its year and connection count; click through to watch it on "
        "Criterion.",
    ),
    "anglophone_classic": (
        "Classic British and American cinema -- Chaplin, Hitchcock, David Lean, the "
        "Archers -- spanning the studio era on both sides of the Atlantic. What makes "
        "it read as one cluster rather than two national cinemas is the English-"
        "language star system underneath it: actors, and the directors who cast them, "
        "moved freely between London and Hollywood productions, leaving a shared-actor "
        "network dense enough that the two countries' output can't be pulled apart.",

        "The films run roughly 1913 to 2015, but the center of gravity is the 1930s-"
        "50s studio era: wartime propaganda and prestige dramas from Korda and Powell "
        "and Pressburger, Ealing comedies, Lean's literary adaptations, Hitchcock's "
        "thrillers on both sides of the Atlantic, Chaplin's silent-into-sound run. "
        "Black-and-white films (rendered here in a darker tint of the cluster's blue) "
        "make up most of that core; color productions (the lighter tint) skew later, "
        "as the studio era gives way to postwar and New Hollywood-adjacent work.",

        "In the graph, Hub films are the small set with the most internal shared-"
        "actor connections -- the studio-era regulars who tie the whole cluster "
        "together. Mid-level films share a solid number of those connections without "
        "being as central. Peripheral films are the loosest members: still part of "
        "the same star system, but linked in by only a handful of shared cast. That's "
        "also what separates this cluster from a neighbor like European Art Cinema, "
        "which is arthouse and auteur-driven rather than built on a commercial studio "
        "star system.",
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


def hub_films(con, cluster_id, n=6):
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
      Every hexagon is one film in the Criterion Collection, grouped by shared
      cast into {n_clusters} clusters. Hover a region to preview it, click to
      explore that cluster's network and read more.
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
            "Every film in the Criterion Collection, grouped into {n_clusters} "
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

      <p>After filtering, the dataset contained 2,029 Criterion movie records.
      The actor co-occurrence graph contained 1,661 connected movie nodes and
      13,573 shared-actor edges. Some films did not appear in the graph because
      they either had no IMDb actor credits or had actors who did not appear in
      any other film in the filtered Criterion dataset. These disconnected
      films were treated separately as hidden gems rather than forcing them
      into clusters.</p>

      <p>Then, groups of films that were strongly connected through shared
      actors were identified. Louvain clustering was used because the graph
      size was manageable and the method works well for finding communities in
      weighted networks. The resulting clusters were reviewed and renamed
      based on the films inside them, producing groups such as European Art
      Cinema, Japanese Cinema, Anglophone Classic, American Independent,
      Hong Kong/Taiwan Cinema, and other smaller regional clusters.</p>

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
