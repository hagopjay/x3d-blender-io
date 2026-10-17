# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Importer regression: an ElevationGrid whose xDimension differs from its zDimension.

The importer built the vertices with x as the outer loop and z as the inner one, but
indexed them (faces, colours, texture coordinates) with z outer and x inner. The two
orders only agree on a square grid, so a non-square one came out as long vertical fins.
Found by importing the Giza Sphinx-site terrain (151 x 121 grid, 2 m spacing).

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_import_elevation_nonsquare_bpy
"""

from __future__ import annotations

import os
import tempfile
import unittest

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

from test_roundtrip_bpy import _register_extension

X_DIM, Z_DIM, X_SP, Z_SP = 4, 3, 2.0, 5.0
HEIGHT = " ".join(str(10 * i + j) for j in range(Z_DIM) for i in range(X_DIM))   # height[j * xDim + i] = 10 i + j
COLORS = ", ".join("%g 0 0" % ((j * X_DIM + i) / (X_DIM * Z_DIM - 1)) for j in range(Z_DIM) for i in range(X_DIM))
TEXT = ("<?xml version='1.0' encoding='UTF-8'?>\n<X3D profile='Immersive' version='4.0'><Scene>\n"
        "<Shape><ElevationGrid xDimension='%d' zDimension='%d' xSpacing='%g' zSpacing='%g' height='%s' "
        "colorPerVertex='true'><Color color='%s'/></ElevationGrid></Shape>\n</Scene></X3D>\n"
        % (X_DIM, Z_DIM, X_SP, Z_SP, HEIGHT, COLORS))


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class ElevationGridNonSquareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="x3d_elev_nonsquare_")
        _register_extension(cls.tmpdir)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        path = os.path.join(cls.tmpdir, "elev_nonsquare.x3d")
        with open(path, "w", encoding="utf-8") as f:
            f.write(TEXT)
        assert bpy.ops.import_scene.x3d(filepath=path) == {"FINISHED"}
        cls.mesh = [o for o in bpy.context.scene.objects if o.type == "MESH"][0].data

    def _ij(self, v):
        return round(v.co.x / X_SP), round(v.co.z / Z_SP)

    def test_every_vertex_sits_on_its_grid_node_with_its_height(self):
        for v in self.mesh.vertices:
            i, j = self._ij(v)
            self.assertAlmostEqual(v.co.y, 10 * i + j, places=4)

    def test_every_face_is_one_grid_cell(self):
        self.assertEqual(len(self.mesh.polygons), (X_DIM - 1) * (Z_DIM - 1))
        for poly in self.mesh.polygons:
            nodes = [self._ij(self.mesh.vertices[k]) for k in poly.vertices]
            xs = sorted({n[0] for n in nodes}); zs = sorted({n[1] for n in nodes})
            self.assertEqual(len(nodes), 4)
            self.assertEqual(len(xs), 2); self.assertEqual(len(zs), 2)
            self.assertEqual(xs[1] - xs[0], 1)
            self.assertEqual(zs[1] - zs[0], 1)

    def test_default_uv_and_colour_follow_the_vertex(self):
        uv = self.mesh.uv_layers.active.data
        col = self.mesh.color_attributes["ColorPerCorner"].data
        reds = []
        for poly in self.mesh.polygons:
            for loop in poly.loop_indices:
                i, j = self._ij(self.mesh.vertices[self.mesh.loops[loop].vertex_index])
                self.assertAlmostEqual(uv[loop].uv[0], i / (X_DIM - 1), places=5)
                self.assertAlmostEqual(uv[loop].uv[1], j / (Z_DIM - 1), places=5)
                reds.append(((j * X_DIM + i), col[loop].color[0]))
        reds.sort(key=lambda t: t[0])
        values = [r for _, r in reds]
        self.assertEqual(values, sorted(values))   # colour rises with the file's vertex index


if __name__ == "__main__":
    unittest.main()
