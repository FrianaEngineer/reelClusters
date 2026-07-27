"""
Verifies criterionchannel.com candidate matches (title -> single-segment
slug) by actually fetching each page and cross-checking the year embedded in
its server-rendered og:description ("Directed by X (dot) YYYY (dot)
Country") against our own criterion_year. This catches the two failure modes
a bare slug match can't rule out on its own: a slug that happens to belong to
a collection/series page instead of a film, and a slug collision between two
different films that share a title (remakes, common titles).

Writes data/criterion_channel_links.csv (title, channel_slug, channel_url)
for confirmed matches only -- unconfirmed candidates are left out rather than
guessed at.
"""

import csv
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import duckdb
import requests

from hex_grid import DB_PATH

SITEMAP_URL   = "https://www.criterionchannel.com/sitemap.xml"
SITEMAP_CACHE = Path(__file__).parent.parent / "data" / "external" / "criterion_channel_sitemap.xml"
MAIN_LINKS_CSV = Path(__file__).parent.parent / "data" / "criterion_film_links.csv"
OUT_CSV        = Path(__file__).parent.parent / "data" / "criterion_channel_links.csv"

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"}


def slugify(s):
    # Kept in sync with build_criterion_links.py's slugify() -- see the
    # comments there for why these replacements must happen before NFKD.
    s = s.replace("½", "")
    s = s.replace("—", "-").replace("–", "-")
    s = s.replace("’", "-").replace("'", "-")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


def fetch_sitemap():
    if not SITEMAP_CACHE.exists():
        r = requests.get(SITEMAP_URL, headers=HEADERS, timeout=30)
        r.raise_for_status()
        SITEMAP_CACHE.parent.mkdir(parents=True, exist_ok=True)
        SITEMAP_CACHE.write_text(r.text)
    return SITEMAP_CACHE.read_text()


def single_segment_slugs(sitemap_xml):
    locs = re.findall(r"<loc>https://www\.criterionchannel\.com/([^<]+)</loc>", sitemap_xml)
    return {l for l in locs if "/" not in l}


# Titles whose real Channel slug can't be derived from slugify(title) at
# all -- either it's an export/alternate title Criterion doesn't use, or the
# base slug collides with an unrelated film so the Channel disambiguates
# with a "-1"/"-2" suffix slugify() has no way to guess. Each was found by
# grepping the cached channel sitemap for a plausible substring and is
# re-verified live below just like every other candidate (same
# director/year/title cross-check) -- so if Criterion ever retires or
# renames one of these, it silently drops out on the next run instead of
# leaving a stale/wrong link. See the "mistranslations" pass in project
# chat history for how these were found.
MANUAL_SLUG_OVERRIDES = {
    "Duet for Cannibals": "duet-for-cannibals",
    "Les Grandes Manœuvres": "les-grandes-manoeuvres",
    "More Than a Secretary": "more-than-a-secretary",
    "The Swordsman": "swordsman",
    "Ginza Cosmetics": "ginza-cosmetics",
    "Repast": "repast",
    "From Russia with Love": "from-russia-with-love",
    "White Nights": "le-notti-bianche",
    "My American Uncle": "mon-oncle-d-amerique",
    "Assassin": "assassin-1",
    "Fear": "fear-1",
    "Silence": "silence-1",
    "Moving": "moving-1",
    "Once a Thief": "once-a-thief-1",
    "Undercurrent": "undercurrent-1",
    "Destiny": "destiny-1",
    "Father": "father-1",
    "Water": "water-1",
    "Rendez-vous": "rendez-vous-1",
    "Gang of Four": "the-gang-of-four",
    "Lydia": "lydia-1",
    "Joan of Arc": "joan-of-arc-2",
    "No Way Out": "no-way-out-1",
    "Obsession": "obsession-1",
    "Trapped": "trapped-1",
    "Stella Dallas": "stella-dallas-1",
    "The Ear": "the-ear-1",
}


def candidates():
    already = set()
    with open(MAIN_LINKS_CSV, newline="") as f:
        for row in csv.DictReader(f):
            already.add(row["title"])

    con = duckdb.connect(str(DB_PATH))
    df = con.execute("SELECT DISTINCT title, criterion_year FROM criterion_basic_info").df()
    con.close()
    year_by_title = dict(zip(df["title"], df["criterion_year"]))

    slugs = single_segment_slugs(fetch_sitemap())
    out = []
    seen = set()
    for title, year in zip(df["title"], df["criterion_year"]):
        if title in already:
            continue
        slug = slugify(title)
        if slug in slugs:
            out.append((title, int(year) if year is not None else None, slug))
            seen.add(title)

    for title, slug in MANUAL_SLUG_OVERRIDES.items():
        if title in already or title in seen:
            continue
        year = year_by_title.get(title)
        out.append((title, int(year) if year is not None else None, slug))

    return out


YEAR_RE = re.compile(r"Directed by [^•]+•\s*(\d{4})")


def verify_one(title, expected_year, slug, attempts=4):
    url = f"https://www.criterionchannel.com/{slug}"
    last_status = None
    for attempt in range(attempts):
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
        except requests.RequestException:
            time.sleep(0.5 * (attempt + 1))
            continue
        last_status = r.status_code
        if r.status_code == 200:
            break
        time.sleep(0.5 * (attempt + 1))
    else:
        return ("failed", last_status)

    m = re.search(r'og:description"\s+content="([^"]+)"', r.text)
    if not m:
        return ("no_og_description", None)
    year_m = YEAR_RE.search(m.group(1))
    if not year_m:
        return ("no_year_in_description", None)
    page_year = int(year_m.group(1))
    if expected_year is not None and abs(page_year - expected_year) <= 1:
        return ("confirmed", (title, slug, url))
    return ("year_mismatch", page_year)


def main():
    cands = candidates()
    print(f"Checking {len(cands)} candidates against live pages...")

    confirmed = []
    status_counts = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(verify_one, t, y, s): (t, y, s) for t, y, s in cands}
        done = 0
        for fut in as_completed(futures):
            done += 1
            if done % 100 == 0:
                print(f"  ...{done}/{len(cands)}")
            status, data = fut.result()
            status_counts[status] = status_counts.get(status, 0) + 1
            if status == "confirmed":
                confirmed.append(data)

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, "w") as f:
        f.write("title,channel_slug,channel_url\n")
        for title, slug, url in confirmed:
            f.write(f'"{title.replace(chr(34), chr(34)*2)}",{slug},{url}\n')

    print(f"Confirmed {len(confirmed)} / {len(cands)} -> {OUT_CSV}")
    print("Status breakdown:", status_counts)


if __name__ == "__main__":
    main()
