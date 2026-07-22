"""
Maps our Criterion titles to their real criterion.com film URLs, so node
graphs can link directly to the exact film page instead of nowhere.

criterion.com blocks scripted requests to its main site (bot protection), but
its sitemap subdomain (meant for search engines, not gated the same way) lists
every currently-live film page as /films/<id>-<slug>. We match by slugifying
our own titles the same way the site would and looking for an exact slug hit
-- NOT fuzzy matching, since a near-miss slug is often a genuinely different
film (e.g. "the-other" vs "the-others", "roma" 1972 vs 2018), and a wrong link
is worse than no link. A handful of slugs collide across two different films
(same title, different years -- "the-killers", "roma", etc); the sitemap
alone can't disambiguate those by year, so they're deliberately left unmapped
rather than risk linking to the wrong one.

Re-fetch the sitemap with:
    curl -A "Mozilla/5.0" http://sitemap.criterion.com/films.xml \
        -o ../data/external/criterion_films_sitemap.xml

Regenerate the mapping with:
    python3 build_criterion_links.py
"""

import re
import unicodedata
from pathlib import Path

import duckdb

from hex_grid import DB_PATH

SITEMAP_PATH = Path(__file__).parent.parent / "data" / "external" / "criterion_films_sitemap.xml"
OUT_CSV      = Path(__file__).parent.parent / "data" / "criterion_film_links.csv"


def slugify(s):
    # Criterion's own slugs replace apostrophes with a hyphen (in-vanda-s-room,
    # casque-d-or) rather than dropping them, so that has to happen BEFORE
    # NFKD/ascii-folding -- ascii encoding with 'ignore' would otherwise just
    # silently delete curly quotes since they have no ascii decomposition.
    s = s.replace("’", "-").replace("'", "-")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


def load_sitemap_slugs():
    xml = SITEMAP_PATH.read_text()
    by_slug = {}
    for fid, slug in re.findall(r"films/(\d+)-([a-z0-9-]+)", xml):
        by_slug.setdefault(slug, []).append(fid)
    return by_slug


def main():
    by_slug = load_sitemap_slugs()
    ambiguous = {slug for slug, ids in by_slug.items() if len(ids) > 1}

    con = duckdb.connect(str(DB_PATH))
    titles = con.execute("SELECT DISTINCT title FROM criterion_basic_info").df()["title"].tolist()
    con.close()

    rows = []
    for title in titles:
        slug = slugify(title)
        if slug in by_slug and slug not in ambiguous:
            fid = by_slug[slug][0]
            rows.append((title, fid, slug, f"https://www.criterion.com/films/{fid}-{slug}"))

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, "w") as f:
        f.write("title,criterion_id,criterion_slug,criterion_url\n")
        for title, fid, slug, url in rows:
            f.write(f'"{title.replace(chr(34), chr(34)*2)}",{fid},{slug},{url}\n')

    print(f"Matched {len(rows)} / {len(titles)} titles -> {OUT_CSV}")
    print(f"({len(ambiguous)} slugs skipped as ambiguous: same title, multiple films)")


if __name__ == "__main__":
    main()
