"""
Phase 3: deduplicate the normalized Best Picture nominee list against the
existing canonical film dataset (data/criterion_basic_info.csv) and merge in
whatever is genuinely new.

Identity hierarchy (see design doc):
  1. Exact IMDb ID match (imdb_tconst == Const) -- authoritative.
  2. (no second stable ID shared by both sources -- skipped)
  3. High-confidence metadata match for an existing record that lacks a
     stable ID -- inapplicable here, every criterion_basic_info row already
     carries imdb_tconst, so this stage always finds zero candidates. Kept
     in for completeness/tests rather than silently assumed away.
  4. Ambiguous candidate: normalized-title + same-or-adjacent-year match
     against an existing film with a DIFFERENT tconst. Not auto-merged --
     written to the ambiguous-match review file for manual resolution.

criterion_basic_info.csv legitimately contains multiple rows sharing one
imdb_tconst for "virtual constituent" Criterion releases (multi-episode /
multi-part / alternate-version spine entries that IMDb records as a single
title -- see git history "Infer collection-level director for IMDb matching
of virtual constituents"). That is existing, intentional structure, not a
duplicate-data bug, and this script does not collapse it. A "canonical
unique film" for the purposes of this project's dedup/count requirements
means one distinct imdb_tconst -- which is exactly the identity the
clustering graph, cluster_assignments table, and films-data.js already key
on (build_recommendation_data.py already reduces to one row per tconst when
it needs a single display row).

Outputs:
  data/criterion_basic_info.csv           -- updated in place (see backup below)
  db/backup/criterion_basic_info_pre_best_picture_import.csv  -- pre-change snapshot
  data/dedup_audit.csv                    -- one row per incoming film, per spec
  data/ambiguous_matches.csv              -- empty unless stage 4 fires

    python3 merge_best_picture_films.py
"""

import csv
import re
import unicodedata
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
CANONICAL_CSV = REPO_ROOT / "data" / "criterion_basic_info.csv"
BACKUP_DIR = REPO_ROOT / "db" / "backup"
BACKUP_CSV = BACKUP_DIR / "criterion_basic_info_pre_best_picture_import.csv"
NORMALIZED_CSV = REPO_ROOT / "data" / "raw" / "imdb_best_picture_nominees_normalized.csv"
ROW_DISPOSITIONS_CSV = REPO_ROOT / "data" / "raw" / "imdb_best_picture_nominees_row_dispositions.csv"
DEDUP_AUDIT_CSV = REPO_ROOT / "data" / "dedup_audit.csv"
AMBIGUOUS_CSV = REPO_ROOT / "data" / "ambiguous_matches.csv"

CANONICAL_FIELDNAMES = [
    "title", "criterion_director", "criterion_country", "criterion_year",
    "imdb_tconst", "imdb_title_type", "imdb_year", "imdb_runtime_minutes",
    "imdb_director_nconst", "imdb_writer_nconst", "match_method",
    "confidence_score", "title_similarity", "director_similarity", "year_similarity",
    # New provenance/metadata columns (blank on all pre-existing Criterion rows):
    "source", "source_position", "source_original_title", "source_release_date",
    "imdb_rating", "num_votes", "also_in_best_picture_csv",
]


def normalize_title(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def format_directors(names):
    """Match criterion_director's existing 'A and B' / 'A, B, and C' style."""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return ", ".join(names[:-1]) + f", and {names[-1]}"


def load_canonical():
    with CANONICAL_CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        for col in CANONICAL_FIELDNAMES:
            row.setdefault(col, "")
    return rows


def load_normalized_incoming():
    with NORMALIZED_CSV.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main():
    canonical_rows = load_canonical()
    incoming = load_normalized_incoming()

    with ROW_DISPOSITIONS_CSV.open(newline="", encoding="utf-8") as f:
        pre_dedup_dispositions = list(csv.DictReader(f))
    # These become audit rows verbatim for rows that never reached matching
    # (duplicate_in_csv / rejected_invalid) -- "ok" rows are superseded below
    # by the richer matched/new/ambiguous entries for that same position.
    carry_over_audit_rows = [
        {
            "source_position": d["source_position"], "imdb_id": d["imdb_id"], "title": d["title"],
            "year": d["year"], "decision": d["decision"], "matched_canonical_film_id": "",
            "match_rule": "", "confidence": "", "metadata_conflicts": d["detail"],
            "final_canonical_film_id": "",
        }
        for d in pre_dedup_dispositions if d["decision"] != "ok"
    ]

    existing_by_tconst = {}
    for row in canonical_rows:
        existing_by_tconst.setdefault(row["imdb_tconst"], []).append(row)

    # Stage-3 candidate pool: existing records lacking a stable ID. Always
    # empty in this dataset -- every row has imdb_tconst -- but computed
    # for real rather than hardcoded to nothing.
    existing_without_tconst = [r for r in canonical_rows if not r["imdb_tconst"].strip()]
    assert existing_without_tconst == [], (
        "found existing canonical rows without imdb_tconst; stage-3 metadata "
        "matching needs implementing for real, not just asserted empty"
    )

    # Stage-4 ambiguous-candidate pool: normalized title -> [(tconst, year), ...]
    title_index = {}
    for row in canonical_rows:
        key = normalize_title(row["title"])
        year = row["criterion_year"].strip()
        title_index.setdefault(key, []).append((row["imdb_tconst"], year))

    audit_rows = []
    ambiguous_rows = []
    new_canonical_rows = []
    matched_count = 0
    new_count = 0

    for rec in incoming:
        tconst = rec["imdb_tconst"]
        title = rec["title"]
        year = rec["year"]
        position = rec["source_position"]

        existing_matches = existing_by_tconst.get(tconst)
        if existing_matches:
            matched_count += 1
            conflicts = []
            for ex in existing_matches:
                if ex["criterion_year"].strip() and year and ex["criterion_year"].strip() != year:
                    conflicts.append(
                        f"year: existing={ex['criterion_year']!r} incoming={year!r} (existing kept)"
                    )
                if normalize_title(ex["title"]) != normalize_title(title):
                    conflicts.append(
                        f"title: existing={ex['title']!r} incoming={title!r} (existing kept, likely alt title/version)"
                    )
                # Mark provenance on every existing row sharing this tconst.
                ex["also_in_best_picture_csv"] = position

            audit_rows.append({
                "source_position": position, "imdb_id": tconst, "title": title, "year": year,
                "decision": "matched_existing", "matched_canonical_film_id": tconst,
                "match_rule": "exact_imdb_id", "confidence": "high",
                "metadata_conflicts": " | ".join(conflicts),
                "final_canonical_film_id": tconst,
            })
            continue

        # Stage 4: same-normalized-title match against a DIFFERENT tconst.
        key = normalize_title(title)
        candidates = [c for c in title_index.get(key, []) if c[0] != tconst]
        plausible = [
            c for c in candidates
            if not (c[1] and year and abs(int(c[1]) - int(year)) > 1)
        ]
        if plausible:
            ambiguous_rows.append({
                "source_position": position, "imdb_id": tconst, "title": title, "year": year,
                "candidate_existing_tconsts": ";".join(c[0] for c in plausible),
                "reason": "normalized title matches an existing canonical film under a different IMDb ID",
            })
            audit_rows.append({
                "source_position": position, "imdb_id": tconst, "title": title, "year": year,
                "decision": "ambiguous", "matched_canonical_film_id": "",
                "match_rule": "title_year_fuzzy", "confidence": "low",
                "metadata_conflicts": f"candidate tconsts: {';'.join(c[0] for c in plausible)}",
                "final_canonical_film_id": "",
            })
            continue

        # Genuinely new film.
        new_count += 1
        director_names = rec["directors"].split("; ") if rec["directors"] else []
        new_row = {col: "" for col in CANONICAL_FIELDNAMES}
        new_row.update({
            "title": title,
            "criterion_director": format_directors(director_names) if director_names else "",
            "criterion_country": "",
            "criterion_year": year or "",
            "imdb_tconst": tconst,
            "imdb_title_type": "movie",
            "imdb_year": year or "",
            "imdb_runtime_minutes": rec["runtime_minutes"] or "",
            "imdb_director_nconst": "",
            "imdb_writer_nconst": "",
            "match_method": "",
            "confidence_score": "",
            "title_similarity": "",
            "director_similarity": "",
            "year_similarity": "",
            "source": "best_picture_nominee",
            "source_position": position,
            "source_original_title": rec["original_title"],
            "source_release_date": rec["release_date"],
            "imdb_rating": rec["imdb_rating"] or "",
            "num_votes": rec["num_votes"] or "",
            "also_in_best_picture_csv": position,
        })
        new_canonical_rows.append(new_row)
        # Index the new row too, so a later duplicate-titled incoming row
        # (shouldn't exist post within-CSV dedup, but defensive) is caught.
        title_index.setdefault(key, []).append((tconst, year))

        audit_rows.append({
            "source_position": position, "imdb_id": tconst, "title": title, "year": year,
            "decision": "new", "matched_canonical_film_id": "",
            "match_rule": "none", "confidence": "high",
            "metadata_conflicts": "",
            "final_canonical_film_id": tconst,
        })

    # Tag pre-existing rows that were never mentioned in the incoming CSV
    # with an explicit blank (already the default) -- no-op, just documents intent.
    for row in canonical_rows:
        row.setdefault("also_in_best_picture_csv", "")

    # --- Write outputs --------------------------------------------------
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    if not BACKUP_CSV.exists():
        with CANONICAL_CSV.open("rb") as src, BACKUP_CSV.open("wb") as dst:
            dst.write(src.read())

    all_rows = canonical_rows + new_canonical_rows
    with CANONICAL_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CANONICAL_FIELDNAMES)
        writer.writeheader()
        writer.writerows(all_rows)

    all_audit_rows = carry_over_audit_rows + audit_rows
    all_audit_rows.sort(key=lambda r: int(r["source_position"]))
    with DEDUP_AUDIT_CSV.open("w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "source_position", "imdb_id", "title", "year", "decision",
            "matched_canonical_film_id", "match_rule", "confidence",
            "metadata_conflicts", "final_canonical_film_id",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_audit_rows)

    with AMBIGUOUS_CSV.open("w", newline="", encoding="utf-8") as f:
        fieldnames = ["source_position", "imdb_id", "title", "year", "candidate_existing_tconsts", "reason"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(ambiguous_rows)

    existing_unique = len(existing_by_tconst)
    final_unique = len(set(existing_by_tconst.keys()) | {r["imdb_tconst"] for r in new_canonical_rows})

    print(f"Existing unique films (pre-merge):     {existing_unique:,}")
    print(f"Incoming unique films (post CSV-dedup): {len(incoming):,}")
    print(f"  matched_existing: {matched_count:,}")
    print(f"  new:              {new_count:,}")
    print(f"  ambiguous:        {len(ambiguous_rows):,}")
    print(f"Final unique films (post-merge):       {final_unique:,}")
    print(f"  equation check: {existing_unique} + {new_count} = {existing_unique + new_count} "
          f"({'OK' if existing_unique + new_count == final_unique else 'MISMATCH'})")
    print(f"\nWrote {CANONICAL_CSV} ({len(all_rows):,} rows)")
    print(f"Backup at {BACKUP_CSV}")
    print(f"Wrote {DEDUP_AUDIT_CSV}")
    print(f"Wrote {AMBIGUOUS_CSV} ({len(ambiguous_rows)} rows)")


if __name__ == "__main__":
    main()
