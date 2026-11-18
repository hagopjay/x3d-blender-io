# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Demo scenes for the Blender-to-splat path: the still life as a mesh and as a surface-seeded splat set.

The splats are NOT trained. They are sampled on the mesh surface (seeded, area-weighted), each a flat disc tangent to the
surface, coloured by the material's base colour times a baked Lambert term from the sun. That is the seed a trainer would
start from (tools/splat_capture.py writes the same kind of points); the demo shows what the add-on does with a splat object
(write a KHR_gaussian_splatting glb, reference it with an Inline), not what a trainer would return.

    python tools/splat_demo.py <out dir> [--count 20000]
"""

from __future__ import annotations

import importlib
import json
import math
import os
import random
import sys
import tempfile
from pathlib import Path

SOURCE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source")
TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))


def register_extension():
    package_dir = Path(tempfile.mkdtemp(prefix="x3d_splat_demo_")) / "io_scene_x3d"
    package_dir.symlink_to(SOURCE_DIR, target_is_directory=True)
    sys.path.insert(0, str(package_dir.parent))
    importlib.import_module("io_scene_x3d").register()


def surface_splats(count, *, seed=7):
    import bpy
    from mathutils import Vector

    sys.path.insert(0, SOURCE_DIR)
    from ir import IRGaussianSplats
    from splat_io import rgb_to_sh0

    rng = random.Random(seed)
    sun = [o for o in bpy.context.scene.objects if o.type == "LIGHT" and o.data.type == "SUN"][0]
    to_sun = (sun.matrix_world.to_3x3() @ Vector((0, 0, 1))).normalized()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    triangles = []
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        mesh.calc_loop_triangles()
        base = (0.8, 0.8, 0.8)
        if obj.data.materials and obj.data.materials[0]:
            base = tuple(obj.data.materials[0].node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value[:3])
        normal_matrix = obj.matrix_world.to_3x3()
        for tri in mesh.loop_triangles:
            points = [obj.matrix_world @ mesh.vertices[i].co for i in tri.vertices]
            normal = (normal_matrix @ tri.normal).normalized()
            area = ((points[1] - points[0]).cross(points[2] - points[0])).length / 2
            if area > 1e-9:
                triangles.append((area, points, normal, base))
        evaluated.to_mesh_clear()
    total = sum(t[0] for t in triangles)
    weights = [t[0] / total for t in triangles]
    spacing = math.sqrt(total / count)
    splats = IRGaussianSplats(name="StillLifeSplats")
    for area, points, normal, base in rng.choices(triangles, weights=weights, k=count):
        u, v = rng.random(), rng.random()
        if u + v > 1:
            u, v = 1 - u, 1 - v
        point = points[0] + (points[1] - points[0]) * u + (points[2] - points[0]) * v
        quat = normal.to_track_quat("Z", "Y")                       # local Z along the surface normal
        shade = 0.25 + 0.75 * max(0.0, normal.dot(to_sun))
        splats.positions.append(tuple(point))
        splats.scales.append((spacing * 0.65, spacing * 0.65, spacing * 0.07))
        splats.orientations.append((quat.x, quat.y, quat.z, quat.w))
        splats.opacities.append(1.0)
        splats.sh.setdefault((0, 0), []).append(rgb_to_sh0(tuple(min(1.0, c * shade) for c in base)))
    return splats, {"triangles": len(triangles), "area_m2": round(total, 4), "spacing_m": round(spacing, 5)}


def splat_object(splats):
    import bpy

    mesh = bpy.data.meshes.new("StillLifeSplats")
    mesh.from_pydata([tuple(p) for p in splats.positions], [], [])
    mesh.update()
    mesh["x3d_gaussian_splats"] = True
    mesh["x3d_splat_color_space"] = "SRGB_REC709_DISPLAY"
    scale = mesh.attributes.new("splat_scale", "FLOAT_VECTOR", "POINT")
    scale.data.foreach_set("vector", [c for s in splats.scales for c in s])
    rotation = mesh.attributes.new("splat_rotation", "QUATERNION", "POINT")
    rotation.data.foreach_set("value", [c for (x, y, z, w) in splats.orientations for c in (w, x, y, z)])
    opacity = mesh.attributes.new("splat_opacity", "FLOAT", "POINT")
    opacity.data.foreach_set("value", splats.opacities)
    attr = mesh.attributes.new("splat_sh0_0", "FLOAT_VECTOR", "POINT")
    attr.data.foreach_set("vector", [c for v in splats.sh[(0, 0)] for c in v])
    obj = bpy.data.objects.new("StillLifeSplats", mesh)
    obj["x3d_splat_glb"] = True
    bpy.context.scene.collection.objects.link(obj)
    return obj


def main():
    import bpy

    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    out = os.path.abspath(argv[0])
    os.makedirs(out, exist_ok=True)
    count = int(argv[argv.index("--count") + 1]) if "--count" in argv else 30000
    sys.path.insert(0, TOOLS_DIR)
    from splat_capture import build_still_life

    register_extension()
    build_still_life()
    cam = bpy.data.objects.new("Overview", bpy.data.cameras.new("Overview"))
    cam.location = (6.4, -7.0, 4.6)
    cam.rotation_euler = (math.radians(63), 0, math.radians(42))
    bpy.context.scene.collection.objects.link(cam)

    def export(name, hide):
        for obj in bpy.context.scene.objects:
            if obj.type == "MESH":
                obj.hide_viewport = hide(obj)
        path = os.path.join(out, name)
        result = bpy.ops.export_scene.x3d(filepath=path, x3d_version="X3D41", use_selection=False, use_visible=True)
        assert result == {"FINISHED"}, result
        return os.path.getsize(path)

    splats, stats = surface_splats(count)
    splat_obj = splat_object(splats)
    receipt = {"blender": bpy.app.version_string, "splats": count, "seed": 7, **stats}
    receipt["mesh_x3d_bytes"] = export("still-life-mesh.x3d", lambda o: o is splat_obj)
    receipt["splat_x3d_bytes"] = export("still-life-splats.x3d", lambda o: o is not splat_obj)
    receipt["splat_glb_bytes"] = os.path.getsize(os.path.join(out, "StillLifeSplats.splats.glb"))
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out, "still-life.blend"))
    with open(os.path.join(out, "receipt.json"), "w") as handle:
        json.dump(receipt, handle, indent=1)
    print(receipt)


if __name__ == "__main__":
    main()
