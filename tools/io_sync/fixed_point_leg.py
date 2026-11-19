# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Blender leg of the import/export fixed-point check.

    blender -b --factory-startup -noaudio --python tools/io_sync/fixed_point_leg.py -- OUT_DIR \
        [--export '{"use_normals": true}'] [--import '{"color_space": "AS_IS"}'] IN.x3d [IN2.x3d ...]

For each input file E0 (normally a file this add-on exported), in a fresh empty scene each time:
    import E0 -> snapshot S1 -> export E1 -> (fresh) import E1 -> snapshot S2 -> export E2
with the given operator options (default: the add-on's defaults, X3D 4.0). Pass the options the input was exported
with, or E0 -> E1 reports option differences as losses. Writes OUT_DIR/<stem>/{e1.x3d,e2.x3d,s1.json,s2.json,log.txt}.

E0 -> E1 is what one round trip loses or changes; E1 -> E2 must be empty (the round trip converges in one step).
S1 -> S2 records a partial Blender-scene snapshot for diagnosis. The driver currently gates only the X3D diff.
"""
from __future__ import annotations

import io
import json
import sys
import traceback
from contextlib import redirect_stdout
from pathlib import Path

import bpy

REPO = Path(__file__).resolve().parents[2]
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
out_root = Path(argv[0])
EXPORT_OPTS = {"x3d_version": "X3D40", "use_selection": False}
IMPORT_OPTS = {}
rest = argv[1:]
inputs = []
while rest:
    a = rest.pop(0)
    if a == "--export":
        EXPORT_OPTS.update(json.loads(rest.pop(0)))
    elif a == "--import":
        IMPORT_OPTS.update(json.loads(rest.pop(0)))
    else:
        inputs.append(Path(a))


def register():
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    (tmp / "io_scene_x3d").symlink_to(REPO / "source", target_is_directory=True)
    sys.path.insert(0, str(tmp))
    import importlib
    importlib.import_module("io_scene_x3d").register()


def fresh():
    # registered operators survive a factory reset (the tests rely on it too)
    bpy.ops.wm.read_factory_settings(use_empty=True)


def r(v, n=5):
    return [round(float(x), n) for x in v]


def socket_value(node, name):
    s = node.inputs.get(name)
    if s is None or s.is_linked:
        return "linked" if s is not None else None
    v = s.default_value
    try:
        return r(v)
    except TypeError:
        return round(float(v), 5)


def snapshot() -> dict:
    objs = {}
    for ob in sorted(bpy.data.objects, key=lambda o: o.name):
        d = {"type": ob.type, "parent": ob.parent.name if ob.parent else None,
             "matrix_world": [r(row, 4) for row in ob.matrix_world],
             "hide_render": ob.hide_render}
        if ob.type == "MESH":
            me = ob.data
            d["mesh"] = {"v": len(me.vertices), "e": len(me.edges), "f": len(me.polygons), "loops": len(me.loops),
                         "uv": [l.name for l in me.uv_layers], "attrs": sorted(a.name for a in me.attributes
                                                                                if not a.name.startswith(".")),
                         "materials": [m.name if m else None for m in me.materials],
                         "smooth": sum(1 for p in me.polygons if p.use_smooth)}
        elif ob.type == "LIGHT":
            li = ob.data
            d["light"] = {"type": li.type, "color": r(li.color), "energy": round(li.energy, 4),
                          "shadow": li.use_shadow}
            if li.type == "SPOT":
                d["light"]["spot"] = [round(li.spot_size, 4), round(li.spot_blend, 4)]
        elif ob.type == "CAMERA":
            c = ob.data
            d["camera"] = {"type": c.type, "angle": round(c.angle, 4), "ortho": round(c.ortho_scale, 4),
                           "clip": [round(c.clip_start, 4), round(c.clip_end, 4)]}
        elif ob.type == "EMPTY":
            d["empty"] = {"instance": ob.instance_collection.name if ob.instance_collection else None}
        if ob.animation_data and ob.animation_data.action:
            act = ob.animation_data.action
            curves = []
            try:
                fcs = list(act.fcurves)
            except AttributeError:  # Blender 5 layered actions
                fcs = [fc for layer in act.layers for strip in layer.strips for bag in strip.channelbags
                       for fc in bag.fcurves]
            for fc in fcs:
                curves.append((fc.data_path, fc.array_index, len(fc.keyframe_points)))
            d["anim"] = sorted(curves)
        objs[ob.name] = d
    mats = {}
    for m in sorted(bpy.data.materials, key=lambda m: m.name):
        md = {"blend": getattr(m, "surface_render_method", None), "backface": m.use_backface_culling}
        if m.node_tree:
            md["nodes"] = sorted(n.bl_idname for n in m.node_tree.nodes)
            bsdf = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
            if bsdf:
                for k in ("Base Color", "Metallic", "Roughness", "Alpha", "Emission Color", "Emission Strength",
                          "IOR", "Transmission Weight", "Specular IOR Level", "Coat Weight", "Sheen Weight"):
                    md[k] = socket_value(bsdf, k)
        mats[m.name] = md
    world = bpy.context.scene.world
    return {"objects": objs, "materials": mats,
            "images": sorted(i.name for i in bpy.data.images if i.type == "IMAGE"),
            "world": world.name if world else None,
            "frame_range": [bpy.context.scene.frame_start, bpy.context.scene.frame_end],
            "fps": bpy.context.scene.render.fps,
            "counts": {k: len(getattr(bpy.data, k)) for k in ("objects", "meshes", "materials", "lights", "cameras",
                                                             "actions", "images", "armatures", "collections")}}


def step(src: Path, dst: Path, snap: Path, log):
    fresh()
    buf = io.StringIO()
    with redirect_stdout(buf):
        res = bpy.ops.import_scene.x3d(filepath=str(src), **IMPORT_OPTS)
    log.write(f"import {src.name}: {res}\n{buf.getvalue()[-4000:]}\n")
    if res != {"FINISHED"}:
        raise RuntimeError(f"import did not finish: {res}")
    snap.write_text(json.dumps(snapshot(), indent=1, sort_keys=True))
    buf = io.StringIO()
    with redirect_stdout(buf):
        res = bpy.ops.export_scene.x3d(filepath=str(dst), **EXPORT_OPTS)
    log.write(f"export {dst.name}: {res}\n{buf.getvalue()[-4000:]}\n")
    if res != {"FINISHED"}:
        raise RuntimeError(f"export did not finish: {res}")


if not inputs:
    raise SystemExit("at least one input file is required")
register()
failed = False
for src in inputs:
    od = out_root / (src.parent.name + "__" + src.stem)
    od.mkdir(parents=True, exist_ok=True)
    with open(od / "log.txt", "w") as log:
        try:
            step(src, od / "e1.x3d", od / "s1.json", log)
            step(od / "e1.x3d", od / "e2.x3d", od / "s2.json", log)
            print("ok", src, flush=True)
        except Exception:
            failed = True
            log.write(traceback.format_exc())
            print("FAIL", src, traceback.format_exc().splitlines()[-1], flush=True)

if failed:
    raise SystemExit(1)
