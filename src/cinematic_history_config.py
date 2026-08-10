"""
Centralized configuration for the "Criterion Over Time" cinematic-history
video: timing, resolution, the exact 14-cue music table, text styling, and
audio targets. Every render stage (schedule, animation, audio manifest,
audio mix, validation) imports from here rather than restating any of these
values -- this file is the single place a re-timing or re-styling request
gets made.

Layout and color are deliberately NOT duplicated here: they're imported by
the modules that need them straight from hex_grid.py / cluster_colors.py /
hex_svg.py, which remain the actual source of truth (see
cinematic_history_schedule.py).
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SITE_DIR = REPO_ROOT / "site"
OUTPUT_DIR = REPO_ROOT / "outputs"
AUDIO_DIR = SITE_DIR / "audioFilesCritOverTime"
AUDIO_MANIFEST_PATH = AUDIO_DIR / "audio-cues.json"
REFERENCE_IMAGE_PATH = SITE_DIR / "assets" / "references" / "criterion-over-time-final-reference.png"

# ── Output format ────────────────────────────────────────────────────────
RESOLUTION = (1920, 1080)
FPS = 30
VIDEO_CODEC = "libx264"
AUDIO_CODEC = "aac"

# ── Top-level timeline ─────────────────────────────────────────────────────
# 2026-08-05 "Reeling Through the Years" restyle: runtime is no longer a
# ~20-minute target at all -- each year now reveals a Top-N film list one
# film at a time (see TOP_N_FILMS / TOP_FILM_INTERVAL_SECONDS below) and then
# gradually fills in that year's remaining films, so total length is whatever
# that per-year sequence actually needs (see cinematic_history_schedule.py's
# build_full_schedule()). Only the opening title and final hold stay fixed.
TITLE_CARD_SECONDS = 2                 # 00:00-00:02, unchanged
FINAL_HOLD_SECONDS = 15                # fixed-length closing hold, unchanged
START_YEAR = 1913
END_YEAR = 2025

# ── Per-year reveal pacing ("Reeling Through the Years" restyle) ───────────
# Each year shows its Top-N films -- ranked by "connections" (that film's
# shared-actor degree to other films in its OWN cluster, i.e. the same
# internal_degree metric already used elsewhere on the site, e.g.
# build_site.py's hub_films() / cluster_ring_viz.py's
# load_films_with_internal_degree() -- see cinematic_history_schedule.py's
# load_connections()) one at a time, each entrance simultaneous with that
# film's exact hex filling in.
# 2026-08-08 "Most Connected Films" restyle: reduced from 5 to 3, and the
# ranking metric switched from imdb_rating/num_votes to connection count
# (see module docstring above and cinematic_history_schedule.py).
TOP_N_FILMS = 3
TOP_FILM_INTERVAL_SECONDS = 2.0     # spec: "reveal one film every two seconds"
EMPTY_YEAR_SECONDS = 0.6            # brief pause for a year with zero films -- just enough to read the year tick over

# After the Top-N list finishes, that year's remaining films (beyond the
# Top-N) fill their exact hexes with no title card, "gradually" per spec.
# Not otherwise spec'd, so paced to scale with how many are left: a light
# year resolves almost instantly, the heaviest year on record (1964, 48
# films -> 43 remaining) still resolves in a few seconds, never a long
# stall. See cinematic_history_schedule.py's remaining_fill_seconds().
REMAINING_FILL_SECONDS_PER_FILM = 0.05
REMAINING_FILL_MIN_SECONDS = 0.4
REMAINING_FILL_MAX_SECONDS = 3.0
REMAINING_HEX_POP_SECONDS = 0.12    # per-hex fade for a remaining-film hex (Top-N hexes use HEX_POP_SECONDS)


def mmss(s):
    """'MM:SS' -> integer seconds."""
    m, sec = s.split(":")
    return int(m) * 60 + int(sec)


def seconds_to_mmss(total_seconds):
    m, s = divmod(round(total_seconds), 60)
    return f"{m:02d}:{s:02d}"


# ── Music cue table ────────────────────────────────────────────────────────
# Track identity, order, and year-range assignment are preserved from the
# client spec exactly. video_start/video_end are NOT: those were the old
# fixed-timestamp table, now replaced -- each era's actual on-screen duration
# is derived from how many batches its real films need (see
# cinematic_history_schedule.py), then used to decide how the assigned track
# gets trimmed/looped. `matched_filename`/`gain_db` are filled in later by
# cinematic_history_audio_manifest.py / cinematic_history_audio_mix.py.
MUSIC_CUES = [
    dict(start_year=1913, end_year=1927,
         track_title="Golden Era of Silent Film", artist="Pilot2Kid",
         notes="Use the full 2:26 track, then extend with a clean loop or held ambience. No speed change."),
    dict(start_year=1928, end_year=1938,
         track_title="1930s Big Band Swing Jazz", artist="HauntSync",
         notes="Use the full 1:44 track. Extend only at a clean phrase boundary or short loop."),
    dict(start_year=1939, end_year=1945,
         track_title="After War Soundtrack - Cinematic War Reflection", artist="OpenMindAudio",
         notes="Select a continuous restrained section, cut only at phrase boundaries."),
    dict(start_year=1946, end_year=1954,
         track_title="Midnight Sidewalk (piano cool jazz)", artist="Surprising_Media",
         notes="Select a continuous section with a complete musical phrase."),
    dict(start_year=1955, end_year=1962,
         track_title="Cool Jazz Session 8", artist="officeMIKADO",
         notes="Select a continuous section."),
    dict(start_year=1963, end_year=1968,
         track_title="Isolation Chamber", artist="TokyoRifft",
         notes="Select a restrained, non-vocal continuous experimental passage."),
    dict(start_year=1969, end_year=1976,
         track_title="Psychedelic Acoustic Folk Instrumental", artist="HauntSync",
         notes="Select a continuous section. Avoid cutting during a strong transition."),
    dict(start_year=1977, end_year=1984,
         track_title="Electro Synth", artist="AdamASR",
         notes="Select a continuous section from the 1:30 source."),
    dict(start_year=1985, end_year=1992,
         track_title="Japan Relaxing Background Music", artist="Tunetank",
         notes="Select a continuous section. No added cultural sound effects."),
    dict(start_year=1993, end_year=2000,
         track_title="Dreamy Floating Ambient Instrumental Journey", artist="SoundsByAmelia",
         notes="Select a continuous passage with audible motion, not the quietest section."),
    dict(start_year=2001, end_year=2008,
         track_title="Minimal Underscore Piano Pulse - Loop Edit", artist="Musinova",
         notes="Use the 1:29 loop edit. Preserve the pulse, cut on the measure."),
    dict(start_year=2009, end_year=2016,
         track_title="Cinematic Ambient Piano - Emotional, Atmospheric", artist="ChrisDjYogi",
         notes="Select a continuous passage."),
    dict(start_year=2017, end_year=2025,
         track_title="Cinematic Atmosphere Score 2", artist="Musictown",
         notes="Select a continuous passage that builds toward the final graph reveal."),
]

# The final-hold reprise isn't a pacing segment (no films reveal during it).
FINAL_HOLD_CUE = dict(
    track_title="Golden Era of Silent Film", artist="Pilot2Kid",
    notes="Reprise: reuse a calm 15-second passage at reduced volume, fading completely to silence.",
    is_reprise_of="Golden Era of Silent Film",
)

for a, b in zip(MUSIC_CUES, MUSIC_CUES[1:]):
    assert a["end_year"] + 1 == b["start_year"], (a["track_title"], b["track_title"])
assert MUSIC_CUES[0]["start_year"] == START_YEAR
assert MUSIC_CUES[-1]["end_year"] == END_YEAR

# ── Reveal timing ─────────────────────────────────────────────────────────
HEX_POP_SECONDS = 0.15          # a Top-N film's hex(es) fade-in duration -- never fades back out

# ── Visual constants ───────────────────────────────────────────────────────
# 2026-07-29 restyle: whole-video background changed from the original dark
# #12121f to an exact client-specified light gray, and the single full-width
# bottom "card" was replaced by a right-hand vertical panel (see
# cinematic_history_animation.py). BACKGROUND_COLOR is intentionally no
# longer required to match hex_svg.py's page literal -- the client spec for
# this restyle explicitly overrides the video's background color, and
# unrevealed/ambient hex faces are painted with this same color so they read
# as "empty" against the new background.
BACKGROUND_COLOR = "#b8b9ba"
# 2026-08-05 "Reeling Through the Years" restyle: interior hex edges made
# lighter/thinner (a mid-gray, ~40% of the old width) so individual hexes
# read as texture, not a grid; the outer perimeter is kept pure black and
# made thicker so the graph's silhouette stays the strongest line in the
# frame -- a clearer light/dark, thin/thick contrast between "inside" and
# "edge of the whole graph" than the old uniform-black-everywhere styling.
HEX_STROKE_COLOR = "#6b6b6b"
HEX_STROKE_WIDTH_PX = 1.0        # interior hex lines -- thinner and lighter than before (was 2.5px, #000000)
OUTER_BORDER_COLOR = "#000000"
OUTER_BORDER_WIDTH_PX = 7.0      # outer perimeter only -- thicker and more defined than before (was 5.0px)

# 2026-08-09 revert: the 2026-08-08 opacity-blend styling (a black-and-white
# film's hex blended toward BACKGROUND_COLOR by a fixed fraction) is reverted
# back to explore.html/hex_svg.py's original behavior -- a black-and-white or
# unresolved film's hex renders as its cluster's exact COLOR_MAP hue with
# every RGB channel multiplied by this factor, byte-for-byte identical to
# hex_svg.py's own BW_DARKEN_FACTOR, so the video and the live site agree on
# every hex's exact color. A confirmed-color film is unaffected (its
# cluster's hue, undarkened).
CLUSTER_HEX_BW_DARKEN_FACTOR = 0.65

# ── Film-info panel text styling ──────────────────────────────────────────
# Title text (film name) is bold and the largest of the three lines; the
# director/country line is one combined "Director · Country" string
# underneath, smaller. Sizes were reduced from the original full-width-card
# values because the panel is now only ~1/3 of the frame width -- a
# small necessary adjustment to keep long titles from clipping.
CARD_TITLE_FONTSIZE_PX = 30
CARD_CREDIT_FONTSIZE_PX = 22
CARD_TEXT_COLOR = "#000000"      # director/country text stays black (spec)
CARD_TITLE_COLOR = "#000000"
# Year / opening title-card text was previously white (legible on the old
# dark #12121f background). Against the new light #b8b9ba background, white
# text would be invisible, which would violate the spec's own legibility and
# "year must appear" requirements -- so these two elements are flipped to a
# dark color. This is the one deliberate color deviation from "keep current
# text colors"; every other text color (all already black) is unchanged.
YEAR_TEXT_COLOR = "#111111"
TITLE_CARD_TEXT_COLOR = "#111111"
TITLE_CARD_SUBTITLE_COLOR = "#333333"

# ── Persistent main title (2026-08-08 restyle) ─────────────────────────────
# A permanent header banner, visible frame 1 through the final frame, in its
# own reserved strip above the graph -- NOT the old 2-second-only centered
# title card (TITLE_CARD_SECONDS/the "title" phase still exists and still
# holds on an empty graph with no year/heading/rows for its same original
# duration, it just no longer needs its own big centered text now that the
# header carries the title at all times).
MAIN_TITLE_TEXT = "Reeling Through the Years: Mapping Cinematic History"
MAIN_TITLE_FONTSIZE_PX = 34
MAIN_TITLE_COLOR = "#111111"
TOP_HEADER_FRAC = 0.115   # fraction of total frame HEIGHT reserved for the header strip

# ── Cluster boundary + completed-cluster labels (2026-08-08 restyle) ───────
# explore.html itself only separates adjacent clusters with a thin
# background-colored gap (see hex_svg.py's boundary_segs, stroke=page
# background) -- this project draws that same adjacency as a genuine black
# line instead, so every cluster's silhouette reads clearly even before any
# of its hexes are filled in (opening frame) and for the rest of the video.
CLUSTER_BOUNDARY_COLOR = "#000000"
CLUSTER_BOUNDARY_WIDTH_PX = 2.2
# Cluster name/position/font-size/line-wrap and on-dark/on-light color are
# NOT restyled here -- they're read verbatim off explore.html's own <text>
# markup by cinematic_history_layout_snapshot.py (cluster_labels in the
# snapshot), this project only supplies the two CSS colors those "on-dark"/
# "on-light" classes resolve to and a fade-in duration for when a label
# first appears.
CLUSTER_LABEL_ON_DARK_COLOR = "#ffffff"
CLUSTER_LABEL_ON_LIGHT_COLOR = "#000000"
CLUSTER_LABEL_STROKE_COLOR = "#000000"
CLUSTER_LABEL_FADE_IN_SECONDS = 0.6

# ── Golden poster-hex border (2026-08-08 restyle) ───────────────────────────
POSTER_HEX_BORDER_COLOR = "#d4af37"
POSTER_HEX_BORDER_WIDTH_PX = 4.5

# ── Right-panel heading (2026-08-08 "Most Connected Films" restyle) ────────
# Static -- no longer "Top N Films of [YEAR]" (the year already appears
# directly above it; repeating it in the heading was redundant).
FILM_HEADING_TEXT = "Most Connected Films"

# ── Country display normalization (2026-08-08 restyle) ─────────────────────
# Applied only to this video's right-panel credit line -- no other display
# normalization currently exists for criterion_country elsewhere on the
# site, so this is deliberately a minimal, explicit map, not a general
# abbreviation scheme.
COUNTRY_DISPLAY_OVERRIDES = {
    "United States": "USA",
}

# ── Film-row timing ─────────────────────────────────────────────────────
# A Top-N row fades in over this long, then (per spec) stays fully visible
# for the rest of that year -- there's no fade-out anymore now that rows no
# longer get superseded/rolled off screen.
ITEM_FADE_IN_SECONDS = 0.5

# ── Smoother year/heading/row/poster transitions (2026-08-08 restyle) ──────
# Applied at the RENDERING layer only (cinematic_history_animation.py), as a
# lookahead fade multiplier over each frame's already-scheduled content --
# the schedule's own per-frame year/heading/rows/poster values (what shows
# when) are unchanged; this only smooths HOW a change in those values reads
# on screen. Never applied across the final segment (nothing plays after the
# closing hold, so there's nothing to fade out into).
YEAR_HEADING_FADE_SECONDS = 0.35   # year number + "Most Connected Films" heading
ROW_FADE_OUT_SECONDS = 0.35        # right-panel film rows, fading out ahead of a year change
POSTER_FADE_SECONDS = 0.45         # poster dips through the background on a year's poster changing

# ── Yearly posters ─────────────────────────────────────────────────────────
# Read-only source directory in the sibling ReelWrangling repo -- per spec,
# posters are used only from there, never copied/downloaded/renamed.
POSTER_SOURCE_DIR = REPO_ROOT.parent / "ReelWrangling" / "data" / "posters"
POSTER_START_YEAR = 1929

# ── Audio ─────────────────────────────────────────────────────────────────
AUDIO_CROSSFADE_SECONDS = 5.0
AUDIO_CROSSFADE_CURVE = "qsin"   # equal-power crossfade curve for ffmpeg's acrossfade
LOUDNESS_TARGET_LUFS = -20.0     # spec range -22..-18 LUFS integrated
TRUE_PEAK_MAX_DBTP = -2.0
