# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Frozen fixture scenes for the Gate 2 oracles (needs ``bpy``).

Every scene is built from explicit numbers with ``from_pydata`` and data-API calls, never with Blender's primitive
operators: the v3 plan's measurement R8 found that four processes which each built a UV sphere with the operator gave
four different exports, while four that opened one saved .blend gave four identical files. Building from data gives
the same mesh in every process and on every Blender version, so these scenes can back golden files
(tests/golden/*.c14n.x3d), the two-process determinism test and the metamorphic relations.

    import frozen_scenes; frozen_scenes.build("lit_cube")      # resets to factory settings first
"""
from __future__ import annotations

import math

SCENES = ("lit_cube", "two_materials", "uv_grid", "vertex_colours", "hierarchy", "four_lights", "cameras",
          "smooth_torus", "linked_instances", "keyframes", "emissive_glass", "loose_edges")


def _reset():
    import bpy

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.scene.frame_start = 1
    bpy.context.scene.frame_end = 48
    bpy.context.scene.render.fps = 24
    return bpy


def _mesh(name, verts, faces, edges=()):
    import bpy

    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([tuple(v) for v in verts], list(edges), [tuple(f) for f in faces])
    mesh.update()
    return mesh


def _cube(size=1.0, offset=(0.0, 0.0, 0.0)):
    h = size / 2.0
    ox, oy, oz = offset
    verts = [(ox + x * h, oy + y * h, oz + z * h) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    return verts, faces


def _material(name, base=(0.8, 0.8, 0.8, 1.0), metallic=0.0, roughness=0.5, emission=None, strength=0.0, alpha=1.0):
    import bpy

    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = base
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Alpha"].default_value = alpha
    if emission is not None:
        bsdf.inputs["Emission Color"].default_value = emission
        bsdf.inputs["Emission Strength"].default_value = strength
    if alpha < 1.0 and hasattr(mat, "surface_render_method"):
        mat.surface_render_method = "BLENDED"
    return mat


def _object(name, data, location=(0.0, 0.0, 0.0), rotation=(0.0, 0.0, 0.0), scale=(1.0, 1.0, 1.0), parent=None):
    import bpy

    obj = bpy.data.objects.new(name, data)
    obj.location = location
    obj.rotation_euler = rotation
    obj.scale = scale
    bpy.context.scene.collection.objects.link(obj)
    if parent is not None:
        obj.parent = parent
    return obj


def _sun():
    import bpy

    data = bpy.data.lights.new("Key", "SUN")
    data.energy = 0.8
    _object("Key", data, location=(4.0, -4.0, 6.0), rotation=(0.7, 0.0, 0.8))


def build(name: str):
    """Build one frozen scene and return the objects the metamorphic relations act on."""
    bpy = _reset()
    if name not in SCENES:
        raise KeyError(name)
    objects = {}
    if name == "lit_cube":
        mesh = _mesh("CubeMesh", *_cube(2.0))
        mesh.materials.append(_material("Clay", (0.7, 0.45, 0.3, 1.0), roughness=0.6))
        objects["main"] = _object("Cube", mesh, location=(0.0, 0.0, 1.0))
        _sun()
    elif name == "two_materials":
        mesh = _mesh("SplitMesh", *_cube(2.0))
        mesh.materials.append(_material("Red", (0.8, 0.1, 0.1, 1.0)))
        mesh.materials.append(_material("Blue", (0.1, 0.2, 0.8, 1.0), metallic=1.0, roughness=0.2))
        for i, poly in enumerate(mesh.polygons):
            poly.material_index = i % 2
        objects["main"] = _object("Split", mesh)
        _sun()
    elif name == "uv_grid":
        n = 4
        verts = [(x - n / 2.0, y - n / 2.0, 0.0) for y in range(n + 1) for x in range(n + 1)]
        faces = [(y * (n + 1) + x, y * (n + 1) + x + 1, (y + 1) * (n + 1) + x + 1, (y + 1) * (n + 1) + x)
                 for y in range(n) for x in range(n)]
        mesh = _mesh("GridMesh", verts, faces)
        uv = mesh.uv_layers.new(name="UVMap")
        for poly in mesh.polygons:
            for li in poly.loop_indices:
                v = mesh.vertices[mesh.loops[li].vertex_index].co
                uv.data[li].uv = ((v.x + n / 2.0) / n, (v.y + n / 2.0) / n)
        mesh.materials.append(_material("Grid", (0.5, 0.5, 0.5, 1.0)))
        objects["main"] = _object("Grid", mesh)
        _sun()
    elif name == "vertex_colours":
        mesh = _mesh("PaintMesh", *_cube(1.5))
        attr = mesh.color_attributes.new("Col", "FLOAT_COLOR", "POINT")
        for i, item in enumerate(attr.data):
            item.color = ((i & 1) * 1.0, ((i >> 1) & 1) * 1.0, ((i >> 2) & 1) * 1.0, 1.0)
        mesh.materials.append(_material("Paint"))
        objects["main"] = _object("Painted", mesh)
        _sun()
    elif name == "hierarchy":
        root = _object("Root", None, location=(0.0, 0.0, 0.5))
        arm = _object("Arm", _mesh("ArmMesh", *_cube(1.0)), location=(1.5, 0.0, 0.0), rotation=(0.0, 0.0, 0.5),
                      parent=root)
        _object("Hand", _mesh("HandMesh", *_cube(0.5)), location=(1.0, 0.0, 0.0), scale=(1.0, 2.0, 1.0), parent=arm)
        objects["main"] = arm
        _sun()
    elif name == "four_lights":
        objects["main"] = _object("Floor", _mesh("FloorMesh", [(-3, -3, 0), (3, -3, 0), (3, 3, 0), (-3, 3, 0)],
                                                 [(0, 1, 2, 3)]))
        for i, (kind, energy) in enumerate((("POINT", 1.0), ("SUN", 0.5), ("SPOT", 1.2), ("AREA", 1.0))):
            data = bpy.data.lights.new(kind.title(), kind)
            data.energy = energy
            data.color = (1.0, 0.9 - 0.1 * i, 0.8, )
            _object(kind.title(), data, location=(2.0 * i - 3.0, -2.0, 3.0), rotation=(0.6, 0.0, 0.3 * i))
    elif name == "cameras":
        objects["main"] = _object("Target", _mesh("TargetMesh", *_cube(1.0)))
        cam = bpy.data.cameras.new("Persp")
        cam.lens = 35.0
        obj = _object("Persp", cam, location=(6.0, -6.0, 4.0), rotation=(1.1, 0.0, 0.8))
        bpy.context.scene.camera = obj
        ortho = bpy.data.cameras.new("Ortho")
        ortho.type = "ORTHO"
        ortho.ortho_scale = 5.0
        _object("Ortho", ortho, location=(0.0, -8.0, 0.0), rotation=(math.pi / 2, 0.0, 0.0))
        _sun()
    elif name == "smooth_torus":
        R, r, nu, nv = 1.0, 0.3, 16, 8
        verts = [((R + r * math.cos(2 * math.pi * j / nv)) * math.cos(2 * math.pi * i / nu),
                  (R + r * math.cos(2 * math.pi * j / nv)) * math.sin(2 * math.pi * i / nu),
                  r * math.sin(2 * math.pi * j / nv)) for i in range(nu) for j in range(nv)]
        faces = [(i * nv + j, ((i + 1) % nu) * nv + j, ((i + 1) % nu) * nv + (j + 1) % nv, i * nv + (j + 1) % nv)
                 for i in range(nu) for j in range(nv)]
        mesh = _mesh("TorusMesh", [tuple(round(c, 6) for c in v) for v in verts], faces)
        mesh.shade_smooth()
        mesh.materials.append(_material("Brass", (0.8, 0.6, 0.2, 1.0), metallic=1.0, roughness=0.3))
        objects["main"] = _object("Torus", mesh)
        _sun()
    elif name == "linked_instances":
        part = bpy.data.collections.new("Part")
        bpy.context.scene.collection.children.link(part)
        mesh = _mesh("PartMesh", *_cube(0.8))
        mesh.materials.append(_material("Steel", (0.6, 0.6, 0.65, 1.0), metallic=1.0, roughness=0.35))
        src = bpy.data.objects.new("PartSource", mesh)
        part.objects.link(src)
        part.hide_render = False
        bpy.context.view_layer.layer_collection.children["Part"].exclude = True
        for i in range(3):
            inst = _object(f"Copy{i}", None, location=(2.0 * i, 0.0, 0.0))
            inst.instance_type = "COLLECTION"
            inst.instance_collection = part
            objects.setdefault("main", inst)
        _sun()
    elif name == "keyframes":
        obj = _object("Mover", _mesh("MoverMesh", *_cube(1.0)))
        for frame, x in ((1, 0.0), (24, 2.0), (48, 0.0)):
            obj.location = (x, 0.0, 0.0)
            obj.keyframe_insert("location", frame=frame)
        objects["main"] = obj
        _sun()
    elif name == "emissive_glass":
        lamp = _mesh("LampMesh", *_cube(0.6, (0.0, 0.0, 1.0)))
        lamp.materials.append(_material("Glow", (0.1, 0.1, 0.1, 1.0), emission=(1.0, 0.8, 0.3, 1.0), strength=1.0))
        objects["main"] = _object("Lamp", lamp)
        glass = _mesh("PaneMesh", [(-1, 0.5, 0), (1, 0.5, 0), (1, 0.5, 2), (-1, 0.5, 2)], [(0, 1, 2, 3)])
        glass.materials.append(_material("Glass", (0.6, 0.8, 1.0, 1.0), roughness=0.05, alpha=0.4))
        _object("Pane", glass)
        _sun()
    elif name == "loose_edges":
        verts = [(math.cos(2 * math.pi * i / 6), math.sin(2 * math.pi * i / 6), 0.0) for i in range(6)]
        edges = [(i, (i + 1) % 6) for i in range(6)]
        objects["main"] = _object("Hexagon", _mesh("HexMesh", [tuple(round(c, 6) for c in v) for v in verts], [],
                                                    edges))
        _sun()
    bpy.context.view_layer.update()
    return objects
