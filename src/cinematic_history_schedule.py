"""
Frame-by-frame reveal schedule for the "Reeling Through the Years" video.
Pure logic, no matplotlib -- testable and inspectable on its own.

Each year reveals its Top-N films (ranked by imdb_rating desc, num_votes as
tiebreak) one at a time, TOP_FILM_INTERVAL_SECONDS apart, each entrance
simultaneous with that exact film's hex(es) filling in. Once the Top-N list
for a year is done, that year's remaining films (beyond the Top-N) gradually
fill their own exact hexes with no title card, then the video advances to
the next year. Runtime is DERIVED from this per-year sequence, not pinned to
any target duration -- see cinematic_history_config.py's per-year pacing
constants.

Data sources, and only these:
  - data/cinematic_history_hex_snapshot.json (frozen extract of the live
    site/explore.html -- positions, cluster, and final fill color per hex,
    plus which film is narratively attached to which hex).
  - db/criterion_graph.duckdb, read-only, for film metadata (title, director,
    country, year, rating, vote count) of exactly the tconsts the snapshot
    already placed.
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


def darken(hex_color, factor=cfg.CLUSTER_HEX_BW_DARKEN_FACTOR):
    """Byte-for-byte identical to hex_svg.py's own darken() (channel *
    factor, truncated -- not rounded) so a black-and-white/unresolved film's
    hex matches explore.html's exact color, not just something close to it."""
    r, g, b = _hex_to_rgb(hex_color)
    return f"#{int(r * factor):02x}{int(g * factor):02x}{int(b * factor):02x}"


def clamp(x, lo, hi):
    return lo if x < lo else (hi if x > hi else x)


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
                   imdb_rating, num_votes,
                   row_number() OVER (
                       PARTITION BY imdb_tconst ORDER BY confidence_score DESC NULLS LAST
                   ) AS rn
            FROM criterion_basic_info
            WHERE imdb_tconst IN ({})
        ) WHERE rn = 1
    """.format(",".join(f"'{t}'" for t in tconsts))).df()
    con.close()
    return df.set_index("imdb_tconst").to_dict("index")


def load_connections(tconsts):
    """tconst -> "connections": internal (within-its-OWN-cluster) shared-actor
    degree -- the identical metric already shown elsewhere on the site (see
    build_site.py's hub_films()/cluster_ring_viz.py's
    load_films_with_internal_degree(): count of movie_edges rows linking
    this film to another film in the SAME cluster_assignments cluster).
    Films with no cluster_assignments row, or zero same-cluster edges, get 0
    -- never missing/None, so this is always a plain int ranking key."""
    if not tconsts:
        return {}
    con = duckdb.connect(str(DB_PATH), read_only=True)
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
        )
        SELECT m AS imdb_tconst, count(*) FILTER (WHERE cluster_other = cluster_m) AS connections
        FROM joined GROUP BY m
    """).df()
    con.close()
    by_tconst = dict(zip(df["imdb_tconst"], df["connections"]))
    return {t: int(by_tconst.get(t, 0)) for t in tconsts}


def display_country(country):
    """criterion_country, with this video's minimal display normalization
    (currently just "United States" -> "USA") applied -- see
    cfg.COUNTRY_DISPLAY_OVERRIDES."""
    if not isinstance(country, str) or not country:
        return country
    return cfg.COUNTRY_DISPLAY_OVERRIDES.get(country, country)


def format_credit_line(director, country, connections):
    """"Director – Country – N connections", e.g. "Michael Curtiz – USA – 18
    connections" -- omitting director/country if either is genuinely absent
    from the data, but always ending in the connection count."""
    parts = [p for p in (director, display_country(country)) if isinstance(p, str) and p]
    parts.append(f"{connections} connection" if connections == 1 else f"{connections} connections")
    return " – ".join(parts)


# ── Reveal events ──────────────────────────────────────────────────────────

def hexes_by_tconst(snapshot):
    by_tconst = defaultdict(list)
    for h in snapshot["hexes"]:
        if h["tconst"]:
            by_tconst[h["tconst"]].append((h["q"], h["r"]))
    return by_tconst


def build_reveal_events(snapshot, meta, connections):
    """One event per unique tconst placed on the snapshot (a handful of
    films occupy more than one hex -- catalog duplicates like "Carlos: Part
    1/2/3" sharing one imdb_tconst -- grouped into a single reveal event
    exactly as hex_grid.py's own downstream consumers already do, so that
    film's card appears once, not 2-3 times in a row)."""
    by_tconst = hexes_by_tconst(snapshot)

    events = []
    missing_meta = []
    for tconst, hexes in by_tconst.items():
        row = meta.get(tconst)
        if row is None or row["criterion_year"] is None:
            missing_meta.append(tconst)
            continue
        conn = connections.get(tconst, 0)
        events.append(dict(
            tconst=tconst,
            title=row["title"],
            director=row["criterion_director"],
            country=row["criterion_country"],
            connections=conn,
            credit_line=format_credit_line(row["criterion_director"], row["criterion_country"], conn),
            year=int(row["criterion_year"]),
            rating=row["imdb_rating"],
            votes=row["num_votes"],
            hexes=hexes,
        ))
    if missing_meta:
        sys.exit(f"ERROR: {len(missing_meta)} placed film(s) have no usable metadata: {missing_meta}")

    events.sort(key=lambda e: (e["year"], e["tconst"]))
    return events


def ambient_hexes(snapshot, final_colors):
    """Hexes with no film attached (the approved unfilled-hex exceptions) --
    shown in their final display color from the very start, never part of
    the per-film reveal."""
    return [(h["q"], h["r"], final_colors[(h["q"], h["r"])]) for h in snapshot["hexes"] if h["tconst"] is None]


def final_color_for_hex(snapshot):
    """Named-cluster hexes: that cluster's own base hue (from the snapshot's
    color_map, itself explore.html's COLOR_MAP) for a confirmed-color film,
    or that hue run through darken() for a black-and-white/unresolved film --
    exactly explore.html/hex_svg.py's own scheme, see cfg.CLUSTER_HEX_BW_DARKEN_FACTOR.
    hiddenGems (a two-ring white/gray border assigned by POSITION, not by any
    film's own color status) is left exactly as explore.html renders it."""
    color_map = snapshot["color_map"]
    colors = {}
    for h in snapshot["hexes"]:
        key = (h["q"], h["r"])
        if h["cluster_id"] == "hiddenGems":
            colors[key] = h["fill"]
        else:
            base = color_map[h["cluster_id"]]
            colors[key] = base if h["is_color"] else darken(base)
    return colors


# ── Per-year Top-N / remaining split ─────────────────────────────────────

def group_events_by_year(events):
    by_year = defaultdict(list)
    for ev in events:
        by_year[ev["year"]].append(ev)
    return by_year


def _rank_key(e):
    # connections is always a plain int (0 if no data), so no None-handling
    # needed -- ties broken by tconst for determinism.
    return (-e["connections"], e["tconst"])


def select_top_and_remaining(events_for_year):
    """-> (top, remaining), both lists of event dicts. `top` is capped at
    cfg.TOP_N_FILMS, ranked by connections desc (ties broken by tconst for
    determinism) -- the "Most Connected Films" of that year. `remaining` is
    every other film from that year, in the same rank order (their
    on-screen order doesn't matter -- they never get a title card -- but a
    stable, deterministic order matters for reproducibility)."""
    ranked = sorted(events_for_year, key=_rank_key)
    return ranked[:cfg.TOP_N_FILMS], ranked[cfg.TOP_N_FILMS:]


def heading_for_year(year):
    """Static "Most Connected Films" (the year itself already appears
    directly above it on screen -- see cfg.FILM_HEADING_TEXT), regardless of
    how many films that year actually has. No invented data: a thin year
    still shows only the films that actually exist for it."""
    return cfg.FILM_HEADING_TEXT


def remaining_fill_seconds(n_remaining):
    if n_remaining <= 0:
        return 0.0
    return clamp(n_remaining * cfg.REMAINING_FILL_SECONDS_PER_FILM,
                 cfg.REMAINING_FILL_MIN_SECONDS, cfg.REMAINING_FILL_MAX_SECONDS)


# ── Music cue timestamps (derived from real per-year durations) ──────────

def recalculate_music_cue_timestamps(year_durations):
    """year_durations: {year: seconds}. Era duration = sum of its years'
    real on-screen durations, replacing the old fixed timestamp table. Track
    order and year-range assignment unchanged."""
    cursor = cfg.TITLE_CARD_SECONDS
    rows = []
    for cue in cfg.MUSIC_CUES:
        years_in_cue = [y for y in range(cue["start_year"], cue["end_year"] + 1)]
        duration = sum(year_durations.get(y, 0.0) for y in years_in_cue)
        n_films = None  # filled in by caller if needed; not required downstream
        rows.append(dict(start_year=cue["start_year"], end_year=cue["end_year"],
                          track_title=cue["track_title"], artist=cue["artist"],
                          duration_seconds=duration, video_start=cursor, video_end=cursor + duration))
        cursor += duration
    return rows, cursor   # cursor == start of the final hold


# ── Full per-frame schedule (for the renderer) ─────────────────────────────

def build_full_schedule():
    """The complete frame-by-frame plan the renderer consumes.

    Each frame carries:
      - phase: "title" | "main" | "hold"
      - year: the active year (or None during the title card)
      - color_diffs: {(q, r): new_fill_color} for hexes that change color on
        this exact frame (empty dict on every other frame)
      - heading: the right-panel heading text for this frame ("Top 5 Films
        of 1962", always "Top 5" even for a thin early year with fewer than
        5 real films -- see heading_for_year() -- / None for an empty year
        or outside the main phase)
      - rows: up to cfg.TOP_N_FILMS dicts, one per Top-N film revealed so
        far THIS YEAR (title, credit_line, swatch_color, alpha) -- the
        currently-entering row fades in over cfg.ITEM_FADE_IN_SECONDS
        (imported lazily below to avoid a hard dependency loop), every
        earlier row for the same year stays fully visible (alpha=1) per
        spec ("previously revealed films... should remain visible"). The
        list resets (a clean cut, matching the year-number's own instant
        change) the moment the active year changes.
    """
    snapshot = load_snapshot()
    all_tconsts = sorted({h["tconst"] for h in snapshot["hexes"] if h["tconst"]})
    meta = load_metadata(all_tconsts)
    connections = load_connections(all_tconsts)
    events = build_reveal_events(snapshot, meta, connections)
    by_year = group_events_by_year(events)
    final_colors = final_color_for_hex(snapshot)
    fps = cfg.FPS

    # Yearly poster -> exact hex(es) for that poster's own film, for the
    # golden poster-hex border (cinematic_history_animation.py). Import kept
    # local to this function: cinematic_history_posters.py has no
    # dependency back on this module, so this isn't a real import cycle, but
    # every other module-level import in this file is a hard dependency of
    # the whole module -- this one is only needed inside schedule-building.
    from cinematic_history_posters import build_poster_index
    poster_tconst_by_year = build_poster_index()["resolved_tconst"]
    tconst_hexes = hexes_by_tconst(snapshot)
    poster_hexes_by_year = {y: tuple(tconst_hexes.get(t, [])) for y, t in poster_tconst_by_year.items()}

    # Completed-cluster tracking: a cluster's title only ever appears once
    # EVERY hex belonging to it -- event hexes and ambient (no-film) hexes
    # alike -- has reached its final display color. Ambient hexes are
    # already "revealed" from the very first title frame (see below), so
    # they're pre-counted before the main per-year loop even starts.
    hex_cluster_map = {(h["q"], h["r"]): h["cluster_id"] for h in snapshot["hexes"]}
    cluster_remaining = Counter(hex_cluster_map.values())
    cluster_complete_frame = {}

    def note_reveal(q, r, frame_idx):
        c = hex_cluster_map[(q, r)]
        cluster_remaining[c] -= 1
        if cluster_remaining[c] == 0 and c not in cluster_complete_frame:
            cluster_complete_frame[c] = frame_idx

    fade_in_frames = max(1, round(fps * cfg.ITEM_FADE_IN_SECONDS))
    top_pop_frames = max(1, round(fps * cfg.HEX_POP_SECONDS))
    remaining_pop_frames = max(1, round(fps * cfg.REMAINING_HEX_POP_SECONDS))
    interval_frames = round(cfg.TOP_FILM_INTERVAL_SECONDS * fps)
    empty_year_frames = round(cfg.EMPTY_YEAR_SECONDS * fps)

    # Frame counts per year, computed once here and reused verbatim below for
    # the actual frame loop -- so the music-cue timestamps (derived from
    # these same frame counts / fps) land on the EXACT same total duration
    # as the rendered video, frame for frame. Deriving the two from separate
    # unrounded-vs-rounded formulas would drift apart by the sum of each
    # year's own rounding error (110 years of it), leaving the audio master
    # a fraction of a second short of the video's real length.
    year_frame_counts = {}
    for year in range(cfg.START_YEAR, cfg.END_YEAR + 1):
        evs = by_year.get(year, [])
        if not evs:
            year_frame_counts[year] = empty_year_frames
            continue
        top, remaining = select_top_and_remaining(evs)
        top_frames_total = len(top) * interval_frames
        remain_frames_total = round(remaining_fill_seconds(len(remaining)) * fps)
        year_frame_counts[year] = top_frames_total + remain_frames_total

    year_durations = {y: n / fps for y, n in year_frame_counts.items()}
    cue_rows, hold_start = recalculate_music_cue_timestamps(year_durations)

    frames = []
    ambient = ambient_hexes(snapshot, final_colors)

    # Spec: the OPENING frame(s) must show a completely empty graph -- no
    # hex filled with a cluster color yet, not even a structural/no-film
    # ambient hex. So the title card stays fully blank, and the ambient
    # hexes' one-time reveal is deferred to the very first frame of the main
    # phase (the instant the reveal timeline itself starts, year
    # cfg.START_YEAR) instead of the title card's frame 0 -- still a single
    # one-time reveal, never part of the per-film schedule, just moved to
    # not precede "the opening frame has nothing revealed yet."
    title_frames = round(cfg.TITLE_CARD_SECONDS * fps)
    for i in range(title_frames):
        frames.append(dict(phase="title", year=None, heading=None, rows=[], poster_hexes=(), color_diffs={}))

    for q, r, _ in ambient:
        note_reveal(q, r, title_frames)
    # Any cluster made ENTIRELY of ambient hexes (no real film in it at all)
    # would already be complete at that point -- doesn't happen for any
    # named cluster today, but handled for correctness rather than assumed.
    for c, remaining in list(cluster_remaining.items()):
        if remaining == 0 and c not in cluster_complete_frame:
            cluster_complete_frame[c] = title_frames

    _ambient_diffs = {(q, r): fill for q, r, fill in ambient}
    _ambient_pending = [True]

    def append_frame(frame_dict):
        if _ambient_pending[0]:
            frame_dict = dict(frame_dict)
            frame_dict["color_diffs"] = {**_ambient_diffs, **frame_dict["color_diffs"]}
            _ambient_pending[0] = False
        frames.append(frame_dict)

    empty_row = lambda: dict(title="", credit_line="", swatch_color=None, alpha=0.0)  # noqa: E731

    for year in range(cfg.START_YEAR, cfg.END_YEAR + 1):
        poster_hexes = poster_hexes_by_year.get(year, ())
        evs = by_year.get(year, [])
        if not evs:
            for _ in range(empty_year_frames):
                append_frame(dict(phase="main", year=year, heading=None, rows=[], color_diffs={},
                                   poster_hexes=poster_hexes))
            continue

        top, remaining = select_top_and_remaining(evs)
        heading = heading_for_year(year)
        n_top = len(top)
        top_frames_total = n_top * interval_frames
        remain_seconds = remaining_fill_seconds(len(remaining))
        remain_frames_total = round(remain_seconds * fps)

        # Precompute each Top-N film's swatch color once (first hex's final
        # fill -- the exact color that hex ends up on the graph).
        for e in top:
            e["swatch_color"] = final_colors[e["hexes"][0]]

        # Each remaining film's own pop-in window, clamped so it can never
        # run past this year's own remaining-fill budget: with many remaining
        # films staggered evenly across a short window (n_remaining can
        # exceed remain_frames_total for a heavy year), a film entering near
        # the very end of the window would otherwise never reach t=1.0
        # before the year advances -- leaving its hex permanently stuck at a
        # partial blend (year N+1 never revisits it, since nothing else ever
        # writes to that hex again). Clamping the window's own length keeps
        # the staggered-entrance stagger for early hexes exactly as before;
        # only a handful of the very last-entering hexes in a heavy year get
        # a proportionally quicker (never fully skipped) pop.
        remaining_windows = []
        n_remaining = len(remaining)
        for ridx, e in enumerate(remaining):
            e_entrance = (ridx * remain_frames_total) // n_remaining if n_remaining else 0
            this_pop_frames = max(1, min(remaining_pop_frames, remain_frames_total - e_entrance))
            remaining_windows.append((e, e_entrance, this_pop_frames))

        revealed_rows = []   # rows fully settled from a previous entrance this year
        for f in range(top_frames_total + remain_frames_total):
            color_diffs = {}
            rows = list(revealed_rows)
            this_frame_idx = len(frames)

            if f < top_frames_total:
                idx = f // interval_frames
                entrance_f = idx * interval_frames
                t_in_slot = f - entrance_f
                cur = top[idx]

                if t_in_slot < top_pop_frames:
                    t = (t_in_slot + 1) / top_pop_frames
                    for (q, r) in cur["hexes"]:
                        if t >= 1.0:
                            color_diffs[(q, r)] = final_colors[(q, r)]
                            note_reveal(q, r, this_frame_idx)
                        else:
                            color_diffs[(q, r)] = blend(cfg.BACKGROUND_COLOR, final_colors[(q, r)], t)

                alpha = clamp((t_in_slot + 1) / fade_in_frames, 0.0, 1.0)
                row_fields = dict(title=cur["title"], credit_line=cur["credit_line"],
                                   director=cur["director"], country=display_country(cur["country"]),
                                   connections=cur["connections"], swatch_color=cur["swatch_color"])
                rows = rows + [dict(**row_fields, alpha=alpha)]
                if t_in_slot == interval_frames - 1:
                    # This row is now permanently settled for the rest of the year.
                    revealed_rows.append(dict(**row_fields, alpha=1.0))
            else:
                # Remaining-films bulk fill: no title cards, just each
                # remaining film's exact hex(es) popping in, staggered
                # evenly across the remaining-fill window (each film's own
                # window pre-clamped to fit -- see remaining_windows above).
                rf = f - top_frames_total
                for e, e_entrance, this_pop_frames in remaining_windows:
                    t_in = rf - e_entrance
                    if 0 <= t_in < this_pop_frames:
                        t = (t_in + 1) / this_pop_frames
                        for (q, r) in e["hexes"]:
                            if t >= 1.0:
                                color_diffs[(q, r)] = final_colors[(q, r)]
                                note_reveal(q, r, this_frame_idx)
                            else:
                                color_diffs[(q, r)] = blend(cfg.BACKGROUND_COLOR, final_colors[(q, r)], t)

            append_frame(dict(phase="main", year=year, heading=heading, rows=rows, color_diffs=color_diffs,
                               poster_hexes=poster_hexes))

    hold_start_frame = len(frames)
    hold_frames_total = round(cfg.FINAL_HOLD_SECONDS * fps)
    last_year = cfg.END_YEAR
    final_rows = revealed_rows if by_year.get(cfg.END_YEAR) else []
    final_heading = heading_for_year(last_year) if by_year.get(last_year) else None
    final_poster_hexes = poster_hexes_by_year.get(last_year, ())
    for i in range(hold_frames_total):
        append_frame(dict(phase="hold", year=last_year, heading=final_heading, rows=final_rows, color_diffs={},
                           poster_hexes=final_poster_hexes))

    # Any cluster whose last hex only ever reaches its final color via a
    # blend() step that never quite hits t>=1.0 due to float rounding would
    # otherwise never register complete -- not expected (top_pop_frames/
    # remaining_pop_frames's own last t is exactly 1.0 by construction), but
    # cheap to guarantee outright: every cluster must be complete by the
    # last frame of the main phase.
    missing_complete = [c for c, remaining in cluster_remaining.items() if remaining > 0]
    if missing_complete:
        sys.exit(f"ERROR: {len(missing_complete)} cluster(s) never fully revealed: {missing_complete}")

    return dict(
        frames=frames,
        fps=fps,
        final_colors=final_colors,
        color_map=snapshot["color_map"],
        cluster_labels=snapshot["cluster_labels"],
        cluster_complete_frames=cluster_complete_frame,
        grid_hexes=[(h["q"], h["r"]) for h in snapshot["hexes"]],
        hex_set={(h["q"], h["r"]) for h in snapshot["hexes"]},
        hex_cluster_map=hex_cluster_map,
        outer_hidden_gems=[(h["q"], h["r"]) for h in snapshot["hexes"]
                            if h["cluster_id"] == "hiddenGems" and h["is_hidden_gems_outer"]],
        music_cue_timestamps=cue_rows,
        final_hold_video_start_seconds=hold_start,
        hold_start_frame=hold_start_frame,
        total_seconds=len(frames) / fps,
        year_durations=year_durations,
        events=events,
    )


# ── Report (no rendering) ───────────────────────────────────────────────────

def build_plan_report():
    """Reuses build_full_schedule() itself (rather than recomputing year
    durations independently) so this report's numbers -- runtime, cue
    timestamps -- can never drift from what actually gets rendered."""
    schedule = build_full_schedule()
    events = schedule["events"]
    by_year = group_events_by_year(events)
    cue_rows = schedule["music_cue_timestamps"]
    hold_start = schedule["final_hold_video_start_seconds"]
    runtime = schedule["total_seconds"]

    counts = Counter(len(evs) for evs in by_year.values())
    years_over_top_n = sum(1 for evs in by_year.values() if len(evs) > cfg.TOP_N_FILMS)
    years_exactly_top_n = sum(1 for evs in by_year.values() if len(evs) == cfg.TOP_N_FILMS)
    years_under_top_n = sum(1 for evs in by_year.values() if 0 < len(evs) < cfg.TOP_N_FILMS)
    empty_years = (cfg.END_YEAR - cfg.START_YEAR + 1) - len(by_year)

    return dict(
        projected_runtime_seconds=runtime,
        projected_runtime_mmss=cfg.seconds_to_mmss(runtime),
        total_films=len(events),
        total_years=len(by_year),
        empty_years=empty_years,
        years_over_top_n=years_over_top_n,
        years_exactly_top_n=years_exactly_top_n,
        years_under_top_n=years_under_top_n,
        film_count_distribution=dict(sorted(counts.items())),
        music_cue_timestamps=cue_rows,
        final_hold_video_start_seconds=hold_start,
        final_hold_video_start_mmss=cfg.seconds_to_mmss(hold_start),
        events=events,
        by_year=by_year,
    )


if __name__ == "__main__":
    report = build_plan_report()
    print(f"Projected total runtime: {report['projected_runtime_mmss']}  "
          f"({report['projected_runtime_seconds']:.1f}s)")
    print(f"Total films: {report['total_films']}  across {report['total_years']} years "
          f"({report['empty_years']} empty years)")
    print(f"Years with >{cfg.TOP_N_FILMS} films (Top-{cfg.TOP_N_FILMS} + gradual remaining-fill): "
          f"{report['years_over_top_n']}")
    print(f"Years with exactly {cfg.TOP_N_FILMS} films: {report['years_exactly_top_n']}")
    print(f"Years with 1-{cfg.TOP_N_FILMS - 1} films (heading still says \"Top {cfg.TOP_N_FILMS}\", "
          f"just fewer rows shown): {report['years_under_top_n']}")
    print(f"\nRecalculated music cue timestamps:")
    for r in report["music_cue_timestamps"]:
        print(f"  {r['start_year']}-{r['end_year']:<6d} "
              f"{cfg.seconds_to_mmss(r['video_start'])}-{cfg.seconds_to_mmss(r['video_end'])}  "
              f"({r['duration_seconds']:>6.1f}s)  \"{r['track_title']}\" -- {r['artist']}")
    print(f"\nFinal hold begins at {report['final_hold_video_start_mmss']}")
