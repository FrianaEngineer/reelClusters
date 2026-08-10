"""
Build the co-occurrence graph and run Louvain community detection.
Writes cluster assignments back to the database as the cluster_assignments table.

Post-processing:
  1. Any Louvain community smaller than MIN_NAMED_CLUSTER_SIZE is merged into
     a single custom cluster called 'hiddenGems' rather than given its own
     page. Through the 2026-07 (pre Best Picture import) run this was a
     literal "exactly 2 films" rule. The 2026-07-31 Best Picture nominee
     import (~2,337 films, up from 1,746) produced a much longer tail of
     small communities (thirteen 2-9 film cliques versus the old handful of
     pairs) -- see src/cluster_naming_evidence.py's output. A flat "size < 2"
     rule would leave a swarm of 3-9-film pages with too little evidence to
     name confidently, so the floor was raised to 15, matching this
     project's own historical minimum for a named cluster (the old
     satyajit_ray_indian/soviet_cinema/youssef_chahine_egyptian clusters
     were 17-24 films -- see clusters/*.csv). This is a documented,
     evidence-based judgment call, not a tuned-to-preserve-old-groupings
     number: it was fixed before the post-import community sizes were
     inspected for naming.
  2. NAME_OVERRIDES renames Louvain's arbitrary numeric community IDs to the
     stable, human-readable slugs used site-wide (NAMED_CLUSTERS in
     build_site.py, CLUSTERS_TO_RENDER in cluster_graph_viz.py, COLOR_MAP in
     cluster_colors.py). Louvain's numbering isn't stable across reruns and
     carries no identity of its own -- this mapping is derived fresh from
     src/cluster_naming_evidence.py's per-community evidence report each
     time the underlying film set changes enough to reshuffle communities;
     it is NOT carried over from a previous run's overlap. See
     data/cluster_naming_report.md for the 2026-07-31 evidence and reasoning
     behind each name below. Any numeric ID left unmapped folds into
     hiddenGems, same as an undersized community.
"""

import duckdb
import networkx as nx
import community as community_louvain
import pandas as pd
from collections import Counter
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "db" / "criterion_graph.duckdb"

MIN_NAMED_CLUSTER_SIZE = 15


def build_graph(con: duckdb.DuckDBPyConnection) -> nx.Graph:
    edges = con.execute("""
        SELECT movie_a, movie_b, shared_actors
        FROM movie_edges
    """).df()

    G = nx.from_pandas_edgelist(
        edges,
        source="movie_a",
        target="movie_b",
        edge_attr="shared_actors",
    )
    return G


def run_louvain(G: nx.Graph, weight: str = "shared_actors", random_state: int = 42) -> dict:
    # Fixed seed: best_partition is otherwise non-deterministic run-to-run,
    # which would silently invalidate NAME_OVERRIDES below (it's keyed to
    # this specific partition's numeric community IDs).
    return community_louvain.best_partition(G, weight=weight, random_state=random_state)


def apply_hidden_gems(partition: dict, min_size: int = MIN_NAMED_CLUSTER_SIZE) -> dict:
    """Merge every Louvain community smaller than min_size into a single
    'hiddenGems' cluster -- see module docstring for why the floor is 15,
    not the old literal "== 2"."""
    cluster_sizes = Counter(partition.values())
    small_ids = {cid for cid, size in cluster_sizes.items() if size < min_size}

    merged = {}
    for tconst, cid in partition.items():
        merged[tconst] = "hiddenGems" if cid in small_ids else str(cid)
    return merged


# Derived from src/cluster_naming_evidence.py's per-community report on the
# 2026-07-31 post-Best-Picture-import graph (2,170 nodes, 18,799 edges),
# run_louvain's fixed random_state=42. Reasoning for each name is in
# data/cluster_naming_report.md. Valid only for THIS graph -- re-derive from
# a fresh evidence report any time the film set changes enough to reshuffle
# communities; do not reuse across runs.
NAME_OVERRIDES = {
    '0':  'modern_american_cinema',
    '4':  'european_art_cinema',
    '7':  'golden_age_hollywood_british',
    '13': 'classic_japanese_cinema',
    '3':  'japanese_new_wave_genre',
    '9':  'hong_kong_taiwan_cinema',
    '10': 'scandinavian_bergman_circle',
    '11': 'czech_new_wave',
    '8':  'silent_era_comedy',
    '21': 'soviet_cinema',
    '5':  'satyajit_ray_indian',
}


def apply_name_overrides(partition: dict) -> dict:
    """Rename Louvain's numeric community IDs to stable slugs; anything not
    in NAME_OVERRIDES (communities under MIN_NAMED_CLUSTER_SIZE, with no
    individually-justifiable identity) folds into hiddenGems alongside the
    undersized communities apply_hidden_gems already merged."""
    return {
        tconst: NAME_OVERRIDES.get(cid, "hiddenGems") if cid != "hiddenGems" else cid
        for tconst, cid in partition.items()
    }


def save_clusters(con: duckdb.DuckDBPyConnection, partition: dict) -> None:
    df = pd.DataFrame(list(partition.items()), columns=["imdb_tconst", "cluster_id"])
    con.execute("CREATE OR REPLACE TABLE cluster_assignments AS SELECT * FROM df")

    hidden = df[df["cluster_id"] == "hiddenGems"]
    named  = df[df["cluster_id"] != "hiddenGems"]
    print(f"  hiddenGems:          {len(hidden):,} films (merged small/uncategorized communities)")
    print(f"  Named clusters:      {named['cluster_id'].nunique()}")
    print(f"  Total nodes saved:   {len(df):,}")


def run_clustering(con: duckdb.DuckDBPyConnection) -> tuple:
    G = build_graph(con)
    partition = run_louvain(G)
    partition = apply_hidden_gems(partition)
    partition = apply_name_overrides(partition)
    return G, partition


if __name__ == "__main__":
    import hashlib
    import json
    import sys
    from datetime import datetime, timezone

    con = duckdb.connect(str(DB_PATH))
    G, partition = run_clustering(con)
    print(f"Graph: {G.number_of_nodes():,} nodes, {G.number_of_edges():,} edges\n")

    # Reproducibility check: same seed on the same graph must give the same
    # assignment, since NAME_OVERRIDES is keyed to specific numeric community
    # IDs from one particular run.
    _, partition_rerun = run_clustering(con)
    reproducible = partition == partition_rerun
    print(f"Reproducibility check (rerun with same seed): {'PASS' if reproducible else 'FAIL'}")
    if not reproducible:
        sys.exit("Louvain assignment was not reproducible across two runs with the same seed -- aborting.")

    save_clusters(con, partition)

    con.execute("""
        COPY (
            SELECT
                ca.cluster_id,
                count(*) OVER (PARTITION BY ca.cluster_id) AS cluster_size,
                cbi.title,
                cbi.criterion_director,
                cbi.criterion_year,
                cbi.imdb_runtime_minutes
            FROM cluster_assignments ca
            JOIN criterion_basic_info cbi ON cbi.imdb_tconst = ca.imdb_tconst
            ORDER BY
                CASE WHEN ca.cluster_id = 'hiddenGems' THEN 1 ELSE 0 END,
                cluster_size DESC,
                ca.cluster_id,
                cbi.criterion_year
        ) TO ? (HEADER, DELIMITER ',')
    """, [str(Path(__file__).parent.parent / "output" / "clusters.csv")])
    print(f"\nClusters written to output/clusters.csv")

    # --- Run manifest -----------------------------------------------------
    import community as community_louvain_pkg
    import networkx

    canonical_csv = Path(__file__).parent.parent / "data" / "criterion_basic_info.csv"
    input_hash = hashlib.sha256(canonical_csv.read_bytes()).hexdigest()
    cluster_counts = Counter(partition.values())

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "algorithm": "Louvain (python-louvain best_partition) on shared-actor graph, weighted by shared_actors",
        "random_state": 42,
        "min_named_cluster_size": MIN_NAMED_CLUSTER_SIZE,
        "reproducibility_check": "PASS" if reproducible else "FAIL",
        "dependency_versions": {
            "python": sys.version.split()[0],
            "networkx": networkx.__version__,
            "python-louvain": getattr(community_louvain_pkg, "__version__", "unknown"),
            "duckdb": duckdb.__version__,
            "pandas": pd.__version__,
        },
        "input": {
            "canonical_csv": str(canonical_csv.relative_to(Path(__file__).parent.parent)),
            "sha256": input_hash,
            "graph_nodes": G.number_of_nodes(),
            "graph_edges": G.number_of_edges(),
        },
        "output": {
            "total_films_assigned": len(partition),
            "named_clusters": len([c for c in cluster_counts if c != "hiddenGems"]),
            "hidden_gems_films": cluster_counts.get("hiddenGems", 0),
            "cluster_sizes": dict(sorted(cluster_counts.items(), key=lambda kv: -kv[1])),
        },
        "name_overrides": NAME_OVERRIDES,
    }
    manifest_path = Path(__file__).parent.parent / "output" / "clustering_run_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"Run manifest written to {manifest_path}")
    con.close()
