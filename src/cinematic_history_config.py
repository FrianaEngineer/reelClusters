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
# Runtime is no longer pinned to an exact 20:00 -- it's now DERIVED from the
# actual film-batch count (see cinematic_history_schedule.py's batching
# logic), because forcing every era into a fixed-duration window made most
# individual films unreadably brief (as little as 0.29s/film in the busiest
# years). Approximately 20 minutes remains the goal; 19-22 minutes is
# acceptable. Only the opening title and final hold stay fixed -- everything
# else scales with how many batches the real film distribution produces.
TITLE_CARD_SECONDS = 2                 # 00:00-00:02, unchanged
FINAL_HOLD_SECONDS = 15                # fixed-length closing hold, unchanged
TARGET_RUNTIME_MIN_SECONDS = 19 * 60
TARGET_RUNTIME_MAX_SECONDS = 22 * 60
STOP_FOR_APPROVAL_MAX_SECONDS = 22 * 60   # hard ceiling -- stop and report, don't render past this
START_YEAR = 1913
END_YEAR = 2025


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

# ── Batching (same-year film groups sharing one on-screen slot) ──────────
# A batch never spans more than one year. Batch size starts small and is
# escalated (densest years first) only as needed to bring the projected
# total runtime down toward the target range -- never the other way around.
PREFERRED_MAX_BATCH_SIZE = 2      # default ceiling before any escalation
CROWDED_MAX_BATCH_SIZE = 3        # first escalation step
ABSOLUTE_MAX_BATCH_SIZE = 4       # hard cap -- never batch more than this many films together
BATCH_SLOT_SECONDS_MIN = 1.3
BATCH_SLOT_SECONDS_MAX = 1.8
BATCH_SLOT_SECONDS_TARGET = 1.5   # nominal per-batch on-screen duration (crossfade-in + hold)

# ── Reveal timing ─────────────────────────────────────────────────────────
HEX_POP_SECONDS = 0.15          # a film's hex(es) fade-in duration -- never fades back out
CARD_FADE_IN_SECONDS = 0.55     # batch fade-in (spec range 0.4-0.75s)
CARD_FADE_OUT_SECONDS = 0.55    # batch fade-out (spec range 0.4-0.75s)
CARD_TRANSITION_EASING = "ease-in-out"   # documented, applied as a smoothstep in the renderer

# ── Visual constants (must match explore.html / hex_svg.py exactly) ──────
# Criterion-Over-Time-specific constant, deliberately not read from or
# written into cluster_colors.py (shared/off-limits) -- kept in sync with
# hex_svg.py's own page-background literal by hand, since this project must
# not modify that shared file.
BACKGROUND_COLOR = "#12121f"
HEX_STROKE_COLOR = "#000000"
HEX_STROKE_WIDTH_PX = 2.5        # spec: 2-3px at 1920x1080
OUTER_BORDER_COLOR = "#000000"
OUTER_BORDER_WIDTH_PX = 5.0      # spec: 4-6px at 1920x1080

# ── Film-info card text styling ───────────────────────────────────────────
CARD_DIRECTOR_FONTSIZE_PX = 32
CARD_COUNTRY_FONTSIZE_PX = 28
CARD_TEXT_COLOR = "#000000"      # director/country text must be black (spec)
# Card surface/background color is not specified by the client spec beyond
# "black text" (implying a light surface) -- TODO: confirm against the
# client's reference image once supplied; using a neutral off-white plate in
# the meantime so the mandated black text stays legible.
CARD_SURFACE_COLOR = "#F2F0EA"

# ── Audio ─────────────────────────────────────────────────────────────────
AUDIO_CROSSFADE_SECONDS = 5.0
AUDIO_CROSSFADE_CURVE = "qsin"   # equal-power crossfade curve for ffmpeg's acrossfade
LOUDNESS_TARGET_LUFS = -20.0     # spec range -22..-18 LUFS integrated
TRUE_PEAK_MAX_DBTP = -2.0
