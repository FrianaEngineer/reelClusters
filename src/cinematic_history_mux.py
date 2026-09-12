"""
Muxes the silent video master and the audio master into the final
Criterion Over Time video.

The render (cinematic_history_animation.py) deliberately writes a SILENT
mp4 so a draft/partial render costs nothing in audio work; this is the step
that marries the two. The video stream is copied, never re-encoded -- the
only new encode is the audio, and only if it isn't already AAC.

Refuses to run if the two masters' durations disagree by more than
TOLERANCE_SECONDS: they are built from the same schedule, so a mismatch
means one of them is stale and the music would drift against the picture.
Rebuild with cinematic_history_audio_manifest.py + cinematic_history_audio_mix.py.

    python3 cinematic_history_mux.py
    python3 cinematic_history_mux.py --install     # also copy into site/assets/
"""

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import cinematic_history_config as cfg  # noqa: E402

import imageio_ffmpeg
FF = imageio_ffmpeg.get_ffmpeg_exe()

SILENT_PATH = cfg.OUTPUT_DIR / "cinematic_history_silent.mp4"
AUDIO_PATH = cfg.OUTPUT_DIR / "cinematic_history_audio_master.m4a"
FINAL_PATH = cfg.OUTPUT_DIR / "cinematic_history.mp4"
SITE_PATH = cfg.REPO_ROOT / "site" / "assets" / "cinematic_history.mp4"

TOLERANCE_SECONDS = 0.5

DURATION_RE = re.compile(r"Duration: (\d+):(\d+):(\d+\.\d+)")


def duration_of(path):
    proc = subprocess.run([FF, "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    m = DURATION_RE.search(proc.stderr)
    if not m:
        sys.exit(f"could not read duration of {path}")
    h, mnt, sec = m.groups()
    return int(h) * 3600 + int(mnt) * 60 + float(sec)


def main():
    parser = argparse.ArgumentParser(description="Mux the silent video master with the audio master.")
    parser.add_argument("--install", action="store_true",
                        help="also copy the result over site/assets/cinematic_history.mp4")
    args = parser.parse_args()

    for p in (SILENT_PATH, AUDIO_PATH):
        if not p.exists():
            sys.exit(f"missing {p}")

    v, a = duration_of(SILENT_PATH), duration_of(AUDIO_PATH)
    print(f"video {v:.2f}s   audio {a:.2f}s")
    if abs(v - a) > TOLERANCE_SECONDS:
        sys.exit(f"ERROR: durations differ by {abs(v - a):.2f}s (> {TOLERANCE_SECONDS}s). "
                 f"One master is stale -- rebuild the audio with "
                 f"cinematic_history_audio_manifest.py then cinematic_history_audio_mix.py.")

    proc = subprocess.run([FF, "-y", "-hide_banner", "-loglevel", "error",
                           "-i", str(SILENT_PATH), "-i", str(AUDIO_PATH),
                           "-map", "0:v:0", "-map", "1:a:0",
                           "-c:v", "copy", "-c:a", "copy",
                           "-movflags", "+faststart", "-shortest", str(FINAL_PATH)],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit(f"ffmpeg failed:\n{proc.stderr[-4000:]}")
    print(f"Final -> {FINAL_PATH}  ({FINAL_PATH.stat().st_size / 1e6:.0f} MB, {duration_of(FINAL_PATH):.2f}s)")

    if args.install:
        shutil.copy2(FINAL_PATH, SITE_PATH)
        print(f"Installed -> {SITE_PATH}")


if __name__ == "__main__":
    main()
