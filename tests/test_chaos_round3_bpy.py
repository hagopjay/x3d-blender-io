# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Crashes the receipt-to-rule engine found still live in 2.7.3 (chaos round 3, 2.7.4), kept fixed.

The engine (x3d.loom kit/loomkit/r2r) turned the 2.7.1 crash receipts into rules and replayed them on 2.7.3; six
rules still crashed, and its sweep of 514 real files found two more failures (one file each):

* CoordinateDouble under a triangle set: AttributeError (only Coordinate was read);
* MetadataBoolean, and any MFBool field: the export's semantic check read ``true false`` as numbers and refused it;
* an index past the points in an IndexedTriangleSet / IndexedTriangleStripSet with Color or TextureCoordinate:
  IndexError in the colour and texture-coordinate passes;
* an IndexedTriangleFanSet of three or more fans: the third fan restarted at the wrong index (RuntimeError);
* an IndexedFaceSet with few indices and many points (the vertex cull path) and an index past the points: IndexError.

And one from this round's held-out scene-chaos seed (rng 11): an Alpha of 1e39 wrote a transparency of -3.4e38 in the
X3D 3.3 writer, which has no export gate.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_chaos_round3_bpy
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

GRID = " ".join(f"{x} {y} 0" for y in range(5) for x in range(5))   # 25 points
COLOURS = " ".join("1 0 0" for _ in range(25))
UVS = " ".join(f"{x / 4} {y / 4}" for y in range(5) for x in range(5))


def _x3d(body: str) -> str:
    return ("<?xml version='1.0' encoding='UTF-8'?>\n<X3D profile='Full' version='4.0'><Scene>"
            f"{body}</Scene></X3D>\n")


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class ReceiptToRuleReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="x3d_chaos3_")
        _register_extension(cls.tmpdir)

    def _import(self, name, body):
        import bpy
        path = os.path.join(self.tmpdir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(_x3d(body))
        bpy.ops.wm.read_factory_settings(use_empty=True)
        result = bpy.ops.import_scene.x3d(filepath=path)
        return result, [o for o in bpy.data.objects if o.type == "MESH"]

    def _round_trip(self, name, body):
        import bpy
        result, meshes = self._import(name, body)
        self.assertEqual(result, {"FINISHED"})
        out = os.path.join(self.tmpdir, "out-" + name)
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=out), {"FINISHED"})
        return meshes

    def test_coordinate_double_triangle_sets_and_face_set(self):
        point = "0 0 0 1 0 0 1 1 0 0 1 0"
        for node, index in (("IndexedTriangleSet", "index='0 1 2 0 2 3'"),
                            ("IndexedTriangleStripSet", "index='0 1 3 2'"),
                            ("IndexedTriangleFanSet", "index='0 1 2 3'"),
                            ("IndexedFaceSet", "coordIndex='0 1 2 3 -1'"),
                            ("TriangleSet", "")):
            with self.subTest(node=node):
                meshes = self._round_trip(node + "_double.x3d",
                                          f"<Shape><{node} {index}><CoordinateDouble point='{point}'/></{node}></Shape>")
                self.assertEqual(len(meshes), 1)
                self.assertEqual(len(meshes[0].data.vertices), 4)

    def test_metadata_boolean_exports(self):
        import bpy
        self._round_trip("metabool.x3d",
                         "<WorldInfo title='t'><MetadataBoolean containerField='metadata' name='flags' "
                         "value='true false true false'/></WorldInfo>"
                         "<Shape><IndexedFaceSet coordIndex='0 1 2 -1'><Coordinate point='0 0 0 1 0 0 1 1 0'/>"
                         "</IndexedFaceSet></Shape>")
        from validate import _coerce_field
        self.assertEqual(_coerce_field("true false", ("value", None, "MFBool")), [True, False])
        with self.assertRaises(ValueError):
            _coerce_field("true 1", ("value", None, "MFBool"))
        self.assertIsNotNone(bpy)

    def test_index_past_the_points_with_colour_and_uv(self):
        cases = {
            "its_color.x3d": f"<Shape><IndexedTriangleSet index='0 2147483647 2 3 4 5'><Coordinate point='{GRID}'/>"
                             f"<Color color='{COLOURS}'/></IndexedTriangleSet></Shape>",
            "itss_color.x3d": f"<Shape><IndexedTriangleStripSet index='0 1 2 536870910'><Coordinate point='{GRID}'/>"
                              f"<Color color='{COLOURS}'/></IndexedTriangleStripSet></Shape>",
            "itss_uv.x3d": f"<Shape><IndexedTriangleStripSet index='0 1 2 19311470'><Coordinate point='{GRID}'/>"
                           f"<TextureCoordinate point='{UVS}'/></IndexedTriangleStripSet></Shape>",
        }
        for name, body in cases.items():
            with self.subTest(name=name):
                result, meshes = self._import(name, body)
                self.assertEqual(result, {"FINISHED"})
                self.assertEqual(len(meshes), 1)
                self.assertEqual(len(meshes[0].data.vertices), 26)   # one added vertex at the origin
                self.assertEqual(len(meshes[0].data.polygons), 2)

    def test_three_fans(self):
        result, meshes = self._import(
            "fans.x3d", f"<Shape><IndexedTriangleFanSet index='0 1 2 3 -1 5 6 7 -1 10 11 12 13 14 -1'>"
                        f"<Coordinate point='{GRID}'/></IndexedTriangleFanSet></Shape>")
        self.assertEqual(result, {"FINISHED"})
        faces = sorted(tuple(p.vertices) for p in meshes[0].data.polygons)
        self.assertEqual(faces, sorted([(0, 1, 2), (0, 2, 3), (5, 6, 7), (10, 11, 12), (10, 12, 13), (10, 13, 14)]))

    def test_short_runs_and_strip_winding(self):
        result, meshes = self._import(
            "strips.x3d", f"<Shape><IndexedTriangleStripSet index='0 1 -1 2 3 4 5 -1 -1 7'>"
                          f"<Coordinate point='{GRID}'/></IndexedTriangleStripSet></Shape>")
        self.assertEqual(result, {"FINISHED"})
        self.assertEqual([tuple(p.vertices) for p in meshes[0].data.polygons], [(2, 3, 4), (4, 3, 5)])

    def test_face_set_cull_path_index_past_the_points(self):
        result, meshes = self._import(
            "crease.x3d", f"<Shape><IndexedFaceSet creaseAngle='1' coordIndex='0 2147483638 2 3 -1'>"
                          f"<Coordinate point='{GRID}'/></IndexedFaceSet></Shape>")
        self.assertEqual(result, {"FINISHED"})
        self.assertEqual(len(meshes[0].data.polygons), 1)
        self.assertEqual(len(meshes[0].data.vertices), 4)


    def test_x3d33_alpha_out_of_range_writes_a_valid_transparency(self):
        import bpy
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.mesh.primitive_cube_add()
        mat = bpy.data.materials.new("Huge")
        mat.use_nodes = True
        mat.node_tree.nodes["Principled BSDF"].inputs["Alpha"].default_value = 1e39
        bpy.context.object.data.materials.append(mat)
        out = os.path.join(self.tmpdir, "alpha33.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=out, x3d_version="X3D33"), {"FINISHED"})
        text = Path(out).read_text(encoding="utf-8")
        self.assertIn('transparency="0.000"', text)
        self.assertNotIn("e+38", text)
        self.assertNotIn('transparency="-', text)


if __name__ == "__main__":
    unittest.main()
