# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Hostile scenes still export to a valid file: NaN and infinite values, odd names, empty and degenerate data.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_export_hardening_bpy
"""

from __future__ import annotations

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


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class ExportHardeningTests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="x3d_hardening_")
        _register_extension(self.tmpdir)
        sys.path.insert(0, str(SOURCE_DIR))
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def _export_and_validate(self, name="scene"):
        from validate import validate_xml_file
        path = os.path.join(self.tmpdir, name + ".x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=path, x3d_version="X3D40", use_selection=False), {"FINISHED"})
        result = validate_xml_file(path)
        self.assertTrue(result.valid, result.errors)
        return path

    def _cube(self, name="Cube"):
        bpy.ops.mesh.primitive_cube_add()
        obj = bpy.context.active_object
        obj.name = name
        return obj

    def test_nan_location_is_written_as_zero(self):
        self._cube().location = (float("nan"), 1.0, float("inf"))
        path = self._export_and_validate()
        with open(path, encoding="utf-8") as handle:
            self.assertNotIn("nan", handle.read().lower())

    def test_special_characters_in_names(self):
        self._cube('Nasty"<&>\'name é 日本')
        self._export_and_validate()

    def test_duplicate_names(self):
        self._cube("Same")
        self._cube("Same").location = (3, 0, 0)
        self._export_and_validate()

    def test_degenerate_transforms_and_data(self):
        cube = self._cube()
        cube.scale = (0, 0, 0)
        cube.rotation_mode = "QUATERNION"
        cube.rotation_quaternion = (0, 0, 0, 0)
        empty = bpy.data.objects.new("EmptyMesh", bpy.data.meshes.new("E"))
        bpy.context.scene.collection.objects.link(empty)
        loose = bpy.data.meshes.new("Loose")
        loose.from_pydata([(0, 0, 0), (1, 0, 0), (2, 2, 2)], [(0, 1)], [])
        bpy.context.scene.collection.objects.link(bpy.data.objects.new("Loose", loose))
        self._export_and_validate()

    def test_malformed_interaction_properties_do_not_break_export(self):
        cube = self._cube()
        cube["x3d_trigger"] = "proximity"
        cube["x3d_radius"] = "abc"
        cube["x3d_action"] = "bogus"
        cube["x3d_target"] = "nonexistent"
        self._export_and_validate()

    def test_infinite_light_energy(self):
        self._cube()
        light = bpy.data.lights.new("L", "POINT")
        light.energy = float("inf")
        bpy.context.scene.collection.objects.link(bpy.data.objects.new("L", light))
        self._export_and_validate()

    def test_compressed_export_is_validated(self):
        self._cube()
        path = os.path.join(self.tmpdir, "c.x3dz")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=path, x3d_version="X3D40", use_selection=False,
                                                  use_compress=True), {"FINISHED"})
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(2), b"\x1f\x8b")


if __name__ == "__main__":
    unittest.main()
