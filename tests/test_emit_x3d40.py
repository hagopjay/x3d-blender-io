# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import io
import re
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


SOURCE_DIR = Path(__file__).resolve().parents[1] / "source"
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

from emit_x3d40 import export_ir_scene, head_meta
from ir import (
    IRBackground, IRGaussianSplats, IRInlineAsset, IRInstance, IRLight, IRMeshGeometry, IRMetadata, IRMetadataNode,
    IRPBRMaterial, IRScene, IRShape, IRTextureRef, IRTextureTransform, IRTransform,
)
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

        self.assertIn('<X3D version="4.0" profile="Immersive"', xml_text)
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
        self.assertIn('DEF="OB_Cube"', xml_text)
        self.assertIn('<Appearance DEF="APP_TestMaterial">', xml_text)
        self.assertIn('transparency="0.250000"', xml_text)
        self.assertIn('<PhysicalMaterial DEF="MA_TestMaterial"', xml_text)
        self.assertIn('<IndexedFaceSet DEF="ME_CubeMesh"', xml_text)
        self.assertIn('solid="false"', xml_text)
        self.assertIn('creaseAngle="0.785398"', xml_text)
        self.assertIn("<Coordinate point=", xml_text)
        self.assertNotIn("MaterialGallery", xml_text)
        self.assertNotIn("GeometryLibrary", xml_text)
        self.assertIn('<meta name="info" content="fixture diagnostic" />', xml_text)

        validation = validate_xml_text(xml_text)
        self.assertTrue(validation.valid, msg=f"Validation errors: {validation.errors}")

    def test_shared_geometry_and_material_use_def_use(self):
        geometry = IRMeshGeometry(
            name="Quad",
            coord=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)],
            coord_index=[0, 1, 2, 3, -1],
            normal=[(0.0, 0.0, 1.0)] * 4,
            tex_coord=[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)],
            color=[(1.0, 0.0, 0.0, 1.0)] * 4,
        )
        material = IRPBRMaterial(name="Shared", base_color=(1.0, 1.0, 1.0, 1.0), metallic=0.0, roughness=0.5)
        scene = IRScene(
            name="Shared",
            geometries=[geometry],
            materials=[material],
            instances=[
                IRInstance(source_key="MESH:Quad", object_name=f"Quad.{index:03d}", object_type="MESH",
                           shapes=[IRShape(geometry_name="Quad", material_name="Shared")])
                for index in range(3)
            ],
        )
        buffer = io.StringIO()
        export_ir_scene(buffer, scene, generator="unit-test")
        xml_text = buffer.getvalue()

        self.assertEqual(xml_text.count('<IndexedFaceSet DEF="ME_Quad"'), 1)
        self.assertEqual(xml_text.count('<IndexedFaceSet USE="ME_Quad" />'), 2)
        self.assertEqual(xml_text.count('<Appearance DEF="APP_Shared">'), 1)
        self.assertEqual(xml_text.count('<Appearance USE="APP_Shared" />'), 2)
        self.assertIn("<Normal vector=", xml_text)
        self.assertIn("<TextureCoordinate point=", xml_text)
        self.assertIn("<ColorRGBA color=", xml_text)
        self.assertIn('DEF="OB_Quad_000"', xml_text)
        self.assertIn('DEF="OB_Quad_002"', xml_text)
        validation = validate_xml_text(xml_text)
        self.assertTrue(validation.valid, msg=f"Validation errors: {validation.errors}")

    def test_multi_material_instance_emits_one_shape_per_slot(self):
        scene = IRScene(
            name="Multi",
            geometries=[
                IRMeshGeometry(name="Mesh_m0", coord=[(0, 0, 0), (1, 0, 0), (0, 1, 0)], coord_index=[0, 1, 2, -1], material_slot=0),
                IRMeshGeometry(name="Mesh_m1", coord=[(0, 0, 1), (1, 0, 1), (0, 1, 1)], coord_index=[0, 1, 2, -1], material_slot=1),
            ],
            materials=[IRPBRMaterial(name="A"), IRPBRMaterial(name="B", unlit=True)],
            instances=[
                IRInstance(source_key="MESH:Mesh", object_name="Mesh", object_type="MESH",
                           shapes=[IRShape("Mesh_m0", "A"), IRShape("Mesh_m1", "B")])
            ],
        )
        buffer = io.StringIO()
        export_ir_scene(buffer, scene, generator="unit-test")
        xml_text = buffer.getvalue()
        self.assertEqual(xml_text.count("<Shape>"), 2)
        self.assertIn("<PhysicalMaterial", xml_text)
        self.assertIn("<UnlitMaterial", xml_text)

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
            instances=[
                IRInstance(source_key="MESH:Lamp", object_name="Lamp", object_type="MESH",
                           geometry_hint="Sphere", material_name="Lamp")
            ],
        )

        buffer = io.StringIO()
        export_ir_scene(buffer, scene, generator="unit-test")
        xml_text = buffer.getvalue()

        self.assertIn("<UnlitMaterial", xml_text)
        self.assertIn('emissiveColor="1.000000 0.700000 0.100000"', xml_text)
        validation = validate_xml_text(xml_text)
        self.assertTrue(validation.valid, msg=f"Validation errors: {validation.errors}")

    def test_emission_strength_above_one_fits_sfcolor_range(self):
        # Blender's Emission Color x Emission Strength can exceed 1; X3D 4.0's XSD caps SFColor at 1.
        scene = IRScene(
            name="GlowFixture",
            materials=[
                IRPBRMaterial(name="Glow", base_color=(0.0, 0.1, 0.1, 1.0), emissive_color=(0.0, 3.270402, 3.497227, 1.0)),
                IRPBRMaterial(name="Neon", base_color=(1.0, 1.0, 1.0, 1.0), emissive_color=(5.0, 2.5, -0.1, 1.0), unlit=True),
            ],
            instances=[
                IRInstance(source_key="MESH:Glow", object_name="Glow", object_type="MESH",
                           geometry_hint="Sphere", material_name="Glow"),
                IRInstance(source_key="MESH:Neon", object_name="Neon", object_type="MESH",
                           geometry_hint="Box", material_name="Neon"),
            ],
        )
        buffer = io.StringIO()
        export_ir_scene(buffer, scene, generator="unit-test")
        xml_text = buffer.getvalue()
        self.assertIn('emissiveColor="0.000000 0.935141 1.000000"', xml_text)
        self.assertIn('emissiveColor="1.000000 0.500000 0.000000"', xml_text)
        for value in re.findall(r'(?:emissiveColor|baseColor)="([^"]+)"', xml_text):
            self.assertTrue(all(0.0 <= float(c) <= 1.0 for c in value.split()), value)

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

    def test_shape_component_declared_when_physical_or_unlit_material_written(self):
        # X3DUOM's Immersive node list leaves out PhysicalMaterial and UnlitMaterial.
        component = '<component name="Shape" level="2" />'
        for unlit in (False, True):
            with self.subTest(unlit=unlit):
                scene = IRScene(
                    name="Header",
                    materials=[IRPBRMaterial(name="Paint", unlit=unlit)],
                    instances=[IRInstance(source_key="MESH:Ball", object_name="Ball", object_type="MESH",
                                          geometry_hint="Sphere", material_name="Paint")],
                )
                buffer = io.StringIO()
                export_ir_scene(buffer, scene, generator="unit-test")
                head, body = buffer.getvalue().split("</head>")
                self.assertIn("<UnlitMaterial" if unlit else "<PhysicalMaterial", body)
                self.assertEqual(head.count(component), 1)
                self.assertLess(head.index(component), head.index('<meta name="generator"'))

    def test_shape_component_absent_without_physical_or_unlit_material(self):
        scene = IRScene(
            name="NoShapes",
            instances=[
                IRInstance(source_key="EMPTY:Part", object_name="Part", object_type="EMPTY",
                           inline=IRInlineAsset(url="part.x3d")),
                IRInstance(source_key="LIGHT:Sun", object_name="Sun", object_type="LIGHT",
                           light=IRLight(name="Sun", light_type="DIRECTIONAL")),
            ],
        )
        buffer = io.StringIO()
        export_ir_scene(buffer, scene, generator="unit-test")
        xml_text = buffer.getvalue()
        self.assertNotIn("Material", xml_text)
        self.assertNotIn("<component", xml_text)

    def test_light_shadow_and_ambient_fields(self):
        scene = IRScene(
            name="Lights",
            instances=[
                IRInstance(source_key="LIGHT:Sun", object_name="Sun", object_type="LIGHT",
                           light=IRLight(name="Sun", light_type="DIRECTIONAL", intensity=1.067, ambient_intensity=0.12,
                                         shadows=True, shadow_intensity=0.72)),
                IRInstance(source_key="LIGHT:SkyFill", object_name="SkyFill", object_type="LIGHT",
                           light=IRLight(name="SkyFill", light_type="DIRECTIONAL", intensity=0.38)),
            ],
        )
        buffer = io.StringIO()
        export_ir_scene(buffer, scene, generator="unit-test")
        xml_text = buffer.getvalue()
        sun = re.search(r'<DirectionalLight DEF="LA_Sun"[^>]*>', xml_text).group(0)
        self.assertIn('intensity="1.067000"', sun)
        self.assertIn('ambientIntensity="0.120000"', sun)
        self.assertIn('shadows="true"', sun)
        self.assertIn('shadowIntensity="0.720000"', sun)
        fill = re.search(r'<DirectionalLight DEF="LA_SkyFill"[^>]*>', xml_text).group(0)
        self.assertNotIn("shadow", fill)  # shadows defaults to false, shadowIntensity to 1
        self.assertTrue(validate_xml_text(xml_text).valid)

    def test_shape_cast_shadow_false(self):
        def instance(name, cast_shadow):
            return IRInstance(source_key=f"MESH:{name}", object_name=name, object_type="MESH",
                              geometry_hint="Box", cast_shadow=cast_shadow)

        buffer = io.StringIO()
        export_ir_scene(buffer, IRScene(name="Shadows", instances=[instance("Ground", False), instance("Tower", True)]))
        xml_text = buffer.getvalue()
        self.assertEqual(xml_text.count('<Shape castShadow="false">'), 1)
        self.assertLess(xml_text.index('<Shape castShadow="false">'), xml_text.index('DEF="OB_Tower"'))
        self.assertEqual(xml_text.count("<Shape>"), 1)
        self.assertTrue(validate_xml_text(xml_text).valid)

    def test_shape_metadata_written_in_first_shape(self):
        lidar = IRMetadataNode("MetadataSet", name="lidar", reference="USGS 3DEP 2017", members=[
            IRMetadataNode("MetadataDouble", name="footprintArea_m2", value="83.8"),
            IRMetadataNode("MetadataInteger", name="roofIntensityMedian", value="19152"),
            IRMetadataNode("MetadataString", name="note", value='"roof & walls" "flat"'),
            IRMetadataNode("MetadataSet", name="empty"),
        ])
        building = IRInstance(source_key="MESH:B0000", object_name="B0000", object_type="MESH", metadata=lidar,
                              shapes=[IRShape(geometry_hint="Box"), IRShape(geometry_hint="Cone")])
        buffer = io.StringIO()
        export_ir_scene(buffer, IRScene(name="Metadata", instances=[building]))
        xml_text = buffer.getvalue()
        self.assertTrue(validate_xml_text(xml_text).valid)
        shapes = ET.fromstring(xml_text).findall(".//Transform[@DEF='OB_B0000']/Shape")
        self.assertEqual(len(shapes), 2)
        self.assertIsNone(shapes[1].find("MetadataSet"))
        written = shapes[0][0]  # the metadata field comes before appearance and geometry
        self.assertEqual((written.tag, written.attrib), ("MetadataSet", {
            "containerField": "metadata", "name": "lidar", "reference": "USGS 3DEP 2017"}))
        self.assertEqual([(member.tag, member.attrib) for member in written], [
            ("MetadataDouble", {"name": "footprintArea_m2", "value": "83.8"}),
            ("MetadataInteger", {"name": "roofIntensityMedian", "value": "19152"}),
            ("MetadataString", {"name": "note", "value": '"roof & walls" "flat"'}),
            ("MetadataSet", {"name": "empty"}),
        ])

    def _background(self, scene):
        buffer = io.StringIO()
        export_ir_scene(buffer, scene)
        xml_text = buffer.getvalue()
        self.assertTrue(validate_xml_text(xml_text).valid)
        backgrounds = ET.fromstring(xml_text).findall("Scene/Background")
        self.assertEqual(len(backgrounds), 1)
        return {name: [round(float(value), 6) for value in text.split()] for name, text in backgrounds[0].attrib.items()}

    def test_background_gradient(self):
        # the earth-twin campus sky: five angles, six colours, one ground angle
        sky = [(0.16, 0.33, 0.62), (0.25, 0.45, 0.75), (0.42, 0.6, 0.85), (0.62, 0.74, 0.9), (0.78, 0.83, 0.9),
               (0.8, 0.84, 0.88)]
        background = IRBackground(sky_color=sky, sky_angle=[0.5, 1.0, 1.35, 1.52, 1.5708],
                                  ground_color=[(0.22, 0.24, 0.2), (0.3, 0.31, 0.27)], ground_angle=[1.5708])
        written = self._background(IRScene(name="Sky", background=background, background_color=(1.0, 0.0, 0.0)))
        self.assertEqual(written, {
            "skyAngle": [0.5, 1.0, 1.35, 1.52, 1.5708],
            "skyColor": [channel for color in sky for channel in color],
            "groundAngle": [1.5708],
            "groundColor": [0.22, 0.24, 0.2, 0.3, 0.31, 0.27],
        })

    def test_background_fitted_to_schema_ranges(self):
        background = IRBackground(sky_color=[(1.5, -0.1, 0.5), (0.2, 0.2, 0.2)], sky_angle=[4.0, 5.0],
                                  ground_color=[(0.1, 0.1, 0.1)], ground_angle=[0.3], transparency=1.5)
        written = self._background(IRScene(name="Sky", background=background))
        self.assertEqual(written, {"skyAngle": [3.1416], "skyColor": [1.0, 0.0, 0.5, 0.2, 0.2, 0.2],
                                   "groundColor": [0.1, 0.1, 0.1], "transparency": [1.0]})

    def test_world_colour_background_without_imported_one(self):
        self.assertEqual(self._background(IRScene(name="Sky", background_color=(0.04, 0.02, 0.08))),
                         {"skyColor": [0.04, 0.02, 0.08]})

    def test_geometry2d_component_declared_for_circle2d_fallback(self):
        scene = IRScene(
            name="Disc",
            instances=[IRInstance(source_key="MESH:Disc", object_name="Disc", object_type="MESH",
                                  geometry_hint="Circle2D")],
        )
        buffer = io.StringIO()
        export_ir_scene(buffer, scene, generator="unit-test")
        xml_text = buffer.getvalue()
        self.assertIn("<Circle2D", xml_text)
        self.assertIn(
            '    <component name="Geometry2D" level="2" />\n    <component name="Shape" level="2" />\n', xml_text
        )


class EmitSplatsAndInlineTests(unittest.TestCase):
    def _splat_scene(self):
        splats = IRGaussianSplats(
            name="Cloud",
            positions=[(0.0, 0.0, 0.0), (1.0, 2.0, 3.0)],
            scales=[(0.1, 0.2, 0.3), (0.4, 0.5, 0.6)],
            orientations=[(0.0, 0.0, 0.0, 1.0), (0.0, 0.707107, 0.0, 0.707107)],
            opacities=[1.0, 0.5],
            sh={(0, 0): [(1.0, 0.0, 0.0), (0.0, 0.0, 1.0)], (1, 0): [(0.1, 0.1, 0.1), (0.2, 0.2, 0.2)],
                (1, 1): [(0.0, 0.0, 0.0), (0.3, 0.3, 0.3)], (1, 2): [(0.5, 0.5, 0.5), (0.0, 0.0, 0.0)]},
        )
        return IRScene(
            name="Splats",
            splats=[splats],
            instances=[IRInstance(source_key="SPLATS:Cloud", object_name="Cloud", object_type="MESH", splats_name="Cloud")],
        )

    def test_x3d41_writes_gaussian_splats_node(self):
        buffer = io.StringIO()
        export_ir_scene(buffer, self._splat_scene(), version="4.1")
        xml = buffer.getvalue()
        self.assertIn('<X3D version="4.1"', xml)
        self.assertIn('x3d-4.1.dtd', xml)
        self.assertIn('<component name="GaussianSplats" level="1" />', xml)
        self.assertIn('<GaussianSplats DEF="GS_Cloud"', xml)
        self.assertIn('orientations="0 0 0 1 0 0.707107 0 0.707107"', xml)
        self.assertIn('opacities="1 0.5"', xml)
        self.assertIn('sphericalHarmonicsDegree0Coef0="1 0 0 0 0 1"', xml)
        self.assertIn('sphericalHarmonicsDegree1Coef0=', xml)
        self.assertNotIn("PointSet", xml)
        self.assertTrue(validate_xml_text(xml).valid)

    def test_splat_arrays_are_float32_exact(self):
        import random
        import struct

        rng = random.Random(7)
        f32 = struct.Struct("<f")
        to32 = lambda v: f32.unpack(f32.pack(v))[0]  # noqa: E731
        # scales over seven decades: %.6f turned the small ones into 0.000000
        scales = [tuple(to32(10 ** rng.uniform(-6, 1)) for _ in range(3)) for _ in range(500)]
        scene = self._splat_scene()
        cloud = scene.splats[0]
        cloud.positions = [tuple(to32(rng.uniform(-50, 50)) for _ in range(3)) for _ in range(500)]
        cloud.scales = scales
        cloud.orientations = [(0.0, 0.0, 0.0, 1.0)] * 500
        cloud.opacities = [to32(rng.random()) for _ in range(500)]
        cloud.sh = {(0, 0): [tuple(to32(rng.gauss(0, 1)) for _ in range(3)) for _ in range(500)]}
        buffer = io.StringIO()
        export_ir_scene(buffer, scene, version="4.1")
        xml = buffer.getvalue()
        node = re.search(r"<GaussianSplats [^>]*>", xml).group(0)
        back = [float(v) for v in re.search(r' scales="([^"]*)"', node).group(1).split()]
        self.assertEqual(back and [to32(v) for v in back], [c for s in scales for c in s])
        back = [float(v) for v in re.search(r' positions="([^"]*)"', node).group(1).split()]
        self.assertEqual([to32(v) for v in back], [c for p in cloud.positions for c in p])
        self.assertTrue(validate_xml_text(xml).valid)

    def test_partial_sh_degree_is_not_written(self):
        scene = self._splat_scene()
        del scene.splats[0].sh[(1, 2)]  # degree 1 now has 2 of its 3 coefficients
        buffer = io.StringIO()
        export_ir_scene(buffer, scene, version="4.1")
        xml = buffer.getvalue()
        self.assertIn("sphericalHarmonicsDegree0Coef0=", xml)
        self.assertNotIn("sphericalHarmonicsDegree1", xml)

    def test_non_finite_splat_value_stops_export(self):
        scene = self._splat_scene()
        scene.splats[0].scales[1] = (0.4, float("nan"), 0.6)
        with self.assertRaisesRegex(ValueError, "scales"):
            export_ir_scene(io.StringIO(), scene, version="4.1")

    def test_x3d40_degrades_splats_to_pointset(self):
        buffer = io.StringIO()
        export_ir_scene(buffer, self._splat_scene(), version="4.0")
        xml = buffer.getvalue()
        self.assertIn('<X3D version="4.0"', xml)
        self.assertNotIn("GaussianSplats", xml.split("<Scene>")[1])
        self.assertIn('<PointSet DEF="GS_Cloud">', xml)
        self.assertIn("<ColorRGBA", xml)
        self.assertIn("written as PointSet", xml)
        self.assertNotIn("<component", xml)  # the PointSet Shape has no material

    def test_inline_written_in_transform(self):
        scene = IRScene(
            name="Inline",
            instances=[IRInstance(source_key="EMPTY:Part", object_name="Part", object_type="EMPTY",
                                  transform=IRTransform(translation=(1.0, 2.0, 3.0)),
                                  inline=IRInlineAsset(url="parts/wheel.glb"))],
        )
        buffer = io.StringIO()
        export_ir_scene(buffer, scene)
        xml = buffer.getvalue()
        self.assertIn('<Transform DEF="OB_Part" translation="1.000000 2.000000 3.000000"', xml)
        self.assertIn("<Inline DEF=\"IN_Part\" url='\"parts/wheel.glb\"' />", xml)
        self.assertTrue(validate_xml_text(xml).valid)

    def test_unknown_version_rejected(self):
        with self.assertRaises(ValueError):
            export_ir_scene(io.StringIO(), IRScene(name="x"), version="3.3")


class HeadMetaTests(unittest.TestCase):
    """Head meta read from an imported file is written back, with the export's own generator and filename."""

    GENERATOR = "X3D Blender I/O v2.6.1"
    COPERNICUS = ("Ground and valley colour: Contains modified Copernicus Sentinel data 2026 "
                  "(scene S2B_17SNB_20261007, 7 Oct 2026, 0.05 percent cloud).")
    # the head of the earth-twin campus scene, cut short
    CAMPUS = [
        ("title", "Blacksburg campus, local frame"),
        ("creator", "x3d.io Earth twin build (open data pipeline)"),
        ("created", "2026-10-16T01:01Z"),
        ("reference", "Terrain, buildings and trees: USGS 3DEP lidar (public domain)."),
        ("reference", COPERNICUS),
        ("license", "Data: public domain (USGS) and free and open (Copernicus Sentinel-2, attribution required)."),
        ("generator", "earth-twin/src/build_x3d.py"),
    ]

    def test_imported_meta_kept_in_order_with_repeated_names(self):
        metadata = IRMetadata(filename="campus.x3d", entries=list(self.CAMPUS))
        self.assertEqual(head_meta(metadata, self.GENERATOR),
                         [("generator", self.GENERATOR), ("filename", "campus.x3d")] + self.CAMPUS)

    def test_dialog_values_replace_single_valued_meta_and_add_references(self):
        metadata = IRMetadata(filename="campus.x3d", entries=list(self.CAMPUS), title="Campus",
                              reference="Re-exported from Blender", license="CC_BY_4.0")
        pairs = head_meta(metadata, self.GENERATOR)
        self.assertEqual([content for name, content in pairs if name == "title"], ["Campus"])
        self.assertEqual([content for name, content in pairs if name == "license"], ["CC_BY_4.0"])
        self.assertEqual([content for name, content in pairs if name == "reference"],
                         [self.CAMPUS[3][1], self.COPERNICUS, "Re-exported from Blender"])
        self.assertEqual(pairs[2], ("title", "Campus"))  # in the imported title's place

    def test_no_licence_without_dialog_or_imported_one(self):
        pairs = head_meta(IRMetadata(filename="cube.x3d", creator="Me"), self.GENERATOR, ["a diagnostic"])
        self.assertEqual(pairs, [("generator", self.GENERATOR), ("filename", "cube.x3d"), ("creator", "Me"),
                                 ("info", "a diagnostic")])

    def test_own_export_meta_is_regenerated_not_carried_over(self):
        imported = [("generator", "X3D Blender I/O v2.5.0"), ("filename", "old.x3d"), ("title", "Campus"),
                    ("license", "NONE"), ("info", "1 Gaussian splat object(s) written as PointSet"),
                    ("translator", "X3D Blender I/O v2.5.0"), ("generator", "Blender 4.5.14 LTS")]
        pairs = head_meta(IRMetadata(filename="new.x3d", entries=imported), self.GENERATOR, ["now"])
        self.assertEqual(pairs, [("generator", self.GENERATOR), ("filename", "new.x3d"), ("title", "Campus"),
                                 ("generator", "Blender 4.5.14 LTS"), ("info", "now")])

    def test_third_party_info_and_exact_repeats(self):
        imported = [("info", "kept"), ("reference", "R"), ("reference", "R")]
        pairs = head_meta(IRMetadata(entries=imported, reference="R"), self.GENERATOR)
        self.assertEqual(pairs, [("generator", self.GENERATOR), ("info", "kept"), ("reference", "R")])

    def test_written_head_validates(self):
        metadata = IRMetadata(filename="campus.x3d", entries=list(self.CAMPUS) + [("description", 'A "quoted" <b> & more')])
        buffer = io.StringIO()
        export_ir_scene(buffer, IRScene(name="Campus", metadata=metadata), generator=self.GENERATOR)
        xml_text = buffer.getvalue()
        head = re.search(r"<head>.*</head>", xml_text, re.S).group(0)
        self.assertEqual(head.count('<meta name="reference"'), 2)
        self.assertIn("Contains modified Copernicus Sentinel data 2026", head)
        self.assertNotIn('content="NONE"', head)
        self.assertTrue(validate_xml_text(xml_text).valid)


if __name__ == "__main__":
    unittest.main()
