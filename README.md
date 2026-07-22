# reelClusters

## Cinematic history animation

Animates the hex-grid visualization (`src/hex_grid.py`): each film's hexagon
pops in strictly one at a time in chronological order by `criterion_year`,
holding fully visible for a dedicated read pause before the next one starts.
Full run is ~13.6 minutes. Pacing is tunable via `--hex-pop-seconds` (fade-in
time per film) and `--read-hold-seconds` (pause after each one) -- see
`--help`.

```bash
./setup_animation_env.sh
source .venv/bin/activate
python src/cinematic_history_animation.py \
  --output outputs/cinematic_history_preview.mp4 \
  --fps 24 --dpi 80 \
  --start-year 1913 --end-year 1930 --preview
python src/cinematic_history_animation.py \
  --output outputs/cinematic_history.mp4
```
