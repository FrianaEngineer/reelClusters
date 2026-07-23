"""
Builds the static project website: an interactive hex-grid home page and one
page per cluster embedding its existing network visualization plus a
data-grounded description. Run after any of the viz scripts so the site
picks up the latest SVGs/assignment.

    python3 build_site.py
"""

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

# Clusters whose force-directed graph is too dense to read as edges (millions
# of overlapping lines); cluster_ring_viz.py made a degree-banded alternative
# for these instead. Everyone else uses the shared-actor network graph.
RING_CLUSTERS = {"european_art_cinema", "japanese_cinema", "anglophone_classic"}

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
    "youssef_chahine_egyptian":
        "Almost entirely the work of a single director: nearly every film here is "
        "Youssef Chahine's own, spanning melodrama, musicals, and autobiography from "
        "Cairo Station through the Alexandria trilogy. Egypt's most prominent director "
        "in the collection, with a recurring cast tight enough to form its own "
        "self-contained island in the shared-actor network.",
    "european_art_cinema":
        "The collection's largest and most heterogeneous cluster -- French New Wave "
        "and its descendants (Godard, Truffaut, Rivette, Varda), Italian and Spanish "
        "art cinema, and Eastern European auteurs, bound together less by any single "
        "movement than by decades of overlapping casts across the postwar European "
        "arthouse circuit. So densely interconnected that a shared-actor edge graph "
        "reads as a solid mass; the ring view groups films by how many internal "
        "connections they carry instead.",
    "transatlantic_auteur_cinema":
        "Independent American cinema (Cassavetes through the Jarmusch/Lynch/Roeg "
        "generation into 21st-century indie film) and New German Cinema (Fassbinder's "
        "prolific ensemble output, Wenders) in a single cluster -- two scenes that read "
        "as separate national cinemas but turn out to share enough cast, once the "
        "collection's documentaries are excluded from the network, to form one "
        "connected community rather than two. About 59% of its films are American, "
        "21% German.",
    "hong_kong_taiwan_cinema":
        "Hong Kong action and New Taiwanese Cinema sharing one cluster -- John Woo and "
        "Jackie Chan's genre filmmaking alongside Wong Kar-wai, Edward Yang, and Hou "
        "Hsiao-hsien's arthouse work, connected by a Hong Kong/Taiwan industry whose "
        "actors moved fluidly between the two scenes.",
    "bergman_scandinavian":
        "Ingmar Bergman's filmography is the dense core of this cluster almost by "
        "himself, surrounded by the wider Swedish and Scandinavian tradition he grew "
        "out of and influenced -- Sjostrom, Molander, Widerberg -- plus a scattering of "
        "films that share cast with his repertory company.",
    "czech_new_wave":
        "The Czechoslovak New Wave of the 1960s -- Forman, Chytilova, Vlacil, Menzel "
        "-- a small, almost entirely self-contained national cinema with a tight "
        "recurring cast and very little cast overlap outside Czechoslovakia.",
    "satyajit_ray_indian":
        "Built around Satyajit Ray's own filmography, the towering figure of Bengali "
        "and Indian art cinema in the collection, with Ritwik Ghatak's Bengali cinema "
        "and a handful of other films connected in by shared cast.",
    "japanese_cinema":
        "The second-largest cluster and the most densely interconnected: classical "
        "Japanese studio cinema across Ozu, Kurosawa, Naruse, Kinoshita, and Kobayashi, "
        "whose stock-company acting culture means the same faces recur across "
        "hundreds of films from different directors and studios. Like European Art "
        "Cinema, too dense to draw as an edge graph -- shown here as degree bands "
        "instead.",
    "soviet_cinema":
        "Soviet and post-Soviet cinema centered on Kira Muratova and Andrei Tarkovsky, "
        "with Bondarchuk, Klimov, and Shepitko filling out a cluster that stays almost "
        "entirely within the former Soviet Union's own production and acting circles.",
    "anglophone_classic":
        "Classic British and American cinema -- Chaplin, Hitchcock, David Lean, the "
        "Archers -- spanning the studio era on both sides of the Atlantic, unified by "
        "an English-language star system whose actors crossed freely between UK and "
        "US productions. Nearly as densely interconnected as European Art Cinema -- "
        "shown here as degree bands rather than an edge graph for the same reason.",
}


def esc(s):
    return escape(str(s))


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
    """Top-n films by internal (within-cluster) shared-actor degree."""
    df = con.execute("""
        WITH internal_edges AS (
            SELECT me.movie_a, me.movie_b
            FROM movie_edges me
            JOIN cluster_assignments ca ON ca.imdb_tconst = me.movie_a
            JOIN cluster_assignments cb ON cb.imdb_tconst = me.movie_b
            WHERE ca.cluster_id = ? AND cb.cluster_id = ?
        ),
        endpoints AS (
            SELECT movie_a AS m FROM internal_edges
            UNION ALL
            SELECT movie_b AS m FROM internal_edges
        ),
        deg AS (
            SELECT m AS imdb_tconst, count(*) AS degree FROM endpoints GROUP BY m
        ),
        best AS (
            SELECT imdb_tconst, title, criterion_year,
                   row_number() OVER (
                       PARTITION BY imdb_tconst ORDER BY confidence_score DESC NULLS LAST
                   ) AS rn
            FROM criterion_basic_info
        )
        SELECT d.imdb_tconst, b.title, b.criterion_year, d.degree
        FROM deg d
        JOIN best b ON b.imdb_tconst = d.imdb_tconst AND b.rn = 1
        ORDER BY d.degree DESC
        LIMIT ?
    """, [cluster_id, cluster_id, n]).df()
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
        <p class="blurb">{blurb}</p>
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
        f'<span class="film-degree">{r.degree} internal links</span></li>'
        for r in rows
    )
    return f"""
      <section>
        <h2>Most connected films</h2>
        <ol class="hub-list">{items}</ol>
      </section>"""


def build_cluster_page(con, cluster_id):
    stats = cluster_stats(con, cluster_id)
    hubs  = hub_films(con, cluster_id)
    color = COLOR_MAP.get(cluster_id, "#888888")
    title = display_name(cluster_id)

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
        blurb=esc(BLURBS.get(cluster_id, "")),
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
        "id": "movie-map",
        "modifier": "map",
        "href": "movie-map.html",
        "kicker": "03 — Geography",
        "title": "Movie Map",
        "body": (
            "Where these films were made and set, laid out geographically "
            "instead of by shared cast."
        ),
        "cta": "Open the map",
        "media": False,
        "scroll_cue": False,
    },
    {
        "id": "methodology",
        "modifier": "methodology",
        "href": "methodology.html",
        "kicker": "04 — The Data",
        "title": "Methodology",
        "body": (
            "How the clusters were built: cast-overlap graphs, community "
            "detection, and the judgment calls behind them."
        ),
        "cta": "Read the methodology",
        "media": False,
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
        <a href="movie-map.html">Movie Map</a>
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
    for sec in LANDING_SECTIONS:
        if sec["id"] in ("explore", "cinematic-history", "methodology"):
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
    <p class="placeholder-kicker">03 — Context</p>
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
    <p class="placeholder-kicker">04 — The Data</p>
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

    con.close()
    print(f"Done. Open {SITE_DIR / 'index.html'}")


if __name__ == "__main__":
    main()
