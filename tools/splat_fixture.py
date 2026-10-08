# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Gaussian-splat fixture: a helix of splats as a splat mesh, plus a PLY of the same data.

    blender --background --python tools/splat_fixture.py -- /tmp/splats.x3d
"""

from __future__ import annotations

import math
import os
import sys

import bpy

SOURCE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source")


def helix_splats(count: int = 48, *, sh_degree: int = 1):
    """IRGaussianSplats along a helix with rainbow colours and twisting orientations."""
    if SOURCE_DIR not in sys.path:
        sys.path.insert(0, SOURCE_DIR)
    from ir import IRGaussianSplats
    from splat_io import rgb_to_sh0

    splats = IRGaussianSplats(name="HelixSplats")
    for index in range(count):
        t = index / max(1, count - 1)
        angle = t * 4.0 * math.pi
        splats.positions.append((math.cos(angle), math.sin(angle), 2.0 * t - 1.0))
        splats.scales.append((0.05 + 0.05 * t, 0.02, 0.08))
        half = angle / 2.0
        splats.orientations.append((0.0, 0.0, math.sin(half), math.cos(half)))
        splats.opacities.append(0.25 + 0.75 * t)
        splats.sh.setdefault((0, 0), []).append(rgb_to_sh0((t, 1.0 - t, 0.5)))
        if sh_degree >= 1:
            for coef in range(3):
                splats.sh.setdefault((1, coef), []).append((0.1 * coef, -0.1 * t, 0.05))
    return splats


def build_splat_fixture(*, count: int = 48) -> dict:
    """Create a splat mesh object 'Helix' in the current scene and return it."""
    if SOURCE_DIR not in sys.path:
        sys.path.insert(0, SOURCE_DIR)
    from splat_io import sh0_to_rgb

    splats = helix_splats(count)
    mesh = bpy.data.meshes.new("HelixSplats")
    mesh.from_pydata([tuple(p) for p in splats.positions], [], [])
    mesh.update()
    mesh["x3d_gaussian_splats"] = True
    mesh["x3d_splat_color_space"] = "SRGB_REC709_DISPLAY"
    scale = mesh.attributes.new("splat_scale", 'FLOAT_VECTOR', 'POINT')
    scale.data.foreach_set("vector", [c for s in splats.scales for c in s])
    rotation = mesh.attributes.new("splat_rotation", 'QUATERNION', 'POINT')
    rotation.data.foreach_set("value", [c for (x, y, z, w) in splats.orientations for c in (w, x, y, z)])
    opacity = mesh.attributes.new("splat_opacity", 'FLOAT', 'POINT')
    opacity.data.foreach_set("value", splats.opacities)
    for (degree, coef), values in splats.sh.items():
        attr = mesh.attributes.new(f"splat_sh{degree}_{coef}", 'FLOAT_VECTOR', 'POINT')
        attr.data.foreach_set("vector", [c for v in values for c in v])
    color = mesh.color_attributes.new("Color", 'FLOAT_COLOR', 'POINT')
    color.data.foreach_set("color", [c for i, dc in enumerate(splats.sh[(0, 0)]) for c in (*sh0_to_rgb(dc), splats.opacities[i])])

    obj = bpy.data.objects.new("Helix", mesh)
    obj.location = (0.0, 0.0, 1.0)
    obj.rotation_euler = (0.0, 0.0, math.radians(30.0))
    bpy.context.scene.collection.objects.link(obj)
    return {"helix": obj, "splats": splats}


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    output = argv[0] if argv else os.path.abspath("splats.x3d")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    build_splat_fixture()
    result = bpy.ops.export_scene.x3d(filepath=output, x3d_version="X3D41", use_selection=False)
    print("export:", result, output)


if __name__ == "__main__":
    main()
