# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Import every given X3D file with physics on, run its rigid body world for two seconds, and report what came in.

    python tools/physics_corpus_sweep.py [--base DIR] FILE.x3d ... > sweep.json        (needs bpy)

Per file: the operator's result, how many bodies, joints, start-up motors and ROUTE-following constraints the import
made, how many physics and ROUTE losses it reported (and which kinds), errors the importer logged, and whether any body
ended up non-finite or more than 1e6 m away after 120 frames at 60 frames a second (a crash or explosion check, not a
judgement of the motion: the ladder in tools/physics_judge.py is that).
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))


def sweep(files, base=None):
    import bpy
    from physics_blender_record import _register
    _register()
    log = io.StringIO()
    handler = logging.StreamHandler(log)
    handler.setLevel(logging.ERROR)
    logging.getLogger().addHandler(handler)
    out = []
    for f in files:
        log.truncate(0)
        log.seek(0)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        t0 = time.time()
        try:
            result = sorted(bpy.ops.import_scene.x3d(filepath=f))
        except Exception as exc:
            result = ["EXCEPTION: " + str(exc)[:200]]
        scene = bpy.context.scene
        bodies = [o for o in bpy.data.objects if "x3d_rigid_body" in o.keys()]
        losses = json.loads(scene.get("x3d_import_losses", "[]"))
        physics_losses = [r for r in losses if r["kind"] == "physics"]
        far = False
        if scene.rigidbody_world is not None:
            scene.render.fps = 60
            scene.frame_start, scene.frame_end = 1, 121
            scene.rigidbody_world.point_cache.frame_end = 121
            for frame in range(1, 122):
                scene.frame_set(frame)
            far = any(any(v != v or abs(v) > 1e6 for v in o.matrix_world.translation) for o in bodies)
        out.append({
            "file": os.path.relpath(f, base) if base else f, "result": result, "bodies": len(bodies),
            "joints": sum(1 for o in bpy.data.objects if "x3d_rigid_joint" in o.keys()),
            "launch": sum(1 for o in bpy.data.objects if str(o.get("x3d_physics_helper", "")).startswith("launch")),
            "follow_constraints": sum(1 for o in bpy.data.objects for c in o.constraints if c.name.startswith("X3D ROUTE")),
            "physics_losses": len(physics_losses), "route_losses": sum(1 for r in losses if r["kind"] == "route"),
            "loss_kinds": sorted({(r["node"].split()[0], r["detail"].split(":")[0]) for r in physics_losses}),
            "errors": log.getvalue().strip().splitlines()[-3:], "nan_or_far": far, "seconds": round(time.time() - t0, 1),
        })
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--base")
    ap.add_argument("files", nargs="+")
    args = ap.parse_args(argv)
    sys.stdout.write(json.dumps(sweep(args.files, args.base), indent=1) + "\n")


if __name__ == "__main__":
    main(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else None)
