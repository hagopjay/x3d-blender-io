# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The second batch of gaps the node board ranked (docs/NODE_BOARD.md): Switch, LOD, IndexedTriangleSet and PixelTexture,
each imported and written back by the X3D 4.0 export in Blender.

Switch and LOD: the import records the Switch and LOD nodes above every object it makes (``x3d_group_chain``), and the
writer gathers siblings into them again, every branch and level in place (an empty one as an empty Group). Before this
batch the Switch dissolved (its other branches written visible="false") and the levels a viewer does not see were not
written at all. IndexedTriangleSet: a mesh the import read from one is written as one while every face is a triangle.
PixelTexture: an image the import read from one is written back inline, pixel for pixel. Every export validates against
x3d-4.0.xsd when lxml and the schema are on the machine (X3D_XSD names it), and the add-on's structural validator always.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_node_board_batch2_bpy
"""

from __future__ import annotations

import os
import re
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    import bpy
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

from test_roundtrip_bpy import _register_extension
from test_node_board_batch_bpy import _valid

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "node_board" / "gap_batch_2.x3d"
PROBE_SWITCH = ROOT / "tests" / "behaviour" / "probe-switch.x3d"


@unittest.skipUnless(HAVE_BPY, "bpy not available")
class NodeBoardBatch2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="x3d_node_board2_")
        _register_extension(self.tmp)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        _register_extension(self.tmp)

    def _export(self, name="out.x3d"):
        out = os.path.join(self.tmp, name)
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=out, x3d_version="X3D40", use_selection=False), {"FINISHED"})
        structural, errors = _valid(out)
        self.assertTrue(structural.valid, structural.errors)
        self.assertEqual(errors or [], [], "does not validate against x3d-4.0.xsd")
        return out, ET.parse(out).getroot()

    def _round_trip(self, source=FIXTURE, **options):
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=str(source), **options), {"FINISHED"})
        return self._export()[1]

    @staticmethod
    def _kids(element):
        return [child for child in element if not child.tag.startswith("Metadata")]

    def test_switch_written_back_with_every_branch(self):
        root = self._round_trip()
        lamp = next(s for s in root.iter("Switch") if s.get("DEF") == "Lamp")
        self.assertEqual(lamp.get("whichChoice"), "2")
        kids = self._kids(lamp)
        self.assertEqual([k.tag for k in kids], ["Transform", "Group", "Transform"])
        self.assertEqual(self._kids(kids[1]), [], "the empty branch stays an empty Group, so whichChoice still counts it")
        self.assertEqual((kids[0].get("DEF"), kids[2].get("DEF")), ("OB_LampOff", "OB_LampOn"))
        inner = kids[0].find("Switch")
        self.assertIsNotNone(inner, "the un-DEF'd Switch inside the first branch is written too")
        self.assertEqual(inner.get("whichChoice"), "0")
        self.assertIsNone(inner.get("DEF"), "no DEF is made up for a Switch the file did not name")
        self.assertEqual(len(self._kids(inner)), 2)
        hidden = [t.get("DEF") for t in lamp.iter("Transform") if t.get("visible") == "false"]
        self.assertEqual(hidden, [], "the Switch chooses: its branches are not also written invisible")

    def test_lod_written_back_with_every_level(self):
        root = self._round_trip()
        lod = root.find(".//LOD")
        self.assertIsNotNone(lod)
        self.assertEqual((lod.get("DEF"), lod.get("range"), lod.get("center")),
                         ("Tree", "5.000000 15.000000", "2.000000 0.000000 0.000000"))
        self.assertEqual([k.get("DEF") for k in self._kids(lod)], ["OB_TreeNear", "OB_TreeMid", "OB_TreeFar"],
                         "all three levels, in order, including the two the first Viewpoint does not see")

    def test_indexed_triangle_set_written_back(self):
        root = self._round_trip()
        its = root.find(".//IndexedTriangleSet")
        self.assertIsNotNone(its)
        self.assertEqual(its.get("index"), "0 1 2 0 2 3")
        self.assertEqual(its.get("solid"), "false")
        self.assertIsNone(its.get("coordIndex"))
        self.assertIsNotNone(its.find("TextureCoordinate"))

    def test_an_edited_triangle_set_with_a_quad_falls_back_to_a_face_set(self):
        mesh = bpy.data.meshes.new("Quad")
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [], [(0, 1, 2, 3)])
        mesh["x3d_geometry"] = "IndexedTriangleSet"
        bpy.context.scene.collection.objects.link(bpy.data.objects.new("Quad", mesh))
        root = self._export()[1]
        self.assertIsNone(root.find(".//IndexedTriangleSet"))
        self.assertIsNotNone(root.find(".//IndexedFaceSet"))

    def test_triangulate_writes_triangle_sets(self):
        mesh = bpy.data.meshes.new("Quad")
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [], [(0, 1, 2, 3)])
        bpy.context.scene.collection.objects.link(bpy.data.objects.new("Quad", mesh))
        out = os.path.join(self.tmp, "tri.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=out, x3d_version="X3D40", use_selection=False,
                                                  use_triangulate=True), {"FINISHED"})
        its = ET.parse(out).getroot().find(".//IndexedTriangleSet")
        self.assertIsNotNone(its)
        self.assertEqual(len(its.get("index").split()), 6)

    def test_pixel_texture_written_back_pixel_for_pixel(self):
        root = self._round_trip()
        pixel = root.find(".//PixelTexture")
        self.assertIsNotNone(pixel)
        self.assertEqual(pixel.get("image"), "2 2 3 0xFF0000 0x00FF00 0x0000FF 0xFFFF00")
        self.assertEqual((pixel.get("repeatS"), pixel.get("repeatT")), ("false", "false"))

    def test_a_second_round_trip_writes_the_same_file(self):
        self._round_trip()
        first_path = os.path.join(self.tmp, "out.x3d")
        first_text = Path(first_path).read_text(encoding="utf-8")
        bpy.ops.wm.read_factory_settings(use_empty=True)
        _register_extension(self.tmp)
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=first_path), {"FINISHED"})
        second_path, _ = self._export("out2.x3d")
        strip = lambda text: re.sub(r'<meta name="(created|modified|generator|filename)"[^>]*>', "", text)
        self.assertEqual(strip(Path(second_path).read_text(encoding="utf-8")), strip(first_text))

    def test_a_route_to_whichchoice_keeps_its_switch(self):
        root = self._round_trip(PROBE_SWITCH, use_behaviour_graph=True)
        defs = {s.get("DEF") for s in root.iter("Switch")}
        self.assertLessEqual({"Pick", "Echo"}, defs)
        routes = [r for r in root.iter("ROUTE") if r.get("toField") == "whichChoice"]
        self.assertTrue(routes, "the ROUTE into Switch.whichChoice is written")
        self.assertTrue(all(r.get("toNode") in defs for r in routes), "and it lands on a Switch in the file")


if __name__ == "__main__":
    unittest.main()
