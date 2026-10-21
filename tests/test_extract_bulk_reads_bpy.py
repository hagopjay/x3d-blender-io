# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Per-corner attributes are read in bulk, so the export of a large mesh is linear in its size.

In Blender 5.x an indexed read of a corner attribute (``layer.uv[i].vector``, ``corner_normals[i].vector``,
``color_attributes.active_color.data[i].color``) costs time proportional to the collection's size. The extractor
read them once per corner, which made the export quadratic: a 66,177-vertex relief grid took 315 s and took
0.67 s once the three accessors read everything with one ``foreach_get`` each.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_extract_bulk_reads_bpy
"""

from __future__ import annotations

import importlib
import tempfile
import time
import unittest

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

from test_roundtrip_bpy import _register_extension


def _grid(n: int):
    """An n x n grid mesh with a non-trivial UV layer and a CORNER float color attribute."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=n - 1, y_subdivisions=n - 1, size=1.0)
    mesh = bpy.context.active_object.data
    corners = len(mesh.loops)
    mesh.uv_layers.active.uv.foreach_set("vector", [((i * 7919) % 1000) / 1000.0 for i in range(corners * 2)])
    colors = mesh.color_attributes.new("c", "FLOAT_COLOR", "CORNER")
    colors.data.foreach_set("color", [((i * 104729) % 1000) / 1000.0 for i in range(corners * 4)])
    mesh.update()
    return mesh


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class BulkAttributeReadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _register_extension(tempfile.mkdtemp())
        cls.extract = importlib.import_module("io_scene_x3d.extract")

    def test_accessors_return_what_element_wise_reads_return(self):
        mesh = _grid(9)
        uv_at = self.extract._uv_values(mesh)
        color_at, domain = self.extract._color_values(mesh)
        normal_at = self.extract._corner_normals(mesh)
        self.assertEqual(domain, "CORNER")
        uv = mesh.uv_layers.active.uv
        colors = mesh.color_attributes.active_color.data
        for i in range(len(mesh.loops)):
            self.assertEqual(uv_at(i), tuple(uv[i].vector[:2]))
            c = colors[i].color
            self.assertEqual(color_at(i), (float(c[0]), float(c[1]), float(c[2]), float(c[3])))
            self.assertEqual(normal_at(i), tuple(mesh.corner_normals[i].vector[:3]))

    def test_large_mesh_is_extracted_in_linear_time(self):
        mesh = _grid(129)  # 16,641 vertices, 65,536 corners; the element-wise reads took about half a minute here
        started = time.perf_counter()
        geometries = self.extract.extract_mesh_geometries(mesh, name="grid", use_normals=True)
        elapsed = time.perf_counter() - started
        self.assertEqual(len(geometries), 1)
        self.assertLess(elapsed, 10.0, f"extraction took {elapsed:.1f} s: corner attributes must be read in bulk")


if __name__ == "__main__":
    unittest.main()
