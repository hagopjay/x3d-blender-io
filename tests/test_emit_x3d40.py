# SPDX-FileCopyrightText: 2026 OpenAI
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path


SOURCE_DIR = Path(__file__).resolve().parents[1] / "source"
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

from emit_x3d40 import export_ir_scene
from ir import IRInstance, IRMeshGeometry, IRMetadata, IRPBRMaterial, IRScene, IRTextureRef, IRTextureTransform, IRTransform
from validate import validate_xml_text


class EmitX3D40Tests(unittest.TestCase):
    def test_emits_valid_x3d40_with_physical_material(self):
        scene = IRScene(
            name="FixtureScene",
            metadata=IRMetadata(title="Fixture Title", creator="Unit Test"),
            diagnostics=["fixture diagnostic"],
            materials=[
                IRPBRMaterial(
                    name="TestMaterial",
                    base_color=(0.2, 0.4, 0.6, 0.75),
                    emissive_color=(0.1, 0.2, 0.3, 1.0),
                    metallic=0.9,
                    roughness=0.15,
                    normal_scale=0.8,
                    occlusion_strength=0.65,
                    base_color_texture=IRTextureRef(
                        image_name="base.png",
                        filepath="textures/base.png",
                        extension="REPEAT",
                        transform=IRTextureTransform(
                            translation=(0.25, 0.5),
                            rotation=0.125,
                            scale=(2.0, 3.0),
                        ),
                        usage="baseColor",
                    ),
                    metallic_roughness_texture=IRTextureRef(
                        image_name="orm.png",
                        filepath="textures/orm.png",
                        usage="metallicRoughness",
                    ),
                    normal_texture=IRTextureRef(
                        image_name="normal.png",
                        filepath="textures/normal.png",
                        usage="normal",
                    ),
                    emissive_texture=IRTextureRef(
                        image_name="emissive.png",
                        filepath="textures/emissive.png",
                        usage="emissive",
                    ),
                    occlusion_texture=IRTextureRef(
                        image_name="ao.png",
                        filepath="textures/ao.png",
                        usage="occlusion",
                    ),
                )
            ],
            geometries=[
                IRMeshGeometry(
                    name="CubeMesh",
                    coord=[
                        (-1.0, -1.0, -1.0),
                        (1.0, -1.0, -1.0),
                        (1.0, 1.0, -1.0),
                        (-1.0, 1.0, -1.0),
                    ],
                    coord_index=[0, 1, 2, 3, -1],
                    solid=False,
                    crease_angle=0.785398,
                )
            ],
            instances=[
                IRInstance(
                    source_key="MESH:Cube",
                    object_name="Cube",
                    object_type="MESH",
                    geometry_hint="Box",
                    geometry_name="CubeMesh",
                    material_name="TestMaterial",
                    transform=IRTransform(
                        translation=(1.0, 2.0, 3.0),
                        rotation_axis_angle=(0.0, 1.0, 0.0, 0.5),
                        scale=(1.0, 2.0, 1.0),
                    ),
                )
            ],
        )

        buffer = io.StringIO()
        export_ir_scene(buffer, scene, generator="unit-test")
        xml_text = buffer.getvalue()

        self.assertIn('<X3D version="4.0" profile="Immersive">', xml_text)
        self.assertIn("<PhysicalMaterial", xml_text)
        self.assertIn('baseColor="0.200000 0.400000 0.600000"', xml_text)
        self.assertIn('metallic="0.900000"', xml_text)
        self.assertIn('roughness="0.150000"', xml_text)
        self.assertIn('normalScale="0.800000"', xml_text)
        self.assertIn('occlusionStrength="0.650000"', xml_text)
        self.assertIn("<ImageTexture", xml_text)
        self.assertIn('containerField="baseTexture"', xml_text)
        self.assertIn('containerField="metallicRoughnessTexture"', xml_text)
        self.assertIn('containerField="normalTexture"', xml_text)
        self.assertIn('containerField="emissiveTexture"', xml_text)
        self.assertIn('containerField="occlusionTexture"', xml_text)
        self.assertIn("<TextureTransform ", xml_text)
        self.assertIn('DEF="OBJ_Cube"', xml_text)
        self.assertIn('<Appearance USE="MAT_000_TestMaterial_APP" />', xml_text)
        self.assertIn('DEF="GEO_000_CubeMesh"', xml_text)
        self.assertIn("<IndexedFaceSet", xml_text)
        self.assertIn('<IndexedFaceSet USE="GEO_000_CubeMesh" />', xml_text)
        self.assertIn("<Coordinate point=", xml_text)

        validation = validate_xml_text(xml_text)
        self.assertTrue(validation.valid, msg=f"Validation errors: {validation.errors}")

    def test_emits_valid_x3d40_with_unlit_material(self):
        scene = IRScene(
            name="UnlitFixture",
            materials=[
                IRPBRMaterial(
                    name="Lamp",
                    base_color=(1.0, 0.7, 0.1, 1.0),
                    emissive_color=(1.0, 0.7, 0.1, 1.0),
                    unlit=True,
                )
            ],
        )

        buffer = io.StringIO()
        export_ir_scene(buffer, scene, generator="unit-test")
        xml_text = buffer.getvalue()

        self.assertIn("<UnlitMaterial", xml_text)
        validation = validate_xml_text(xml_text)
        self.assertTrue(validation.valid, msg=f"Validation errors: {validation.errors}")

    def test_falls_back_to_primitive_geometry_when_mesh_payload_missing(self):
        scene = IRScene(
            name="PrimitiveFallback",
            instances=[
                IRInstance(
                    source_key="MESH:Sphere",
                    object_name="Sphere",
                    object_type="MESH",
                    geometry_hint="Sphere",
                )
            ],
        )

        buffer = io.StringIO()
        export_ir_scene(buffer, scene, generator="unit-test")
        xml_text = buffer.getvalue()

        self.assertIn("<Sphere", xml_text)
        self.assertNotIn("<IndexedFaceSet USE=", xml_text)
        validation = validate_xml_text(xml_text)
        self.assertTrue(validation.valid, msg=f"Validation errors: {validation.errors}")


if __name__ == "__main__":
    unittest.main()
