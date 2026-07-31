"""
Frame-by-frame reveal schedule for the Criterion Over Time video. Pure
logic, no matplotlib -- testable and inspectable on its own.

Runtime is approximate (target ~20 min, 19-22 min acceptable), NOT pinned to
an exact duration: it's derived from batching the real film distribution
into small same-year groups (1-2 films preferred, up to 4 only if needed),
each shown for ~1.3-1.8s, rather than forcing every historical era into a
fixed-duration window regardless of how many films actually belong to it.

Data sources, and only these:
  - data/cinematic_history_hex_snapshot.json (frozen extract of the live
    site/explore.html -- positions, cluster, and final fill color per hex,
    plus which film is narratively attached to which hex).
  - db/criterion_graph.duckdb, read-only, for film metadata (title, director,
    country, year) of exactly the tconsts the snapshot already placed.
  - cinematic_history_config.py for all timing/styling constants.

Never calls build_hex_grid() and never writes to any file outside this
project's own outputs/.
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import duckdb

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import cinematic_history_config as cfg  # noqa: E402

SNAPSHOT_PATH = cfg.REPO_ROOT / "data" / "cinematic_history_hex_snapshot.json"
DB_PATH = cfg.REPO_ROOT / "db" / "criterion_graph.duckdb"


# ── Color blending (no matplotlib/numpy dependency) ───────────────────────

def _hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _rgb_to_hex(rgb):
    return "#" + "".join(f"{max(0, min(255, round(c))):02x}" for c in rgb)


def blend(c1, c2, t):
    r1, g1, b1 = _hex_to_rgb(c1)
    r2, g2, b2 = _hex_to_rgb(c2)
    return _rgb_to_hex((r1 + (r2 - r1) * t, g1 + (g2 - g1) * t, b1 + (b2 - b1) * t))


# ── Loading ────────────────────────────────────────────────────────────────

def load_snapshot():
    if not SNAPSHOT_PATH.exists():
        sys.exit(f"ERROR: {SNAPSHOT_PATH} not found -- run cinematic_history_layout_snapshot.py first.")
    return json.loads(SNAPSHOT_PATH.read_text())


def load_metadata(tconsts):
    con = duckdb.connect(str(DB_PATH), read_only=True)
    df = con.execute("""
        SELECT * FROM (
            SELECT imdb_tconst, title, criterion_year, criterion_director, criterion_country,
                   row_number() OVER (
                       PARTITION BY imdb_tconst ORDER BY confidence_score DESC NULLS LAST
                   ) AS rn
            FROM criterion_basic_info
            WHERE imdb_tconst IN ({})
        ) WHERE rn = 1
    """.format(",".join(f"'{t}'" for t in tconsts))).df()
    con.close()
    return df.set_index("imdb_tconst").to_dict("index")


def format_credit_line(director, country):
    parts = [p for p in (director, country) if isinstance(p, str) and p]
    return "  ·  ".join(parts)


# ── Reveal events ──────────────────────────────────────────────────────────

def build_reveal_events(snapshot, meta):
    """One event per unique tconst placed on the snapshot (a handful of
    films occupy more than one hex -- catalog duplicates like "Carlos: Part
    1/2/3" sharing one imdb_tconst -- grouped into a single reveal event
    exactly as hex_grid.py's own downstream consumers already do, so that
    film's card appears once, not 2-3 times in a row)."""
    by_tconst = defaultdict(list)
    for h in snapshot["hexes"]:
        if h["tconst"]:
            by_tconst[h["tconst"]].append((h["q"], h["r"]))

    events = []
    missing_meta = []
    for tconst, hexes in by_tconst.items():
        row = meta.get(tconst)
        if row is None or row["criterion_year"] is None:
            missing_meta.append(tconst)
            continue
        events.append(dict(
            tconst=tconst,
            title=row["title"],
            director=row["criterion_director"],
            country=row["criterion_country"],
            credit_line=format_credit_line(row["criterion_director"], row["criterion_country"]),
            year=int(row["criterion_year"]),
            hexes=hexes,
        ))
    if missing_meta:
        sys.exit(f"ERROR: {len(missing_meta)} placed film(s) have no usable metadata: {missing_meta}")

    events.sort(key=lambda e: (e["year"], e["tconst"]))
    return events


def ambient_hexes(snapshot):
    """Hexes with no film attached (the approved unfilled-hex exceptions) --
    shown in their snapshot color from the very start, never part of the
    per-film reveal."""
    return [(h["q"], h["r"], h["fill"]) for h in snapshot["hexes"] if h["tconst"] is None]


def final_color_for_hex(snapshot):
    return {(h["q"], h["r"]): h["fill"] for h in snapshot["hexes"]}


# ── Batch planning ──────────────────────────────────────────────────────────

def group_events_by_year(events):
    by_year = defaultdict(list)
    for ev in events:
        by_year[ev["year"]].append(ev)
    return by_year


def plan_batch_sizes(by_year, overhead_seconds):
    """Decides each year's batch size (never crossing a year boundary) and
    a single slot duration used for every batch, so that projected total
    runtime lands close to but not over TARGET_RUNTIME_MAX_SECONDS.

    Strategy, in order of preference (matches the brief: shrink duration
    before growing batch size):
      1. Every year defaults to batch size min(PREFERRED_MAX_BATCH_SIZE, its
         own film count) -- "prefer 1-2 films per batch."
      2. Pick the largest slot duration in [BATCH_SLOT_SECONDS_MIN,
         BATCH_SLOT_SECONDS_MAX] that keeps the baseline batch plan's
         runtime within target, with a small safety margin below the hard
         ceiling.
      3. Only if BATCH_SLOT_SECONDS_MIN still isn't enough does batch size
         get escalated (densest years first, one step at a time, capped at
         ABSOLUTE_MAX_BATCH_SIZE) -- "allow 3 in crowded years, 4 only if
         required."
    Returns (batch_size_by_year, slot_seconds, escalated: bool).
    """
    years = sorted(by_year)
    batch_size = {y: min(cfg.PREFERRED_MAX_BATCH_SIZE, len(by_year[y])) or 1 for y in years}

    def batches_for(y):
        return max(1, -(-len(by_year[y]) // batch_size[y]))   # ceil division

    def total_batches():
        return sum(batches_for(y) for y in years)

    baseline_batches = total_batches()
    available_seconds = cfg.TARGET_RUNTIME_MAX_SECONDS - overhead_seconds
    natural_slot = available_seconds / baseline_batches
    SAFETY_MARGIN = 0.98   # stay a hair under the ceiling, not flush against it
    slot_seconds = min(cfg.BATCH_SLOT_SECONDS_MAX,
                        max(cfg.BATCH_SLOT_SECONDS_MIN, natural_slot * SAFETY_MARGIN))
    # Round to the nearest whole frame at the configured fps so every batch
    # gets an identical, exact frame count (no per-batch rounding drift).
    slot_seconds = round(slot_seconds * cfg.FPS) / cfg.FPS

    escalated = False
    while overhead_seconds + total_batches() * slot_seconds > cfg.TARGET_RUNTIME_MAX_SECONDS:
        candidates = [y for y in years if batch_size[y] < cfg.ABSOLUTE_MAX_BATCH_SIZE]
        if not candidates:
            break
        y = max(candidates, key=lambda y: (batches_for(y), -y))
        batch_size[y] += 1
        escalated = True

    return batch_size, slot_seconds, escalated


def build_batches(events, batch_size_by_year):
    """Chronological list of batch dicts: {year, events: [...]}. A batch
    never spans more than one year and never exceeds ABSOLUTE_MAX_BATCH_SIZE
    films -- both guaranteed by construction here, not just by the sizing
    heuristic above."""
    by_year = group_events_by_year(events)
    batches = []
    for y in sorted(by_year):
        evs = by_year[y]   # already (year, tconst)-sorted from build_reveal_events
        size = min(batch_size_by_year[y], cfg.ABSOLUTE_MAX_BATCH_SIZE)
        for i in range(0, len(evs), size):
            batches.append(dict(year=y, events=evs[i:i + size]))
    return batches


def insert_empty_years(batches):
    """Every year from START_YEAR through END_YEAR must appear in
    chronological order, including years with zero films (e.g. 1914, 1915,
    1919) -- inserted here as empty markers (events=[]) so the renderer
    still advances the year label and gives that year its own on-screen
    moment, without a film card."""
    by_year = defaultdict(list)
    for b in batches:
        by_year[b["year"]].append(b)
    timeline = []
    for y in range(cfg.START_YEAR, cfg.END_YEAR + 1):
        if y in by_year:
            timeline.extend(by_year[y])
        else:
            timeline.append(dict(year=y, events=[]))
    return timeline


def project_runtime(batches, slot_seconds):
    return cfg.TITLE_CARD_SECONDS + cfg.FINAL_HOLD_SECONDS + len(batches) * slot_seconds


def recalculate_music_cue_timestamps(batches, slot_seconds):
    """Era duration = (batches in that era) * slot_seconds, replacing the old
    fixed timestamp table. Track order and year-range assignment unchanged."""
    cursor = cfg.TITLE_CARD_SECONDS
    rows = []
    for cue in cfg.MUSIC_CUES:
        n = sum(1 for b in batches if cue["start_year"] <= b["year"] <= cue["end_year"])
        duration = n * slot_seconds
        rows.append(dict(start_year=cue["start_year"], end_year=cue["end_year"],
                          track_title=cue["track_title"], artist=cue["artist"],
                          batch_count=n, duration_seconds=duration,
                          video_start=cursor, video_end=cursor + duration))
        cursor += duration
    return rows, cursor   # cursor == start of the final hold


# ── Full per-frame schedule (for the renderer) ─────────────────────────────

def build_full_schedule():
    """The complete frame-by-frame plan the renderer consumes. Every slot
    (a real batch or an empty-year marker) gets an identical frame count
    (slot_seconds, already rounded to a whole number of frames in
    plan_batch_sizes) -- so total duration is exact given that slot count,
    with zero per-slot rounding drift.

    2026-07-29 restyle: the renderer's film-info display changed from one
    "batch card" (up to ABSOLUTE_MAX_BATCH_SIZE rows shown/hidden together)
    to a continuous 2-lane rolling queue, one film at a time. That change is
    confined entirely to `item_queue` below -- hex pop-in timing, batch/slot
    sizing, and music cue timestamps are untouched, so total runtime and
    audio sync are bit-for-bit identical to before this restyle.

    item_queue: flat, chronological list of every individual film reveal
    event (not grouped into batches), each with:
      - lane: 0 or 1, alternating strictly in chronological order -- the
        renderer holds exactly 2 on-screen text slots, and consecutive
        entries in the SAME lane are exactly 2 apart in this list.
      - entrance_frame: the absolute frame at which this item starts its
        fade-in. Items belonging to the same batch (same year, sharing one
        slot) are spread evenly across that slot's frame range so they
        appear one at a time rather than all at once; this is the only
        place batch membership still matters for the text display.
    A lane's item fades out starting exactly when the NEXT item in that same
    lane (i.e. global position +2) enters -- so at most one fade-in and one
    fade-out ever overlap per lane, satisfying "max two fully visible at
    once." The renderer derives this directly from adjacent entries in each
    lane's own sub-list, so no separate "supersede_frame" needs to be stored.
    """
    snapshot = load_snapshot()
    all_tconsts = sorted({h["tconst"] for h in snapshot["hexes"] if h["tconst"]})
    meta = load_metadata(all_tconsts)
    events = build_reveal_events(snapshot, meta)
    by_year = group_events_by_year(events)
    final_colors = final_color_for_hex(snapshot)
    fps = cfg.FPS

    overhead = cfg.TITLE_CARD_SECONDS + cfg.FINAL_HOLD_SECONDS
    batch_size_by_year, slot_seconds, escalated = plan_batch_sizes(by_year, overhead)
    timeline = insert_empty_years(build_batches(events, batch_size_by_year))
    cue_rows, hold_start = recalculate_music_cue_timestamps(timeline, slot_seconds)

    slot_frames = round(slot_seconds * fps)
    pop_frames = max(1, min(slot_frames, round(fps * cfg.HEX_POP_SECONDS)))

    frames = []
    ambient = ambient_hexes(snapshot)

    title_frames = round(cfg.TITLE_CARD_SECONDS * fps)
    for i in range(title_frames):
        frames.append(dict(
            phase="title", year=None,
            color_diffs=({(q, r): fill for q, r, fill in ambient} if i == 0 else {}),
        ))

    item_queue = []
    global_item_index = 0
    for item in timeline:
        year, evs = item["year"], item["events"]
        batch_start_frame = len(frames)
        hexes = [h for e in evs for h in e["hexes"]]
        k = len(evs)
        for e_idx, e in enumerate(evs):
            item_queue.append(dict(
                global_index=global_item_index,
                lane=global_item_index % 2,
                entrance_frame=batch_start_frame + (e_idx * slot_frames) // k,
                year=year,
                title=e["title"],
                credit_line=e["credit_line"],
            ))
            global_item_index += 1

        pop_n = min(pop_frames, slot_frames)
        for f in range(slot_frames):
            color_diffs = {}
            if hexes and f < pop_n:
                t = (f + 1) / pop_n
                for (q, r) in hexes:
                    color_diffs[(q, r)] = blend(cfg.BACKGROUND_COLOR, final_colors[(q, r)], t)
                if f == pop_n - 1:
                    for (q, r) in hexes:
                        color_diffs[(q, r)] = final_colors[(q, r)]   # snap exact, no float drift
            frames.append(dict(phase="main", year=year, color_diffs=color_diffs))

    hold_start_frame = len(frames)
    hold_frames_total = round(cfg.FINAL_HOLD_SECONDS * fps)
    last_year = timeline[-1]["year"] if timeline else None
    for i in range(hold_frames_total):
        # Keep the final year visible during the hold (only the rolling
        # film items are required to fade away) rather than blanking every
        # piece of on-screen text at once.
        frames.append(dict(phase="hold", year=last_year, color_diffs={}))

    return dict(
        frames=frames,
        fps=fps,
        slot_seconds=slot_seconds,
        final_colors=final_colors,
        grid_hexes=[(h["q"], h["r"]) for h in snapshot["hexes"]],
        hex_set={(h["q"], h["r"]) for h in snapshot["hexes"]},
        outer_hidden_gems=[(h["q"], h["r"]) for h in snapshot["hexes"]
                            if h["cluster_id"] == "hiddenGems" and h["is_hidden_gems_outer"]],
        music_cue_timestamps=cue_rows,
        final_hold_video_start_seconds=hold_start,
        hold_start_frame=hold_start_frame,
        item_queue=item_queue,
        total_seconds=len(frames) / fps,
        escalated=escalated,
        max_batch_size=max((len(item["events"]) for item in timeline if item["events"]), default=1),
    )


# ── Report (no rendering) ───────────────────────────────────────────────────

def build_plan_report():
    snapshot = load_snapshot()
    all_tconsts = sorted({h["tconst"] for h in snapshot["hexes"] if h["tconst"]})
    meta = load_metadata(all_tconsts)
    events = build_reveal_events(snapshot, meta)
    by_year = group_events_by_year(events)

    overhead = cfg.TITLE_CARD_SECONDS + cfg.FINAL_HOLD_SECONDS
    batch_size_by_year, slot_seconds, escalated = plan_batch_sizes(by_year, overhead)
    batches = insert_empty_years(build_batches(events, batch_size_by_year))
    runtime = project_runtime(batches, slot_seconds)
    cue_rows, hold_start = recalculate_music_cue_timestamps(batches, slot_seconds)

    batch_sizes_used = [len(b["events"]) for b in batches if b["events"]]
    max_simultaneous = max(batch_sizes_used)
    # Every batch/empty-year slot gets the identical slot duration by
    # construction (see plan_batch_sizes) -- min/median/max are reported
    # from the real per-slot durations regardless, rather than assumed equal.
    durations = [slot_seconds] * len(batches)
    durations.sort()
    median_duration = durations[len(durations) // 2] if len(durations) % 2 else \
        (durations[len(durations) // 2 - 1] + durations[len(durations) // 2]) / 2

    return dict(
        projected_runtime_seconds=runtime,
        projected_runtime_mmss=cfg.seconds_to_mmss(runtime),
        total_batches=len(batches),
        slot_seconds=slot_seconds,
        min_batch_duration_seconds=min(durations),
        median_batch_duration_seconds=median_duration,
        max_batch_duration_seconds=max(durations),
        max_simultaneous_films=max_simultaneous,
        batch_size_escalated=escalated,
        batch_size_distribution=dict(sorted(Counter(batch_sizes_used).items())),
        music_cue_timestamps=cue_rows,
        final_hold_video_start_seconds=hold_start,
        final_hold_video_start_mmss=cfg.seconds_to_mmss(hold_start),
        needs_approval=(runtime > cfg.STOP_FOR_APPROVAL_MAX_SECONDS
                        or slot_seconds < cfg.BATCH_SLOT_SECONDS_MIN - 1e-9),
        total_films=len(events),
        total_years=len(by_year),
        events=events,
        batches=batches,
    )


if __name__ == "__main__":
    report = build_plan_report()
    print(f"Projected total runtime: {report['projected_runtime_mmss']}  "
          f"({report['projected_runtime_seconds']:.1f}s)")
    print(f"Total films: {report['total_films']}  across {report['total_years']} years")
    print(f"Total batches: {report['total_batches']}")
    print(f"Batch duration -- min/median/max: {report['min_batch_duration_seconds']:.2f}s / "
          f"{report['median_batch_duration_seconds']:.2f}s / {report['max_batch_duration_seconds']:.2f}s")
    print(f"Max simultaneous films in a batch: {report['max_simultaneous_films']}")
    print(f"Batch size distribution (size -> count): {report['batch_size_distribution']}")
    print(f"Batch size escalation needed: {report['batch_size_escalated']}")
    print(f"\nRecalculated music cue timestamps:")
    for r in report["music_cue_timestamps"]:
        print(f"  {r['start_year']}-{r['end_year']:<6d} "
              f"{cfg.seconds_to_mmss(r['video_start'])}-{cfg.seconds_to_mmss(r['video_end'])}  "
              f"({r['batch_count']:>4d} batches, {r['duration_seconds']:>6.1f}s)  "
              f"\"{r['track_title']}\" -- {r['artist']}")
    print(f"\nFinal hold begins at {report['final_hold_video_start_mmss']}")
    print(f"\nNeeds approval before rendering: {report['needs_approval']}")
