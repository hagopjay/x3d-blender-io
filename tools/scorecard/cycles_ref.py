#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Blender renders of X3D scenes for the scorecard: the Cycles path-traced reference and the EEVEE leg.

Runs inside a Python that has bpy (BPY_PYTHON); the scorecard driver (run.py) calls it as a subprocess, once per leg, with
every scene of the run in ONE process (EEVEE pays about 66 s of shader compile on the first render of a process, so it must
not be paid per scene; Cycles saves its import-module start-up the same way):

    python cycles_ref.py --jobs JOBS.json --addon ADDON_SOURCE_DIR --engine cycles --samples 256 --seeds 0 1 --size 512 --threads 2
    xvfb-run -a python eevee_ref.py --jobs JOBS.json --addon ADDON_SOURCE_DIR        # EEVEE needs a GL context: Mesa llvmpipe under Xvfb

JOBS.json: [{"name", "x3d", "outdir", "view": {position, forward, up, fov[, ortho]} | null, "clear": [r, g, b] (display values),
"headlight": null | "auto" | lux}]. For each job it writes OUTDIR/<stem>.png (stem `ref` for seed 0, `ref_seed1` for seed 1, ... for
Cycles; `eevee` for EEVEE) and prints one `BLENDER_LEG {json}` line per job (also collected in --result FILE), ok or not: a
job that fails (import error, render error) is recorded and the next job still runs.

Conventions, shared with the Castle quality leg's cycles_reference.py (read for this file, not imported from it):
- The add-on is registered the way tools/fidelity_rig/blender_leg.py does it; the X3D is imported with colour space SRGB and the
  add-on's default light units (X_ITE units, calibrated to what X_ITE draws). The importer's own camera is not used.
- Camera from the job's `view` (X3D coordinates, converted with the add-on's own axis conversion); fov is X3D fieldOfView, which
  X3D applies to the SMALLER image side. OrthoViewpoint becomes an orthographic camera with the same extents.
- World: the clear colour, seen by camera rays only; it emits no light (an X3D Background does not light a scene, a Blender world
  does). The colour is a display (sRGB) value, stored linear.
- Headlight: a sun lamp along the view direction, strength = lux (the add-on's convention, the same value the rig gives Babylon.js).
- Colour management: view transform Standard, look None, exposure 0, gamma 1, sRGB display, no dither: display-referred like the
  web renderers. Output 8-bit sRGB PNG, no alpha.
- Cycles: CPU, fixed samples (adaptive off), 12 bounces (Cycles' defaults: indirect light is part of the image, which X_ITE and
  Babylon.js do not have), no denoise, X3D point and spot lights at radius 0 and suns at angle 0 (ideal lights, as in X3D and glTF).
  Two seeds give the reference's own noise floor.
- EEVEE (engine id BLENDER_EEVEE, Blender 5.3): same scene, same camera, light and colour setup; its own screen-space lighting and
  soft shadows with its defaults (64 render samples). It is a rasteriser and is scored against the Cycles image like any other leg.
The JSON lines record settings, versions, add-on commit, seconds and importer warnings."""
import argparse
import contextlib
import importlib
import json
import logging
import math
import os
import re
import subprocess
import sys
import tempfile
import time
import warnings as warnings_mod

TOOL_VERSION = 1
DEFAULT_VIEW = dict(position=[0.0, 0.0, 10.0], forward=[0.0, 0.0, -1.0], up=[0.0, 1.0, 0.0], fov=math.pi / 4)


def srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def addon_commit(addon):
    """(commit, dirty) of the git checkout holding the add-on source folder, or (None, None)."""
    try:
        head = subprocess.run(["git", "-C", addon, "rev-parse", "HEAD"], capture_output=True, text=True, timeout=20)
        if head.returncode == 0:
            st = subprocess.run(["git", "-C", addon, "status", "--porcelain", "--", "."], capture_output=True, text=True, timeout=20)
            return head.stdout.strip(), (bool(st.stdout.strip()) if st.returncode == 0 else None)
    except (OSError, subprocess.SubprocessError):
        pass
    return None, None


class ListHandler(logging.Handler):
    """Collects the importer's WARNING-and-above log records."""
    def __init__(self):
        super().__init__(logging.WARNING)
        self.records = []

    def emit(self, record):
        try:
            self.records.append(record.getMessage())
        except Exception:  # noqa: BLE001 - a logging failure must not fail the job
            pass


def register_addon(addon):
    """Register the add-on from the source folder (symlinked in as io_scene_x3d) exactly like fidelity_rig/blender_leg.py."""
    import bpy
    tmp = tempfile.mkdtemp(prefix="scorecard_ref_")
    os.symlink(os.path.abspath(addon), os.path.join(tmp, "io_scene_x3d"), target_is_directory=True)
    sys.path.insert(0, tmp)
    importlib.import_module("io_scene_x3d").register()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    try:
        importlib.import_module("io_scene_x3d").register()
    except ValueError:
        pass   # still registered (factory reset keeps the class registrations)


def prepare_scene(job, a, handler):
    """Import the X3D, build camera, world, headlight and colour management on a fresh empty scene. Returns (scene, info)."""
    import bpy
    from mathutils import Matrix, Vector
    from bpy_extras.io_utils import axis_conversion
    bpy.ops.wm.read_factory_settings(use_empty=True)
    try:
        importlib.import_module("io_scene_x3d").register()
    except ValueError:
        pass
    sc = bpy.context.scene
    width = height = int(a.size)
    sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = width, height, 100
    sc.frame_start = 0   # the importer puts X3D time 0 on frame_start; the render draws that frame
    handler.records.clear()
    t_imp = time.time()
    res = bpy.ops.import_scene.x3d(filepath=job["x3d"], color_space="SRGB", light_units="X_ITE")
    if res != {"FINISHED"}:
        raise RuntimeError(f"import_scene.x3d returned {res}")
    seconds_import = time.time() - t_imp
    importer_warnings = list(handler.records)

    M = axis_conversion(from_forward="-Z", from_up="Y").to_4x4()
    lights = []
    for ob in sc.objects:
        if ob.type == "LIGHT":
            d = ob.data
            if a.light_size == "ideal":
                if d.type == "SUN":
                    d.angle = 0.0
                else:
                    d.shadow_soft_size = 0.0
            lights.append(dict(name=ob.name, type=d.type, energy=round(d.energy, 5), shadow=bool(d.use_shadow)))
    meshes = [ob for ob in sc.objects if ob.type in ("MESH", "CURVE", "SURFACE", "FONT", "META")]

    view = job.get("view") or DEFAULT_VIEW
    pos = M.to_3x3() @ Vector(view["position"])
    fwd = (M.to_3x3() @ Vector(view["forward"])).normalized()
    up = M.to_3x3() @ Vector(view["up"])
    right = fwd.cross(up).normalized()
    up = right.cross(fwd).normalized()
    cam_matrix = Matrix((right, up, -fwd)).transposed().to_4x4()
    cam_matrix.translation = pos
    cam = bpy.data.cameras.new("scorecard_camera")
    cam.clip_start, cam.clip_end = float(view.get("minZ", 0.01)), float(view.get("maxZ", 10000.0))
    notes = []
    if view.get("ortho"):
        l, b, r, t = view["ortho"]
        cam.type = "ORTHO"
        cam.sensor_fit = "HORIZONTAL" if (r - l) >= (t - b) else "VERTICAL"
        cam.ortho_scale = max(r - l, t - b)
        cam.shift_x, cam.shift_y = 0.5 * (l + r) / cam.ortho_scale, 0.5 * (b + t) / cam.ortho_scale
        if abs((r - l) / (t - b) - 1.0) > 1e-3:
            notes.append("OrthoViewpoint extents are not square; the web legs stretch, Blender cannot")
    else:
        cam.type = "PERSP"
        cam.sensor_fit = "VERTICAL"   # square image: fieldOfView spans the smaller side, which is both
        cam.angle = float(view["fov"])
    cam_ob = bpy.data.objects.new("scorecard_camera", cam)
    sc.collection.objects.link(cam_ob)
    cam_ob.matrix_world = cam_matrix
    sc.camera = cam_ob

    head = job.get("headlight")
    lux = None
    if head == "auto":
        lux = float(sc.get("x3d_headlight_lux") or 1.0)
    elif head is not None:
        lux = float(head)
    if lux:
        sd = bpy.data.lights.new("x3d_headlight", "SUN")
        sd.energy, sd.angle, sd.use_shadow = lux, 0.0, False
        so = bpy.data.objects.new("x3d_headlight", sd)
        sc.collection.objects.link(so)
        so.matrix_world = cam_matrix   # a sun shines along its local -Z, the camera looks along -Z

    clear = [float(c) for c in (job.get("clear") or [0, 0, 0])[:3]]
    world = bpy.data.worlds.new("scorecard_world")
    with warnings_mod.catch_warnings():
        warnings_mod.simplefilter("ignore", DeprecationWarning)   # World.use_nodes goes in Blender 6.0
        world.use_nodes = True
    nt = world.node_tree
    nt.nodes.clear()
    lin = [srgb_to_linear(max(0.0, min(1.0, c))) for c in clear]
    bg_clear = nt.nodes.new("ShaderNodeBackground")
    bg_clear.inputs["Color"].default_value = (*lin, 1.0)
    bg_dark = nt.nodes.new("ShaderNodeBackground")
    bg_dark.inputs["Color"].default_value = (0, 0, 0, 1)
    bg_dark.inputs["Strength"].default_value = 0.0
    lp = nt.nodes.new("ShaderNodeLightPath")
    mix = nt.nodes.new("ShaderNodeMixShader")
    outn = nt.nodes.new("ShaderNodeOutputWorld")
    nt.links.new(lp.outputs["Is Camera Ray"], mix.inputs[0])
    nt.links.new(bg_dark.outputs["Background"], mix.inputs[1])
    nt.links.new(bg_clear.outputs["Background"], mix.inputs[2])
    nt.links.new(mix.outputs["Shader"], outn.inputs["Surface"])
    sc.world = world

    sc.render.film_transparent = False
    sc.render.dither_intensity = 0.0
    sc.render.use_motion_blur = False
    sc.view_settings.view_transform = "Standard"
    sc.view_settings.look = "None"
    sc.view_settings.exposure = 0.0
    sc.view_settings.gamma = 1.0
    sc.view_settings.use_curve_mapping = False
    sc.display_settings.display_device = "sRGB"
    ims = sc.render.image_settings
    ims.file_format, ims.color_mode, ims.color_depth, ims.compression = "PNG", "RGB", "8", 15
    sc.render.threads_mode = "FIXED"
    sc.render.threads = int(a.threads)
    sc.frame_set(sc.frame_start)
    return sc, dict(seconds_import=round(seconds_import, 2), importer_warnings=importer_warnings, lights=len(lights), meshes=len(meshes),
                    headlight_lux=lux, clear=clear, view_source=("job" if job.get("view") else "X3D default (no Viewpoint)"),
                    scene_headlight_lux=sc.get("x3d_headlight_lux"), lighting_model=sc.get("x3d_lighting_model"), notes=notes)


def image_stats(path, clear):
    import numpy as np
    from PIL import Image
    arr = np.asarray(Image.open(path).convert("RGB"), dtype=np.float64)
    bgpx = np.all(np.abs(arr - np.round(np.array(clear) * 255.0)) <= 1.0, axis=-1)
    return dict(size=[arr.shape[1], arr.shape[0]], mean_rgb_0_255=[round(float(v), 3) for v in arr.reshape(-1, 3).mean(0)],
                share_pixels_at_clear_colour=round(float(bgpx.mean()), 4))


def render_to(sc, path):
    import bpy
    sc.render.filepath = path
    t = time.time()
    bpy.ops.render.render(write_still=True)
    seconds = time.time() - t
    if not os.path.exists(path):
        raise RuntimeError("render finished but no PNG was written")
    return seconds


def configure_cycles(sc, a, seed):
    cy = sc.cycles
    sc.render.engine = "CYCLES"
    cy.device = "CPU"
    cy.samples = int(a.samples)
    cy.use_adaptive_sampling = False
    cy.seed = int(seed)
    cy.use_animated_seed = False
    cy.time_limit = 0.0
    cy.use_denoising = False
    return cy


def versions():
    import bpy
    return dict(blender=bpy.app.version_string, python=sys.version.split()[0],
                hash=(bpy.app.build_hash.decode() if isinstance(bpy.app.build_hash, bytes) else str(bpy.app.build_hash)))


def run_job(job, a, handler, first):
    import bpy
    rec = dict(name=job["name"], engine=a.engine, ok=False, error=None, tool="cycles_ref.py", tool_version=TOOL_VERSION)
    os.makedirs(job["outdir"], exist_ok=True)
    t0 = time.time()
    try:
        sc, info = prepare_scene(job, a, handler)
        rec.update(info)
        rec["frames"] = []
        if a.engine == "cycles":
            cy = configure_cycles(sc, a, a.seeds[0])
            for i, seed in enumerate(a.seeds):
                cy.seed = int(seed)
                stem = "ref" if i == 0 else f"ref_seed{seed}"
                path = os.path.join(job["outdir"], stem + ".png")
                if os.path.exists(path):
                    os.remove(path)
                sec = render_to(sc, path)
                rec["frames"].append(dict(file=stem + ".png", seed=int(seed), seconds=round(sec, 2)))
            rec["settings"] = dict(engine="CYCLES", device=cy.device, samples=cy.samples, adaptive=bool(cy.use_adaptive_sampling), seeds=list(a.seeds),
                                   max_bounces=cy.max_bounces, diffuse_bounces=cy.diffuse_bounces, glossy_bounces=cy.glossy_bounces,
                                   transmission_bounces=cy.transmission_bounces, transparent_bounces=cy.transparent_max_bounces,
                                   denoise="none", light_size=a.light_size, light_tree=bool(cy.use_light_tree), threads=sc.render.threads,
                                   size=int(a.size), color_space="SRGB", light_units="X_ITE", view_transform="Standard")
            rec["seconds_render"] = rec["frames"][0]["seconds"]
        else:
            sc.render.engine = "BLENDER_EEVEE"
            ee = sc.eevee
            path = os.path.join(job["outdir"], "eevee.png")
            if os.path.exists(path):
                os.remove(path)
            sec = render_to(sc, path)
            rec["frames"].append(dict(file="eevee.png", seed=None, seconds=round(sec, 2)))
            rec["settings"] = dict(engine=sc.render.engine, taa_render_samples=ee.taa_render_samples, use_shadows=bool(getattr(ee, "use_shadows", True)),
                                   raytracing=bool(getattr(ee, "use_raytracing", False)), light_size=a.light_size, size=int(a.size),
                                   color_space="SRGB", light_units="X_ITE", view_transform="Standard")
            rec["seconds_render"] = round(sec, 2)
            rec["first_render_of_process"] = bool(first)
        rec["image"] = image_stats(os.path.join(job["outdir"], rec["frames"][0]["file"]), info["clear"])
        rec["ok"] = True
    except Exception as exc:   # record it, run the next job
        rec["error"] = f"{type(exc).__name__}: {exc}"[:600]
    rec["seconds_total"] = round(time.time() - t0, 2)
    return rec


def parse_args(argv=None, engine_default="cycles"):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--jobs", required=True)
    p.add_argument("--addon", required=True, help="the add-on source folder (the one that holds __init__.py)")
    p.add_argument("--engine", choices=("cycles", "eevee"), default=engine_default)
    p.add_argument("--samples", type=int, default=256)
    p.add_argument("--seeds", type=int, nargs="+", default=[0, 1])
    p.add_argument("--size", type=int, default=512)
    p.add_argument("--threads", type=int, default=2)
    p.add_argument("--light-size", choices=("ideal", "importer"), default="ideal")
    p.add_argument("--result", help="write all job records here as JSON (default: JOBS.json.result.json)")
    return p.parse_args(argv)


def main(argv=None, engine_default="cycles"):
    a = parse_args(argv, engine_default)
    jobs = json.load(open(a.jobs))
    import bpy
    import addon_utils
    handler = ListHandler()
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.WARNING)
    register_addon(a.addon)
    if a.engine == "cycles":
        addon_utils.enable("cycles")
    commit, dirty = addon_commit(os.path.abspath(a.addon))
    meta = dict(versions(), addon_commit=commit, addon_dirty=dirty,
                addon_version=list(importlib.import_module("io_scene_x3d").bl_info["version"]), engine=a.engine)
    print("BLENDER_META", json.dumps(meta), flush=True)
    out_path = a.result or a.jobs + ".result.json"
    results = []
    for i, job in enumerate(jobs):
        rec = run_job(job, a, handler, first=(i == 0))
        rec["meta"] = meta
        results.append(rec)
        print("BLENDER_LEG", json.dumps(rec), flush=True)
        json.dump(dict(meta=meta, results=results), open(out_path, "w"), indent=1)   # incremental: a crash keeps what was done
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)   # Blender's module teardown can crash after good renders; the PNGs and JSON are on disk
