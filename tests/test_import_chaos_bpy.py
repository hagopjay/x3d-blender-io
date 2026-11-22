# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Crashes found by the differential chaos round (tools/chaos/differential.py, 22 Nov 2026), kept fixed.

Each case is one edit to an ordinary file, the way the mutator made it:

* a bool spelt ``1`` (also ``yes``, ``TRUE,``): ``getFieldAsBool`` formatted ``f[1]`` of a one-item list in its warning,
  so the IndexError ended the import (Blender's own importer has the same line);
* one coordIndex far past the points: the importer padded the point list up to that index, so ``5000000`` built
  5,000,001 vertices for one quad and ``2147483647`` raised MemoryError (all four validators accept the file);
* a scale of ``1 1 --1``: two numbers parse, and ``translateScale`` indexed the third;
* a NaN scale imports, and the re-export's ``inverted64`` raised ``LinAlgError`` (SVD did not converge);
* a scene 1,200 Groups deep: the x3d.py validator walked it by recursion and raised RecursionError;
* the same far coordIndex on a coloured or textured mesh: ``pad_values`` padded the colours too (MemoryError);
* fieldOfView INF: ``tan`` raised "math domain error";
* a PointLight radius of -1 (unlimited in X_ITE) imports, and the export then failed its own x3d.py check.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_import_chaos_bpy
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

from test_roundtrip_bpy import _register_extension

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "source"))

QUAD = "<IndexedFaceSet solid='{solid}' coordIndex='{index}'><Coordinate point='0 0 0 1 0 0 1 1 0 0 1 0'/></IndexedFaceSet>"


def _file(body: str) -> str:
    return ("<?xml version='1.0' encoding='UTF-8'?>\n<X3D profile='Interchange' version='4.0'><Scene>\n"
            f"{body}\n</Scene></X3D>\n")


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class ImportChaosTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="x3d_chaos_")
        _register_extension(cls.tmpdir)

    def _import(self, name: str, body: str):
        import bpy
        bpy.ops.wm.read_factory_settings(use_empty=True)
        path = os.path.join(self.tmpdir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(_file(body))
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=path), {"FINISHED"})
        return [o for o in bpy.data.objects if o.type == "MESH"]

    def test_bool_spelt_one_imports_with_the_default(self):
        for spelling in ("1", "yes", "TRUE,"):
            with self.subTest(spelling=spelling):
                meshes = self._import("bool.x3d", f"<Shape>{QUAD.format(solid=spelling, index='0 1 2 3 -1')}</Shape>")
                self.assertEqual(len(meshes), 1)
                self.assertEqual(len(meshes[0].data.polygons), 1)

    def test_index_far_past_the_points_adds_one_vertex(self):
        for index in ("5000000", "2147483647"):
            with self.subTest(index=index):
                meshes = self._import("index.x3d", f"<Shape>{QUAD.format(solid='false', index=f'0 1 2 {index} -1')}</Shape>")
                mesh = meshes[0].data
                self.assertEqual(len(mesh.vertices), 5)           # the 4 points and one added at the origin
                self.assertEqual(list(mesh.polygons[0].vertices), [0, 1, 2, 4])
                self.assertEqual(tuple(mesh.vertices[4].co), (0.0, 0.0, 0.0))

    def test_two_far_indices_get_two_vertices_and_keep_the_face_count(self):
        meshes = self._import("two.x3d", f"<Shape>{QUAD.format(solid='false', index='0 1 9 -1 0 9 8 -1')}</Shape>")
        mesh = meshes[0].data
        self.assertEqual(len(mesh.polygons), 2)
        self.assertEqual(len(mesh.vertices), 6)
        self.assertEqual(list(mesh.polygons[0].vertices)[2], list(mesh.polygons[1].vertices)[1])   # 9 maps once

    def test_scale_with_a_typo_is_read_as_no_scale(self):
        meshes = self._import("scale.x3d", "<Transform DEF='T' scale='1 1 --1'><Shape>"
                              f"{QUAD.format(solid='false', index='0 1 2 3 -1')}</Shape></Transform>")
        self.assertEqual(len(meshes), 1)
        for axis in meshes[0].matrix_world.to_scale():
            self.assertAlmostEqual(axis, 1.0)

    def test_nan_scale_re_exports(self):
        import bpy
        self._import("nan.x3d", "<Transform DEF='T' scale='NaN 1 1'><Transform DEF='Child'><Shape>"
                     f"{QUAD.format(solid='false', index='0 1 2 3 -1')}</Shape></Transform></Transform>")
        out = os.path.join(self.tmpdir, "nan-out.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=out), {"FINISHED"})
        self.assertTrue(os.path.getsize(out) > 0)

    def test_far_index_on_a_coloured_mesh_does_not_pad_two_billion_colours(self):
        body = ("<Shape><IndexedFaceSet solid='false' colorPerVertex='true' coordIndex='0 1 2 2147483647 -1'>"
                "<Coordinate point='0 0 0 1 0 0 1 1 0 0 1 0'/><Color color='1 0 0 0 1 0 0 0 1 1 1 0'/>"
                "<TextureCoordinate point='0 0 1 0 1 1 0 1'/></IndexedFaceSet></Shape>")
        mesh = self._import("colour.x3d", body)[0].data
        self.assertEqual(len(mesh.vertices), 5)

    def test_infinite_field_of_view_uses_the_default(self):
        import bpy
        import math
        self._import("fov.x3d", "<Viewpoint DEF='V' fieldOfView='INF'/>"
                     f"<Shape>{QUAD.format(solid='false', index='0 1 2 3 -1')}</Shape>")
        cameras = [o for o in bpy.data.objects if o.type == "CAMERA"]
        self.assertEqual(len(cameras), 1)
        self.assertTrue(math.isfinite(cameras[0].data.angle))

    def test_x_ite_unlimited_radius_re_exports(self):
        import bpy
        self._import("radius.x3d", "<PointLight DEF='Lamp' radius='-1' location='0 2 0'/>"
                     f"<Shape>{QUAD.format(solid='false', index='0 1 2 3 -1')}</Shape>")
        out = os.path.join(self.tmpdir, "radius-out.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=out), {"FINISHED"})   # failed its x3d.py check before
        with open(out, encoding="utf-8") as f:
            text = f.read()
        self.assertNotIn('radius="-1', text)
        self.assertNotIn("radius='-1", text)


class ValidatorDepthTests(unittest.TestCase):
    def test_x3d_py_validator_walks_a_deep_scene(self):
        import validate
        try:
            import x3d.x3d as x3d_module
        except Exception:
            self.skipTest("x3d.py is not installed")
        import xml.etree.ElementTree as ET
        depth = 1200
        text = ("<X3D profile='Interchange' version='4.0'><Scene>" + "<Group>" * depth
                + "<Shape><Box size='1 1 1'/></Shape>" + "</Group>" * depth + "</Scene></X3D>")
        result = validate.validate_tree_with_x3d_py(ET.fromstring(text), x3d_module)
        self.assertTrue(result.valid, result.errors[:3])
        bad = text.replace("size='1 1 1'", "size='1 1'")
        result = validate.validate_tree_with_x3d_py(ET.fromstring(bad), x3d_module)
        self.assertFalse(result.valid)        # the deepest node is still checked


if __name__ == "__main__":
    unittest.main()
