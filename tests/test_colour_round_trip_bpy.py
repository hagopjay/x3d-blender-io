# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Colour round trip: what the import converts, the export converts back.

X_ITE reads Material, TwoSidedMaterial and UnlitMaterial colours, and a Color node under them, in display space; it
reads a Color node under PhysicalMaterial as a linear factor on baseColor (measured 12 Nov 2026, X_ITE 16.7.1,
headless Chrome 153, SwiftShader). Blender holds linear colours. So:

- an sRGB import followed by an export with the scene's own colour space gives the X3D 3.3 file's numbers back;
- the X3D 3.3 writer keeps emissiveColor (it always wrote 0 before);
- an imported Color node is the mesh's active colour attribute, so the X3D 4.0 export writes it again;
- under PhysicalMaterial a Color node is not converted, so it comes back unchanged.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_colour_round_trip_bpy
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

CLASSIC = """<?xml version="1.0" encoding="UTF-8"?>
<X3D profile="Interchange" version="4.0"><Scene>
<Shape><Appearance><Material diffuseColor="0.5 0.25 0.75" emissiveColor="0.2 0.1 0"/></Appearance>
<IndexedFaceSet coordIndex="0 1 2 -1" colorPerVertex="true"><Coordinate point="0 0 0 1 0 0 0 1 0"/>
<Color color="0.5 0.5 0.5 0.2 0.4 0.8 1 0 0"/></IndexedFaceSet></Shape>
</Scene></X3D>
"""

PHYSICAL = """<?xml version="1.0" encoding="UTF-8"?>
<X3D profile="Interchange" version="4.0"><Scene>
<Shape><Appearance><PhysicalMaterial baseColor="1 1 1"/></Appearance>
<IndexedFaceSet coordIndex="0 1 2 -1" colorPerVertex="true"><Coordinate point="0 0 0 1 0 0 0 1 0"/>
<Color color="0.5 0.5 0.5 0.2 0.4 0.8 1 0 0"/></IndexedFaceSet></Shape>
</Scene></X3D>
"""


def _floats(text):
    return [float(v) for v in text.replace(",", " ").split()]


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class ColourRoundTripTests(unittest.TestCase):

    def setUp(self):
        import bpy
        self.tmpdir = tempfile.mkdtemp(prefix="x3d_colour_round_trip_")
        _register_extension(self.tmpdir)
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def _import(self, text, color_space):
        import bpy
        path = os.path.join(self.tmpdir, "in.x3d")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=path, color_space=color_space), {"FINISHED"})
        return [ob for ob in bpy.context.scene.objects if ob.type == 'MESH']

    def _export(self, version, color_space="AUTO"):
        import bpy
        path = os.path.join(self.tmpdir, "out_%s_%s.x3d" % (version, color_space))
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=path, x3d_version=version, use_selection=False,
                                                  color_space=color_space), {"FINISHED"})
        return ET.parse(path).getroot()

    def assertColours(self, got, want, places=3):
        self.assertEqual(len(got), len(want), (got, want))
        for g, w in zip(got, want):
            self.assertAlmostEqual(g, w, places=places)

    def test_srgb_import_and_x3d33_export_give_the_numbers_back(self):
        import bpy
        self._import(CLASSIC, 'SRGB')
        self.assertEqual(bpy.context.scene.get("x3d_color_space"), 'SRGB')
        material = self._export("X3D33").find(".//Material")
        self.assertColours(_floats(material.attrib["diffuseColor"]), [0.5, 0.25, 0.75])
        self.assertColours(_floats(material.attrib["emissiveColor"]), [0.2, 0.1, 0.0])

    def test_as_is_import_and_x3d33_export_keep_emissive(self):
        self._import(CLASSIC, 'AS_IS')
        material = self._export("X3D33").find(".//Material")
        self.assertColours(_floats(material.attrib["diffuseColor"]), [0.5, 0.25, 0.75])
        self.assertColours(_floats(material.attrib["emissiveColor"]), [0.2, 0.1, 0.0])

    def test_explicit_export_colour_space_wins_over_the_scene(self):
        self._import(CLASSIC, 'SRGB')
        material = self._export("X3D33", "AS_IS").find(".//Material")
        # linear values written as they are: 0.5 in sRGB is 0.214 linear
        self.assertColours(_floats(material.attrib["diffuseColor"]), [0.214, 0.051, 0.523])

    def test_imported_colour_node_is_active_and_exported(self):
        objects = self._import(CLASSIC, 'SRGB')
        colours = objects[0].data.color_attributes
        self.assertIsNotNone(colours.active_color)
        self.assertEqual(colours.render_color_index, colours.active_color_index)
        node = self._export("X3D40").find(".//ColorRGBA")
        if node is None:
            node = self._export("X3D40").find(".//Color")
        self.assertIsNotNone(node, "the X3D 4.0 export dropped the Color node")
        values = _floats(node.attrib["color"])
        step = 4 if node.tag == "ColorRGBA" else 3
        # a classic Color goes to linear on import and comes back as the file's display value under the Material the 4.0
        # export now keeps for a Material-lit scene (it used to stay linear under a PhysicalMaterial, which X_ITE draws
        # differently: that old expectation was the bug)
        self.assertColours(values[:3], [0.5, 0.5, 0.5])
        self.assertEqual(len(values), 3 * step)

    def test_colour_under_physical_material_round_trips_unchanged(self):
        objects = self._import(PHYSICAL, 'SRGB')
        attribute = objects[0].data.color_attributes.active_color
        self.assertAlmostEqual(attribute.data[0].color[0], 0.5, places=4)
        node = self._export("X3D40").find(".//ColorRGBA")
        if node is None:
            node = self._export("X3D40").find(".//Color")
        self.assertIsNotNone(node)
        values = _floats(node.attrib["color"])
        step = 4 if node.tag == "ColorRGBA" else 3
        self.assertColours([values[0], values[step + 1], values[2 * step + 2]], [0.5, 0.4, 0.0])

    def test_blender_material_is_srgb_encoded_for_x3d33(self):
        import bpy
        mesh = bpy.data.meshes.new("Tri")
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
        material = bpy.data.materials.new("Grey")
        material.use_nodes = True
        material.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.214041, 0.214041, 0.214041, 1.0)
        mesh.materials.append(material)
        bpy.context.scene.collection.objects.link(bpy.data.objects.new("Tri", mesh))
        written = self._export("X3D33", "SRGB").find(".//Material")
        self.assertColours(_floats(written.attrib["diffuseColor"]), [0.5, 0.5, 0.5])
        written = self._export("X3D33", "AS_IS").find(".//Material")
        self.assertColours(_floats(written.attrib["diffuseColor"]), [0.214, 0.214, 0.214])


if __name__ == "__main__":
    unittest.main()
