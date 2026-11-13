# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""X3D 4.0 export keeps a light that lit nothing out of the scene (round-trip audit D1).

A DirectionalLight (X3D default ``global`` FALSE) beside no geometry lights nothing in X_ITE 16.7.1; the export wrote
``global="true"`` on every light, so such a light lit the whole scene (lights-before: mean|delta| 61.889, FLIP 0.686).

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_export_light_scope_bpy
"""

from __future__ import annotations

import os
import tempfile
import unittest
import xml.etree.ElementTree as ET

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

from test_roundtrip_bpy import _register_extension

BOX = "<Shape><Appearance><PhysicalMaterial/></Appearance><Box/></Shape>"


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class ExportLightScopeTests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="x3d_light_scope_")
        _register_extension(self.tmpdir)
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def _round_trip(self, body):
        path = os.path.join(self.tmpdir, "in.x3d")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("<?xml version='1.0' encoding='UTF-8'?>\n<X3D profile='Immersive' version='4.0'><Scene>\n"
                         + body + "\n</Scene></X3D>\n")
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=path), {"FINISHED"})
        out = os.path.join(self.tmpdir, "out.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=out, x3d_version="X3D40", use_selection=False),
                         {"FINISHED"})
        return ET.parse(out).getroot()

    @staticmethod
    def _info(root):
        return [m.attrib["content"] for m in root.iter("meta") if m.attrib.get("name") == "info"]

    def test_a_scoped_light_with_nothing_in_its_scope_stays_global_false(self):
        # lights-before: each light in a Transform of its own with no geometry beside it
        root = self._round_trip("<Transform translation='0 5 0'><DirectionalLight DEF='Sun'/></Transform>" + BOX)
        self.assertEqual(root.find(".//DirectionalLight").attrib["global"], "false")
        self.assertTrue(any("lit nothing" in text for text in self._info(root)), self._info(root))

    def test_a_scoped_light_that_lit_geometry_is_written_global_with_a_diagnostic(self):
        # chirp: lights at the top of the scene, default global FALSE, light their siblings
        root = self._round_trip("<DirectionalLight DEF='Sun'/>" + BOX)
        self.assertEqual(root.find(".//DirectionalLight").attrib["global"], "true")
        self.assertTrue(any("scoped to its group" in text for text in self._info(root)), self._info(root))

    def test_global_point_and_spot_lights_stay_global(self):
        root = self._round_trip("<Transform><PointLight DEF='P'/></Transform>"
                                "<Transform><SpotLight DEF='S' global='true'/></Transform>" + BOX)
        self.assertEqual(root.find(".//PointLight").attrib["global"], "true")      # X3D's default for a point light
        self.assertEqual(root.find(".//SpotLight").attrib["global"], "true")
        self.assertFalse(any("lit nothing" in text for text in self._info(root)), self._info(root))

    def test_a_light_made_in_blender_is_global(self):
        bpy.ops.mesh.primitive_cube_add()
        light = bpy.data.objects.new("Lamp", bpy.data.lights.new("Lamp", 'SUN'))
        bpy.context.scene.collection.objects.link(light)
        out = os.path.join(self.tmpdir, "blender.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=out, x3d_version="X3D40", use_selection=False),
                         {"FINISHED"})
        self.assertEqual(ET.parse(out).getroot().find(".//DirectionalLight").attrib["global"], "true")


if __name__ == "__main__":
    unittest.main()
