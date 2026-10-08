# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Build the material "swatch book" used to exercise the X3D 4.0 path.

Each swatch is one 16:9 quad carrying one material, following the fixture
layout proposed on the Web3D X3D-Ecosystem list for PhysicalMaterial export
testing. Run inside Blender (or with the ``bpy`` wheel)::

    blender --background --python tools/swatch_book.py -- /tmp/swatches.x3d
"""

from __future__ import annotations

import os
import sys

import bpy


SWATCH_WIDTH = 1.6
SWATCH_HEIGHT = 0.9
GAP = 0.2


def _quad(name: str, index: int):
    bpy.ops.mesh.primitive_plane_add(size=1.0, location=(index * (SWATCH_WIDTH + GAP), 0.0, 0.0))
    obj = bpy.context.active_object
    obj.name = name
    obj.data.name = f"{name}Mesh"
    obj.scale = (SWATCH_WIDTH, SWATCH_HEIGHT, 1.0)
    return obj


def _principled(name: str):
    material = bpy.data.materials.new(name)
    if not material.use_nodes:
        material.use_nodes = True
    bsdf = material.node_tree.nodes["Principled BSDF"]
    return material, bsdf


def _checker_image(name: str, size: int = 8, directory: str | None = None):
    image = bpy.data.images.new(name, size, size, alpha=True)
    pixels = []
    for y in range(size):
        for x in range(size):
            on = (x // 2 + y // 2) % 2 == 0
            pixels.extend((1.0, 1.0, 1.0, 1.0) if on else (0.1, 0.3, 0.8, 1.0))
    image.pixels = pixels
    if directory:
        image.filepath_raw = os.path.join(directory, f"{name}.png")
        image.file_format = "PNG"
        image.save()
    return image


def build_swatch_book(texture_dir: str | None = None) -> list:
    """Create the swatch quads in the current scene and return the objects."""

    objects = []

    # 1. Dielectric, rough, opaque
    obj = _quad("SwatchDielectric", 0)
    material, bsdf = _principled("Dielectric")
    bsdf.inputs["Base Color"].default_value = (0.8, 0.1, 0.1, 1.0)
    bsdf.inputs["Metallic"].default_value = 0.0
    bsdf.inputs["Roughness"].default_value = 0.8
    material.use_backface_culling = True
    obj.data.materials.append(material)
    objects.append(obj)

    # 2. Metal, polished
    obj = _quad("SwatchMetal", 1)
    material, bsdf = _principled("Gold")
    bsdf.inputs["Base Color"].default_value = (1.0, 0.77, 0.34, 1.0)
    bsdf.inputs["Metallic"].default_value = 1.0
    bsdf.inputs["Roughness"].default_value = 0.2
    obj.data.materials.append(material)
    objects.append(obj)

    # 3. Transparent (alpha blend)
    obj = _quad("SwatchGlass", 2)
    material, bsdf = _principled("Glass")
    bsdf.inputs["Base Color"].default_value = (0.2, 0.4, 0.9, 1.0)
    bsdf.inputs["Alpha"].default_value = 0.4
    bsdf.inputs["Roughness"].default_value = 0.05
    material.surface_render_method = "BLENDED"
    obj.data.materials.append(material)
    objects.append(obj)

    # 4. Unlit / emissive (Emission shader straight into the output)
    obj = _quad("SwatchUnlit", 3)
    material = bpy.data.materials.new("Neon")
    if not material.use_nodes:
        material.use_nodes = True
    tree = material.node_tree
    for node in list(tree.nodes):
        if node.type != "OUTPUT_MATERIAL":
            tree.nodes.remove(node)
    output = next(node for node in tree.nodes if node.type == "OUTPUT_MATERIAL")
    emission = tree.nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = (1.0, 0.5, 0.0, 1.0)
    emission.inputs["Strength"].default_value = 1.0
    tree.links.new(emission.outputs["Emission"], output.inputs["Surface"])
    obj.data.materials.append(material)
    objects.append(obj)

    # 5. Textured base colour with UVs
    obj = _quad("SwatchTextured", 4)
    material, bsdf = _principled("Checker")
    image = _checker_image("swatch_checker", directory=texture_dir)
    tex = material.node_tree.nodes.new("ShaderNodeTexImage")
    tex.image = image
    material.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.5
    obj.data.materials.append(material)
    objects.append(obj)

    # 6. Two material slots on one mesh, smooth shaded sphere with vertex colours
    bpy.ops.mesh.primitive_uv_sphere_add(segments=12, ring_count=6, radius=0.45,
                                         location=(5 * (SWATCH_WIDTH + GAP), 0.0, 0.0))
    obj = bpy.context.active_object
    obj.name = "SwatchTwoTone"
    obj.data.name = "SwatchTwoToneMesh"
    bpy.ops.object.shade_smooth()
    top, bsdf_top = _principled("TwoToneTop")
    bsdf_top.inputs["Base Color"].default_value = (0.1, 0.8, 0.2, 1.0)
    bottom, bsdf_bottom = _principled("TwoToneBottom")
    bsdf_bottom.inputs["Base Color"].default_value = (0.9, 0.9, 0.1, 1.0)
    obj.data.materials.append(top)
    obj.data.materials.append(bottom)
    for polygon in obj.data.polygons:
        polygon.material_index = 0 if polygon.center.z >= 0.0 else 1
    colors = obj.data.color_attributes.new("Col", "FLOAT_COLOR", "POINT")
    for index, vertex in enumerate(obj.data.vertices):
        shade = (vertex.co.z / 0.45 + 1.0) * 0.5
        colors.data[index].color = (shade, 1.0 - shade, 0.5, 1.0)
    objects.append(obj)

    # 7. Shared mesh data: two objects using one mesh (DEF/USE on export)
    bpy.ops.mesh.primitive_cube_add(size=0.6, location=(6 * (SWATCH_WIDTH + GAP), 0.0, 0.0))
    cube = bpy.context.active_object
    cube.name = "SwatchCubeA"
    cube.data.name = "SharedCube"
    cube.data.materials.append(bpy.data.materials["Dielectric"])
    twin = cube.copy()
    twin.name = "SwatchCubeB"
    twin.location = (6 * (SWATCH_WIDTH + GAP), 1.5, 0.0)
    bpy.context.collection.objects.link(twin)
    objects.extend([cube, twin])

    return objects


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    output = argv[0] if argv else os.path.abspath("swatch_book.x3d")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    build_swatch_book(texture_dir=os.path.dirname(os.path.abspath(output)))
    bpy.ops.export_scene.x3d(filepath=output, x3d_version="X3D40", use_normals=True, use_selection=False)
    print("wrote", output)


if __name__ == "__main__":
    main()
