# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Export -> validate -> import round trip of the swatch book under Blender.

Skipped when ``bpy`` is not importable. Run with the ``bpy`` wheel or from a
Blender build::

    cd tests && python -m unittest test_roundtrip_bpy
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "source"
TOOLS_DIR = ROOT / "tools"


def _register_extension(tmpdir: str):
    """Expose ``source/`` as the ``io_scene_x3d`` package and register it."""
    package_dir = Path(tmpdir) / "io_scene_x3d"
    if not package_dir.exists():
        try:
            package_dir.symlink_to(SOURCE_DIR, target_is_directory=True)
        except OSError:
            import shutil
            shutil.copytree(SOURCE_DIR, package_dir)
    if tmpdir not in sys.path:
        sys.path.insert(0, tmpdir)
    import importlib
    module = importlib.import_module("io_scene_x3d")
    try:
        module.register()
    except Exception:
        # already registered by an earlier test in the same interpreter
        pass
    return module


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class SwatchBookRoundTripTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="x3d_roundtrip_")
        _register_extension(cls.tmpdir)
        if str(TOOLS_DIR) not in sys.path:
            sys.path.insert(0, str(TOOLS_DIR))
        import bpy
        from swatch_book import build_swatch_book

        bpy.ops.wm.read_factory_settings(use_empty=True)
        cls.objects = build_swatch_book(texture_dir=cls.tmpdir)
        cls.export_path = os.path.join(cls.tmpdir, "swatches.x3d")
        result = bpy.ops.export_scene.x3d(
            filepath=cls.export_path, x3d_version="X3D40", use_normals=True, use_selection=False
        )
        assert result == {"FINISHED"}, result
        cls.xml_text = Path(cls.export_path).read_text(encoding="utf-8")
        cls.root = ET.fromstring(cls.xml_text)

    def test_document_is_x3d40_and_validates(self):
        sys.path.insert(0, str(SOURCE_DIR))
        from validate import validate_xml_file, validate_with_x3d_py

        self.assertEqual(self.root.attrib["version"], "4.0")
        self.assertIn('DTD X3D 4.0//EN', self.xml_text)
        structural = validate_xml_file(self.export_path)
        self.assertTrue(structural.valid, structural.errors)
        semantic = validate_with_x3d_py(self.export_path)
        if semantic is not None:
            self.assertEqual(semantic.errors, [], semantic.errors)
            self.assertEqual(semantic.warnings, [], semantic.warnings)

    def test_materials_are_physical_or_unlit(self):
        physical = self.root.findall(".//PhysicalMaterial")
        unlit = self.root.findall(".//UnlitMaterial")
        self.assertEqual(len(unlit), 1)
        self.assertEqual(unlit[0].attrib["emissiveColor"].split()[:3], ["1.000000", "0.500000", "0.000000"])
        by_def = {node.attrib["DEF"]: node for node in physical}
        gold = by_def["MA_Gold"]
        self.assertEqual(gold.attrib["metallic"], "1.000000")
        self.assertEqual(gold.attrib["roughness"], "0.200000")
        glass = by_def["MA_Glass"]
        self.assertEqual(glass.attrib["transparency"], "0.600000")
        glass_app = self.root.find(".//Appearance[@DEF='APP_Glass']")
        self.assertEqual(glass_app.attrib.get("alphaMode"), "BLEND")
        self.assertNotIn("<Material ", self.xml_text)
        self.assertNotIn("MaterialGallery", self.xml_text)

    def test_texture_written_next_to_file(self):
        textures = self.root.findall(".//ImageTexture")
        self.assertEqual(len(textures), 1)
        self.assertEqual(textures[0].attrib["containerField"], "baseTexture")
        url = textures[0].attrib["url"].strip('"')
        self.assertTrue(os.path.exists(os.path.join(self.tmpdir, url)), url)
        checker = self.root.find(".//IndexedFaceSet[@DEF='ME_SwatchTexturedMesh']")
        self.assertIsNotNone(checker.find("TextureCoordinate"))

    def test_geometry_carries_normals_colors_and_solid(self):
        dielectric = self.root.find(".//IndexedFaceSet[@DEF='ME_SwatchDielectricMesh']")
        self.assertNotIn("solid", dielectric.attrib)  # backface culling on -> solid default true
        gold = self.root.find(".//IndexedFaceSet[@DEF='ME_SwatchMetalMesh']")
        self.assertEqual(gold.attrib.get("solid"), "false")
        self.assertIsNotNone(gold.find("Normal"))
        sphere_top = self.root.find(".//IndexedFaceSet[@DEF='ME_SwatchTwoToneMesh_m0']")
        sphere_bottom = self.root.find(".//IndexedFaceSet[@DEF='ME_SwatchTwoToneMesh_m1']")
        self.assertIsNotNone(sphere_top)
        self.assertIsNotNone(sphere_bottom)
        self.assertIsNotNone(sphere_top.find("ColorRGBA"))
        two_tone = self.root.find(".//Transform[@DEF='OB_SwatchTwoTone']")
        self.assertEqual(len(two_tone.findall("Shape")), 2)

    def test_shared_mesh_uses_def_use(self):
        self.assertEqual(self.xml_text.count('<IndexedFaceSet DEF="ME_SharedCube"'), 1)
        self.assertEqual(self.xml_text.count('<IndexedFaceSet USE="ME_SharedCube" />'), 1)
        self.assertEqual(self.xml_text.count('<Appearance DEF="APP_Dielectric">'), 1)
        self.assertEqual(self.xml_text.count('<Appearance USE="APP_Dielectric" />'), 2)

    def test_reimport_restores_materials_and_meshes(self):
        import bpy

        bpy.ops.wm.read_factory_settings(use_empty=True)
        result = bpy.ops.import_scene.x3d(filepath=self.export_path)
        self.assertEqual(result, {"FINISHED"})

        meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
        # 7 swatch objects; the two-tone sphere imports as two shapes
        self.assertEqual(len(meshes), 9, [obj.name for obj in meshes])

        materials = {material.name: material for material in bpy.data.materials}
        gold = materials["MA_Gold"]
        bsdf = gold.node_tree.nodes["Principled BSDF"]
        self.assertAlmostEqual(bsdf.inputs["Metallic"].default_value, 1.0, places=5)
        self.assertAlmostEqual(bsdf.inputs["Roughness"].default_value, 0.2, places=5)
        self.assertAlmostEqual(bsdf.inputs["Base Color"].default_value[0], 1.0, places=5)
        self.assertAlmostEqual(bsdf.inputs["Base Color"].default_value[1], 0.77, places=5)

        glass = materials["MA_Glass"]
        bsdf = glass.node_tree.nodes["Principled BSDF"]
        self.assertAlmostEqual(bsdf.inputs["Alpha"].default_value, 0.4, places=5)
        self.assertEqual(glass.surface_render_method, "BLENDED")

        neon = materials["MA_Neon"]
        bsdf = neon.node_tree.nodes["Principled BSDF"]
        self.assertAlmostEqual(bsdf.inputs["Emission Strength"].default_value, 1.0, places=5)
        self.assertAlmostEqual(bsdf.inputs["Emission Color"].default_value[1], 0.5, places=5)

        checker = materials["MA_Checker"]
        image_nodes = [node for node in checker.node_tree.nodes if node.type == "TEX_IMAGE"]
        self.assertEqual(len(image_nodes), 1)
        self.assertIsNotNone(image_nodes[0].image)

        dielectric = materials["MA_Dielectric"]
        self.assertTrue(dielectric.use_backface_culling)
        self.assertFalse(materials["MA_Gold"].use_backface_culling)

        textured = next(obj for obj in meshes if "SwatchTextured" in obj.name)
        self.assertTrue(textured.data.uv_layers)
        self.assertEqual(len(textured.data.polygons), 1)
        shared = [obj for obj in meshes if "SharedCube" in obj.data.name or "SharedCube" in obj.name]
        self.assertGreaterEqual(len(shared), 1)


if __name__ == "__main__":
    unittest.main()
