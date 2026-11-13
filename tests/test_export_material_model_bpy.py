# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""X3D 4.0 export keeps the material model a scene was imported with (round-trip audit D5, D13).

X_ITE 16.7.1 lights a Material (Phong) in display space and a PhysicalMaterial the glTF way, much darker for the same
colour (a 0.8 grey box lit by a point light: 204 with the Material, 130 with the PhysicalMaterial; measured 13 Nov 2026,
Chromium 153 SwiftShader). A scene imported from Material-lit X3D is exported as Materials, with specularColor and
shininess; a scene made in Blender, or imported from PhysicalMaterials, keeps PhysicalMaterial.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_export_material_model_bpy
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
<NavigationInfo headlight='false'/>
<PointLight location='0 0 5' intensity='1' global='true'/>
<Shape><Appearance>{material}</Appearance><Box size='1 1 0.1'/></Shape>
</Scene></X3D>
"""
CLASSIC = "<Material diffuseColor='0.8 0.4 0.2' specularColor='0.3 0.3 0.3' shininess='0.5' emissiveColor='0.1 0 0'/>"
PHYSICAL = "<PhysicalMaterial baseColor='0.8 0.4 0.2' metallic='0' roughness='0.5'/>"


def _floats(text):
    return [float(v) for v in text.replace(",", " ").split()]


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class ExportMaterialModelTests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="x3d_material_model_")
        _register_extension(self.tmpdir)
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def _import(self, material):
        path = os.path.join(self.tmpdir, "in.x3d")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(SCENE.format(material=material))
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=path), {"FINISHED"})

    def _export(self, **options):
        path = os.path.join(self.tmpdir, "out_%d.x3d" % len(os.listdir(self.tmpdir)))
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=path, x3d_version="X3D40", use_selection=False, **options),
                         {"FINISHED"})
        return ET.parse(path).getroot()

    def test_a_material_lit_scene_is_exported_with_phong_fields(self):
        self._import(CLASSIC)
        self.assertEqual(bpy.context.scene["x3d_lighting_model"], "classic")
        root = self._export()
        self.assertIsNone(root.find(".//PhysicalMaterial"))
        material = root.find(".//Material")
        for got, want in zip(_floats(material.attrib["diffuseColor"]), (0.8, 0.4, 0.2)):
            self.assertAlmostEqual(got, want, places=3)
        for got in _floats(material.attrib["specularColor"]):
            self.assertAlmostEqual(got, 0.3, places=2)
        self.assertAlmostEqual(float(material.attrib["shininess"]), 0.5, places=3)
        for got, want in zip(_floats(material.attrib["emissiveColor"]), (0.1, 0.0, 0.0)):
            self.assertAlmostEqual(got, want, places=3)

    def test_the_option_can_force_either_model(self):
        self._import(CLASSIC)
        self.assertIsNotNone(self._export(material_model="PHYSICAL").find(".//PhysicalMaterial"))
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self._import(PHYSICAL)
        self.assertIsNotNone(self._export().find(".//PhysicalMaterial"))
        root = self._export(material_model="CLASSIC")
        self.assertIsNone(root.find(".//PhysicalMaterial"))
        self.assertIsNotNone(root.find(".//Material"))

    def test_a_scene_made_in_blender_stays_physical(self):
        bpy.ops.mesh.primitive_cube_add()
        bpy.context.object.data.materials.append(bpy.data.materials.new("Grey"))
        self.assertIsNone(bpy.context.scene.get("x3d_lighting_model"))
        root = self._export()
        self.assertIsNotNone(root.find(".//PhysicalMaterial"))
        self.assertIsNone(root.find(".//Material"))

    def test_a_metallic_material_in_a_classic_scene_stays_physical(self):
        self._import(CLASSIC)
        principled = bpy.data.materials[0].node_tree.nodes["Principled BSDF"]
        principled.inputs["Metallic"].default_value = 1.0
        root = self._export()
        self.assertIsNotNone(root.find(".//PhysicalMaterial"))


if __name__ == "__main__":
    unittest.main()
