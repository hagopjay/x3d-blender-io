# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The third batch of gaps the node board ranked (docs/NODE_BOARD.md): Billboard, GeoLocation, GeoLOD and
GeoElevationGrid (with its GeoOrigin), each imported and written back by the X3D 4.0 export in Blender.

Billboard, GeoLocation and GeoLOD ride on batch 2's record (``x3d_group_chain``): the import dissolves them and keeps
their fields as the file wrote them (geospatial doubles, quoted string lists), the writer puts the children back inside;
a GeoLOD's content is its rootNode. GeoElevationGrid is kept like an ElevationGrid (``x3d_primitive``) and written back
while the mesh is unedited, with the GeoOrigin that placed it. x3d-4.0.xsd wants a GeoLOD's GeoOrigin after its children
and requires one once there are children, so the fixture's GeoLOD has one and the writer puts it last.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_node_board_batch3_bpy
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
FIXTURE = ROOT / "tests" / "node_board" / "gap_batch_3.x3d"
GD = '"GD" "WE"'


@unittest.skipUnless(HAVE_BPY, "bpy not available")
class NodeBoardBatch3Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="x3d_node_board3_")
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

    def _round_trip(self):
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=str(FIXTURE)), {"FINISHED"})
        return self._export()[1]

    def test_billboard_written_back_around_its_child(self):
        board = self._round_trip().find(".//Billboard")
        self.assertIsNotNone(board)
        self.assertEqual((board.get("DEF"), board.get("axisOfRotation")), ("Sign", "0 1 0"))
        self.assertEqual([t.get("DEF") for t in board.findall("Transform")], ["OB_SignBoard"])

    def test_geolocation_keeps_its_coordinates_as_written(self):
        pin = self._round_trip().find(".//GeoLocation")
        self.assertIsNotNone(pin)
        self.assertEqual((pin.get("DEF"), pin.get("geoSystem"), pin.get("geoCoords")),
                         ("Pin", GD, "37.4219999 -122.0840575 12.5"), "doubles and the geoSystem list, unrounded")
        self.assertEqual([t.get("DEF") for t in pin.findall("Transform")], ["OB_Marker"])

    def test_geolod_writes_its_content_as_rootnode_and_its_geoorigin_last(self):
        tile = self._round_trip().find(".//GeoLOD")
        self.assertIsNotNone(tile)
        self.assertEqual((tile.get("center"), tile.get("range"), tile.get("child4Url")),
                         ("37.42 -122.08 0", "2500", '"tile-se.x3d"'))
        kids = list(tile)
        self.assertEqual([(k.tag, k.get("containerField")) for k in kids], [("Transform", "rootNode"), ("GeoOrigin", None)])

    def test_geoelevationgrid_written_back_with_its_geoorigin(self):
        root = self._round_trip()
        grid = root.find(".//GeoElevationGrid")
        self.assertIsNotNone(grid)
        self.assertEqual((grid.get("geoGridOrigin"), grid.get("xDimension"), grid.get("height"), grid.get("solid")),
                         ("37.4 -122.1 0", "3", "0 1 0 1 3 1 0 1 0", "false"))
        origin = grid.find("GeoOrigin")
        self.assertEqual((origin.get("geoCoords"), origin.get("rotateYUp")), ("37.4001 -122.0999 0", "true"))
        self.assertIn(("Geospatial", "1"), [(c.get("name"), c.get("level")) for c in root.iter("component")])

    def test_an_edited_geoelevationgrid_is_written_as_a_mesh(self):
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=str(FIXTURE)), {"FINISHED"})
        mesh = next(m for m in bpy.data.meshes if "x3d_primitive" in m and "GeoElevationGrid" in m["x3d_primitive"])
        mesh.vertices[0].co.z += 0.5
        root = self._export()[1]
        self.assertIsNone(root.find(".//GeoElevationGrid"), "a moved vertex is not what the grid fields describe")

    def test_a_used_grouping_node_gets_one_def(self):
        # docs/showcase/scenes/geolod-origin.x3d USEs one GeoLocation three times: each copy comes back with its own
        # children, and only the first carries the DEF (a DEF twice is not a valid file)
        src = os.path.join(self.tmp, "used.x3d")
        Path(src).write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n<X3D profile="Immersive" version="4.0"><head>'
            '<component name="Geospatial" level="1"/></head><Scene>\n'
            '<Transform DEF="A"><GeoLocation DEF="Campus" geoCoords="37.2 -80.4 0">'
            '<Shape DEF="Mark"><Box/></Shape></GeoLocation></Transform>\n'
            '<Transform DEF="B" translation="2 0 0"><GeoLocation USE="Campus"/></Transform>\n'
            '<Switch DEF="Pick" whichChoice="0"><Shape DEF="One"><Box/></Shape></Switch>\n'
            '<Transform DEF="C" translation="4 0 0"><Switch USE="Pick"/></Transform>\n'
            '</Scene></X3D>\n', encoding="utf-8")
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=src), {"FINISHED"})
        root = self._export()[1]
        for tag, name in (("GeoLocation", "Campus"), ("Switch", "Pick")):
            copies = list(root.iter(tag))
            self.assertGreaterEqual(len(copies), 1, tag)
            self.assertEqual([c.get("DEF") for c in copies].count(name), 1, f"{tag}: one DEF, the rest without")

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


if __name__ == "__main__":
    unittest.main()
