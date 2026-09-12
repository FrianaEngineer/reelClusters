"""
Measures how far each cluster label on site/explore.html's hex map can grow
before its text stops sitting entirely on its own cluster's hexes, and prints
the safe multiplier for snapshot_grid.LABEL_SCALE.

Unlike a character-width estimate, this measures the real thing: the SVG is
rendered in headless Chrome and each label's getBBox() is read back in SVG
user units, which are the same units the hex centers live in. Every point of
that box is then tested against the nearest hex center's cluster id.

    python3 explore_label_fit.py soviet_cinema classic_japanese_cinema

Prints findings only -- paste the ones you want into LABEL_SCALE by hand, so
label sizes never change as a silent side effect of running this.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import hex_svg  # noqa: E402
import snapshot_grid  # noqa: E402
from hex_grid import display_name  # noqa: E402

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
SAMPLES_X, SAMPLES_Y = 24, 6
SAFETY = 0.94   # back off the measured boundary; glyph overhang + the label stroke

HARNESS = """<!doctype html><meta charset="utf-8">%s
<script>
window.addEventListener("load", function () {
  var out = {};
  document.querySelectorAll("text.label").forEach(function (t) {
    var b = t.getBBox();
    out[t.textContent.replace(/\\s+/g, " ").trim()] = [b.x, b.y, b.width, b.height];
  });
  document.title = "BBOX" + JSON.stringify(out);
});
</script>"""


def measure(svg):
    """label text -> (x, y, w, h) in SVG user units, from a real render."""
    with tempfile.TemporaryDirectory() as td:
        page = Path(td) / "m.html"
        page.write_text(HARNESS % svg)
        proc = subprocess.run(
            [CHROME, "--headless", "--disable-gpu", "--virtual-time-budget=3000",
             "--dump-dom", page.as_uri()],
            capture_output=True, text=True)
    i = proc.stdout.find("BBOX")
    if i < 0:
        sys.exit("could not read label boxes from the browser")
    return json.loads(proc.stdout[i + 4:proc.stdout.index("</title>", i)])


def hex_centers(grid):
    """Hex centers in the same SVG user-unit frame the labels are measured in."""
    px = np.array([hex_svg.axial_to_pixel(q, r, hex_svg.HEX_SIZE) for q, r in grid.grid_hexes])
    x_min = px[:, 0].min() - hex_svg.MARGIN
    y_max = px[:, 1].max() + hex_svg.MARGIN
    pts = np.column_stack([px[:, 0] - x_min, y_max - px[:, 1]])
    owners = np.array([grid.hex_cluster[h] for h in grid.grid_hexes])
    return pts, owners


def fits(cluster_id, box, centers, owners):
    x, y, w, h = box
    gx, gy = np.meshgrid(np.linspace(x, x + w, SAMPLES_X),
                         np.linspace(y, y + h, SAMPLES_Y))
    pts = np.column_stack([gx.ravel(), gy.ravel()])
    d = ((pts[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
    return bool((owners[d.argmin(axis=1)] == cluster_id).all())


def main():
    targets = sys.argv[1:]
    grid = snapshot_grid.load()
    centers, owners = hex_centers(grid)
    if not targets:
        targets = sorted(grid.cluster_size)

    for cluster_id in targets:
        name = display_name(cluster_id)
        lo, hi = 1.0, 3.0
        base_ok = None
        for _ in range(12):
            mid = (lo + hi) / 2 if base_ok is not None else 1.0
            svg = hex_svg.build_svg(grid=grid,
                                    labels=snapshot_grid.load_labels({cluster_id: mid}))
            boxes = measure(svg)
            box = boxes.get(name)
            if box is None:
                sys.exit(f"label {name!r} not found in the rendered SVG")
            ok = fits(cluster_id, box, centers, owners)
            if base_ok is None:
                base_ok = ok
                if not ok:
                    print(f"{cluster_id:32} already spills at 1.0x -- leave it alone")
                    break
                continue
            if ok:
                lo = mid
            else:
                hi = mid
        else:
            print(f"{cluster_id:32} max {lo:.2f}x  -> suggested {lo * SAFETY:.2f}x")


if __name__ == "__main__":
    main()
