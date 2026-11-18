# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A Shape under a rotated Transform inside a non-uniformly scaled one keeps its world-space vertices.

The product of such Transforms has shear, which an object's location/rotation/scale cannot hold: setting
``matrix_world`` dropped it, so the geometry came in skewed (every vertex of a random round trip off by up to a few
units). The importer now keeps the nearest location/rotation/scale on the object and bakes the remaining shear into
the mesh, copying a mesh other objects share first.

Expected positions are computed from the X3D text alone (spec matrix composition), not by Blender.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_import_sheared_transform_bpy
"""

from __future__ import annotations

import math
import os
import sys
import tempfile
import unittest

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

from test_roundtrip_bpy import _register_extension, SOURCE_DIR

POINTS = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 1)]
OUTER = {"translation": (1, 2, 3), "rotation": (0, 0, 1, 0.6), "scale": (3, 0.5, 1)}
INNER = {"translation": (2, 0, 0), "rotation": (1, 1, 0, 0.9), "scale": (1, 1, 1)}

DOCUMENT = ('<X3D version="4.0"><Scene>'
            '<Transform translation="1 2 3" rotation="0 0 1 0.6" scale="3 0.5 1">'
            '<Transform translation="2 0 0" rotation="1 1 0 0.9">'
            '<Shape DEF="Piece"><IndexedFaceSet coordIndex="0 1 2 -1 0 2 3 -1">'
            '<Coordinate point="0 0 0 1 0 0 1 1 0 0 1 1"/></IndexedFaceSet></Shape>'
            '</Transform></Transform>'
            '<Transform translation="-5 0 0"><Shape USE="Piece"/></Transform>'
            '</Scene></X3D>')


def _rotation(axis, angle):
    length = math.sqrt(sum(a * a for a in axis))
    x, y, z = (a / length for a in axis)
    c, s, t = math.cos(angle), math.sin(angle), 1 - math.cos(angle)
    return [[c + x * x * t, x * y * t - z * s, x * z * t + y * s],
            [y * x * t + z * s, c + y * y * t, y * z * t - x * s],
            [z * x * t - y * s, z * y * t + x * s, c + z * z * t]]


def _apply(transform, point):
    rotation = _rotation(transform["rotation"][:3], transform["rotation"][3])
    scaled = [point[i] * transform["scale"][i] for i in range(3)]
    return tuple(sum(rotation[r][c] * scaled[c] for c in range(3)) + transform["translation"][r] for r in range(3))


def _to_blender(point):
    """X3D is Y-up; the importer's default axis conversion maps (x, y, z) to (x, -z, y)."""
    x, y, z = point
    return (x, -z, y)


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class ImportShearedTransformTests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="x3d_shear_")
        _register_extension(self.tmpdir)
        sys.path.insert(0, str(SOURCE_DIR))
        bpy.ops.wm.read_factory_settings(use_empty=True)
        _register_extension(self.tmpdir)
        path = os.path.join(self.tmpdir, "shear.x3d")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(DOCUMENT)
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=path), {"FINISHED"})
        bpy.context.view_layer.update()
        self.meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]

    def _world(self, obj):
        return [tuple(obj.matrix_world @ vertex.co) for vertex in obj.data.vertices]

    def _assert_points(self, got, want):
        self.assertEqual(len(got), len(want))
        for point in want:
            nearest = min(math.dist(point, other) for other in got)
            self.assertLess(nearest, 1e-4, f"{point} not imported; nearest is {nearest:.4f} away")

    def test_sheared_shape_keeps_its_world_vertices(self):
        want = [_to_blender(_apply(OUTER, _apply(INNER, p))) for p in POINTS]
        sheared = min(self.meshes, key=lambda obj: min(math.dist(want[0], p) for p in self._world(obj)))
        self._assert_points(self._world(sheared), want)

    def test_use_in_an_unsheared_place_is_unchanged(self):
        """The USE elsewhere still shares the original mesh, or at least keeps its own correct vertices."""
        moved = {"translation": (-5, 0, 0), "rotation": (0, 0, 1, 0), "scale": (1, 1, 1)}
        want = [_to_blender(_apply(moved, p)) for p in POINTS]
        plain = min(self.meshes, key=lambda obj: min(math.dist(want[0], p) for p in self._world(obj)))
        self._assert_points(self._world(plain), want)
        self.assertEqual(len(self.meshes), 2)


if __name__ == "__main__":
    unittest.main()
