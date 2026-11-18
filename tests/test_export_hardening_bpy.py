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

    def test_failed_export_keeps_the_previous_valid_file(self):
        self._cube()
        path = os.path.join(self.tmpdir, "keep.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=path, x3d_version="X3D40", use_selection=False), {"FINISHED"})
        with open(path, "rb") as handle:
            before = handle.read()
        from emit_x3d40 import _meta  # noqa: F401  (import check: the emitter module loads top-level)
        import io_scene_x3d.validate as validate
        original = validate.validate_xml_file
        validate.validate_xml_file = lambda _path: validate.ValidationResult(valid=False, errors=["forced failure"])
        try:
            with self.assertRaises(Exception):
                bpy.ops.export_scene.x3d(filepath=path, x3d_version="X3D40", use_selection=False)
        finally:
            validate.validate_xml_file = original
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), before)
        self.assertEqual([n for n in os.listdir(self.tmpdir) if n.startswith(".x3d-stage-")], [])

    DOOR = ('<?xml version="1.0" encoding="UTF-8"?><X3D version="4.0" profile="Immersive"><Scene>'
            '<Transform DEF="Door"><Shape><Appearance><Material/></Appearance><Box/></Shape></Transform>'
            '<Transform DEF="Handle"><TouchSensor DEF="Touch"/><Shape><Sphere/></Shape></Transform>'
            '<TimeSensor DEF="TT" cycleInterval="2" loop="false" startTime="1e+30"/>'
            '<PositionInterpolator DEF="Slide" key="0 1" keyValue="0 0 0 2 0 0"/>'
            '<ROUTE fromNode="Touch" fromField="touchTime" toNode="TT" toField="set_startTime"/>'
            '<ROUTE fromNode="TT" fromField="fraction_changed" toNode="Slide" toField="set_fraction"/>'
            '<ROUTE fromNode="Slide" fromField="value_changed" toNode="Door" toField="set_translation"/>'
            '</Scene></X3D>')

    def _import_door(self):
        path = os.path.join(self.tmpdir, "door.x3d")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(self.DOOR)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        return bpy.ops.import_scene.x3d(filepath=path)

    def test_import_records_what_it_cannot_keep(self):
        import json
        self.assertEqual(self._import_door(), {"FINISHED"})
        losses = json.loads(bpy.context.scene["x3d_import_losses"])
        kinds = sorted((r["kind"], r["node"].split()[0]) for r in losses)
        self.assertIn(("node", "TouchSensor"), kinds)
        self.assertIn(("route", "Touch.touchTime"), kinds)
        self.assertIn(("timer", "TimeSensor"), kinds)

    def test_strict_import_fails_on_lost_behaviour(self):
        os.environ["X3D_IMPORT_STRICT"] = "1"
        try:
            with self.assertRaises(Exception):
                self._import_door()
        finally:
            del os.environ["X3D_IMPORT_STRICT"]

    def test_compressed_export_is_validated(self):
        self._cube()
        path = os.path.join(self.tmpdir, "c.x3dz")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=path, x3d_version="X3D40", use_selection=False,
                                                  use_compress=True), {"FINISHED"})
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(2), b"\x1f\x8b")


if __name__ == "__main__":
    unittest.main()
