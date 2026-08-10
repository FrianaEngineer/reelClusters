"""
Clustering integrity tests: reads the actual generated db/criterion_graph.duckdb,
output/clusters.csv, and output/clustering_run_manifest.json produced by the
2026-07-31 rebuild (src/cluster.py) and checks the Definition-of-Done
invariants from the design doc.
"""

import json
import sys
from collections import Counter
from pathlib import Path

import duckdb
import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

import cluster as cluster_mod  # noqa: E402

DB_PATH = REPO_ROOT / "db" / "criterion_graph.duckdb"
MANIFEST_PATH = REPO_ROOT / "output" / "clustering_run_manifest.json"


@pytest.fixture(scope="module")
def con():
    c = duckdb.connect(str(DB_PATH), read_only=True)
    yield c
    c.close()


def test_manifest_exists_and_records_reproducibility_pass():
    assert MANIFEST_PATH.exists()
    manifest = json.loads(MANIFEST_PATH.read_text())
    assert manifest["reproducibility_check"] == "PASS"
    assert manifest["random_state"] == 42


def test_manifest_input_hash_matches_current_canonical_csv():
    import hashlib
    manifest = json.loads(MANIFEST_PATH.read_text())
    canonical_csv = REPO_ROOT / "data" / "criterion_basic_info.csv"
    actual_hash = hashlib.sha256(canonical_csv.read_bytes()).hexdigest()
    assert manifest["input"]["sha256"] == actual_hash, (
        "criterion_basic_info.csv changed since the last clustering run -- "
        "cluster.py needs rerunning"
    )


def test_every_film_in_cluster_assignments_has_exactly_one_cluster(con):
    df = con.execute("""
        SELECT imdb_tconst, count(*) AS n
        FROM cluster_assignments GROUP BY imdb_tconst HAVING count(*) > 1
    """).df()
    assert len(df) == 0, f"films with >1 cluster assignment: {df['imdb_tconst'].tolist()}"


def test_no_assignment_references_a_nonexistent_film(con):
    df = con.execute("""
        SELECT ca.imdb_tconst
        FROM cluster_assignments ca
        LEFT JOIN criterion_basic_info cbi ON cbi.imdb_tconst = ca.imdb_tconst
        WHERE cbi.imdb_tconst IS NULL
    """).df()
    assert len(df) == 0


def test_every_cluster_has_nonempty_unique_display_name():
    names = list(cluster_mod.NAME_OVERRIDES.values()) + ["hiddenGems"]
    assert all(n and n.strip() for n in names)
    assert len(names) == len(set(names)), "duplicate cluster display name"


def test_no_old_pre_rebuild_cluster_ids_in_name_overrides():
    retired = {"anglophone_classic", "japanese_cinema", "bergman_scandinavian",
               "transatlantic_auteur_cinema", "youssef_chahine_egyptian"}
    current = set(cluster_mod.NAME_OVERRIDES.values())
    assert not (current & retired), "a retired pre-rebuild cluster ID is still in use"


def test_named_clusters_all_meet_the_minimum_size_floor(con):
    df = con.execute("""
        SELECT cluster_id, count(*) AS n FROM cluster_assignments
        WHERE cluster_id != 'hiddenGems' GROUP BY cluster_id
    """).df()
    assert len(df) == 11
    assert (df["n"] >= cluster_mod.MIN_NAMED_CLUSTER_SIZE).all()


def test_clusters_csv_output_reproducible_across_two_fresh_runs(con):
    G, partition_a = cluster_mod.run_clustering(con)
    _, partition_b = cluster_mod.run_clustering(con)
    assert partition_a == partition_b


def test_cluster_stats_and_manifest_counts_agree(con):
    manifest = json.loads(MANIFEST_PATH.read_text())
    df = con.execute("SELECT cluster_id, count(*) AS n FROM cluster_assignments GROUP BY cluster_id").df()
    actual_sizes = dict(zip(df["cluster_id"], df["n"]))
    assert actual_sizes == {k: v for k, v in manifest["output"]["cluster_sizes"].items()}
    assert sum(actual_sizes.values()) == manifest["output"]["total_films_assigned"]
