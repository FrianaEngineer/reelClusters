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
# 2026-08-19: darkened again (#6b6b6b -> #454545, 1.0 -> 1.3px) -- the
# original gray nearly disappeared against Modern American Cinema's own
# muted brown/gray fill, leaving that cluster's individual hexes almost
# unreadable. #454545 keeps a clear gap below the cluster-boundary lines'
# pure black (see CLUSTER_BOUNDARY_COLOR) so the two line systems (hex edge
# vs cluster edge) still read as distinct, not just by width.
HEX_STROKE_COLOR = "#454545"
HEX_STROKE_WIDTH_PX = 1.3        # interior hex lines
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
# 2026-08-17: grown from 0.115 to make room for the film-reel year display
# (top-right corner) above the title without crowding either -- the title
# no longer sits at this band's vertical CENTER (see MAIN_TITLE_Y_ABOVE_
# HEADER_BOTTOM_FRAC below), it stays close to its old absolute position
# near the graph, and the reel occupies the newly added space above it.
TOP_HEADER_FRAC = 0.19   # fraction of total frame HEIGHT reserved for the header strip
MAIN_TITLE_Y_ABOVE_HEADER_BOTTOM_FRAC = 0.058   # matches the title's pre-reel position (was TOP_HEADER_FRAC/2 of the old, shorter band)

# ── Cluster boundary + cluster labels (2026-08-08 restyle; labels always-on
# ── from 0:00 as of 2026-08-17) ─────────────────────────────────────────────
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
# "on-light" classes resolve to. Per spec, every cluster name is visible in
# its permanent position from frame 1 -- no fade-in delay anymore.
CLUSTER_LABEL_ON_DARK_COLOR = "#ffffff"
CLUSTER_LABEL_ON_LIGHT_COLOR = "#000000"
CLUSTER_LABEL_STROKE_COLOR = "#000000"

# Per-cluster multiplier on the snapshot's own font-size, for the video only
# -- explore.html's hex mosaic is untouched. explore.html sizes every label
# with a shrink-to-fit pass that stops at the first size that clears the
# cluster's hexes; on a 1920x1080 frame a few of those land smaller than they
# need to be. Each value below is the largest multiple of the snapshot size
# whose rendered text still sits entirely on its OWN cluster's hexes,
# measured from real matplotlib text extents against the frozen snapshot by
# src/cinematic_history_label_fit.py -- re-run it if the snapshot changes.
CLUSTER_LABEL_SCALE = {
    'soviet_cinema':                1.36,   # snapshot 1.00 -> 1.36 data units
    'classic_japanese_cinema':      1.75,   # snapshot 1.34 -> 2.35
    'golden_age_hollywood_british': 1.37,   # snapshot 1.47 -> 2.01
}

# ── Golden poster-hex border (2026-08-08 restyle) ───────────────────────────
POSTER_HEX_BORDER_COLOR = "#d4af37"
POSTER_HEX_BORDER_WIDTH_PX = 4.5

# ── Best Picture winner row label (2026-08-17 restyle) ─────────────────────
# The 3rd featured-film row each year (when that year has a match) is always
# that year's Academy Award Best Picture winner -- see cinematic_history_
# schedule.py's select_featured_films(). Its own swatch/small-hex reuses
# POSTER_HEX_BORDER_COLOR above instead of the plain black outline every
# other row's swatch gets.
BEST_PICTURE_LABEL_TEXT = "ACADEMY AWARD BEST PICTURE WINNER"
BEST_PICTURE_LABEL_FONTSIZE_PX = 13   # 2026-08-19: enlarged (was 11), per feedback
BEST_PICTURE_LABEL_COLOR = "#8a6d1a"   # a darker gold -- reads clearly as text at small size, same hue family as the border

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

# ── Yearly posters (Best Picture winners) ───────────────────────────────────
# Read-only source directory in the sibling ReelWrangling repo -- per spec,
# posters are used only from there, never copied/downloaded/renamed.
POSTER_SOURCE_DIR = REPO_ROOT.parent / "ReelWrangling" / "data" / "posters"
# Fallback only -- cinematic_history_posters.py's build_poster_index() keys
# posters by each film's own criterion_year and derives the real start year
# from that (currently 1927, *Wings*) rather than trusting this constant;
# kept as the value to fall back to if somehow nothing resolves at all.
POSTER_START_YEAR = 1927

# ── Period fonts (2026-08-17 restyle) ───────────────────────────────────────
# A restrained, readable font per ~20-year cinematic period, applied only to
# the film title lines and the big year number (the two most prominent text
# elements) -- headings/credit lines/cluster labels/clapperboard text stay in
# matplotlib's default bold sans throughout for guaranteed legibility at
# small sizes, per spec ("readability over decorative accuracy"). Bundled as
# static Bold TTFs (Google Fonts, OFL-licensed, instantiated from each
# family's variable font at wght=700) under assets/fonts/ rather than relying
# on the render machine having them installed system-wide.
FONTS_DIR = REPO_ROOT / "assets" / "fonts"
PERIOD_FONTS = [
    # (start_year, end_year, family_name, ttf_filename)
    (1913, 1939, "Libre Baskerville", "LibreBaskerville-Bold.ttf"),
    (1940, 1959, "Lora", "Lora-Bold.ttf"),
    (1960, 1979, "Oswald", "Oswald-Bold.ttf"),
    (1980, 1999, "Source Sans 3", "SourceSans3-Bold.ttf"),
    (2000, 9999, "Inter", "Inter-Bold.ttf"),
]
DEFAULT_FONT_FAMILY = "DejaVu Sans"   # everything NOT covered by PERIOD_FONTS above (unchanged from before this restyle)

# ── Clapperboard (2026-08-17 restyle) ───────────────────────────────────────
# Bottom-right corner, beside the (now narrower) poster -- shows whichever
# film's poster is currently on screen (see cinematic_history_schedule.py's
# poster_active_year). Director comes from the DB (criterion_director);
# studio/release_date come from data/best_picture_winner_details.csv (TMDB-
# sourced -- neither exists anywhere else in this project's own data, see
# build_best_picture_details.py).
CLAPPERBOARD_BODY_COLOR = "#1a1a1a"
CLAPPERBOARD_STRIPE_LIGHT = "#f2f2f2"
CLAPPERBOARD_STRIPE_DARK = "#1a1a1a"
CLAPPERBOARD_TEXT_COLOR = "#f2f2f2"
CLAPPERBOARD_LABEL_FONTSIZE_PX = 12   # 2026-08-19: enlarged alongside the bigger clapperboard (was 10)
CLAPPERBOARD_VALUE_FONTSIZE_PX = 13   # was 11
CLAPPERBOARD_OPEN_ANGLE_DEG = 10   # 2026-09-08: the "stick"/arm is hinged at its left edge and rotated open by this much, not flat/closed

# ── Film reel + year display (2026-08-19 restyle) ───────────────────────────
# Right side of the header, roughly on the title's own row. A continuously
# spinning disc with a straight black film strip (individual frame cells +
# sprocket holes) emerging directly from its rim, carrying the current year
# -- see cinematic_history_animation.py's build_reel()/update_reel(). Timing
# is driven entirely from the schedule's own real year-transition frames
# (never a fixed/arbitrary duration), so it can't drift across a 12+ minute
# video, and is deliberately two-phase per year (see REEL_SETTLE_DRIFT_IN /
# REEL_TRANSITION_SECONDS below) so a year's own number never leaves the
# legible zone before that year's films are done revealing, no matter how
# long or short that year's own reveal takes.
REEL_ROTATION_DEGREES_PER_SECOND = 55
REEL_SPOKE_COUNT = 6
REEL_FILM_STRIP_COLOR = "#0d0d0d"
REEL_SPROCKET_COLOR = "#b8b9ba"   # matches cfg.BACKGROUND_COLOR -- reads as a punched-through hole
REEL_YEAR_TEXT_COLOR = "#f2f2f2"
REEL_BLANK_CELLS_BETWEEN_YEARS = 3   # per spec: "several blank film-frame sections pass" between a year exiting and the next emerging
# Two-phase per-year motion: a SETTLE phase (the bulk of that year's own
# duration) where the cell drifts only this small, FIXED distance regardless
# of how long the year is on screen -- so it stays inside the visible/
# legible window and never disappears before that year's own films finish
# revealing -- followed by a short, fixed-duration TRANSITION phase (see
# below) that sweeps the rest of the way to the next slot (showing several
# blanks pass) and lands exactly on the real transition frame. Both phases
# ease smoothly (zero velocity at every phase boundary), so speed never
# snaps -- see cinematic_history_animation.py's compute_reel_scroll().
REEL_SETTLE_DRIFT_IN = 0.30
REEL_TRANSITION_SECONDS = 1.6
REEL_YEAR_FADE_IN_SECONDS = 0.7   # time-based, not distance-based -- see compute_reel_scroll()'s own docstring

# ── Audio ─────────────────────────────────────────────────────────────────
AUDIO_CROSSFADE_SECONDS = 5.0
AUDIO_CROSSFADE_CURVE = "qsin"   # equal-power crossfade curve for ffmpeg's acrossfade
LOUDNESS_TARGET_LUFS = -20.0     # spec range -22..-18 LUFS integrated
TRUE_PEAK_MAX_DBTP = -2.0
