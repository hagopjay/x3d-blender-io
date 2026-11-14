# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The X3D 4.0 export writes ``solid`` as the imported file had it (round-trip audit D14).

The import leaves a classic Material's surface two-sided in Blender (no backface culling), and the export followed that
flag, so every Box, Cylinder and IndexedFaceSet with X3D's default solid TRUE came back solid="false".

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_export_solid_bpy
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

CLASSIC = "<Appearance><Material diffuseColor='0.8 0.8 0.8'/></Appearance>"
PHYSICAL = "<Appearance><PhysicalMaterial baseColor='0.8 0.8 0.8'/></Appearance>"
FACES = ("<IndexedFaceSet {solid} coordIndex='0 1 2 -1'><Coordinate point='0 0 0, 1 0 0, 0 1 0'/></IndexedFaceSet>")


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class ExportSolidTests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="x3d_solid_")
        _register_extension(self.tmpdir)
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def _round_trip(self, appearance, geometry):
        path = os.path.join(self.tmpdir, "in.x3d")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("<?xml version='1.0' encoding='UTF-8'?>\n<X3D profile='Immersive' version='4.0'><Scene>"
                         f"<Shape>{appearance}{geometry}</Shape></Scene></X3D>\n")
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=path), {"FINISHED"})
        out = os.path.join(self.tmpdir, "out.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=out, x3d_version="X3D40", use_selection=False),
                         {"FINISHED"})
        return ET.parse(out).getroot()

    def test_default_solid_comes_back_solid_for_primitives_and_meshes(self):
        for appearance in (CLASSIC, PHYSICAL):
            for tag, geometry in (("Box", "<Box/>"), ("Cylinder", "<Cylinder/>"),
                                  ("IndexedFaceSet", FACES.format(solid=""))):
                node = self._round_trip(appearance, geometry).find(f".//{tag}")
                self.assertIsNotNone(node, (appearance, tag))
                self.assertNotEqual(node.attrib.get("solid"), "false", (appearance, tag))

    def test_solid_false_stays_false(self):
        for appearance in (CLASSIC, PHYSICAL):
            for tag, geometry in (("Box", "<Box solid='false'/>"),
                                  ("IndexedFaceSet", FACES.format(solid="solid='false'"))):
                node = self._round_trip(appearance, geometry).find(f".//{tag}")
                self.assertEqual(node.attrib.get("solid"), "false", (appearance, tag))

    def test_geometry2d_nodes_default_to_two_sided_and_follow_an_explicit_solid(self):
        # X3D 4.0: Rectangle2D, Disk2D, ArcClose2D and TriangleSet2D default to solid FALSE (review round 1, F1)
        shapes = {"Rectangle2D": "{tag}", "Disk2D": "{tag}", "ArcClose2D": "{tag} endAngle='1.5'",
                  "TriangleSet2D": "{tag} vertices='0 0, 1 0, 0 1'"}
        for appearance in (CLASSIC, PHYSICAL):
            for tag, template in shapes.items():
                node = self._round_trip(appearance, "<" + template.format(tag=tag) + "/>").find(".//IndexedFaceSet")
                self.assertIsNotNone(node, (appearance, tag))
                self.assertEqual(node.attrib.get("solid"), "false", (appearance, tag))
                node = self._round_trip(appearance, "<" + template.format(tag=tag) + " solid='true'/>").find(".//IndexedFaceSet")
                self.assertNotEqual(node.attrib.get("solid"), "false", (appearance, tag, "explicit solid"))

    def test_a_mesh_made_in_blender_keeps_following_the_material(self):
        bpy.ops.mesh.primitive_plane_add()
        material = bpy.data.materials.new("Cull")
        material.use_backface_culling = True
        bpy.context.object.data.materials.append(material)
        out = os.path.join(self.tmpdir, "blender.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=out, x3d_version="X3D40", use_selection=False),
                         {"FINISHED"})
        self.assertNotEqual(ET.parse(out).getroot().find(".//IndexedFaceSet").attrib.get("solid"), "false")


if __name__ == "__main__":
    unittest.main()
