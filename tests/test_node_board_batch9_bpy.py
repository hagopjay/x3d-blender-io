# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The ninth batch of gaps the node board ranked (docs/NODE_BOARD.md, docs/NODE_BOARD_PRIORITIES.md): Fog,
MetadataBoolean, MetadataFloat, TwoSidedMaterial and TextureBackground, each imported and written back by the X3D 4.0
export in Blender.

Fog becomes the world's mist (start 0, depth visibilityRange, the nearest falloff, the Mist pass on), and the export
reads the distance and type back from the mist, with the colour from the scene record (mist has none). TextureBackground
keeps its gradient as Background does, and its ImageTexture and PixelTexture faces as Blender images, written through
the same path handling as a material's textures. TwoSidedMaterial: the Blender material is the front, the back fields
are kept on it (``x3d_two_sided``) and written back. MetadataBoolean and MetadataFloat already rode the Metadata* path;
these tests pin that they come back with their type and value on a Shape, a material and a WorldInfo. Every export
validates against x3d-4.0.xsd when lxml and the schema are on the machine (X3D_XSD names it), and the add-on's
structural validator always.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_node_board_batch9_bpy
"""

from __future__ import annotations

import os
import re
import shutil
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
FIXTURE = ROOT / "tests" / "node_board" / "gap_batch_9.x3d"


@unittest.skipUnless(HAVE_BPY, "bpy not available")
class NodeBoardBatch9Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="x3d_node_board9_")
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

    def _import(self, path=FIXTURE, world=False):
        if world:
            bpy.context.scene.world = bpy.data.worlds.new("World")
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=str(path)), {"FINISHED"})

    def _reimport(self, path, world=False):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        _register_extension(self.tmp)
        self._import(path, world)

    @staticmethod
    def _components(root):
        return {c.get("name"): c.get("level") for c in root.iter("component")}

    @staticmethod
    def _material():
        return next(m for m in bpy.data.materials if m.get("x3d_two_sided") is not None)

    def test_each_node_is_written_back(self):
        self._import()
        root = self._export()[1]
        fog = root.find(".//Fog")
        self.assertIsNotNone(fog)
        self.assertEqual((fog.get("color"), fog.get("fogType"), fog.get("visibilityRange")),
                         ("0.600000 0.700000 0.800000", "EXPONENTIAL", "40.000000"))
        background = root.find(".//TextureBackground")
        self.assertIsNotNone(background)
        self.assertIsNone(root.find(".//Background"))
        self.assertEqual(background.get("skyAngle"), "1.200000")
        self.assertEqual(background.get("groundColor"), "0.200000 0.150000 0.100000")
        faces = {child.get("containerField"): child for child in background}
        self.assertEqual(sorted(faces), ["bottomTexture", "frontTexture", "topTexture"])
        self.assertEqual(faces["frontTexture"].tag, "ImageTexture")
        self.assertIn("gap_batch_9_sky.png", faces["frontTexture"].get("url"))
        self.assertEqual((faces["topTexture"].tag, faces["topTexture"].get("image")), ("PixelTexture", "1 1 3 3368652"),
                         "0x3366CC, in decimal as main writes SFImage pixels (x3d.py reads them with float())")
        material = root.find(".//TwoSidedMaterial")
        self.assertIsNotNone(material)
        self.assertIsNone(root.find(".//Appearance/Material"))
        self.assertEqual(material.get("diffuseColor"), "0.800000 0.200000 0.200000", "the front is the Blender material")
        self.assertEqual((material.get("backDiffuseColor"), material.get("backShininess"), material.get("backTransparency"),
                          material.get("separateBackColor")), ("0.200000 0.200000 0.800000", "0.600000", "0.250000", "true"))
        self.assertEqual(material.find("MetadataFloat").get("value"), "0.75")
        shape_flags = root.find(".//Shape/MetadataBoolean")
        self.assertEqual((shape_flags.get("name"), shape_flags.get("value")), ("flags", "true false true"))
        self.assertEqual(root.find(".//WorldInfo/MetadataFloat").get("value"), "0.5 1.25")
        components = self._components(root)
        self.assertEqual((components.get("EnvironmentalEffects"), components.get("Shape")), ("3", "4"))

    def test_fog_is_the_world_mist_and_follows_it(self):
        self._import(world=True)
        world = bpy.context.scene.world
        mist = world.mist_settings
        self.assertEqual((mist.start, mist.depth, mist.falloff), (0.0, 40.0, "INVERSE_QUADRATIC"))
        self.assertTrue(bpy.context.scene.view_layers[0].use_pass_mist, "the Mist pass shows it")
        mist.start, mist.depth, mist.falloff = 5.0, 20.0, "LINEAR"
        fog = self._export()[1].find(".//Fog")
        self.assertEqual(fog.get("visibilityRange"), "25.000000", "full mist at start + depth")
        self.assertIsNone(fog.get("fogType"), "a linear falloff is X3D's default LINEAR")
        self.assertEqual(fog.get("color"), "0.600000 0.700000 0.800000")

    def test_fog_beside_the_world_colour_background(self):
        self._import(world=True)
        del bpy.context.scene["x3d_background"]
        root = self._export()[1]
        self.assertEqual(len(list(root.iter("Background"))), 1, "the world colour's Background, once")
        self.assertEqual(len(list(root.iter("Fog"))), 1)

    def test_without_the_records_the_nodes_fall_back(self):
        self._import()
        scene = bpy.context.scene
        del scene["x3d_fog"]
        del self._material()["x3d_two_sided"]
        root = self._export()[1]
        self.assertIsNone(root.find(".//Fog"))
        self.assertIsNone(root.find(".//TwoSidedMaterial"))
        self.assertIsNotNone(root.find(".//Appearance/Material"))
        self.assertNotEqual(self._components(root).get("Shape"), "4")
        del scene["x3d_background"]
        root = self._export("plain.x3d")[1]
        self.assertIsNone(root.find(".//TextureBackground"))
        self.assertNotIn("EnvironmentalEffects", self._components(root))

    def test_a_removed_face_image_is_left_out(self):
        self._import()
        top = next(i for i in bpy.data.images if i.get("x3d_pixel_texture") and i.name
                   == bpy.context.scene["x3d_background"]["textures"]["topTexture"])
        bpy.data.images.remove(top)
        background = self._export()[1].find(".//TextureBackground")
        self.assertEqual(sorted(c.get("containerField") for c in background), ["bottomTexture", "frontTexture"])

    def test_a_bad_back_record_writes_only_what_checks_out(self):
        self._import()
        self._material()["x3d_two_sided"] = '{"backDiffuseColor": [2, 0, 0], "backShininess": "x", "separateBackColor": true}'
        material = self._export()[1].find(".//TwoSidedMaterial")
        self.assertIsNotNone(material)
        self.assertIsNone(material.get("backDiffuseColor"), "out of [0, 1]")
        self.assertIsNone(material.get("backShininess"))
        self.assertEqual(material.get("separateBackColor"), "true")

    def test_a_second_round_trip_writes_the_same_file(self):
        self._import()
        first_path = self._export()[0]
        first_text = Path(first_path).read_text(encoding="utf-8")
        second_dir = tempfile.mkdtemp(prefix="x3d_node_board9_again_")
        shutil.copy(first_path, second_dir)
        shutil.copy(os.path.join(self.tmp, "gap_batch_9_sky.png"), second_dir)
        self._reimport(os.path.join(second_dir, "out.x3d"))
        second_path, _ = self._export("out2.x3d")
        strip = lambda text: re.sub(r'<meta name="(created|modified|generator|filename)"[^>]*>', "", text)
        self.assertEqual(strip(Path(second_path).read_text(encoding="utf-8")), strip(first_text))


if __name__ == "__main__":
    unittest.main()
