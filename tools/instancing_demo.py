# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Build a grove from collection instances and export it three ways to measure what DEF/USE saves.

A  Collection instances      60 Trees + 12 Huts as Empties that instance two collections (this exporter: one DEF'd Group,
                             then USE).
B  Realised, meshes shared   the same 72 placements as ordinary objects that share mesh data (what the exporter already
                             did for linked duplicates: geometry DEF/USE, but one Transform+Shape per part per copy).
C  Realised, single-user     as B with every mesh made single-user: no geometry sharing at all, which is what an exporter
                             without DEF/USE writes.

    python tools/instancing_demo.py <out dir> [--blend file.blend]

Writes grove-A-collection-instances.x3d, grove-B-realised-shared-meshes.x3d, grove-C-realised-single-user.x3d and
sizes.json (bytes from os.path.getsize, gzip -9 bytes from Python's gzip module).
"""

from __future__ import annotations

import gzip
import importlib
import json
import math
import os
import random
import sys
import tempfile
from pathlib import Path

import bpy
from mathutils import Euler, Matrix, Vector

SOURCE_DIR = Path(__file__).resolve().parents[1] / "source"


def register_extension():
    package_dir = Path(tempfile.mkdtemp(prefix="x3d_instancing_demo_")) / "io_scene_x3d"
    package_dir.symlink_to(SOURCE_DIR, target_is_directory=True)
    sys.path.insert(0, str(package_dir.parent))
    importlib.import_module("io_scene_x3d").register()


def material(name, rgb, roughness=0.7):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*rgb, 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    return mat


def make_mesh(kind, name, mat, **kwargs):
    getattr(bpy.ops.mesh, f"primitive_{kind}_add")(**kwargs)
    obj = bpy.context.active_object
    obj.name = name
    obj.data.name = name
    obj.data.materials.append(mat)
    bpy.context.scene.collection.objects.unlink(obj)        # an asset library: not part of the scene
    return obj


def library():
    bark, leaf = material("Bark", (0.30, 0.18, 0.09)), material("Leaf", (0.12, 0.45, 0.14), 0.55)
    wall, roof = material("Wall", (0.80, 0.74, 0.62)), material("Roof", (0.55, 0.15, 0.10))
    tree = bpy.data.collections.new("Tree")
    for obj, loc, scale in (
        (make_mesh("cylinder", "TreeTrunk", bark, vertices=24, radius=0.25, depth=2.0), (0, 0, 1.0), (1, 1, 1)),
        (make_mesh("ico_sphere", "TreeCrownLow", leaf, subdivisions=4, radius=1.3), (0, 0, 2.6), (1, 1, 1.15)),
        (make_mesh("ico_sphere", "TreeCrownHigh", leaf, subdivisions=4, radius=0.9), (0, 0, 3.7), (1, 1, 1.2)),
    ):
        obj.location, obj.scale = loc, scale
        tree.objects.link(obj)
    hut = bpy.data.collections.new("Hut")
    for obj, loc, scale in (
        (make_mesh("cube", "HutWalls", wall, size=2.0), (0, 0, 1.0), (1.2, 1.0, 1.0)),
        (make_mesh("cone", "HutRoof", roof, vertices=32, radius1=1.9, depth=1.4), (0, 0, 2.7), (1, 1, 1)),
    ):
        obj.location, obj.scale = loc, scale
        hut.objects.link(obj)
    return tree, hut


def placements(seed=7):
    rng = random.Random(seed)
    out = []
    for index in range(60):
        out.append(("Tree", Vector((rng.uniform(-30, 30), rng.uniform(-30, 30), 0)), rng.uniform(0, math.tau),
                    rng.uniform(0.7, 1.4)))
    for index in range(12):
        out.append(("Hut", Vector((rng.uniform(-28, 28), rng.uniform(-28, 28), 0)), rng.uniform(0, math.tau), 1.0))
    return out


def build_collection_instances(collections):
    scene = bpy.context.scene
    for index, (kind, loc, angle, scale) in enumerate(placements()):
        empty = bpy.data.objects.new(f"{kind}_{index:02d}", None)
        empty.instance_type, empty.instance_collection = "COLLECTION", collections[kind]
        empty.location, empty.rotation_euler, empty.scale = loc, (0, 0, angle), (scale,) * 3
        scene.collection.objects.link(empty)


def build_realised(collections, *, single_user):
    scene = bpy.context.scene
    for index, (kind, loc, angle, scale) in enumerate(placements()):
        root = Matrix.LocRotScale(loc, Euler((0, 0, angle)), Vector((scale,) * 3))
        for member in collections[kind].objects:
            obj = bpy.data.objects.new(f"{kind}_{index:02d}.{member.name}", member.data)
            obj.matrix_world = root @ member.matrix_basis
            scene.collection.objects.link(obj)
            if single_user:
                obj.data = obj.data.copy()


def common_scene():
    scene = bpy.context.scene
    ground = bpy.data.objects.new("Ground", None)
    mat = material("Grass", (0.25, 0.4, 0.2), 0.9)
    bpy.ops.mesh.primitive_plane_add(size=80)
    plane = bpy.context.active_object
    plane.name = "Ground"
    plane.data.materials.append(mat)
    bpy.data.objects.remove(ground)
    cam = bpy.data.objects.new("Start", bpy.data.cameras.new("Start"))
    scene.collection.objects.link(cam)
    cam.location = (0, -62, 38)
    cam.rotation_euler = (math.radians(55), 0, 0)
    cam.data.lens = 35
    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
    sun.data.energy = 3.0
    sun.rotation_euler = (math.radians(45), math.radians(15), math.radians(35))
    scene.collection.objects.link(sun)
    scene.world = bpy.data.worlds.new("World")
    scene.world.use_nodes = True
    scene.world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.45, 0.6, 0.8, 1.0)


def export(path):
    result = bpy.ops.export_scene.x3d(filepath=path, x3d_version="X3D40", use_selection=False)
    assert result == {"FINISHED"}, result
    raw = Path(path).read_bytes()
    return {"bytes": len(raw), "gzip9_bytes": len(gzip.compress(raw, 9)),
            "Shape": raw.count(b"<Shape"), "Transform": raw.count(b"<Transform"),
            "DEF": raw.count(b" DEF="), "USE": raw.count(b" USE="),
            "IndexedFaceSet": raw.count(b"<IndexedFaceSet")}


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    out_dir = Path(argv[0])
    out_dir.mkdir(parents=True, exist_ok=True)
    blend = argv[argv.index("--blend") + 1] if "--blend" in argv else None
    register_extension()
    sizes = {}
    for key, label in (("A", "collection-instances"), ("B", "realised-shared-meshes"), ("C", "realised-single-user")):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        collections = dict(zip(("Tree", "Hut"), library()))
        common_scene()
        if key == "A":
            build_collection_instances(collections)
            if blend:
                bpy.ops.wm.save_as_mainfile(filepath=blend)
        else:
            build_realised(collections, single_user=key == "C")
        sizes[key] = {"file": f"grove-{key}-{label}.x3d", **export(str(out_dir / f"grove-{key}-{label}.x3d"))}
        print(key, sizes[key])
    (out_dir / "sizes.json").write_text(json.dumps(sizes, indent=1))


if __name__ == "__main__":
    main()
