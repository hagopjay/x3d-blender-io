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
            # Unknown nodes or fields are warnings; CI sets X3D_STRICT_VALIDATION=1
            # so fixtures must also be warning-free when the x3d package is present.
            if os.environ.get("X3D_STRICT_VALIDATION") == "1":
                self.assertEqual(semantic.warnings, [], semantic.warnings)
            elif semantic.warnings:
                print("x3d.py warnings:", semantic.warnings)

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


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class SceneStructureRoundTripTests(unittest.TestCase):
    """Hierarchy, lights, camera, text and animation on the X3D 4.0 path."""

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="x3d_scene_")
        _register_extension(cls.tmpdir)
        if str(TOOLS_DIR) not in sys.path:
            sys.path.insert(0, str(TOOLS_DIR))
        import bpy
        from scene_fixture import build_scene_fixture

        bpy.ops.wm.read_factory_settings(use_empty=True)
        cls.objects = build_scene_fixture()
        cls.child_world = cls.objects["child"].matrix_world.copy()
        cls.camera_angle = float(cls.objects["camera"].data.angle)
        cls.export_path = os.path.join(cls.tmpdir, "scene.x3d")
        result = bpy.ops.export_scene.x3d(
            filepath=cls.export_path, x3d_version="X3D40", use_hierarchy=True,
            use_animation=True, use_selection=False,
        )
        assert result == {"FINISHED"}, result
        cls.xml_text = Path(cls.export_path).read_text(encoding="utf-8")
        cls.root = ET.fromstring(cls.xml_text)

    def test_validates(self):
        sys.path.insert(0, str(SOURCE_DIR))
        from validate import validate_xml_file, validate_with_x3d_py

        self.assertTrue(validate_xml_file(self.export_path).valid)
        semantic = validate_with_x3d_py(self.export_path)
        if semantic is not None:
            self.assertEqual(semantic.errors, [], semantic.errors)
            if os.environ.get("X3D_STRICT_VALIDATION") == "1":
                self.assertEqual(semantic.warnings, [], semantic.warnings)

    def test_hierarchy_is_nested(self):
        rig = self.root.find(".//Transform[@DEF='OB_Rig']")
        self.assertIsNotNone(rig)
        child = rig.find("Transform[@DEF='OB_ChildCube']")
        self.assertIsNotNone(child, "child Transform must be nested inside its parent")
        self.assertEqual(child.attrib["translation"].split()[0], "1.000000")  # local offset survives
        self.assertIsNotNone(child.find("Shape/IndexedFaceSet"))

    def test_lights_camera_and_navigation(self):
        self.assertIsNotNone(self.root.find(".//Transform[@DEF='OB_KeyLight']/PointLight"))
        self.assertIsNotNone(self.root.find(".//Transform[@DEF='OB_Spot']/SpotLight"))
        self.assertIsNotNone(self.root.find(".//Transform[@DEF='OB_Sun']/DirectionalLight"))
        point = self.root.find(".//PointLight")
        self.assertEqual(point.attrib["color"], "1.000000 0.900000 0.800000")
        view = self.root.find(".//Transform[@DEF='OB_MainCamera']/Viewpoint")
        self.assertIsNotNone(view)
        self.assertEqual(view.attrib["fieldOfView"], "%.6f" % self.camera_angle)
        nav = self.root.find("Scene/NavigationInfo")
        self.assertEqual(nav.attrib["headlight"], "false")
        self.assertIsNotNone(self.root.find("Scene/Background"))

    def test_text_becomes_mesh(self):
        label = self.root.find(".//Transform[@DEF='OB_Label']/Shape/IndexedFaceSet")
        self.assertIsNotNone(label)
        self.assertGreater(len(label.attrib["coordIndex"].split()), 20)

    def test_animation_nodes_and_routes(self):
        timer = self.root.find("Scene/TimeSensor")
        self.assertIsNotNone(timer)
        self.assertEqual(timer.attrib["cycleInterval"], "%.6f" % (23 / 24))
        self.assertEqual(timer.attrib["loop"], "true")
        self.assertIsNotNone(self.root.find("Scene/PositionInterpolator[@DEF='PI_Mover']"))
        self.assertIsNotNone(self.root.find("Scene/OrientationInterpolator[@DEF='OI_Mover']"))
        self.assertIsNone(self.root.find("Scene/PositionInterpolator[@DEF='PI_ChildCube']"))
        routes = self.root.findall("Scene/ROUTE")
        pairs = {(r.attrib["fromNode"], r.attrib["toNode"], r.attrib["toField"]) for r in routes}
        self.assertIn(("PI_Mover", "OB_Mover", "set_translation"), pairs)
        self.assertIn(("OI_Mover", "OB_Mover", "set_rotation"), pairs)
        keys = self.root.find("Scene/PositionInterpolator[@DEF='PI_Mover']").attrib["key"].split()
        self.assertEqual(keys[0], "0.000000")
        self.assertEqual(keys[-1], "1.000000")

    def test_reimport_restores_structure(self):
        import bpy
        from mathutils import Vector

        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=self.export_path), {"FINISHED"})
        by_type = {}
        for obj in bpy.context.scene.objects:
            by_type.setdefault(obj.type, []).append(obj)
        self.assertEqual(len(by_type.get("LIGHT", [])), 3)
        self.assertEqual(len(by_type.get("CAMERA", [])), 1)
        light_types = sorted(obj.data.type for obj in by_type["LIGHT"])
        self.assertEqual(light_types, ["POINT", "SPOT", "SUN"])
        child = next(obj for obj in by_type["MESH"] if "ChildCube" in obj.name or "ChildCube" in obj.data.name)
        delta = (child.matrix_world.to_translation() - self.child_world.to_translation()).length
        self.assertLess(delta, 1e-3, "child cube must land where it was in world space")
        camera = by_type["CAMERA"][0]
        self.assertAlmostEqual(camera.data.angle, self.camera_angle, places=3)
        cam_delta = (camera.matrix_world.to_translation() - Vector((7.0, -7.0, 5.0))).length
        self.assertLess(cam_delta, 1e-2)

    def test_reimport_restores_animation(self):
        import bpy
        from mathutils import Vector

        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.context.scene.frame_start = 1
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=self.export_path), {"FINISHED"})
        mover = next(obj for obj in bpy.context.scene.objects if "Mover" in obj.name)
        self.assertIsNotNone(mover.animation_data)
        self.assertIsNotNone(mover.animation_data.action)
        scene = bpy.context.scene
        self.assertGreaterEqual(scene.frame_end, 24)
        scene.frame_set(1)
        bpy.context.view_layer.update()
        start = mover.matrix_world.to_translation()
        scene.frame_set(24)
        bpy.context.view_layer.update()
        end = mover.matrix_world.to_translation()
        self.assertLess((start - Vector((0.0, 3.0, 0.0))).length, 1e-2, start)
        self.assertLess((end - Vector((3.0, 3.0, 1.0))).length, 1e-2, end)
        axis, angle = mover.matrix_world.to_quaternion().to_axis_angle()
        self.assertAlmostEqual(abs(angle), 1.5708, places=2)
        self.assertAlmostEqual(abs(axis.z), 1.0, places=2)
        static = next(obj for obj in bpy.context.scene.objects if "ChildCube" in obj.name)
        self.assertIsNone(static.animation_data)


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class HAnimExportTests(unittest.TestCase):
    """Armature + skinned mesh -> HAnimHumanoid with joints, skin and joint animation."""

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="x3d_hanim_")
        _register_extension(cls.tmpdir)
        if str(TOOLS_DIR) not in sys.path:
            sys.path.insert(0, str(TOOLS_DIR))
        import bpy
        from hanim_fixture import build_hanim_fixture

        bpy.ops.wm.read_factory_settings(use_empty=True)
        cls.objects = build_hanim_fixture()
        cls.vertex_count = len(cls.objects["skin"].data.vertices)
        cls.export_path = os.path.join(cls.tmpdir, "hanim.x3d")
        result = bpy.ops.export_scene.x3d(
            filepath=cls.export_path, x3d_version="X3D40", use_animation=True, use_selection=False
        )
        assert result == {"FINISHED"}, result
        cls.xml_text = Path(cls.export_path).read_text(encoding="utf-8")
        cls.root = ET.fromstring(cls.xml_text)

    def test_validates(self):
        sys.path.insert(0, str(SOURCE_DIR))
        from validate import validate_xml_file, validate_with_x3d_py

        self.assertTrue(validate_xml_file(self.export_path).valid)
        semantic = validate_with_x3d_py(self.export_path)
        if semantic is not None:
            self.assertEqual(semantic.errors, [], semantic.errors)
            if os.environ.get("X3D_STRICT_VALIDATION") == "1":
                self.assertEqual(semantic.warnings, [], semantic.warnings)

    def test_humanoid_skeleton_and_skin(self):
        humanoid = self.root.find(".//HAnimHumanoid")
        self.assertIsNotNone(humanoid)
        self.assertEqual(humanoid.attrib["version"], "2.0")
        lower = humanoid.find("HAnimJoint[@containerField='skeleton']")
        self.assertIsNotNone(lower)
        self.assertEqual(lower.attrib["name"], "lower")
        upper = lower.find("HAnimJoint")
        self.assertIsNotNone(upper, "child bone must nest inside its parent joint")
        self.assertEqual(upper.attrib["name"], "upper")
        self.assertEqual(upper.attrib["center"], "0.000000 0.000000 1.000000")
        joint_refs = humanoid.findall("HAnimJoint[@containerField='joints']")
        self.assertEqual(len(joint_refs), 2)
        skin_coord = humanoid.find("Coordinate[@containerField='skinCoord']")
        self.assertIsNotNone(skin_coord)
        self.assertGreaterEqual(len(skin_coord.attrib["point"].split()) // 3, self.vertex_count)
        skin_shape = humanoid.find("Shape[@containerField='skin']")
        self.assertIsNotNone(skin_shape)
        self.assertEqual(skin_shape.find("IndexedFaceSet/Coordinate").attrib["USE"], skin_coord.attrib["DEF"])
        # every skin vertex is weighted by at least one joint
        weighted = set()
        for joint in (lower, upper):
            indices = [int(i) for i in joint.attrib["skinCoordIndex"].split()]
            weights = [float(w) for w in joint.attrib["skinCoordWeight"].split()]
            self.assertEqual(len(indices), len(weights))
            weighted.update(indices)
        self.assertEqual(len(weighted), len(skin_coord.attrib["point"].split()) // 3)
        # the skinned mesh is not also written as a plain Shape
        self.assertIsNone(self.root.find(".//Transform[@DEF='OB_Arm']"))

    def test_joint_animation_routed(self):
        upper_def = self.root.find(".//HAnimJoint[@name='upper']").attrib["DEF"]
        interp = self.root.find("Scene/OrientationInterpolator")
        self.assertIsNotNone(interp)
        routes = {(r.attrib["fromNode"], r.attrib["toNode"], r.attrib["toField"]) for r in self.root.findall("Scene/ROUTE")}
        self.assertIn((interp.attrib["DEF"], upper_def, "set_rotation"), routes)
        values = [float(v) for v in interp.attrib["keyValue"].split()]
        last = values[-4:]
        self.assertAlmostEqual(abs(last[3]), 1.0472, places=2)  # 60 degrees
        self.assertAlmostEqual(abs(last[0]), 1.0, places=2)      # about the X axis
        lower_def = self.root.find(".//HAnimJoint[@name='lower']").attrib["DEF"]
        self.assertFalse(any(r[1] == lower_def for r in routes), "unposed bone must not be animated")


if __name__ == "__main__":
    unittest.main()
