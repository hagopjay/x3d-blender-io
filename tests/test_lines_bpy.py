# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Round trip of an IndexedLineSet: the X3D 4.0 export keeps lines.

An IndexedLineSet imports as a Blender curve; its evaluated mesh has edges and no faces, and the
export used to write nothing for it, so the 12 evidence-graded travel legs of the Shroud "journey"
scene vanished from every export.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_lines_bpy
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

SCENE = """<?xml version='1.0' encoding='UTF-8'?>
<X3D profile='Immersive' version='4.0'><Scene>
<Shape>
  <Appearance><Material emissiveColor='0 1 0'/></Appearance>
  <IndexedLineSet coordIndex='0 1 2 -1 3 4 -1'>
    <Coordinate point='0 0 0, 1 0 0, 1 1 0, 0 0 1, 0 1 1'/>
  </IndexedLineSet>
</Shape>
</Scene></X3D>
"""


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class IndexedLineSetRoundTripTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="x3d_lines_")
        _register_extension(cls.tmpdir)

    def _roundtrip(self):
        import bpy
        bpy.ops.wm.read_factory_settings(use_empty=True)
        src = os.path.join(self.tmpdir, "lines.x3d")
        with open(src, "w", encoding="utf-8") as f:
            f.write(SCENE)
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=src), {"FINISHED"})
        out = os.path.join(self.tmpdir, "lines_out.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=out, x3d_version="X3D40", use_selection=False),
                         {"FINISHED"})
        return out

    def test_export_keeps_both_polylines(self):
        out = self._roundtrip()
        nodes = list(ET.parse(out).getroot().iter("IndexedLineSet"))
        self.assertEqual(len(nodes), 1)
        index = [int(v) for v in nodes[0].get("coordIndex").split()]
        self.assertEqual(index.count(-1), 2)
        lengths = [len(part.split()) for part in " ".join(map(str, index)).split("-1")[:2]]
        self.assertEqual(lengths, [3, 2])
        coord = nodes[0].find("Coordinate").get("point").split()
        self.assertEqual(len(coord), 5 * 3)

    def test_reimport_gives_a_curve_with_two_splines(self):
        import bpy
        out = self._roundtrip()
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=out), {"FINISHED"})
        curves = [o for o in bpy.context.scene.objects if o.type == "CURVE"]
        self.assertEqual(len(curves), 1)
        self.assertEqual(len(curves[0].data.splines), 2)


if __name__ == "__main__":
    unittest.main()


COLOURED = """<?xml version='1.0' encoding='UTF-8'?>
<X3D profile='Immersive' version='4.0'><Scene>
<Shape>
  <Appearance><UnlitMaterial emissiveColor='0.8 0.84 0.9'/></Appearance>
  <IndexedLineSet colorPerVertex='{per_vertex}' coordIndex='0 1 2 -1 3 4 -1'>
    <Coordinate point='0 0 0, 1 0 0, 1 1 0, 0 0 1, 0 1 1'/>
    <{node} color='{colours}'/>
  </IndexedLineSet>
</Shape>
</Scene></X3D>
"""


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class ColouredLineSetRoundTripTests(unittest.TestCase):
    """IndexedLineSet colours come back as a Color node (round-trip audit D12): the export used to drop them, and
    X_ITE then drew the lines in the material's emissiveColor instead (habsburg-unlit-color: mean|delta| 7.771)."""

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="x3d_coloured_lines_")
        _register_extension(cls.tmpdir)

    def _roundtrip(self, **fields):
        import bpy
        bpy.ops.wm.read_factory_settings(use_empty=True)
        src = os.path.join(self.tmpdir, "coloured.x3d")
        with open(src, "w", encoding="utf-8") as f:
            f.write(COLOURED.format(**fields))
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=src), {"FINISHED"})
        out = os.path.join(self.tmpdir, "coloured_out.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=out, x3d_version="X3D40", use_selection=False),
                         {"FINISHED"})
        return ET.parse(out).getroot().find(".//IndexedLineSet")

    @staticmethod
    def _floats(node):
        return [float(v) for v in node.get("color").replace(",", " ").split()]

    def test_per_vertex_colours_come_back_as_written(self):
        colours = "1 0 0, 0 1 0, 0 0 1, 0.5 0.25 0.75, 0.2 0.4 0.6"
        node = self._roundtrip(per_vertex="true", node="Color", colours=colours)
        colour = node.find("Color")
        self.assertIsNotNone(colour, "the line set's colours were dropped")
        want = [float(v) for v in colours.replace(",", " ").split()]
        for got, expected in zip(self._floats(colour), want):
            self.assertAlmostEqual(got, expected, places=4)

    def test_per_polyline_colours_come_back_per_vertex(self):
        node = self._roundtrip(per_vertex="false", node="Color", colours="1 0 0, 0 0 1")
        values = self._floats(node.find("Color"))
        self.assertEqual(len(values), 5 * 3)
        self.assertEqual([round(v, 4) for v in values[:9]], [1, 0, 0] * 3)
        self.assertEqual([round(v, 4) for v in values[9:]], [0, 0, 1] * 2)

    def test_an_alpha_below_one_keeps_colorrgba(self):
        colours = "1 0 0 1, 0 1 0 0.5, 0 0 1 1, 1 1 1 1, 0 0 0 1"
        node = self._roundtrip(per_vertex="true", node="ColorRGBA", colours=colours)
        values = self._floats(node.find("ColorRGBA"))
        self.assertEqual(len(values), 5 * 4)
        self.assertAlmostEqual(values[7], 0.5, places=4)


WIDTHS = """<?xml version='1.0' encoding='UTF-8'?>
<X3D profile='Immersive' version='4.0'><Scene>
<Shape><Appearance DEF='A'><UnlitMaterial emissiveColor='0.8 0.84 0.9'/><LineProperties linewidthScaleFactor='5'/></Appearance>
  <IndexedLineSet coordIndex='0 1 -1'><Coordinate point='0 0 0, 1 0 0'/></IndexedLineSet></Shape>
<Shape><Appearance><UnlitMaterial emissiveColor='0.8 0.84 0.9'/><LineProperties linewidthScaleFactor='2.4'/></Appearance>
  <IndexedLineSet coordIndex='0 1 -1'><Coordinate point='0 1 0, 1 1 0'/></IndexedLineSet></Shape>
<Shape><Appearance><UnlitMaterial emissiveColor='0.8 0.84 0.9'/></Appearance>
  <IndexedLineSet coordIndex='0 1 -1'><Coordinate point='0 2 0, 1 2 0'/></IndexedLineSet></Shape>
</Scene></X3D>
"""


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class LinePropertiesRoundTripTests(unittest.TestCase):
    """LineProperties linewidthScaleFactor comes back (round-trip audit D12)."""

    def test_line_widths_are_written_back_per_shape(self):
        import bpy
        tmpdir = tempfile.mkdtemp(prefix="x3d_line_widths_")
        _register_extension(tmpdir)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        src = os.path.join(tmpdir, "widths.x3d")
        with open(src, "w", encoding="utf-8") as f:
            f.write(WIDTHS)
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=src), {"FINISHED"})
        out = os.path.join(tmpdir, "widths_out.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=out, x3d_version="X3D40", use_selection=False),
                         {"FINISHED"})
        root = ET.parse(out).getroot()
        widths = sorted(float(node.get("linewidthScaleFactor")) for node in root.iter("LineProperties"))
        self.assertEqual(widths, [2.4, 5.0])
        shapes = [shape for shape in root.iter("Shape") if shape.find("IndexedLineSet") is not None]
        self.assertEqual(len(shapes), 3)
        with_width = [shape for shape in shapes if shape.find("Appearance/LineProperties") is not None]
        self.assertEqual(len(with_width), 2)
        # the third line keeps a plain Appearance
        self.assertEqual(len([s for s in shapes if s.find("Appearance/LineProperties") is None]), 1)
