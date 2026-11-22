# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Same renderer, two exporters: X_ITE draws this add-on's X3D and Blender's own glb of the same frozen scene.

    cd tools/fidelity_rig && npm ci
    python same_renderer.py [--source ../../source] [--scenes a,b] [--out out/same] [--baseline FILE] [--write-baseline]

(run with a Python that has bpy, numpy and pillow: the bpy 5.3.0 wheel.)

The existing gate (compare.py, gate.py) asks "does X_ITE on our X3D look like Babylon.js on our glb": two renderers, one
exporter. This judge holds the renderer fixed and changes the exporter (v3 plan, Gate 2): for each scene of
tests/frozen_scenes.py it writes

  addon.x3d    this add-on's X3D 4.0 export (defaults, x3d_version X3D40); addon_view.x3d adds the judge's Viewpoint
  blender.glb  Blender's own glTF exporter (io_scene_gltf2 that ships with Blender; defaults plus export_lights=True
               and lighting mode COMPAT, see LIGHTING)
  blender.x3d  addon.x3d with every Shape and light removed and <Inline url="blender.glb"/> added, so the Viewpoint,
               NavigationInfo and Background are the same bytes in both and only geometry, materials and lights differ;
               both bind the same judge Viewpoint, framed on the export's world bounding box (judge_view)

and renders both with X_ITE 16.7.1 in the rig's headless Chromium (render.mjs, xiteOnly jobs, 512 x 512, SwiftShader).
Reported per scene: mean |delta| per pixel (0-255, RGB) and the share of pixels whose largest channel delta is over 24.

The tolerance is written before the gate is used (--write-baseline: the measured value x 1.5 + 2 per scene, so the
numbers are calibration, not a target), and the gate fails a scene whose delta grows past its tolerance. A planted
fault (tools/oracles/plants.json "basecolour-channels-swapped") must fail it.
"""
from __future__ import annotations

import argparse
import importlib
import json
import math
import os
import subprocess
import sys
import tempfile
import time
import warnings
import xml.etree.ElementTree as ET
from pathlib import Path

warnings.filterwarnings("ignore", category=DeprecationWarning)
RIG = Path(__file__).resolve().parent
REPO = RIG.parents[1]
BASELINE = RIG / "same-renderer-baseline.json"
# Blender's glTF exporter defaults to "SPEC" (physical units: a 0.8 W/m2 sun is written as 546.4 lux, 0.8 x 683), and
# X_ITE takes a KHR_lights_punctual intensity as X3D intensity, so every lit surface saturates to white (measured
# 22 Nov 2026: mean |delta| 68 on lit_cube). "COMPAT" writes the sun's W/m2 as lux and a point light's W / (4 pi) as
# candela, the convention the add-on's own glb leg uses (tools/fidelity_rig/README.md); the judge compares like units.
LIGHTING = os.environ.get("SAME_RENDERER_GLTF_LIGHTING", "COMPAT")
REMOVE = {"Shape", "DirectionalLight", "PointLight", "SpotLight", "EnvironmentLight"}
sys.path.insert(0, str(REPO / "tests"))


def register(source):
    tmp = tempfile.mkdtemp(prefix="same_addon_")
    (Path(tmp) / "io_scene_x3d").symlink_to(Path(source).resolve(), target_is_directory=True)
    sys.path.insert(0, tmp)
    addon = importlib.import_module("io_scene_x3d")
    try:
        addon.register()
    except ValueError:
        pass


def judge_view(addon_x3d: Path) -> ET.Element:
    """One Viewpoint that frames the scene's world bounding box from above, front and right (the same for both legs).

    Most frozen scenes have no camera, and X3D's default view (0 0 10 looking down -Z) sees the uv_grid and four_lights
    floors edge-on: both legs would draw black and agree about nothing. The judge's own view binds first in both files."""
    sys.path.insert(0, str(REPO / "tools" / "io_sync"))
    import invariants

    box = invariants.measure(addon_x3d.read_bytes())["bbox"] or [[-1, -1, -1], [1, 1, 1]]
    centre = [(a + b) / 2 for a, b in zip(*box)]
    radius = max(0.5, math.dist(box[0], box[1]) / 2)
    fov = 0.785398
    distance = radius / math.tan(fov / 2) * 1.25
    direction = [0.55, 0.6, 0.58]
    n = math.sqrt(sum(v * v for v in direction))
    pos = [c + distance * v / n for c, v in zip(centre, direction)]
    f = [c - q for c, q in zip(centre, pos)]
    fl = math.sqrt(sum(v * v for v in f))
    f = [v / fl for v in f]
    r = [f[1] * 0 - f[2] * 1, f[2] * 0 - f[0] * 0, f[0] * 1 - f[1] * 0]      # f x (0, 1, 0)
    rl = math.sqrt(sum(v * v for v in r))
    r = [v / rl for v in r]
    u = [r[1] * f[2] - r[2] * f[1], r[2] * f[0] - r[0] * f[2], r[0] * f[1] - r[1] * f[0]]
    m = [[r[0], u[0], -f[0]], [r[1], u[1], -f[1]], [r[2], u[2], -f[2]]]   # columns: camera x, y, z (looks down -z)
    angle = math.acos(max(-1.0, min(1.0, (m[0][0] + m[1][1] + m[2][2] - 1) / 2)))
    axis = [m[2][1] - m[1][2], m[0][2] - m[2][0], m[1][0] - m[0][1]]
    al = math.sqrt(sum(v * v for v in axis)) or 1.0
    return ET.Element("Viewpoint", {"DEF": "JudgeView", "description": "same-renderer judge",
                                    "position": " ".join(f"{v:.5f}" for v in pos),
                                    "orientation": " ".join(f"{v / al:.6f}" for v in axis) + f" {angle:.6f}",
                                    "fieldOfView": f"{fov}"})


def with_view(addon_x3d: Path, view: ET.Element) -> str:
    _, _, body = addon_x3d.read_text(encoding="utf-8").partition("<X3D")
    root = ET.fromstring("<X3D" + body)
    root.find("Scene").insert(0, view)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


def wrapper(addon_x3d: Path, glb_name: str, view: ET.Element) -> str:
    text = addon_x3d.read_text(encoding="utf-8")
    head, _, body = text.partition("<X3D")
    root = ET.fromstring("<X3D" + body)
    scene = root.find("Scene")
    removed = 0

    def prune(parent):
        nonlocal removed
        for child in list(parent):
            if child.tag in REMOVE:
                parent.remove(child)
                removed += 1
            else:
                prune(child)
    prune(scene)
    # ROUTEs into removed nodes would be errors in X_ITE; the frozen scenes have none, but stay safe
    gone = {el.get("DEF") for el in ET.fromstring("<X3D" + body).iter() if el.tag in REMOVE and el.get("DEF")}
    for route in list(scene.findall("ROUTE")):
        if route.get("toNode") in gone or route.get("fromNode") in gone:
            scene.remove(route)
    inline = ET.Element("Inline", {"DEF": "BlenderGlb", "url": f'"{glb_name}"'})
    scene.insert(0, inline)
    scene.insert(0, view)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


def export_all(names, out: Path):
    import bpy
    import frozen_scenes

    for name in names:
        folder = out / name
        folder.mkdir(parents=True, exist_ok=True)
        for stale in folder.rglob("*"):     # an earlier run's frames must not be read as this run's
            if stale.is_file():
                stale.unlink()
        frozen_scenes.build(name)
        x3d = folder / "addon.x3d"
        assert bpy.ops.export_scene.x3d(filepath=str(x3d), x3d_version="X3D40", use_selection=False) == {"FINISHED"}
        glb = folder / "blender.glb"
        assert bpy.ops.export_scene.gltf(filepath=str(glb), export_format="GLB", export_lights=True,
                                         export_import_convert_lighting_mode=LIGHTING) == {"FINISHED"}
        view = judge_view(x3d)
        (folder / "addon_view.x3d").write_text(with_view(x3d, view), encoding="utf-8")
        (folder / "blender.x3d").write_text(wrapper(x3d, "blender.glb", view), encoding="utf-8")
        print(f"[same-renderer] {name}: addon.x3d {x3d.stat().st_size:,} B, blender.glb {glb.stat().st_size:,} B")


def render(names, out: Path):
    jobs = []
    for name in names:
        for leg, file in (("addon", "addon_view.x3d"), ("blender", "blender.x3d")):
            jobs.append({"name": f"{name}:{leg}", "x3d": str((out / name / file).resolve()), "glb": None,
                         "clear": [0, 0, 0], "headlight": None, "xiteOnly": True,
                         "outdir": str((out / name / leg).resolve())})
    job_file = out / "jobs.json"
    job_file.write_text(json.dumps(jobs, indent=1))
    t0 = time.time()
    proc = subprocess.run(["node", str(RIG / "render.mjs"), str(job_file), "--strict"], capture_output=True, text=True,
                          cwd=RIG, timeout=1800)
    for line in proc.stdout.splitlines():
        if line.startswith(("BROWSER", "X_ITE", "xite fail", "FAILED")):
            print(f"[same-renderer] {line}")
    print(f"[same-renderer] rendered {len(jobs)} X_ITE frames in {time.time() - t0:.0f} s")
    if proc.returncode:
        print(proc.stdout[-2000:] + proc.stderr[-2000:])
        raise SystemExit("[same-renderer] render.mjs failed")


def compare(names, out: Path) -> dict:
    import numpy as np
    from PIL import Image

    results = {}
    for name in names:
        a = np.asarray(Image.open(out / name / "addon" / "xite.png").convert("RGB"), dtype=np.int16)
        b = np.asarray(Image.open(out / name / "blender" / "xite.png").convert("RGB"), dtype=np.int16)
        d = np.abs(a - b)
        drawn = (a.max(axis=2) > 8) | (b.max(axis=2) > 8)
        results[name] = {"mean_abs_delta": round(float(d.mean()), 2),
                         "drawn_addon": round(float((a.max(axis=2) > 8).mean()), 4),
                         "drawn_blender": round(float((b.max(axis=2) > 8).mean()), 4),
                         "delta_where_drawn": round(float(d[drawn].mean()) if drawn.any() else 0.0, 2),
                         "pixels_over_24": round(float((d.max(axis=2) > 24).mean()), 4)}
        Image.fromarray(np.clip(d * 4, 0, 255).astype("uint8")).save(out / name / "diff_x4.png")
        for leg in ("addon", "blender"):
            log = out / name / leg / "xite_console.txt"
            errors = [l for l in log.read_text().splitlines() if l.startswith("error")] if log.exists() else []
            if errors:
                results[name][f"{leg}_console_errors"] = len(errors)
    return results


def main(argv):
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    elif argv[:1] and argv[0].endswith(".py"):
        argv = argv[1:]
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--source", default=str(REPO / "source"))
    p.add_argument("--scenes", default="")
    p.add_argument("--out", default=str(RIG / "out" / "same"))
    p.add_argument("--baseline", default=str(BASELINE))
    p.add_argument("--write-baseline", action="store_true")
    args = p.parse_args(argv)
    register(args.source)
    import bpy
    import frozen_scenes

    names = [n for n in (args.scenes.split(",") if args.scenes else frozen_scenes.SCENES) if n]
    out = Path(args.out)
    export_all(names, out)
    render(names, out)
    results = compare(names, out)
    tools = {"blender": bpy.app.version_string, "gltf_lighting_mode": LIGHTING, "x_ite": "16.7.1 (tools/fidelity_rig/package-lock.json)",
             "gltf_exporter": ".".join(str(v) for v in importlib.import_module("io_scene_gltf2").bl_info["version"])}
    (out / "results.json").write_text(json.dumps({"tools": tools, "scenes": results}, indent=1))
    baseline_path = Path(args.baseline)
    if args.write_baseline:
        baseline = {"schema": "x3d-blender-io.same-renderer/1",
                    "about": "Tolerances for X_ITE on the add-on's X3D vs X_ITE on Blender's own glb, per frozen scene: "
                             "measured mean |delta| x 1.5 + 2, written before the gate was used (calibration run).",
                    "measured_with": tools,
                    "scenes": {n: {"measured": r["mean_abs_delta"], "tolerance": round(r["mean_abs_delta"] * 1.5 + 2, 2),
                                   "pixels_over_24": r["pixels_over_24"]} for n, r in results.items()}}
        baseline_path.write_text(json.dumps(baseline, indent=1) + "\n")
        print(f"[same-renderer] wrote {baseline_path}")
    baseline = json.loads(baseline_path.read_text()) if baseline_path.exists() else {"scenes": {}}
    failures = []
    for name, r in results.items():
        tol = baseline["scenes"].get(name, {}).get("tolerance")
        verdict = "no tolerance yet" if tol is None else ("ok" if r["mean_abs_delta"] <= tol else "OVER TOLERANCE")
        if tol is not None and r["mean_abs_delta"] > tol:
            failures.append(name)
        if r["drawn_addon"] < 0.005:   # a judge that compares two black frames agrees about nothing
            verdict = "ADD-ON FRAME BLANK"
            failures.append(name)
        print(f"[same-renderer] {name:18} mean |delta| {r['mean_abs_delta']:6.2f}  where drawn {r['delta_where_drawn']:6.2f}  "
              f"over-24 {r['pixels_over_24']:6.1%}  drawn add-on {r['drawn_addon']:6.1%} glb {r['drawn_blender']:6.1%}  "
              f"tolerance {tol}  {verdict}")
    print(f"[same-renderer] Blender {tools['blender']}, glTF exporter {tools['gltf_exporter']}, X_ITE 16.7.1: "
          f"{len(results) - len(failures)} of {len(results)} within tolerance"
          + (f"; OVER TOLERANCE: {', '.join(failures)}" if failures else ""))
    return 1 if failures and not args.write_baseline else 0


if __name__ == "__main__":
    code = main(sys.argv)
    sys.stdout.flush()
    os._exit(code)
