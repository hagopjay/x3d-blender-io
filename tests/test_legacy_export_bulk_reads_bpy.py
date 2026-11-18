# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The X3D 3.0/3.3 writer reads UV and colour layers in bulk, so its export time is linear in the mesh size.

In Blender 5.x ``layer.data[i]`` costs time proportional to the layer's size. The legacy writer read the active UV
and colour layers once per corner, which made it quadratic: a 129 x 129 grid with UVs and corner colours (65,536
corners) took 74 s, 151 s triangulated, and a 1M-triangle scene did not finish in 20 minutes (Blender 5.1.0). The
same pattern was fixed for the 4.0 extractor in test_extract_bulk_reads_bpy.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_legacy_export_bulk_reads_bpy
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
import time
import unittest

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

from test_roundtrip_bpy import _register_extension, SOURCE_DIR


def _grid(n):
    """An n x n grid with its UV map and a CORNER byte colour attribute that varies per corner."""
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=n - 1, y_subdivisions=n - 1)
    mesh = bpy.context.active_object.data
    colours = mesh.color_attributes.new("Colour", "BYTE_COLOR", "CORNER")
    flat = []
    for index in range(len(mesh.loops)):
        flat += [(index % 7) / 6.0, (index % 5) / 4.0, 0.5, 1.0]
    colours.data.foreach_set("color", flat)
    return mesh


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class LegacyExportBulkReadsTests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="x3d_legacy_bulk_")
        _register_extension(self.tmpdir)
        sys.path.insert(0, str(SOURCE_DIR))
        bpy.ops.wm.read_factory_settings(use_empty=True)
        _register_extension(self.tmpdir)

    def _export(self, name, **options):
        path = os.path.join(self.tmpdir, name + ".x3d")
        started = time.perf_counter()
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=path, x3d_version="X3D33", use_selection=False, **options),
                         {"FINISHED"})
        with open(path, encoding="utf-8") as handle:
            return handle.read(), time.perf_counter() - started

    def test_large_mesh_exports_in_linear_time(self):
        _grid(97)  # 36,864 corners: 15 s plain and 37 s triangulated with per-corner reads (Blender 5.1.0, macOS)
        for triangulate in (False, True):
            with self.subTest(triangulate=triangulate):
                _text, elapsed = self._export(f"grid_{triangulate}", use_triangulate=triangulate)
                self.assertLess(elapsed, 5.0, f"export took {elapsed:.1f} s: corner layers must be read in bulk")

    def test_written_uvs_and_colours_are_the_layer_values(self):
        mesh = _grid(5)
        text, _elapsed = self._export("small")
        uv_field = re.search(r'<TextureCoordinate point="([^"]*)"', text).group(1).split()
        uvs = [(float(uv_field[i]), float(uv_field[i + 1])) for i in range(0, len(uv_field), 2)]
        layer = mesh.uv_layers.active.data
        want = [tuple(round(v, 4) for v in layer[loop].uv) for polygon in mesh.polygons for loop in polygon.loop_indices]
        self.assertEqual([tuple(round(v, 4) for v in uv) for uv in uvs], want)
        colour_field = re.search(r'<ColorRGBA color="([^"]*)"', text).group(1).split()
        first_face = [float(v) for v in colour_field[:4]]
        expected = mesh.vertex_colors.active.data[mesh.polygons[0].loop_start].color
        self.assertEqual(first_face, [round(v, 3) for v in expected])


if __name__ == "__main__":
    unittest.main()
