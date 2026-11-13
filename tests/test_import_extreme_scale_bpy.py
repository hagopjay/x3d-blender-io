# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Importer: an Inline under a Transform with an extreme (or zero) scale.

Matrix.inverted() works in float32, where the determinant of a uniform 1e-16 scale
(one unit = one light-year, as in docs/showcase/scenes/stars-view.x3d) underflows to 0
and raised "matrix does not have an inverse", aborting the whole import. The parent
inverse is now computed in float64. A scale of exactly 0 is singular for real: the
import keeps going and logs a warning.

The glTF exporter has the same float32 problem one step later: it writes each child as
``parent.matrix_world.inverted_safe() @ child.matrix_world``, and inverted_safe() turns a 1e-16 scale into
about 1e8, so stars-view.glb came out about 1e8 too small. The import now moves such a scale off the Inline's
empty onto its children (source/matrix_safety.py) and the X3D export puts it back on the Inline's Transform.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_import_extreme_scale_bpy
"""

from __future__ import annotations

import json
import math
import os
import re
import struct
import tempfile
import unittest
from pathlib import Path

import numpy as np

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

from test_roundtrip_bpy import _register_extension

HEADER = ("<?xml version='1.0' encoding='UTF-8'?>\n"
          "<X3D profile='Immersive' version='4.0'><Scene>\n")
FOOTER = "</Scene></X3D>\n"
STARS_VIEW = Path(__file__).resolve().parents[1] / "docs" / "showcase" / "scenes" / "stars-view.x3d"
LIGHT_YEAR = 9.4607e15

# The Inlined file: a unit Box at X3D (3, 2, 1).
CHILD_BODY = ("<Transform translation='3 2 1'>"
              "<Shape DEF='Child'><Box size='1 1 1'/></Shape></Transform>")
ANGLE = math.pi / 2
# Laid out like stars-splats.x3d under stars-view.x3d: the Inlined file scales itself up by 1e16 and the Inline
# scales it down by 1e-16, so the world result is ordinary-sized and only the Inline's matrix is extreme.
FAR_CHILD_BODY = ("<Transform scale='1e16 1e16 1e16'><Transform translation='3 2 1'>"
                  "<Shape DEF='Child'><Box size='1 1 1'/></Shape></Transform></Transform>")


def _expected_world(scale: float):
    """Blender world position of the Box centre: Ry(90 deg) * scale * (3, 2, 1) in X3D, then (x, y, z) -> (x, -z, y)."""
    x, y, z = 3.0 * scale, 2.0 * scale, 1.0 * scale
    x, z = x * math.cos(ANGLE) + z * math.sin(ANGLE), -x * math.sin(ANGLE) + z * math.cos(ANGLE)
    return (x, -z, y)


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class ImportExtremeScaleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="x3d_extreme_scale_")
        _register_extension(cls.tmpdir)

    def _write(self, name: str, body: str) -> str:
        path = os.path.join(self.tmpdir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(HEADER + body + FOOTER)
        return path

    def _import_inline(self, tag: str, scale: str, body: str = CHILD_BODY):
        import bpy
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self._write(f"child_{tag}.x3d", body)
        path = self._write(
            f"outer_{tag}.x3d",
            f"<Transform rotation='0 1 0 {ANGLE}' scale='{scale}'><Inline url='\"child_{tag}.x3d\"'/></Transform>")
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=path), {"FINISHED"})
        return {o.name: o for o in bpy.data.objects}

    def test_scale_1e_16_inline_lands_at_the_expected_world_position(self):
        scale = 1e-16
        objs = self._import_inline("tiny", f"{scale} {scale} {scale}")
        child = objs["Child"]
        self.assertIsNotNone(child.parent)
        expected = _expected_world(scale)
        got = tuple(child.matrix_world.translation)
        # float32 matrices: about 1e-7 relative to the position, so compare against the distance from the origin
        tolerance = 1e-5 * scale * math.sqrt(14.0)
        for g, e in zip(got, expected):
            self.assertAlmostEqual(g, e, delta=tolerance)
        # the cube's edge is `scale` long in world space
        corners = [child.matrix_world @ v.co for v in child.data.vertices]
        extent = max(c.x for c in corners) - min(c.x for c in corners)
        self.assertAlmostEqual(extent / scale, 1.0, delta=1e-5)

    def test_the_result_is_the_same_scene_scaled(self):
        """1e-16 and 1e-3 give the same layout up to the scale factor (and float precision)."""
        small = self._import_inline("a", "1e-16 1e-16 1e-16")["Child"].matrix_world.translation.copy()
        large = self._import_inline("b", "1e-3 1e-3 1e-3")["Child"].matrix_world.translation.copy()
        for s, l in zip(small, large):
            self.assertAlmostEqual(s / 1e-16, l / 1e-3, delta=1e-5 * 4)

    def test_scale_zero_does_not_abort_the_import(self):
        with self.assertLogs("import_x3d", level="WARNING") as logs:
            objs = self._import_inline("zero", "0 0 0")
        self.assertIn("Child", objs)
        self.assertTrue(any("singular" in line for line in logs.output), logs.output)

    def test_inverted_helper(self):
        from mathutils import Matrix
        import io_scene_x3d.import_x3d as importer
        for scale in (1.0, 1e-3, 1e-16, 1e-30):
            inverse = importer._inverted(Matrix.Diagonal((scale, scale, scale, 1.0)))
            self.assertAlmostEqual(inverse[0][0] * scale, 1.0, delta=1e-6, msg=scale)
        with self.assertLogs("import_x3d", level="WARNING"):
            self.assertEqual(importer._inverted(Matrix.Diagonal((0.0, 0.0, 0.0, 1.0))),
                             Matrix.Diagonal((0.0, 0.0, 0.0, 1.0)))
        with self.assertLogs("import_x3d", level="WARNING"):   # 1e-39 inverts to 1e39, past float32's 3.4e38
            self.assertEqual(importer._inverted(Matrix.Diagonal((1e-39, 1e-39, 1e-39, 1.0))), Matrix())

    def test_a_flat_parent_keeps_its_inlined_content_in_place(self):
        """Scale 0 on one axis: the pseudo-inverse keeps the parent's translation from being applied twice."""
        import bpy
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self._write("child_flat.x3d", "<Transform><Shape DEF='Child'><Box size='1 1 1'/></Shape></Transform>")
        path = self._write("outer_flat.x3d", "<Transform translation='0 5 0' scale='0 1 1'>"
                                             "<Inline url='\"child_flat.x3d\"'/></Transform>")
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=path), {"FINISHED"})
        centre = bpy.data.objects["Child"].matrix_world.translation
        self.assertAlmostEqual(centre.z, 5.0, delta=1e-4)   # X3D y 5 is Blender z 5; the identity gave 10

    # --- glTF export and X3D re-export (the scale moved onto the Inline's children) ---------------------------

    def _export_glb(self, tag: str):
        import bpy
        path = os.path.join(self.tmpdir, f"{tag}.glb")
        self.assertEqual(bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", export_yup=True,
                                                   use_mesh_edges=True, use_mesh_vertices=True), {"FINISHED"})
        data = Path(path).read_bytes()
        (json_len,) = struct.unpack_from("<I", data, 12)
        doc = json.loads(data[20:20 + json_len])
        return doc, data[20 + json_len + 8:]

    @staticmethod
    def _node_worlds(doc):
        """World matrix of every glTF node, composed in float64 from its TRS."""
        def local(node):
            if "matrix" in node:
                return np.array(node["matrix"], dtype=np.float64).reshape(4, 4).T
            x, y, z, w = node.get("rotation", [0, 0, 0, 1])
            r = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                          [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                          [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
            m = np.eye(4)
            m[:3, :3] = r @ np.diag(node.get("scale", [1, 1, 1]))
            m[:3, 3] = node.get("translation", [0, 0, 0])
            return m
        parents = {c: i for i, n in enumerate(doc["nodes"]) for c in n.get("children", [])}
        worlds = {}
        def world(i):
            if i not in worlds:
                worlds[i] = (world(parents[i]) @ local(doc["nodes"][i])) if i in parents else local(doc["nodes"][i])
            return worlds[i]
        return {doc["nodes"][i].get("name", str(i)): world(i) for i in range(len(doc["nodes"]))}

    def _glb_box_centre(self, doc, blob, name="Child"):
        """glTF world-space centre of the named mesh node's POSITION bounds (y up)."""
        worlds = self._node_worlds(doc)
        node = next(n for n in doc["nodes"] if n.get("name") == name)
        accessor = doc["accessors"][doc["meshes"][node["mesh"]]["primitives"][0]["attributes"]["POSITION"]]
        centre = (np.array(accessor["min"]) + np.array(accessor["max"])) / 2.0
        return (worlds[name] @ np.append(centre, 1.0))[:3]

    def test_glb_export_keeps_the_world_position_at_scale_1e_16(self):
        """Was about 1e8 too small: the glTF exporter inverted the Inline empty's 1e-16 matrix in float32."""
        self._import_inline("glb_tiny", "1e-16 1e-16 1e-16", FAR_CHILD_BODY)
        doc, blob = self._export_glb("glb_tiny")
        bx, by, bz = _expected_world(1.0)                 # Blender z up -> glTF y up: (x, z, -y)
        expected = np.array([bx, bz, -by])
        got = self._glb_box_centre(doc, blob)
        np.testing.assert_allclose(got, expected, rtol=0, atol=1e-5 * math.sqrt(14.0))

    def test_glb_export_matches_a_moderate_scale(self):
        """1e-16 and 1e-3 give glbs whose box centres differ by exactly the scale ratio."""
        self._import_inline("glb_a", "1e-16 1e-16 1e-16", FAR_CHILD_BODY)
        tiny = self._glb_box_centre(*self._export_glb("glb_a"))
        self._import_inline("glb_b", "1e-3 1e-3 1e-3")
        milli = self._glb_box_centre(*self._export_glb("glb_b"))
        np.testing.assert_allclose(tiny, milli / 1e-3, rtol=1e-5, atol=1e-5)

    def test_inline_empty_is_unit_scaled_and_keeps_the_moved_scale(self):
        from io_scene_x3d.matrix_safety import SCALE_TO_CHILDREN_PROPERTY, axis_scales
        objs = self._import_inline("prop", "1e-16 1e-16 1e-16")
        empty = objs["Child"].parent
        while empty.parent is not None:
            empty = empty.parent
        self.assertTrue(empty.get("x3d_inline_url"))
        for s in axis_scales(empty.matrix_world):
            self.assertAlmostEqual(s, 1.0, delta=1e-6)
        moved = list(empty[SCALE_TO_CHILDREN_PROPERTY])
        for s in moved:
            self.assertAlmostEqual(s / 1e-16, 1.0, delta=1e-6)
        # the inverse Blender's exporters use now round-trips
        product = empty.matrix_world.inverted_safe() @ empty.matrix_world
        for i in range(4):
            for j in range(4):
                self.assertAlmostEqual(product[i][j], 1.0 if i == j else 0.0, delta=1e-5)

    def test_moderate_scales_are_left_alone(self):
        from io_scene_x3d.matrix_safety import SCALE_TO_CHILDREN_PROPERTY, axis_scales
        objs = self._import_inline("cm", "0.01 0.01 0.01")
        empty = objs["Child"].parent
        self.assertNotIn(SCALE_TO_CHILDREN_PROPERTY, empty)
        for s in axis_scales(empty.matrix_world):
            self.assertAlmostEqual(s, 0.01, delta=1e-8)

    def test_non_uniform_extreme_scale(self):
        """X3D (1e-16, 1, 1e-16): the moved scale is per axis and the child still lands where X3D puts it."""
        body = ("<Transform scale='1e16 1 1e16'><Transform translation='3 2 1'>"
                "<Shape DEF='Child'><Box size='1 1 1'/></Shape></Transform></Transform>")
        objs = self._import_inline("aniso", "1e-16 1 1e-16", body)
        child = objs["Child"]
        # Ry(90) * (3, 2, 1) = (1, 2, -3); Blender (x, -z, y) = (1, 3, 2)
        got = child.matrix_world.translation
        for g, e in zip(got, (1.0, 3.0, 2.0)):
            self.assertAlmostEqual(g, e, delta=1e-5)
        doc, blob = self._export_glb("aniso")
        np.testing.assert_allclose(self._glb_box_centre(doc, blob), [1.0, 2.0, -3.0], rtol=0, atol=1e-5)

    def test_nested_inlines_each_1e_minus_8(self):
        """Two Inlines at 1e-8 each (1e-16 together): every parent ends well scaled, the box lands right."""
        import bpy
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self._write("nest_leaf.x3d", FAR_CHILD_BODY)
        self._write("nest_mid.x3d", "<Transform scale='1e-8 1e-8 1e-8'><Inline url='\"nest_leaf.x3d\"'/></Transform>")
        path = self._write("nest_top.x3d", f"<Transform rotation='0 1 0 {ANGLE}' scale='1e-8 1e-8 1e-8'>"
                                           "<Inline url='\"nest_mid.x3d\"'/></Transform>")
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=path), {"FINISHED"})
        child = bpy.data.objects["Child"]
        expected = _expected_world(1.0)
        for g, e in zip(child.matrix_world.translation, expected):
            self.assertAlmostEqual(g, e, delta=1e-4)
        from io_scene_x3d.matrix_safety import axis_scales, is_extreme
        for ob in bpy.data.objects:
            if ob.type == "EMPTY" and ob.children:
                self.assertFalse(is_extreme(axis_scales(ob.matrix_world)), (ob.name, axis_scales(ob.matrix_world)))
        doc, blob = self._export_glb("nested")
        bx, by, bz = expected
        np.testing.assert_allclose(self._glb_box_centre(doc, blob), np.array([bx, bz, -by]), rtol=0, atol=1e-4)

    def test_x3d_reexport_puts_the_scale_back_on_the_inline(self):
        import bpy
        self._import_inline("rt", "1e-16 1e-16 1e-16")
        out = os.path.join(self.tmpdir, "rt_out.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=out, x3d_version="X3D40", use_selection=False),
                         {"FINISHED"})
        text = Path(out).read_text(encoding="utf-8")
        match = re.search(r"<Transform[^>]*?scale=['\"]([^'\"]+)['\"][^>]*>\s*<Inline", text)
        self.assertIsNotNone(match, text[:2000])
        for value in match.group(1).split():
            self.assertAlmostEqual(float(value) / 1e-16, 1.0, delta=1e-5)

    @unittest.skipUnless(STARS_VIEW.exists(), "docs/showcase/scenes/stars-view.x3d is not in this checkout")
    def test_stars_view_glb_spans_fifty_light_years(self):
        """The showcase scene: 978 stars within 50 ly, one unit one light-year. Was about 5e-7 across."""
        import bpy
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=str(STARS_VIEW)), {"FINISHED"})
        doc, _ = self._export_glb("stars_view")
        worlds = self._node_worlds(doc)
        reach = 0.0
        for node in doc["nodes"]:
            if "mesh" not in node:
                continue
            for primitive in doc["meshes"][node["mesh"]]["primitives"]:
                accessor = doc["accessors"][primitive["attributes"]["POSITION"]]
                for corner in np.array(np.meshgrid(*zip(accessor["min"], accessor["max"]))).T.reshape(-1, 3):
                    reach = max(reach, float(np.linalg.norm((worlds[node["name"]] @ np.append(corner, 1.0))[:3])))
        # the bounding box corners of a 50 ly ball reach at most 50 * sqrt(3); the farthest star is 49.9 ly out
        self.assertGreater(reach, 45.0)
        self.assertLess(reach, 50.0 * math.sqrt(3.0) + 1.0)


if __name__ == "__main__":
    unittest.main()
