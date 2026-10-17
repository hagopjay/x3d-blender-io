# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Importer regression: an ElevationGrid with a Color or ColorRGBA child.

The per-corner colour attribute holds four floats per corner; the importer used to
hand it three (Color) or three of four (ColorRGBA), so the whole import stopped with
"internal error setting the array". Found by importing the Shroud of Turin
face-relief scene (a 150 x 150 grid with per-vertex Color).

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_import_elevation_color_bpy
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

HEADER = ("<?xml version='1.0' encoding='UTF-8'?>\n"
          "<X3D profile='Immersive' version='4.0'><Scene>\n")
FOOTER = "</Scene></X3D>\n"

GRID = ("<Shape><ElevationGrid xDimension='3' zDimension='3' xSpacing='1' zSpacing='1' "
        "height='0 0.1 0  0.2 0.3 0.2  0 0.1 0' colorPerVertex='true'>%s</ElevationGrid></Shape>")
RGB = "<Color color='" + " ".join("1 0 0," if i % 2 else "0 0 1," for i in range(9)).rstrip(",") + "'/>"
RGBA = "<ColorRGBA color='" + " ".join("1 0 0 0.5," for i in range(9)).rstrip(",") + "'/>"


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class ElevationGridColorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="x3d_elev_color_")
        _register_extension(cls.tmpdir)

    def _import(self, name: str, color_node: str):
        import bpy
        bpy.ops.wm.read_factory_settings(use_empty=True)
        path = os.path.join(self.tmpdir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(HEADER + GRID % color_node + FOOTER)
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=path), {"FINISHED"})
        meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
        self.assertEqual(len(meshes), 1)
        return meshes[0].data

    def test_color_child_imports(self):
        mesh = self._import("elev_rgb.x3d", RGB)
        self.assertEqual(len(mesh.polygons), 4)
        attr = mesh.color_attributes["ColorPerCorner"]
        self.assertEqual(len(attr.data), 16)
        self.assertTrue(all(abs(d.color[3] - 1.0) < 1e-6 for d in attr.data))

    def test_color_rgba_child_keeps_alpha(self):
        mesh = self._import("elev_rgba.x3d", RGBA)
        attr = mesh.color_attributes["ColorPerCorner"]
        self.assertEqual(len(attr.data), 16)
        self.assertTrue(all(d.color[3] > 0.2 for d in attr.data))


if __name__ == "__main__":
    unittest.main()
