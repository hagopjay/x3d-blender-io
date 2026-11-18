# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Blender as the training-image source for Gaussian splats: Fibonacci-sphere cameras, renders, transforms.json.

A synthetic scene has no capture noise and known poses, so it needs no structure-from-motion step: this writes the images
and a NeRF-synthetic style ``transforms_train.json`` / ``transforms_test.json`` (``camera_angle_x`` plus a camera-to-world
matrix per frame, OpenGL convention, which is Blender's own camera matrix) that 3DGS-family trainers read directly, and a
``points3d.ply`` of surface points to seed them. The splat file the trainer returns then comes back through this add-on
(``x3d_splat_glb``, or the X3D 4.1 GaussianSplats node), and the X3D validator and the render diff check it: the loop
Blender scene → cameras → images → splats → X3D → validator.

    python tools/splat_capture.py <out dir> [--views 48] [--size 256] [--samples 32] [--hemisphere] [--blend scene.blend]

Without ``--blend`` it builds a small still life. Pure helpers (``fibonacci_directions``, ``look_at``) need no ``bpy``.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

GOLDEN_ANGLE = math.pi * (3.0 - math.sqrt(5.0))


def fibonacci_directions(count: int, *, hemisphere: bool = False):
    """``count`` unit vectors spread evenly over the sphere (or the upper hemisphere, z >= 0) by the golden-angle spiral."""
    directions = []
    for index in range(count):
        if hemisphere:
            z = (index + 0.5) / count                      # 0..1: skip the exact equator and pole
        else:
            z = 1.0 - 2.0 * (index + 0.5) / count          # +1..-1 without hitting the poles exactly
        ring = math.sqrt(max(0.0, 1.0 - z * z))
        angle = GOLDEN_ANGLE * index
        directions.append((ring * math.cos(angle), ring * math.sin(angle), z))
    return directions


def look_at(eye, target, up=(0.0, 0.0, 1.0)):
    """Camera-to-world 4x4 (row lists) for a camera at ``eye`` looking at ``target``: -Z forward, +Y up (Blender, OpenGL)."""
    forward = _normalize([t - e for t, e in zip(target, eye)])
    right = _cross(forward, up)
    if _length(right) < 1e-9:                              # looking straight along up
        right = _cross(forward, (0.0, 1.0, 0.0))
    right = _normalize(right)
    true_up = _cross(right, forward)
    columns = (right, true_up, [-component for component in forward], eye)
    return [[columns[column][row] for column in range(4)] for row in range(3)] + [[0.0, 0.0, 0.0, 1.0]]


def _cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def _length(v):
    return math.sqrt(sum(c * c for c in v))


def _normalize(v):
    length = _length(v)
    return [c / length for c in v]


def camera_poses(count, *, radius, target=(0.0, 0.0, 0.0), hemisphere=False):
    return [look_at([t + radius * d for t, d in zip(target, direction)], target)
            for direction in fibonacci_directions(count, hemisphere=hemisphere)]


def transforms_json(poses, *, angle_x, prefix, size):
    return {"camera_angle_x": angle_x, "w": size, "h": size,
            "frames": [{"file_path": f"./{prefix}/r_{index:03d}", "transform_matrix": pose}
                       for index, pose in enumerate(poses)]}


# ---------------------------------------------------------------------------- Blender side


def build_still_life():
    import bpy

    bpy.ops.wm.read_factory_settings(use_empty=True)

    def material(name, rgb, metallic=0.0, roughness=0.5):
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes["Principled BSDF"]
        bsdf.inputs["Base Color"].default_value = (*rgb, 1.0)
        bsdf.inputs["Metallic"].default_value = metallic
        bsdf.inputs["Roughness"].default_value = roughness
        return mat

    for kind, loc, mat in (("cube", (-0.5, 0, 0.5), material("Red", (0.8, 0.1, 0.1))),
                           ("uv_sphere", (0.7, 0.3, 0.45), material("Gold", (0.9, 0.7, 0.2), 1.0, 0.3)),
                           ("cone", (0.1, -0.8, 0.5), material("Green", (0.1, 0.6, 0.2)))):
        getattr(bpy.ops.mesh, f"primitive_{kind}_add")(location=loc)
        bpy.context.active_object.data.materials.append(mat)
        if kind == "uv_sphere":
            bpy.context.active_object.scale = (0.45, 0.45, 0.45)
    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
    sun.data.energy = 4.0
    sun.rotation_euler = (math.radians(50), 0, math.radians(30))
    bpy.context.scene.collection.objects.link(sun)
    world = bpy.data.worlds.new("World")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)   # white: easy to key out
    bpy.context.scene.world = world


def scene_bounds():
    import bpy
    from mathutils import Vector

    points = [obj.matrix_world @ Vector(corner) for obj in bpy.context.scene.objects if obj.type == "MESH"
              for corner in obj.bound_box]
    low = Vector((min(p[i] for p in points) for i in range(3)))
    high = Vector((max(p[i] for p in points) for i in range(3)))
    center = (low + high) / 2
    return tuple(center), (high - low).length / 2


def write_seed_points(path, *, count=6000):
    """ASCII PLY of vertex positions and normals of the scene's meshes (evaluated), a seed for the trainer."""
    import bpy

    depsgraph = bpy.context.evaluated_depsgraph_get()
    rows = []
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        mesh = obj.evaluated_get(depsgraph).to_mesh()
        for vertex in mesh.vertices:
            world = obj.matrix_world @ vertex.co
            normal = (obj.matrix_world.to_3x3() @ vertex.normal).normalized()
            rows.append((*world, *normal))
        obj.evaluated_get(depsgraph).to_mesh_clear()
    step = max(1, len(rows) // count)
    rows = rows[::step]
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("ply\nformat ascii 1.0\n" + f"element vertex {len(rows)}\n"
                     + "".join(f"property float {axis}\n" for axis in ("x", "y", "z", "nx", "ny", "nz"))
                     + "end_header\n")
        for row in rows:
            handle.write(" ".join(f"{value:.6f}" for value in row) + "\n")
    return len(rows)


def capture(out_dir: Path, *, views=48, size=256, samples=32, hemisphere=False, test_every=8):
    import bpy
    from mathutils import Matrix

    scene = bpy.context.scene
    center, radius = scene_bounds()
    distance = radius * 3.2
    cam_data = bpy.data.cameras.new("CaptureCam")
    cam_data.lens_unit = "FOV"
    cam_data.angle = math.radians(40.0)
    cam = bpy.data.objects.new("CaptureCam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = samples
    scene.cycles.use_denoising = False
    scene.render.resolution_x = scene.render.resolution_y = size
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    poses = camera_poses(views, radius=distance, target=center, hemisphere=hemisphere)
    split = {"train": [], "test": []}
    for index, pose in enumerate(poses):
        name = "test" if test_every and index % test_every == test_every - 1 else "train"
        split[name].append(pose)
        cam.matrix_world = Matrix(pose)
        folder = out_dir / name
        folder.mkdir(parents=True, exist_ok=True)
        scene.render.filepath = str(folder / f"r_{len(split[name]) - 1:03d}.png")
        bpy.ops.render.render(write_still=True)
    for name, group in split.items():
        (out_dir / f"transforms_{name}.json").write_text(
            json.dumps(transforms_json(group, angle_x=cam_data.angle_x, prefix=name, size=size), indent=1))
    seeds = write_seed_points(out_dir / "points3d.ply")
    return {"views": views, "train": len(split["train"]), "test": len(split["test"]), "size": size, "samples": samples,
            "radius_m": round(distance, 4), "target": [round(c, 4) for c in center], "seed_points": seeds,
            "camera_angle_x": cam_data.angle_x, "hemisphere": hemisphere, "blender": bpy.app.version_string}


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    out_dir = Path(argv[0])
    out_dir.mkdir(parents=True, exist_ok=True)

    def option(flag, default, cast=int):
        return cast(argv[argv.index(flag) + 1]) if flag in argv else default

    import bpy

    if "--blend" in argv:
        bpy.ops.wm.open_mainfile(filepath=argv[argv.index("--blend") + 1])
    else:
        build_still_life()
    summary = capture(out_dir, views=option("--views", 48), size=option("--size", 256), samples=option("--samples", 32),
                      hemisphere="--hemisphere" in argv)
    (out_dir / "capture.json").write_text(json.dumps(summary, indent=1))
    print(summary)


if __name__ == "__main__":
    main()
