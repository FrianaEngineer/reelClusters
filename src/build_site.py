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

import hex_svg
import snapshot_grid
import hidden_gem_grid
from hex_grid import DB_PATH, display_name
from cluster_colors import COLOR_MAP

SITE_DIR     = Path(__file__).parent.parent / "site"
OUTPUT_DIR   = Path(__file__).parent.parent / "output"
CLUSTERS_DIR = SITE_DIR / "clusters"
ASSETS_DIR   = SITE_DIR / "assets"

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
        "This is the Collection's largest and most varied cluster. "
        "Mainstream awards-season filmmaking from directors like "
        "Spielberg, Scorsese, and Eastwood sits alongside the American "
        "independent and art-house tradition of Cassavetes, Jarmusch, and "
        "Lynch, with decades of overlapping casts tying the two "
        "traditions together into one large network.",

        "The cluster holds 498 films spanning 1954 to 2025, with a "
        "median release year of 1997. Steven Spielberg (14 films) and "
        "Martin Scorsese (11) are its most prolific directors, followed "
        "by Jim Jarmusch, Francis Ford Coppola, Mike Leigh, David Lynch, "
        "Clint Eastwood, and John Cassavetes with 5 films each. No "
        "single filmmaker dominates the way they do in several of the "
        "Collection's smaller clusters. Most of the cluster is in "
        "color, with 455 color films to 43 black-and-white.",

        "This cluster is so densely interconnected that a shared-actor "
        "graph would look like a solid mass of lines, so it's shown "
        "here grouped by connection count instead. A small hub of 28 "
        "films, each with 21 or more connections, forms the connective "
        "tissue holding everything together. Below that, 234 mid-level "
        "films carry a solid share of the ties with 7 to 20 connections "
        "each, while the remaining 236 peripheral films, nearly half "
        "the cluster, are tied in more loosely, often through just a "
        "single shared actor.",
    ),
    "european_art_cinema": (
        "This is the Collection's broadest continental-European "
        "arthouse cluster, spanning French New Wave and its descendants "
        "(Truffaut, Rivette, Godard, Malle), Italian and Spanish art "
        "cinema, Eastern European auteurs, and Youssef Chahine's "
        "Egyptian filmography. It holds together less through any "
        "single movement than through decades of overlapping casts "
        "across the postwar European arthouse circuit.",

        "The cluster holds 477 films spanning 1916 to 2024, with a "
        "median release year of 1970. Rainer Werner Fassbinder (19 "
        "films) and Youssef Chahine (18) are its most prolific "
        "directors, followed by Carlos Saura, François Truffaut, and "
        "Bertrand Tavernier. Of the 462 films with a recorded country, "
        "France accounts for the largest share with 260, followed by "
        "Italy, Germany, Spain, and Egypt. Black-and-white and color "
        "are close to an even split, with 260 color films to 217 "
        "black-and-white: the black-and-white films cluster in the "
        "mid-century core, while color productions spread out from the "
        "1960s onward.",

        "This cluster is so densely interconnected that a shared-actor "
        "graph would read as a solid mass, so it's grouped here by "
        "connection count instead. Its hub is 23 films with 25 or more "
        "connections each, the true connective tissue of the cluster, "
        "including Mr. Klein and The Phantom of Liberty. A wider "
        "mid-level group of 211 films carries a solid share of the "
        "remaining ties with 10 to 24 connections each, while the "
        "largest group, 243 peripheral films with fewer than 10 "
        "connections, are tied in more loosely, often through a single "
        "shared actor or a one-off international production.",
    ),
    "golden_age_hollywood_british": (
        "This cluster covers classic British and American studio-era "
        "cinema. Hitchcock, David Lean, William Wyler, John Ford, and "
        "George Stevens anchor it, alongside classic-era pictures like "
        "Wuthering Heights, Rebecca, Mr. Smith Goes to Washington, and "
        "Lawrence of Arabia, together representing the studio-era "
        "English-language star system. (Chaplin's own silent-era work "
        "forms its own cluster; see Silent-Era Comedy.)",

        "The cluster holds 467 films spanning 1913 to 2015, with a "
        "median release year of 1946. William Wyler and David Lean lead "
        "with 13 films each, followed by Alfred Hitchcock and John Ford "
        "with 10 each, then George Stevens, Henry King, and Frank "
        "Capra. It's predominantly black-and-white, with 324 films to "
        "143 in color, reflecting the era it's centered on.",

        "A hub of 30 films, each with 32 or more connections, are the "
        "studio-era regulars who tie the whole cluster together. A "
        "larger mid-level group of 203 films carries a solid number of "
        "ties with 15 to 31 connections each, and the remaining 234 "
        "peripheral films have fewer than 15 connections. Those are the "
        "loosest members, still part of the same star system but linked "
        "in by only a handful of shared cast.",
    ),
    "classic_japanese_cinema": (
        "This cluster covers classical Japanese studio cinema: Ozu and "
        "Naruse's shomin-geki family dramas, Kinoshita's melodramas, "
        "and Kurosawa and Kobayashi's period and social films. It's "
        "built on a stock-company acting culture that carries the same "
        "faces across hundreds of films from different directors and "
        "studios. A separate, genre- and New Wave-leaning half of "
        "Japanese cinema forms its own cluster; see Japanese New Wave & "
        "Genre Cinema.",

        "The cluster holds 216 films spanning 1929 to 1998, with a "
        "median release year of 1956, almost entirely Japanese "
        "productions (210 of 216). Keisuke Kinoshita (35 films) and "
        "Yasujiro Ozu (32) lead, followed by Akira Kurosawa (22), "
        "Ishiro Honda (16), Mikio Naruse (15), and Masaki Kobayashi "
        "(12). It's predominantly black-and-white, with 144 films to 72 "
        "in color, reflecting its center of gravity in the classical "
        "studio era of roughly the 1930s through the early 1960s.",

        "This is a small but dense cluster, where the median film has "
        "44.5 connections. Its 10 hub films, led by The Bad Sleep Well "
        "at 122 connections, each have 84 or more and represent the "
        "studio system's most connected stars and directors. A further "
        "98 mid-level films still carry heavy connections, from 45 to "
        "83 each, and the remaining 108 peripheral films have fewer "
        "than 45. That's loose only by this cluster's own standard; "
        "it's still substantial compared to most other clusters in the "
        "Collection.",
    ),
    "japanese_new_wave_genre": (
        "This cluster brings together samurai and genre action, "
        "including Kenji Misumi's Zatoichi series and other chanbara "
        "swordplay, alongside the Japanese New Wave of Oshima, Shinoda, "
        "Imamura, and Suzuki. These are two different sensibilities, "
        "but they share enough cast to form one connected community, "
        "distinct from the classical studio-drama cluster of Classic "
        "Japanese Cinema.",

        "The cluster holds 142 films spanning 1937 to 2008, with a "
        "median release year of 1968, almost entirely Japanese (140 of "
        "142). Kenji Misumi and Nagisa Oshima lead with 13 films each, "
        "followed by Masahiro Shinoda (12), Juzo Itami (9), and Shohei "
        "Imamura and Seijun Suzuki with 8 each. Unlike Classic Japanese "
        "Cinema, color is the clear majority here, with 95 color films "
        "to 47 black-and-white, reflecting this cluster's later center "
        "of gravity.",

        "A small, tightly-connected core of 7 hub films, led by "
        "Zatoichi's Conspiracy and Harakiri, each have 41 or more "
        "connections. A mid-level group of 65 films still carries real "
        "weight with 22 to 40 connections each, and the remaining 70 "
        "peripheral films, with fewer than 22 connections, make up "
        "about half the cluster.",
    ),
    "hong_kong_taiwan_cinema": (
        "Hong Kong action and New Taiwanese Cinema share one cluster "
        "here: John Woo and Jackie Chan's genre filmmaking sits "
        "alongside Wong Kar-wai, Edward Yang, and Hou Hsiao-hsien's "
        "arthouse work. Actors moved fluidly between the two scenes, "
        "connecting the whole cluster through a shared Hong Kong/Taiwan "
        "industry.",

        "The cluster holds 82 films spanning 1967 to 2025. Of the 79 "
        "films with a recorded country, the split is roughly 63 Hong "
        "Kong to 13 Taiwan. The commercial and arthouse halves look "
        "very different on screen, from Woo's bullet ballets and "
        "Chan's stunt-driven comedies to Wong's saturated color and "
        "Yang and Hou's austere long takes, but action choreographers, "
        "ensemble stars, and repertory actors cut across both. "
        "Virtually the entire cluster is in color, with 81 color films "
        "to just 1 black-and-white.",

        "This cluster is small but dense: the typical film here has "
        "about as many connections as in the Collection's biggest ring "
        "clusters, despite the much smaller film count. A genuinely "
        "large, tightly-connected core of 19 hub films, led by The "
        "Eagle Shooting Heroes and Days of Being Wild, each have 20 or "
        "more connections. The 36 mid-level films still carry real "
        "weight with 8 to 19 connections each, and the remaining 27 "
        "peripheral films, with fewer than 8 connections, come close "
        "to being the majority without quite getting there.",
    ),
    "scandinavian_bergman_circle": (
        "Ingmar Bergman's filmography is the dense core of this "
        "cluster, almost by himself, surrounded by the wider Swedish "
        "and Scandinavian tradition he grew out of: Sjöström, Molander, "
        "Widerberg. Actress Ingrid Bergman's international career also "
        "pulls in several 1940s Hollywood pictures, including "
        "Casablanca, Gaslight, and For Whom the Bell Tolls, which share "
        "cast with Bergman's Scandinavian repertory company rather "
        "than with the classic-Hollywood cluster they'd otherwise sit "
        "in.",

        "The cluster holds 80 films spanning 1917 to 2011, with Ingmar "
        "Bergman alone accounting for 31 of them, more than four times "
        "his nearest peer. Of the 71 films with a recorded country, "
        "Sweden accounts for the large majority with 58, while Denmark, "
        "France, and Italy each contribute a handful, reflecting the "
        "Ingrid Bergman Hollywood pictures pulled in by shared cast. "
        "It's mostly black-and-white, with 65 films to 15 in color.",

        "This is one of the densest small clusters in the Collection. "
        "Its 23 hub films each have 25 or more connections: Bergman's "
        "own most-connected work, including Autumn Sonata and Brink of "
        "Life, plus the Ingrid Bergman Hollywood pictures. A further 38 "
        "mid-level films are still solidly tied in with 10 to 24 "
        "connections each, and the remaining 19 peripheral films, with "
        "fewer than 10 connections, are the loosest members, mostly "
        "drawn from the wider Scandinavian tradition around Bergman.",
    ),
    "czech_new_wave": (
        "This cluster is the Czechoslovak New Wave of the 1960s: "
        "Forman, Chytilová, Vláčil, Menzel. It's a small, almost "
        "entirely self-contained national cinema, with a tight "
        "recurring cast and very little overlap with actors outside "
        "Czechoslovakia.",

        "The cluster holds 36 films running 1958 to 1987, almost all "
        "Czechoslovak productions (35 of 36). No single director "
        "dominates the way Bergman or Kinoshita do elsewhere in the "
        "Collection: Vláčil (5 films), Chytilová (4), Forman (3), and "
        "Menzel (2) each contribute a handful. It holds together "
        "through a shared pool of actors working across the state-run "
        "film industry of the era, rather than through one director's "
        "repertory company.",

        "This cluster is shown as a shared-actor network, where each "
        "node is a film and a line between two films means they share "
        "at least one credited actor. Even its most connected films, "
        "The Cassandra Cat, The Unfortunate Bridegroom, and Courage "
        "for Every Day, each with around 10 to 12 connections, are far "
        "less centrally linked than the hubs of the Collection's "
        "bigger clusters. That fits a small national cinema working "
        "with a correspondingly small acting pool. Hover a film for "
        "its year and connection count, or click through to watch it "
        "on Criterion.",
    ),
    "silent_era_comedy": (
        "This cluster covers silent-and-into-sound American slapstick "
        "comedy, centered on Charlie Chaplin's own filmography "
        "alongside the Harold Lloyd collaborators (Newmeyer, Taylor, "
        "Bruckman, Wilde) and Buster Keaton. It's distinct enough from "
        "the Golden Age Hollywood & British cluster's dramas and "
        "prestige pictures to form its own connected community.",

        "The cluster holds 27 films spanning 1921 to 1957, with a "
        "median release year of 1928, almost entirely American (26 of "
        "27). Chaplin has the largest single share with 10 films, but "
        "not a majority: Clyde Bruckman and the Newmeyer/Taylor/Wilde "
        "circle of Harold Lloyd collaborators together outnumber him. "
        "All 27 films are black-and-white, true to the cluster's "
        "silent-and-early-sound center of gravity, even though a few "
        "members, including Chaplin's Limelight (1952), run later.",

        "Shown here as a shared-actor network, given its size. The "
        "Milky Way, The Great Dictator, and Movie Crazy are among its "
        "most-connected films. Hover a film for its year and "
        "connection count, or click through to watch it on Criterion.",
    ),
    "soviet_cinema": (
        "Soviet and post-Soviet cinema centered on Kira Muratova and "
        "Andrei Tarkovsky, with Bondarchuk, Klimov, and Shepitko "
        "filling out the cluster. It stays almost entirely within the "
        "former Soviet Union's own production and acting circles.",

        "The cluster holds 24 films running 1957 to 2004, mostly "
        "credited to the Soviet Union itself (20 of 24), with a few "
        "later Ukrainian and Russian productions extending it past "
        "1991. Muratova (7 films) and Tarkovsky (5) anchor it, followed "
        "by Bondarchuk (4), with Kalatozov and Shepitko each "
        "contributing a couple. It's a small enough cast of directors "
        "that individual careers, more than any single movement, hold "
        "the cluster together.",

        "Shown here as a shared-actor network, given its small size. "
        "None of its 24 films share a credited actor with a film "
        "outside the cluster, so every connection stays within Soviet "
        "and post-Soviet cinema itself. Mirror, Stalker, and Andrei "
        "Rublev, all Tarkovsky, share the highest connection count at "
        "6 each, with Solaris and Ivan's Childhood close behind at 5. "
        "Hover a film for its year and connection count, or click "
        "through to watch it on Criterion.",
    ),
    "satyajit_ray_indian": (
        "This cluster is built around Satyajit Ray's own filmography, "
        "the towering figure of Bengali and Indian art cinema in the "
        "Collection, along with Ritwik Ghatak's Bengali cinema and a "
        "handful of other Indian and Indian-adjacent films connected "
        "in by shared cast.",

        "The cluster holds 18 films spanning 1955 to 1994, 15 of them "
        "Ray's own, from Apur Sansar and Devi in the early 1960s "
        "through later work like The Home and the World in the 1980s. "
        "It's small enough that it holds together almost entirely on "
        "the strength of Ray's own recurring collaborators, rather "
        "than a broader movement or national scene.",

        "Shown as a shared-actor network of individual films, rather "
        "than grouped by connection count, given its small size. Devi "
        "is the clear hub with 14 connections, followed by Apur Sansar "
        "and The Elephant God at 9 each. Hover a film for its year and "
        "connection count, or click through to watch it on Criterion.",
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
<title>Hidden Gems Mosaic — Criterion Clusters</title>
<link rel="stylesheet" href="../style.css">
</head>
<body>
<div class="page">
  <a class="back-link" href="../explore.html">&larr; All clusters</a>
  <header class="cluster-header" style="border-color:#5a5a5a">
    <span class="swatch" style="background:#FFFFFF;border:1px solid #5a5a5a"></span>
    <div>
      <h1>Hidden Gems Mosaic</h1>
      <p class="stat-line">{stat_line}</p>
    </div>
  </header>

  <div class="cluster-body single-column">
    <section>
      <p class="blurb">
        Hidden Gems Mosaic is the periphery bucket: every film with no shared-actor
        connection to any of the ten named clusters, plus {n_no_actor} films
        carrying no actor credits at all. It is the one cluster on the hex grid
        that was never a community in the first place. Underneath the label sit
        {n_pockets} separate pockets covering {n_films} films, each a Louvain
        community that came out perfectly coherent on its own and was folded in
        here only because it was too small to name and place beside the others.
      </p>
      <p class="blurb">
        What keeps them at the edge is how little crosses between them.
        {n_self_contained} of the {n_pockets} pockets share not one credited
        actor with any film outside themselves, which is precisely why nothing
        ever pulled them into a larger cluster. The seal is usually a single
        career: of the {n_multi} pockets holding three films or more,
        {n_director_led} are mostly one director's own filmography, the same
        faces recurring from picture to picture, and {n_country_led} draw every
        film with a recorded country of origin from one country. Read that way
        the pockets are less an assortment of leftovers than a set of small
        national cinemas and closed working troupes -- {largest_name} is the
        biggest at {largest_size} films -- alongside {n_pairs} isolated pairs,
        two films joined by a single shared actor and nothing more.
      </p>
    </section>
  </div>

  <section class="gem-grid-section">
    <h2>The {n_pockets} Pockets</h2>
    <p class="gem-grid-note">
      Each card is one raw Louvain community, drawn as its own shared-actor
      graph: a dot per film, a line per pair sharing at least one credited
      actor, thicker the more actors they share, and larger dots for the films
      with the most connections inside the pocket. Hover or focus a dot for the
      film. Titles are hand-authored -- the underlying Louvain communities
      carry only numbers.
    </p>
    {gem_grid}
  </section>

</div>
<div class="gem-tip" id="gem-tip" role="tooltip" hidden></div>
<script>
(function () {{
  var tip = document.getElementById("gem-tip");
  function show(node) {{
    tip.textContent = node.getAttribute("data-film");
    tip.hidden = false;
    var r = node.getBoundingClientRect();
    var t = tip.getBoundingClientRect();
    var x = r.left + r.width / 2 - t.width / 2 + window.scrollX;
    var y = r.top - t.height - 8 + window.scrollY;
    x = Math.max(6, Math.min(x, window.innerWidth - t.width - 6));
    tip.style.left = x + "px";
    tip.style.top = y + "px";
  }}
  function hide() {{ tip.hidden = true; }}
  document.querySelectorAll(".gem-node").forEach(function (n) {{
    n.addEventListener("mouseenter", function () {{ show(n); }});
    n.addEventListener("mouseleave", hide);
    n.addEventListener("focus", function () {{ show(n); }});
    n.addEventListener("blur", hide);
  }});
  window.addEventListener("scroll", hide, {{passive: true}});
}})();
</script>
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

    # output/small_cluster_analysis.md is no longer rendered onto this page at
    # all: its intro, its Edge Statistics table, its per-community prose
    # profiles and its Key Findings are all carried instead by the narrative
    # above the grid and by the grid itself, which draws every pocket (the
    # 2-film pairs that file never profiled included) under a hand-authored
    # title rather than a Louvain community number. The file is still written
    # by src/build_small_cluster_analysis.py as the standalone report it was.
    gem_grid, pocket_stats = hidden_gem_grid.build_grid(con)

    html = HIDDEN_GEMS_TEMPLATE.format(
        stat_line=f"{n_assigned + n_no_actor} films",
        n_no_actor=n_no_actor,
        gem_grid=gem_grid,
        **pocket_stats,
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
    # Layout comes from the video's frozen snapshot, not from a fresh
    # hex_grid run: the film data has moved on since that snapshot, so a
    # fresh layout can no longer reproduce the map the video animates, and
    # the two pages would show different maps of the same thing. Colors, the
    # gold Best Picture borders and the cluster names still come from current
    # code/data -- only positions and label placement are taken from the
    # snapshot. See src/snapshot_grid.py.
    svg_markup = hex_svg.build_svg(grid=snapshot_grid.load(),
                                   labels=snapshot_grid.load_labels())
    html = EXPLORE_TEMPLATE.format(n_clusters=len(NAMED_CLUSTERS) + 1, hex_svg=svg_markup)
    (SITE_DIR / "explore.html").write_text(html)


LANDING_SECTIONS = [
    {
        "id": "cinematic-history",
        "modifier": "history",
        "href": "cinematic-history.html",
        "title": "Criterion Over Time",
        "body": (
            "The movements, studios, and eras behind the clusters — how each "
            "one fits into the broader story of film."
        ),
        "cta": "Read the history",
        # A silent, looping background instead of a still: a ~21x timelapse of
        # the whole video, so the hero shows the map filling in. Half-res and
        # 1.4MB -- the full 12-minute video is 256MB and would be unusable as
        # an autoplaying page background. Rebuild it with:
        #   ffmpeg -i outputs/cinematic_history.mp4 -an \
        #     -vf "setpts=PTS/21,scale=960:540,fps=30" -c:v libx264 -crf 28 \
        #     -pix_fmt yuv420p -movflags +faststart \
        #     site/assets/cinematic_history_loop.mp4
        "media": "assets/cinematic_history_loop.mp4",
        "media_poster": "assets/cinematic_history_loop_poster.jpg",
        "scroll_cue": True,
    },
    {
        "id": "explore",
        "modifier": "explore",
        "href": "explore.html",
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
        "title": "Explore Directors by Cluster",
        "body": (
            "Every director in the collection, grouped by the cluster their "
            "films belong to."
        ),
        "cta": "Explore by director",
        # Screen recording of the directors tab itself, re-encoded for
        # background use (1152px wide, 24fps, no audio, 9.9MB from a 268MB
        # source):
        #   ffmpeg -i explore_directors.mov -an -vf "scale=1152:-2,fps=24" \
        #     -c:v libx264 -crf 33 -preset slow -pix_fmt yuv420p \
        #     -movflags +faststart site/assets/explore_directors_loop.mp4
        "media": "assets/explore_directors_loop.mp4",
        "media_poster": "assets/explore_directors_loop_poster.jpg",
        "scroll_cue": False,
    },
    {
        "id": "methodology",
        "modifier": "methodology",
        "href": "methodology.html",
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
        # An .mp4 becomes an autoplaying muted loop rather than an <img>.
        # Muted + playsinline are what let mobile browsers autoplay at all;
        # the poster covers the case where a browser blocks it anyway. The
        # element is decorative and sits under the hero's own stretch link,
        # so it takes no focus and never intercepts the click.
        if not sec.get("media"):
            media = ""
        elif str(sec["media"]).endswith(".mp4"):
            media = (f'<video class="landing-hero-media" autoplay muted loop playsinline '
                     f'preload="auto" aria-hidden="true" poster="{sec["media_poster"]}">'
                     f'<source src="{sec["media"]}" type="video/mp4"></video>')
        else:
            media = f'<img class="landing-hero-media" src="{sec["media"]}" alt="">'

        scroll_cue = LANDING_SCROLL_CUE if sec["scroll_cue"] else ""
        sections += LANDING_HERO_TEMPLATE.format(
            id=sec["id"],
            modifier=sec["modifier"],
            href=sec["href"],
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


# site/assets is committed and published by .github/workflows/pages.yml, and
# GitHub rejects any file over 100MB outright. The full-quality master is well
# past that, so the web encode is preferred and an oversized file is never
# copied in -- this copy silently re-breaking every push is exactly what used
# to happen. See src/cinematic_history_mux.py for the encode command.
GITHUB_FILE_LIMIT_MB = 100


def build_cinematic_history():
    web_src = ANIMATION_DIR / "cinematic_history_web.mp4"
    video_src = web_src if web_src.exists() else ANIMATION_DIR / "cinematic_history.mp4"
    if video_src.exists():
        size_mb = video_src.stat().st_size / 1e6
        if size_mb > GITHUB_FILE_LIMIT_MB:
            print(f"  (skipping video copy: {video_src.name} is {size_mb:.0f}MB, past "
                  f"GitHub's {GITHUB_FILE_LIMIT_MB}MB limit -- encode a web version first)")
        else:
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
