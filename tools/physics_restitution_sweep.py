# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The restitution sweep: how much of a bounce of 0.5 Blender's rigid body world keeps, by impact speed and step.

    python tools/physics_restitution_sweep.py > sweep.json                  (needs bpy)
    python tools/physics_restitution_sweep.py --xite X_ITE_DIST > sweep.json   (X_ITE 16.8.1 instead, through
                                                                             tools/physics_record.cjs; needs Node, Playwright)

Each case is tests/physics/fixtures/drop-bounce.x3d with the sphere raised so it meets the floor at the given speed; it is
imported with the add-on (physics on) and run with the rigid body world's sub-steps set per row (1 to 10 a frame at 60
frames a second: steps of 1/60 to 1/600 s). The number reported is the effective coefficient, sqrt(rebound apex / drop
height), against the authored 0.5.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
SPEEDS = (1, 2, 3, 4, 6, 8, 10, 12, 15)
SUBSTEPS = (1, 2, 3, 4, 5, 6, 8, 10)
G = 9.8


def scene_for(speed, folder):
    drop = speed * speed / (2 * G)
    text = (ROOT / "tests" / "physics" / "fixtures" / "drop-bounce.x3d").read_text()
    path = Path(folder) / f"drop-v{speed}.x3d"
    path.write_text(text.replace('position="0 5 0"', f'position="0 {0.5 + drop:.6f} 0"'))
    return str(path), drop


def effective(y, drop, fps=60):
    k = int(math.sqrt(2 * drop / G) * fps) + 1
    return round(math.sqrt(max(max(y[k:]) - 0.5, 0.0) / drop), 3)


def blender_rows(folder):
    from physics_blender_record import _register, record
    _register()
    rows = {}
    for sub in SUBSTEPS:
        row = []
        for v in SPEEDS:
            path, drop = scene_for(v, folder)

            def steps(scene, sub=sub):
                scene.rigidbody_world.substeps_per_frame = sub
            seconds = math.sqrt(2 * drop / G) + v / G + 0.5
            tr = record(path, seconds, 60, after_import=steps)
            row.append(effective([p[1] for p in tr["trajectories"]["S"]["p"]], drop))
        rows[str(sub)] = row
    return rows


def xite_row(folder, xite_dir):
    row = []
    for v in SPEEDS:
        path, drop = scene_for(v, folder)
        seconds = math.sqrt(2 * drop / G) + v / G + 0.5
        out = subprocess.run(["node", str(ROOT / "tools" / "physics_record.cjs"), xite_dir, path, f"{seconds:.3f}", "--runs=1"],
                             capture_output=True, text=True, check=True, env={**os.environ})
        tr = json.loads(out.stdout)
        row.append(effective([p[1] for p in tr["trajectories"]["S"]["p"]], drop))
    return row


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--xite")
    args = ap.parse_args(argv)
    folder = tempfile.mkdtemp(prefix="x3d_restitution_")
    out = {"authored_bounce": 0.5, "impact_speeds_m_s": list(SPEEDS)}
    if args.xite:
        out["x_ite_1_600_s"] = xite_row(folder, args.xite)
    else:
        import bpy
        out["blender"] = {"engine_version": bpy.app.version_string, "rows_by_substeps_at_60_fps": blender_rows(folder)}
    sys.stdout.write(json.dumps(out, indent=1) + "\n")


if __name__ == "__main__":
    main(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else None)
