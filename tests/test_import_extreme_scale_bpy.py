# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Importer: an Inline under a Transform with an extreme (or zero) scale.

Matrix.inverted() works in float32, where the determinant of a uniform 1e-16 scale
(one unit = one light-year, as in docs/showcase/scenes/stars-view.x3d) underflows to 0
and raised "matrix does not have an inverse", aborting the whole import. The parent
inverse is now computed in float64. A scale of exactly 0 is singular for real: the
import keeps going and logs a warning.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_import_extreme_scale_bpy
"""

from __future__ import annotations

import math
import os
import tempfile
import unittest

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

from test_roundtrip_bpy import _register_extension

HEADER = ("<?xml version='1.0' encoding='UTF-8'?>\n"
          "<X3D profile='Immersive' version='4.0'><Scene>\n")
FOOTER = "</Scene></X3D>\n"

# The Inlined file: a unit Box at X3D (3, 2, 1).
CHILD_BODY = ("<Transform translation='3 2 1'>"
              "<Shape DEF='Child'><Box size='1 1 1'/></Shape></Transform>")
ANGLE = math.pi / 2


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

    def _import_inline(self, tag: str, scale: str):
        import bpy
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self._write(f"child_{tag}.x3d", CHILD_BODY)
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


if __name__ == "__main__":
    unittest.main()
