# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A Gaussian-splat import reaches a glb with its colours (COLOR_0 on a POINTS primitive).

Blender 5.3's glTF exporter (io_scene_gltf2 pointcloud.py) writes a PointCloud's POSITION and, only when the object's
material reads a named colour attribute, COLOR_0. The native splat layout keeps colour in ``radiance:base`` alone, so the
glb held POSITION only (stilllife-splats-24k, stars-view). The importer adds the ``Color`` attribute and an unlit
material on it.

Skipped when ``bpy`` is not importable or cannot size a PointCloud (Blender 5.1+); the native point-cloud glb test also
skips before Blender 5.3, whose glTF exporter writes no PointCloud (CI 5.1.2 and 5.2.2)::

    cd tests && python -m unittest test_splat_glb_colours_bpy
"""

from __future__ import annotations

import json
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

SOURCE_DIR = Path(__file__).resolve().parents[1] / "source"
from test_roundtrip_bpy import _force_splat_import, _register_extension, _pointcloud_resizable

COLOURS = [(0.9, 0.2, 0.1), (0.1, 0.5, 0.9), (0.5, 0.5, 0.5)]


def _srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _sh0(rgb):
    return tuple((c - 0.5) / 0.28209479177387814 for c in rgb)


def _glb(path):
    with open(path, "rb") as f:
        blob = f.read()
    length = struct.unpack("<I", blob[12:16])[0]
    doc = json.loads(blob[20:20 + length])
    return doc, blob[20 + length + 8:]


@unittest.skipUnless(HAVE_BPY and _pointcloud_resizable(), "needs bpy with PointCloud.resize (Blender 5.1+)")
class SplatGlbColourTests(unittest.TestCase):
    def _import_export(self, target, **export):
        import bpy
        tmp = tempfile.mkdtemp(prefix="x3d_splat_glb_")
        _register_extension(tmp)
        _force_splat_import(self, target)
        text = ("<?xml version='1.0' encoding='UTF-8'?><X3D profile='Immersive' version='4.1'><Scene>"
                "<GaussianSplats positions='0 0 0 1 0 0 0 1 0' scales='0.1 0.1 0.1 0.1 0.1 0.1 0.1 0.1 0.1' "
                "orientations='0 0 0 1 0 0 0 1 0 0 0 1' opacities='1 0.5 1' "
                f"sphericalHarmonicsDegree0Coef0='{' '.join(' '.join(f'{v:.6f}' for v in _sh0(c)) for c in COLOURS)}'/>"
                "</Scene></X3D>")
        src = os.path.join(tmp, "splats.x3d")
        with open(src, "w", encoding="utf-8") as f:
            f.write(text)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=src), {"FINISHED"})
        out = os.path.join(tmp, "splats.glb")
        self.assertEqual(bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", **export), {"FINISHED"})
        return _glb(out)

    def test_native_splat_pointcloud_glb_has_colours(self):
        import bpy
        doc, blob = self._import_export("pointcloud")
        if "meshes" not in doc and bpy.app.version < (5, 3, 0):
            # CI Blender 5.1.2 and 5.2.2: "Mesh 'GaussianSplats' has no primitives and will be omitted". Their glTF exporter
            # (io_scene_gltf2) does not write point clouds; the PointCloud exists since 5.1, its glb export since 5.3.
            self.skipTest("this Blender's glTF exporter does not write PointCloud objects (5.3+ does)")
        self.assertIn("meshes", doc, "Blender 5.3+ must write the splat point cloud")
        primitive = doc["meshes"][0]["primitives"][0]
        self.assertEqual(primitive.get("mode"), 0)                  # POINTS
        self.assertIn("COLOR_0", primitive["attributes"])
        accessor = doc["accessors"][primitive["attributes"]["COLOR_0"]]
        view = doc["bufferViews"][accessor["bufferView"]]
        self.assertEqual((accessor["count"], accessor["componentType"], accessor["type"]), (3, 5126, "VEC4"))
        values = struct.unpack_from("<12f", blob, view.get("byteOffset", 0) + accessor.get("byteOffset", 0))
        for i, rgb in enumerate(COLOURS):
            for got, want in zip(values[4 * i:4 * i + 3], rgb):
                self.assertAlmostEqual(got, _srgb_to_linear(want), places=4)    # glTF colours are linear
        material = doc["materials"][primitive["material"]]
        self.assertIn("KHR_materials_unlit", material.get("extensions", {}))

    def test_mesh_target_still_carries_colours(self):
        doc, _ = self._import_export("mesh", use_mesh_vertices=True)   # loose vertices are off by default
        self.assertIn("COLOR_0", doc["meshes"][0]["primitives"][0]["attributes"])

    def test_the_x3d_export_of_a_splat_import_is_unchanged_by_the_colour_attribute(self):
        import bpy
        self._import_export("pointcloud")
        out = os.path.join(tempfile.mkdtemp(prefix="x3d_splat_x3d_"), "again.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=out, x3d_version="X3D41", use_selection=False), {"FINISHED"})
        with open(out, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("<GaussianSplats", text)
        self.assertNotIn("<ColorRGBA", text)


if __name__ == "__main__":
    unittest.main()
