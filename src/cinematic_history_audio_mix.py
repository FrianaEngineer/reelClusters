"""
Builds the Criterion Over Time continuous audio master: trims/loops each
cue's matched file (from audio-cues.json) to its recalculated era duration,
loudness-normalizes each, and chains them with 5-second equal-power
crossfades centered on each era boundary -- producing one audio file whose
total duration matches the video's total runtime exactly.

Uses ONLY the bundled ffmpeg binary (imageio_ffmpeg) via subprocess -- no
shell=True, no new pip dependency, no network access, no file outside
site/audioFilesCritOverTime/ (input) and outputs/ (output).

Simplification, disclosed rather than hidden: source in/out points default
to the start of each matched file (trim or loop from position 0), not a
hand-curated "best 1:24 passage" -- picking an ideal internal excerpt of
each track is a creative-listening judgment call this script can't make.
Loop seams (for tracks shorter than their assigned era) are a hard restart
via ffmpeg's stream_loop, not a crossfaded seam -- noted as a known
simplification, not silently presented as spec-complete.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import cinematic_history_config as cfg  # noqa: E402

import imageio_ffmpeg
FF = imageio_ffmpeg.get_ffmpeg_exe()

TMP_DIR = cfg.OUTPUT_DIR / "audio_tmp"
MASTER_PATH = cfg.OUTPUT_DIR / "cinematic_history_audio_master.m4a"


def run(*args):
    proc = subprocess.run([FF, "-y", "-hide_banner", *map(str, args)],
                           capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit(f"ffmpeg failed: {' '.join(map(str, args))}\n{proc.stderr[-4000:]}")
    return proc.stderr


def probe_duration(path):
    # `ffmpeg -i <path>` with no output always exits non-zero ("At least one
    # output file must be specified") -- but it prints Duration to stderr
    # before that, which is all this needs, so it bypasses the strict run()
    # wrapper that would otherwise treat that expected non-zero exit as fatal.
    proc = subprocess.run([FF, "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    out = proc.stderr
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out)
    if not m:
        sys.exit(f"Could not read duration for {path}")
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


def trim_or_loop(src, target_duration, out_path):
    src_duration = probe_duration(src)
    if src_duration >= target_duration:
        run("-i", src, "-t", f"{target_duration:.3f}", "-ar", "48000", "-ac", "2", out_path)
    else:
        # Hard-restart loop (see module docstring) -- covers the needed
        # duration, does not hide the seam with an internal crossfade.
        run("-stream_loop", "-1", "-i", src, "-t", f"{target_duration:.3f}",
            "-ar", "48000", "-ac", "2", out_path)


def loudnorm(in_path, out_path):
    """Two-pass loudnorm: measure, then apply the measured correction --
    more accurate than a single blind pass."""
    measure_out = run("-i", in_path, "-af",
                       f"loudnorm=I={cfg.LOUDNESS_TARGET_LUFS}:TP={cfg.TRUE_PEAK_MAX_DBTP}:print_format=json",
                       "-f", "null", "-")
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", measure_out, re.S)
    if not m:
        sys.exit(f"loudnorm measurement pass failed to produce stats for {in_path}")
    stats = json.loads(m.group(0))
    af = (f"loudnorm=I={cfg.LOUDNESS_TARGET_LUFS}:TP={cfg.TRUE_PEAK_MAX_DBTP}:"
          f"measured_I={stats['input_i']}:measured_TP={stats['input_tp']}:"
          f"measured_LRA={stats['input_lra']}:measured_thresh={stats['input_thresh']}:"
          f"offset={stats['target_offset']}:linear=true")
    run("-i", in_path, "-af", af, "-ar", "48000", "-ac", "2", out_path)
    return stats


def build_master():
    if not cfg.AUDIO_MANIFEST_PATH.exists():
        sys.exit(f"ERROR: {cfg.AUDIO_MANIFEST_PATH} not found -- run cinematic_history_audio_manifest.py first.")
    manifest = json.loads(cfg.AUDIO_MANIFEST_PATH.read_text())
    if manifest["unresolved"]:
        sys.exit(f"ERROR: {len(manifest['unresolved'])} cue(s) still unresolved in the manifest -- "
                 f"cannot build the audio master: {[u['track_title'] for u in manifest['unresolved']]}")

    cues = sorted(manifest["cues"], key=lambda c: c["video_start"])
    # The opening title (0:00-0:02) has no dedicated cue -- the FIRST music
    # cue's audio should start at 0:00 so the opening music plays under the
    # title card, per "start the opening music at 00:00."
    cues[0] = dict(cues[0], video_start=0.0)

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    xfade = cfg.AUDIO_CROSSFADE_SECONDS
    half = xfade / 2

    segment_paths = []
    loudness_reports = []
    for i, cue in enumerate(cues):
        core_duration = cue["video_end"] - cue["video_start"]
        pad_before = half if i > 0 else 0.0
        pad_after = half if i < len(cues) - 1 else 0.0
        total_needed = core_duration + pad_before + pad_after

        src = cfg.AUDIO_DIR / cue["matched_filename"]
        raw_path = TMP_DIR / f"{i:02d}_raw.wav"
        trim_or_loop(src, total_needed, raw_path)

        norm_path = TMP_DIR / f"{i:02d}_norm.wav"
        stats = loudnorm(raw_path, norm_path)
        loudness_reports.append(dict(cue=cue["track_title"], measured_input_lufs=stats["input_i"],
                                      output_target_lufs=cfg.LOUDNESS_TARGET_LUFS))
        segment_paths.append(norm_path)

    # Chain sequential acrossfade operations: ((s0 x s1) x s2) x s3 ...
    # Each crossfade overlaps by exactly `xfade` seconds, which the pad_before
    # /pad_after allowance above exists to supply -- so the final total
    # duration equals sum(core_duration), landing exactly on the schedule's
    # own era boundaries.
    current = segment_paths[0]
    for i in range(1, len(segment_paths)):
        out_path = TMP_DIR / f"chain_{i:02d}.wav"
        run("-i", current, "-i", segment_paths[i], "-filter_complex",
            f"acrossfade=d={xfade}:c1={cfg.AUDIO_CROSSFADE_CURVE}:c2={cfg.AUDIO_CROSSFADE_CURVE}",
            "-ar", "48000", "-ac", "2", out_path)
        current = out_path

    # Fade the opening in, fade the closing reprise to silence, per spec.
    final_raw = TMP_DIR / "final_raw.wav"
    total_duration = probe_duration(current)
    fade_in_s = 1.5
    fade_out_s = min(cfg.FINAL_HOLD_SECONDS, 8.0)
    run("-i", current, "-af",
        f"afade=t=in:st=0:d={fade_in_s},afade=t=out:st={total_duration - fade_out_s:.3f}:d={fade_out_s}",
        "-ar", "48000", "-ac", "2", final_raw)

    MASTER_PATH.parent.mkdir(parents=True, exist_ok=True)
    run("-i", final_raw, "-c:a", cfg.AUDIO_CODEC, "-b:a", "192k", MASTER_PATH)

    return dict(master_path=MASTER_PATH, total_duration=probe_duration(MASTER_PATH),
                loudness_reports=loudness_reports, cue_count=len(cues))


def main():
    result = build_master()
    print(f"Audio master -> {result['master_path']}")
    print(f"Duration: {result['total_duration']:.1f}s ({result['total_duration'] / 60:.2f} min)")
    print(f"Cues mixed: {result['cue_count']}")
    for r in result["loudness_reports"]:
        print(f"  {r['cue']}: measured {float(r['measured_input_lufs']):.1f} LUFS -> "
              f"target {r['output_target_lufs']} LUFS")


if __name__ == "__main__":
    main()
