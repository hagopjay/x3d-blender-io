# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Small and extreme numbers survive X3D 4.0 export.

* Mesh coordinates below 1e-3 keep their significant digits (``%.6f`` wrote a 3e-7 mesh as all zeros), in a plain
  Coordinate, in a skinned or morphed Coordinate and in a CoordinateInterpolator.
* An object scale beyond float32's squared range (|s| > ~1e19 or < ~1e-19) keeps its value and does not corrupt the
  rotation: ``Matrix.decompose()`` squares the axis lengths in float32, got 0, and returned a rotation that tilted the
  other two axes.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_export_number_precision_bpy
"""

from __future__ import annotations

import math
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

from test_roundtrip_bpy import _register_extension, SOURCE_DIR


def _floats(text):
    return [float(token) for token in text.split()]


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class ExportNumberPrecisionTests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="x3d_numbers_")
        _register_extension(self.tmpdir)
        sys.path.insert(0, str(SOURCE_DIR))
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def _export(self, name, **options):
        from validate import validate_xml_file
        path = os.path.join(self.tmpdir, name + ".x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=path, x3d_version="X3D40", use_selection=False, **options),
                         {"FINISHED"})
        result = validate_xml_file(path)
        self.assertTrue(result.valid, result.errors)
        return ET.parse(path).getroot()

    def _tiny_mesh(self, name="Tiny", size=3e-7):
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata([(0, 0, 0), (size, 0, 0), (0, size, 0), (0, 0, size)], [], [(0, 1, 2), (0, 1, 3)])
        obj = bpy.data.objects.new(name, mesh)
        bpy.context.scene.collection.objects.link(obj)
        return obj

    def test_sub_micrometre_mesh_keeps_its_coordinates(self):
        self._tiny_mesh()
        root = self._export("tiny")
        points = _floats(root.find(".//IndexedFaceSet/Coordinate").attrib["point"])
        self.assertEqual(len(points), 12)
        # Z-up to Y-up: the four vertices are the origin and 3e-7 along each axis
        nonzero = sorted(abs(value) for value in points if value != 0.0)
        self.assertEqual(len(nonzero), 3, points)
        for value in nonzero:
            self.assertAlmostEqual(value / 3e-7, 1.0, places=6)

    def test_sub_micrometre_morph_keeps_its_key_values(self):
        obj = self._tiny_mesh()
        obj.shape_key_add(name="Basis")
        key = obj.shape_key_add(name="Grow")
        key.data[1].co.x = 6e-7
        key.value = 0.0
        key.keyframe_insert("value", frame=1)
        key.value = 1.0
        key.keyframe_insert("value", frame=10)
        root = self._export("tiny_morph", use_animation=True)
        interpolator = root.find(".//CoordinateInterpolator")
        self.assertIsNotNone(interpolator)
        values = _floats(interpolator.attrib["keyValue"])
        self.assertTrue(any(abs(value / 6e-7 - 1.0) < 1e-6 for value in values), values)
        self.assertTrue(any(abs(value / 3e-7 - 1.0) < 1e-6 for value in values), values)

    def _transform(self, root, name):
        return root.find(f".//Transform[@DEF='OB_{name}']")

    def _extreme_scale_case(self, factor):
        bpy.ops.mesh.primitive_cube_add()
        reference = bpy.context.active_object
        reference.name = "Reference"
        reference.rotation_euler = (0.3, 0.2, 0.1)
        bpy.ops.mesh.primitive_cube_add(location=(5, 0, 0))
        extreme = bpy.context.active_object
        extreme.name = "Extreme"
        extreme.rotation_euler = (0.3, 0.2, 0.1)
        extreme.scale = (factor, 1.0, 1.0)
        root = self._export("scale_%g" % factor)
        want = _floats(self._transform(root, "Reference").attrib["rotation"])
        got_transform = self._transform(root, "Extreme")
        got = _floats(got_transform.attrib["rotation"])
        # the same rotation, allowing the equivalent (-axis, -angle) spelling
        if got[3] * want[3] < 0:
            got = [-value for value in got]
        for a, b in zip(got, want):
            self.assertAlmostEqual(a, b, places=4, msg=f"rotation {got} != {want}")
        scale = _floats(got_transform.attrib["scale"])
        self.assertTrue(math.isclose(scale[0], factor, rel_tol=1e-5), scale)
        self.assertEqual(scale[1:], [1.0, 1.0])

    def test_huge_scale_keeps_value_and_rotation(self):
        self._extreme_scale_case(1e20)

    def test_minute_scale_keeps_value_and_rotation(self):
        self._extreme_scale_case(1e-20)

    def test_everyday_matrices_are_unchanged(self):
        """The float64 fallback only runs for extreme scales: a normal transform is written as before."""
        bpy.ops.mesh.primitive_cube_add(location=(1.5, -2.25, 0.125))
        cube = bpy.context.active_object
        cube.name = "Normal"
        cube.rotation_euler = (0.5, 0.0, 1.0)
        cube.scale = (2.0, 0.5, 1.0)
        transform = self._transform(self._export("normal"), "Normal")
        self.assertEqual(transform.attrib["translation"], "1.500000 0.125000 2.250000")
        self.assertEqual(transform.attrib["scale"], "2.000000 0.500000 1.000000")


if __name__ == "__main__":
    unittest.main()
