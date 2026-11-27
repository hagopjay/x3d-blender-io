# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The first batch of gaps the node board ranked (docs/NODE_BOARD.md), each as a real import and export in Blender.

Written back, while nothing about them was edited: Rectangle2D, Extrusion and ElevationGrid (the importer keeps the node and
its fields on the mesh, like a Box), and Text with its FontStyle (a Blender text object, whether imported or made in Blender).
Observed and pinned: WorldInfo with its MetadataSet, MetadataString, MetadataDouble and MetadataInteger, and a Color on an
IndexedLineSet. Read: a bare Sound no longer stops the import. Every export validates against x3d-4.0.xsd when lxml and
the schema are on the machine (X3D_XSD names it), and against the add-on's own structural validator always.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_node_board_batch_bpy
"""

from __future__ import annotations

import os
import re
import sys
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

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "node_board"
XSD = Path(os.environ.get("X3D_XSD", "/home/user/x3d_mcp/src/validation/schemas/x3d-4.0.xsd"))
HEAD = '<?xml version="1.0" encoding="UTF-8"?>\n<X3D profile="Immersive" version="4.0"><head/><Scene>\n'
TAIL = "</Scene></X3D>\n"


def _valid(path):
    """(structural result ok, xsd errors or None when no validator is available)."""
    sys.path.insert(0, str(ROOT / "source"))
    from validate import validate_xml_file
    structural = validate_xml_file(str(path))
    errors = None
    try:
        from lxml import etree
        if XSD.is_file():
            schema = etree.XMLSchema(etree.parse(str(XSD)))
            schema.validate(etree.parse(str(path)))
            errors = [str(e) for e in schema.error_log]
    except ImportError:
        pass
    return structural, errors


@unittest.skipUnless(HAVE_BPY, "bpy not available")
class NodeBoardBatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="x3d_node_board_")
        _register_extension(self.tmp)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        _register_extension(self.tmp)

    def _export(self, name="out.x3d"):
        out = os.path.join(self.tmp, name)
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=out, x3d_version="X3D40", use_selection=False), {"FINISHED"})
        structural, errors = _valid(out)
        self.assertTrue(structural.valid, structural.errors)
        self.assertEqual(errors or [], [], "does not validate against x3d-4.0.xsd")
        return ET.parse(out).getroot()

    def _round_trip(self, source):
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=str(source)), {"FINISHED"})
        return self._export()

    def _import_text(self, body):
        src = os.path.join(self.tmp, "in.x3d")
        Path(src).write_text(HEAD + body + TAIL, encoding="utf-8")
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=src), {"FINISHED"})

    # --- written back while unedited -------------------------------------------------------------------------------

    def test_text_and_fontstyle_round_trip(self):
        root = self._round_trip(FIXTURES / "gap_batch_1.x3d")
        texts = {t.get("string"): t for t in root.iter("Text")}
        self.assertEqual(set(texts), {'"Hello" "board"', '"x"'})
        style = texts['"Hello" "board"'].find("FontStyle")
        self.assertEqual((style.get("size"), style.get("spacing"), style.get("justify"), style.get("style")),
                         ("0.5", "1.5", '"MIDDLE" "FIRST"', "BOLD"))
        self.assertIsNone(texts['"x"'].find("FontStyle"), "a Text at the FontStyle defaults has none")

    def test_a_text_made_in_blender_is_a_text_node(self):
        curve = bpy.data.curves.new("Label", "FONT")
        curve.body = "one\ntwo"
        curve.size = 0.25
        curve.align_x = "RIGHT"
        bpy.context.scene.collection.objects.link(bpy.data.objects.new("Label", curve))
        root = self._export()
        text = root.find(".//Text")
        self.assertEqual(text.get("string"), '"one" "two"')
        self.assertEqual((text.find("FontStyle").get("size"), text.find("FontStyle").get("justify")),
                         ("0.25", '"END" "FIRST"'))

    def test_an_extruded_text_stays_a_mesh(self):
        curve = bpy.data.curves.new("Slab", "FONT")
        curve.body = "A"
        curve.extrude = 0.2
        bpy.context.scene.collection.objects.link(bpy.data.objects.new("Slab", curve))
        root = self._export()
        self.assertIsNone(root.find(".//Text"))
        self.assertIsNotNone(root.find(".//IndexedFaceSet"))

    def test_extrusion_keeps_every_field(self):
        root = self._round_trip(FIXTURES / "gap_batch_1.x3d")
        node = root.find(".//Extrusion")
        self.assertIsNone(root.find(".//Shape//IndexedFaceSet"), "no mesh stands in for the primitives")
        self.assertEqual(node.get("crossSection"), "1 0 0 1 -1 0 0 -1 1 0")
        self.assertEqual(node.get("spine"), "0 0 0 0 1 0 0 2 1")
        self.assertEqual(node.get("scale"), "1 1 0.5 0.5 0.25 0.25")
        self.assertEqual(node.get("orientation"), "0 1 0 0 0 1 0 0.2 0 1 0 0")
        self.assertEqual((node.get("beginCap"), node.get("endCap"), node.get("creaseAngle"), node.get("solid")),
                         ("false", None, "0.5", "false"))

    def test_elevation_grid_keeps_its_heights(self):
        grid = self._round_trip(FIXTURES / "gap_batch_1.x3d").find(".//ElevationGrid")
        self.assertEqual((grid.get("xDimension"), grid.get("zDimension"), grid.get("xSpacing"), grid.get("zSpacing")),
                         ("3", "3", "0.5", "0.5"))
        self.assertEqual(grid.get("height"), "0 0.2 0 0.2 1 0.2 0 0.2 0")
        self.assertEqual(grid.get("creaseAngle"), "0.8")

    def test_an_elevation_grid_with_a_texture_coordinate_is_not_written_back(self):
        self._import_text('<Shape><ElevationGrid xDimension="2" zDimension="2" height="0 0 0 1">'
                          '<TextureCoordinate point="0 0 1 0 0 1 1 1"/></ElevationGrid></Shape>')
        root = self._export()
        self.assertIsNone(root.find(".//ElevationGrid"), "its own TextureCoordinate would be lost")
        self.assertIsNotNone(root.find(".//IndexedFaceSet"))

    def test_rectangle2d_comes_back_with_its_size_and_solid(self):
        rect = self._round_trip(FIXTURES / "gap_batch_1.x3d").find(".//Rectangle2D")
        self.assertEqual((rect.get("size"), rect.get("solid")), ("3.000000 1.500000", "true"))

    def test_an_edited_primitive_falls_back_to_a_mesh(self):
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=str(FIXTURES / "gap_batch_1.x3d")), {"FINISHED"})
        for name in ("Pipe", "Hills", "Panel"):
            mesh = next(o.data for o in bpy.data.objects if o.name.endswith(name) and o.type == "MESH")
            mesh.vertices[0].co.z += 0.5
        root = self._export()
        for tag in ("Extrusion", "ElevationGrid", "Rectangle2D"):
            self.assertIsNone(root.find(f".//{tag}"), f"{tag} written although a vertex moved")

    # --- observed with a fixture -------------------------------------------------------------------------------------

    def test_world_info_and_metadata_nodes_round_trip(self):
        root = self._round_trip(FIXTURES / "writable_nodes.x3d")
        info = root.find(".//WorldInfo")
        self.assertEqual((info.get("title"), info.get("info")), ("Node board fixture", '"first line" "second line"'))
        meta = info.find("MetadataSet")
        self.assertEqual({c.tag: (c.get("name"), c.get("value")) for c in meta},
                         {"MetadataString": ("author", '"Ada"'), "MetadataDouble": ("ratio", "0.5 1.25"),
                          "MetadataInteger": ("count", "3")})

    def test_a_coloured_line_set_writes_color(self):
        root = self._round_trip(FIXTURES / "writable_nodes.x3d")
        color = root.find(".//IndexedLineSet/Color")
        self.assertEqual(color.get("color").split().count("1.000000"), 3)

    # --- read --------------------------------------------------------------------------------------------------------

    def test_a_bare_sound_does_not_stop_the_import(self):
        import wave
        with wave.open(os.path.join(self.tmp, "tick.wav"), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(8000)
            handle.writeframes(b"\0\0" * 800)
        # no maxBack, maxFront, minBack or minFront: the standard's defaults stand in (this raised a TypeError)
        self._import_text('<Sound><AudioClip url=\'"tick.wav"\'/></Sound>')
        speaker = next(o for o in bpy.data.objects if o.type == "SPEAKER")
        self.assertAlmostEqual(speaker.data.distance_max, 10.0, places=3)
        self.assertAlmostEqual(speaker.data.distance_reference, 1.0, places=3)

    def test_fontstyle_style_reads_the_4_0_sfstring_and_the_3_x_mfstring(self):
        for style in ("BOLD", '"BOLD"'):
            bpy.ops.wm.read_factory_settings(use_empty=True)
            _register_extension(self.tmp)
            self._import_text(f'<Shape><Text string=\'"a"\'><FontStyle style=\'{style}\'/></Text></Shape>')
            obj = next(o for o in bpy.data.objects if o.type == "FONT")
            self.assertTrue(any(f.use_bold for f in obj.data.body_format), style)


if __name__ == "__main__":
    unittest.main()
