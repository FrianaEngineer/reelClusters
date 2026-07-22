#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

if [ ! -d .venv ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate

python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements-animation.txt

if command -v ffmpeg >/dev/null 2>&1; then
    echo "System ffmpeg found: $(command -v ffmpeg)"
else
    echo "No system ffmpeg found -- will fall back to the bundled imageio-ffmpeg binary."
fi

python - <<'PY'
import duckdb
import matplotlib
import numpy
import pandas
import PIL
import sklearn
import imageio_ffmpeg
print("Python dependencies installed successfully.")
print("Bundled FFmpeg:", imageio_ffmpeg.get_ffmpeg_exe())
PY

echo
echo "Environment ready."
echo "Activate it with: source .venv/bin/activate"
echo "Then render a preview with:"
echo "python src/cinematic_history_animation.py \\"
echo "  --output outputs/cinematic_history_preview.mp4 \\"
echo "  --fps 24 --dpi 80 \\"
echo "  --start-year 1913 --end-year 1930 --preview"
