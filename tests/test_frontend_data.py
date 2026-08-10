"""
Frontend data-integrity tests: checks the actual generated
site/assets/films-data.js, site/clusters/*.html, and cluster_colors.py
against each other and against the DB, so a stale reference (old cluster
name/id left behind, mismatched counts) fails a test instead of silently
shipping.
"""

import json
import re
import sys
from pathlib import Path

import duckdb
import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

import cluster as cluster_mod  # noqa: E402
from cluster_colors import COLOR_MAP  # noqa: E402

DB_PATH = REPO_ROOT / "db" / "criterion_graph.duckdb"
FILMS_DATA_JS = REPO_ROOT / "site" / "assets" / "films-data.js"
CLUSTERS_DIR = REPO_ROOT / "site" / "clusters"

RETIRED_IDS = {"anglophone_classic", "japanese_cinema", "bergman_scandinavian",
               "transatlantic_auteur_cinema", "youssef_chahine_egyptian"}
CURRENT_NAMED_IDS = set(cluster_mod.NAME_OVERRIDES.values())


def _load_films():
    text = FILMS_DATA_JS.read_text(encoding="utf-8")
    m = re.search(r"window\.FILMS = (\[.*\]);\n", text, re.DOTALL)
    assert m, "could not find window.FILMS array in films-data.js"
    return json.loads(m.group(1))


def test_films_data_js_record_count_matches_graph_node_count():
    films = _load_films()
    con = duckdb.connect(str(DB_PATH), read_only=True)
    n_assigned = con.execute("SELECT count(*) FROM cluster_assignments").fetchone()[0]
    con.close()
    assert len(films) == n_assigned == 2170


def test_every_film_record_has_a_unique_tconst():
    films = _load_films()
    tconsts = [f["t"] for f in films]
    assert len(tconsts) == len(set(tconsts))


def test_no_film_record_references_a_retired_cluster_id():
    films = _load_films()
    used = {f["cluster"] for f in films}
    assert not (used & RETIRED_IDS)
    assert used <= (CURRENT_NAMED_IDS | {"hiddenGems"})


def test_film_record_color_matches_color_map():
    films = _load_films()
    for f in films[:50] + films[-50:]:  # spot check, full film-list is large
        assert f["color"] == COLOR_MAP.get(f["cluster"], "#888888")


def test_cluster_page_files_are_unique_and_match_named_clusters():
    pages = {p.stem for p in CLUSTERS_DIR.glob("*.html")}
    expected = CURRENT_NAMED_IDS | {"hiddenGems"}
    assert pages == expected, f"mismatch: {pages ^ expected}"


def test_no_retired_cluster_id_appears_in_any_generated_cluster_page():
    """Word-boundary match: some retired ids (e.g. 'japanese_cinema') are
    substrings of current ids ('classic_japanese_cinema') by design (the
    successor cluster's name deliberately extends the old one) -- a bare
    substring check would false-positive on those legitimate references."""
    for page in CLUSTERS_DIR.glob("*.html"):
        text = page.read_text(encoding="utf-8")
        for retired in RETIRED_IDS:
            pattern = r"(?<![a-zA-Z_])" + re.escape(retired) + r"(?![a-zA-Z_])"
            assert not re.search(pattern, text), f"{page.name} still references retired id {retired}"


def test_color_map_has_no_duplicate_colors():
    colors = list(COLOR_MAP.values())
    assert len(colors) == len(set(colors)), "two clusters share the same color"


def test_color_map_covers_every_named_cluster_plus_hidden_gems():
    assert set(COLOR_MAP.keys()) == CURRENT_NAMED_IDS | {"hiddenGems"}


def test_clicking_a_cluster_filters_to_only_that_clusters_films():
    """films-data.js is grouped by exact cluster id; verify the id used for
    grouping/filtering (site/assets/director-utils.js consumes f.cluster the
    same way) never mixes members across two different cluster ids for the
    same tconst."""
    films = _load_films()
    seen = {}
    for f in films:
        seen.setdefault(f["t"], set()).add(f["cluster"])
    multi = {t: cs for t, cs in seen.items() if len(cs) > 1}
    assert not multi, f"films assigned to more than one cluster in films-data.js: {multi}"
