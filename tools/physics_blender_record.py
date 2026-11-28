# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Record what Blender's rigid body world does with an imported X3D RigidBodyPhysics scene, frame by frame, in the same
trace format as tools/physics_record.cjs (X_ITE), so tools/physics_judge.py can compare them.

    python tools/physics_blender_record.py file.x3d SECONDS [--fps 60] [--runs 2] > trace.json      (needs bpy)

The scene is imported with the add-on's operator (default options: physics on), the scene's frame rate is set to --fps
(the physics step stays 1 / (60 x iterations) s; see source/physics_blender.py), and every body's world matrix is read at
every frame and turned back into the file's coordinates (Y up), so the numbers read like X_ITE's. Each frame's state is
hashed (FNV-1a over float32 position and quaternion; Blender does not give velocities to Python) and --runs imports the
file again into a fresh scene and compares.
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))


def _register():
    from test_roundtrip_bpy import _register_extension
    return _register_extension(tempfile.mkdtemp(prefix="x3d_physics_rec_"))


def fnv1a(data: bytes) -> int:
    h = 0x811C9DC5
    for b in data:
        h ^= b
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def record(path: str, seconds: float, fps: int, options=None):
    import bpy
    from mathutils import Matrix
    from bpy_extras.io_utils import axis_conversion
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.fps, scene.render.fps_base = fps, 1.0
    steps = int(round(seconds * fps))
    scene.frame_start, scene.frame_end = 1, 1 + steps
    result = bpy.ops.import_scene.x3d(filepath=path, **(options or {}))
    if result != {"FINISHED"}:
        raise RuntimeError(f"import failed: {result}")
    world = scene.rigidbody_world
    if world is None:
        raise RuntimeError("the import made no rigid body world")
    world.point_cache.frame_start, world.point_cache.frame_end = 1, 1 + steps
    to_file = axis_conversion(from_forward="-Z", from_up="Y").to_4x4().inverted()   # the operator's default axes
    bodies = sorted((ob for ob in bpy.data.objects if "x3d_rigid_body" in ob.keys()),
                    key=lambda ob: json.loads(ob["x3d_rigid_body"])["name"])
    names = [json.loads(ob["x3d_rigid_body"])["name"] for ob in bodies]
    trajectories = {n: {"p": [], "q": []} for n in names}
    hashes = []
    for frame in range(1, steps + 2):
        scene.frame_set(frame)
        packed = b""
        for ob, name in zip(bodies, names):
            m = to_file @ ob.matrix_world
            t, q, _s = m.decompose()
            p = [t.x, t.y, t.z]
            quat = [q.x, q.y, q.z, q.w]
            trajectories[name]["p"].append(p)
            trajectories[name]["q"].append(quat)
            packed += struct.pack("<7f", *p, *quat)
        hashes.append(fnv1a(packed))
    info = {"substeps_per_frame": world.substeps_per_frame, "solver_iterations": world.solver_iterations,
            "gravity": list(scene.gravity), "losses": json.loads(scene.get("x3d_import_losses", "[]")),
            "launch_constraints": sum(1 for ob in bpy.data.objects if str(ob.get("x3d_physics_helper", "")).startswith("launch")),
            "joints": sum(1 for ob in bpy.data.objects if "x3d_rigid_joint" in ob.keys())}
    return {"bodies": names, "trajectories": trajectories, "hashes": hashes, "steps": steps, "info": info}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("seconds", type=float)
    ap.add_argument("--fps", type=int, default=60)
    ap.add_argument("--runs", type=int, default=2)
    args = ap.parse_args(argv)
    import bpy
    _register()
    runs = [record(os.path.abspath(args.file), args.seconds, args.fps) for _ in range(max(1, args.runs))]
    first = runs[0]
    replays = []
    for r in runs[1:]:
        diff = [i for i, (a, b) in enumerate(zip(first["hashes"], r["hashes"])) if a != b]
        replays.append({"mismatches": len(diff), "first_mismatch": diff[0] if diff else None})
    out = {"schema": "x3d-blender-io.physics-trace/1", "engine": "blender", "engine_version": bpy.app.version_string,
           "file": os.path.basename(args.file), "fps": args.fps, "dt": 1.0 / args.fps, "steps": first["steps"],
           "bodies": first["bodies"], "info": first["info"], "replays": replays, "hashes": first["hashes"],
           "trajectories": first["trajectories"]}
    sys.stdout.write(json.dumps(out))


if __name__ == "__main__":
    main(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else None)
