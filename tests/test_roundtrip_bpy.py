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


def _force_splat_import(test: unittest.TestCase, target: str):
    """Pin the importer's splat target ('mesh' or 'pointcloud') for one test."""
    previous = os.environ.get("X3D_SPLAT_IMPORT")
    os.environ["X3D_SPLAT_IMPORT"] = target

    def restore():
        if previous is None:
            os.environ.pop("X3D_SPLAT_IMPORT", None)
        else:
            os.environ["X3D_SPLAT_IMPORT"] = previous
    test.addCleanup(restore)


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
        for tag in ("PointLight", "SpotLight", "DirectionalLight"):
            # each light sits in its own Transform, so a non-global light would illuminate nothing
            self.assertEqual(self.root.find(f".//{tag}").attrib.get("global"), "true", tag)
        point = self.root.find(".//PointLight")
        self.assertEqual(point.attrib["color"], "1.000000 0.900000 0.800000")
        view = self.root.find(".//Transform[@DEF='OB_MainCamera']/Viewpoint")
        self.assertIsNotNone(view)
        # X3D measures fieldOfView across the smaller side; the fixture's 16:9 camera fits the wider side.
        import bpy
        from viewpoint_fov import render_size, x3d_field_of_view
        expected = x3d_field_of_view(self.camera_angle, "AUTO", *render_size(bpy.context.scene))
        self.assertLess(expected, self.camera_angle)
        self.assertEqual(view.attrib["fieldOfView"], "%.6f" % expected)
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

    def test_reimport_builds_armature_and_skin(self):
        import bpy
        from mathutils import Vector

        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.context.scene.frame_start = 1
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=self.export_path), {"FINISHED"})
        armatures = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
        self.assertEqual(len(armatures), 1)
        armature = armatures[0]
        self.assertEqual(sorted(bone.name for bone in armature.data.bones), ["lower", "upper"])
        upper = armature.data.bones["upper"]
        self.assertEqual(upper.parent.name, "lower")
        self.assertLess((upper.head_local - Vector((0.0, 0.0, 1.0))).length, 1e-4, upper.head_local)
        self.assertLess((armature.data.bones["lower"].head_local - Vector((0.0, 0.0, 0.0))).length, 1e-4)

        meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
        self.assertEqual(len(meshes), 1, [obj.name for obj in meshes])
        skin = meshes[0]
        self.assertEqual(skin.parent, armature)
        self.assertEqual(len(skin.data.vertices), self.vertex_count)
        self.assertEqual(sorted(group.name for group in skin.vertex_groups), ["lower", "upper"])
        self.assertTrue(any(m.type == "ARMATURE" and m.object == armature for m in skin.modifiers))
        self.assertEqual(skin.data.materials[0].name, "MA_Skin")
        weighted = sum(1 for v in skin.data.vertices if v.groups)
        self.assertEqual(weighted, self.vertex_count)

        # the posed keyframe comes back on the upper bone: 60 degrees about the bone's rest X
        self.assertIsNotNone(armature.animation_data)
        scene = bpy.context.scene
        scene.frame_set(24)
        bpy.context.view_layer.update()
        pose_upper = armature.pose.bones["upper"]
        axis, angle = pose_upper.rotation_quaternion.to_axis_angle()
        self.assertAlmostEqual(abs(angle), 1.0472, places=2)
        scene.frame_set(1)
        bpy.context.view_layer.update()
        axis, angle = armature.pose.bones["upper"].rotation_quaternion.to_axis_angle()
        self.assertAlmostEqual(abs(angle), 0.0, places=3)
        # the deformed tip of the arm actually moves between the two frames
        depsgraph = bpy.context.evaluated_depsgraph_get()
        tip_index = max(range(self.vertex_count), key=lambda i: skin.data.vertices[i].co.z)
        start_tip = (skin.evaluated_get(depsgraph).matrix_world @ skin.evaluated_get(depsgraph).data.vertices[tip_index].co).copy()
        scene.frame_set(24)
        depsgraph = bpy.context.evaluated_depsgraph_get()
        end_tip = skin.evaluated_get(depsgraph).matrix_world @ skin.evaluated_get(depsgraph).data.vertices[tip_index].co
        self.assertGreater((end_tip - start_tip).length, 0.5, (start_tip, end_tip))


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class GaussianSplatRoundTripTests(unittest.TestCase):
    """Splat mesh -> X3D 4.1 GaussianSplats -> splat mesh, and the 4.0 PointSet fallback."""

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="x3d_splats_")
        _register_extension(cls.tmpdir)
        if str(TOOLS_DIR) not in sys.path:
            sys.path.insert(0, str(TOOLS_DIR))
        import bpy
        from splat_fixture import build_splat_fixture

        bpy.ops.wm.read_factory_settings(use_empty=True)
        cls.fixture = build_splat_fixture(count=40)
        cls.splats = cls.fixture["splats"]
        bpy.context.view_layer.update()
        cls.helix_world = cls.fixture["helix"].matrix_world.copy()
        cls.export_path = os.path.join(cls.tmpdir, "splats.x3d")
        result = bpy.ops.export_scene.x3d(filepath=cls.export_path, x3d_version="X3D41", use_selection=False)
        assert result == {"FINISHED"}, result
        cls.root = ET.parse(cls.export_path).getroot()
        cls.fallback_path = os.path.join(cls.tmpdir, "splats40.x3d")
        result = bpy.ops.export_scene.x3d(filepath=cls.fallback_path, x3d_version="X3D40", use_selection=False)
        assert result == {"FINISHED"}, result

    def test_document_is_x3d41_and_validates(self):
        sys.path.insert(0, str(SOURCE_DIR))
        from validate import validate_xml_file, validate_with_x3d_py

        self.assertEqual(self.root.attrib["version"], "4.1")
        self.assertIsNotNone(self.root.find("head/component[@name='GaussianSplats']"))
        self.assertTrue(validate_xml_file(self.export_path).valid)
        semantic = validate_with_x3d_py(self.export_path)
        if semantic is not None:
            self.assertTrue(semantic.valid, semantic.errors)
            if os.environ.get("X3D_STRICT_VALIDATION"):
                self.assertEqual(semantic.warnings, [])

    def test_node_carries_every_splat_field(self):
        node = self.root.find(".//GaussianSplats")
        self.assertIsNotNone(node)
        count = len(self.splats)
        self.assertEqual(len(node.attrib["positions"].split()), 3 * count)
        self.assertEqual(len(node.attrib["scales"].split()), 3 * count)
        self.assertEqual(len(node.attrib["orientations"].split()), 4 * count)
        self.assertEqual(len(node.attrib["opacities"].split()), count)
        self.assertEqual(len(node.attrib["sphericalHarmonicsDegree0Coef0"].split()), 3 * count)
        self.assertEqual(len(node.attrib["sphericalHarmonicsDegree1Coef2"].split()), 3 * count)
        self.assertNotIn("sphericalHarmonicsDegree2Coef0", node.attrib)
        # the quaternion of the last splat: twist about Z by half of 4 pi
        qx, qy, qz, qw = [float(v) for v in node.attrib["orientations"].split()[-4:]]
        self.assertAlmostEqual(qx, 0.0, places=5)
        self.assertAlmostEqual(abs(qz * qz + qw * qw), 1.0, places=4)

    def test_x3d40_fallback_is_pointset(self):
        root = ET.parse(self.fallback_path).getroot()
        self.assertIsNone(root.find(".//GaussianSplats"))
        point_set = root.find(".//PointSet")
        self.assertIsNotNone(point_set)
        self.assertEqual(len(point_set.find("Coordinate").attrib["point"].split()), 3 * len(self.splats))
        self.assertIsNotNone(point_set.find("ColorRGBA"))
        self.assertTrue(any("PointSet" in (m.attrib.get("content") or "") for m in root.findall("head/meta")))

    def test_reimport_restores_splat_attributes(self):
        import bpy

        _force_splat_import(self, "mesh")
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=self.export_path), {"FINISHED"})
        helix = bpy.context.scene.objects.get("Helix")
        self.assertIsNotNone(helix, [o.name for o in bpy.context.scene.objects])
        mesh = helix.data
        self.assertTrue(mesh.get("x3d_gaussian_splats"))
        self.assertEqual(len(mesh.vertices), len(self.splats))
        self.assertEqual(len(mesh.polygons), 0)
        for name in ("splat_scale", "splat_rotation", "splat_opacity", "splat_sh0_0", "splat_sh1_0", "splat_sh1_2", "Color"):
            self.assertIn(name, mesh.attributes.keys(), name)
        for a, b in zip(helix.matrix_world.translation, self.helix_world.translation):
            self.assertAlmostEqual(a, b, places=4)
        last = len(self.splats) - 1
        scale = mesh.attributes["splat_scale"].data[last].vector
        for a, b in zip(scale, self.splats.scales[last]):
            self.assertAlmostEqual(a, b, places=4)
        w, x, y, z = mesh.attributes["splat_rotation"].data[last].value
        ex, ey, ez, ew = self.splats.orientations[last]
        self.assertAlmostEqual(abs(w * ew + x * ex + y * ey + z * ez), 1.0, places=4)
        self.assertAlmostEqual(mesh.attributes["splat_opacity"].data[last].value, self.splats.opacities[last], places=4)
        self.assertEqual(mesh.color_attributes.active_color.name, "Color")

        # and the imported mesh exports again as the same node (second generation)
        again = os.path.join(self.tmpdir, "splats_again.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=again, x3d_version="X3D41", use_selection=False), {"FINISHED"})
        node = ET.parse(again).getroot().find(".//GaussianSplats")
        self.assertEqual(len(node.attrib["opacities"].split()), len(self.splats))


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class LargeSplatRoundTripTests(unittest.TestCase):
    """20,000 degree-3 splats: export then import gives back the same float32 bits.

    Guards two defects: Expat 2.6+ deferring a multi-megabyte start tag past
    the point where minidom stops reading (the node imported as nothing), and
    %.6f text rounding small scales to zero.
    """

    COUNT = 20000

    @classmethod
    def setUpClass(cls):
        import numpy as np

        cls.tmpdir = tempfile.mkdtemp(prefix="x3d_bigsplats_")
        _register_extension(cls.tmpdir)
        import bpy

        bpy.ops.wm.read_factory_settings(use_empty=True)
        rng = np.random.default_rng(3)
        n = cls.COUNT
        quats = rng.standard_normal((n, 4)).astype(np.float32)
        quats /= np.linalg.norm(quats, axis=1, keepdims=True)
        cls.data = {
            "co": rng.uniform(-20, 20, (n, 3)).astype(np.float32),
            "splat_scale": (10.0 ** rng.uniform(-5, 0.5, (n, 3))).astype(np.float32),
            "splat_rotation": quats,  # w x y z, as Blender stores quaternions
            "splat_opacity": rng.uniform(0, 1, n).astype(np.float32),
        }
        mesh = bpy.data.meshes.new("BigCloud")
        mesh.vertices.add(n)
        mesh.vertices.foreach_set("co", cls.data["co"].ravel())
        mesh["x3d_gaussian_splats"] = True
        mesh.attributes.new("splat_scale", "FLOAT_VECTOR", "POINT").data.foreach_set("vector", cls.data["splat_scale"].ravel())
        mesh.attributes.new("splat_rotation", "QUATERNION", "POINT").data.foreach_set("value", quats.ravel())
        mesh.attributes.new("splat_opacity", "FLOAT", "POINT").data.foreach_set("value", cls.data["splat_opacity"])
        for degree in range(4):
            for coef in range(2 * degree + 1):
                name = f"splat_sh{degree}_{coef}"
                cls.data[name] = rng.standard_normal((n, 3)).astype(np.float32) * (0.5 ** degree)
                mesh.attributes.new(name, "FLOAT_VECTOR", "POINT").data.foreach_set("vector", cls.data[name].ravel())
        mesh.update()
        bpy.context.scene.collection.objects.link(bpy.data.objects.new("BigCloud", mesh))
        cls.path = os.path.join(cls.tmpdir, "big.x3d")
        result = bpy.ops.export_scene.x3d(filepath=cls.path, x3d_version="X3D41", use_selection=False)
        assert result == {"FINISHED"}, result

    def test_file_is_past_the_old_parser_limit(self):
        self.assertGreater(os.path.getsize(self.path), 4_000_000)

    def test_reimport_is_bit_exact(self):
        import bpy
        import numpy as np

        _force_splat_import(self, "mesh")
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=self.path), {"FINISHED"})
        obj = bpy.context.scene.objects.get("BigCloud")
        self.assertIsNotNone(obj, [o.name for o in bpy.context.scene.objects])
        mesh = obj.data
        n = self.COUNT
        self.assertEqual(len(mesh.vertices), n)

        def read(name, width, key):
            out = np.empty(n * width, dtype=np.float32)
            if name == "co":
                mesh.vertices.foreach_get("co", out)
            else:
                mesh.attributes[name].data.foreach_get(key, out)
            return out.reshape(n, width) if width > 1 else out

        np.testing.assert_array_equal(read("co", 3, None), self.data["co"])
        np.testing.assert_array_equal(read("splat_scale", 3, "vector"), self.data["splat_scale"])
        np.testing.assert_array_equal(read("splat_opacity", 1, "value"), self.data["splat_opacity"])
        np.testing.assert_array_equal(read("splat_rotation", 4, "value"), self.data["splat_rotation"])
        for degree in range(4):
            for coef in range(2 * degree + 1):
                name = f"splat_sh{degree}_{coef}"
                np.testing.assert_array_equal(read(name, 3, "vector"), self.data[name], err_msg=name)

    def test_import_unit_scale_applies_to_splat_scales(self):
        import bpy
        import numpy as np

        _force_splat_import(self, "mesh")
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=self.path, global_scale=0.01), {"FINISHED"})
        mesh = bpy.context.scene.objects["BigCloud"].data
        n = self.COUNT
        co = np.empty(3 * n, dtype=np.float32)
        mesh.vertices.foreach_get("co", co)
        scale = np.empty(3 * n, dtype=np.float32)
        mesh.attributes["splat_scale"].data.foreach_get("vector", scale)
        # a Gaussian's extent is a length: it shrinks with the spacing between splats
        np.testing.assert_allclose(co, self.data["co"].ravel() * 0.01, rtol=1e-5, atol=1e-7)
        np.testing.assert_allclose(scale, self.data["splat_scale"].ravel() * 0.01, rtol=1e-5)


def _pointcloud_resizable() -> bool:
    return HAVE_BPY and "resize" in bpy.types.PointCloud.bl_rna.functions


@unittest.skipUnless(_pointcloud_resizable(), "needs bpy with PointCloud.resize (Blender 5.1+)")
class NativeSplatPointCloudTests(unittest.TestCase):
    """Blender's native splat PointCloud (5.3 layout) -> X3D 4.1 GaussianSplats -> PointCloud."""

    DEGREE = 3

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="x3d_native_splats_")
        _register_extension(cls.tmpdir)
        for path in (str(TOOLS_DIR), str(SOURCE_DIR)):
            if path not in sys.path:
                sys.path.insert(0, path)
        import bpy
        from splat_fixture import helix_splats
        from splat_native import build_native_splat_pointcloud

        splats = helix_splats(24, sh_degree=1)
        count = len(splats.positions)
        for degree in (2, 3):  # fill degrees 2 and 3 so every radiance:sh_ index 0..14 is exercised
            for coef in range(2 * degree + 1):
                splats.sh[(degree, coef)] = [(0.01 * degree, 0.001 * coef, -0.002 * i) for i in range(count)]
        cls.splats = splats
        bpy.ops.wm.read_factory_settings(use_empty=True)
        # the same layout Blender 5.3's PLY / SPZ / glTF / USD splat importers produce
        pointcloud = build_native_splat_pointcloud("NativeSplats", splats)
        obj = bpy.data.objects.new("Native", pointcloud)
        obj.location = (0.5, 0.0, 1.0)
        bpy.context.scene.collection.objects.link(obj)
        bpy.context.view_layer.update()
        cls.world = obj.matrix_world.copy()
        cls.export_path = os.path.join(cls.tmpdir, "native.x3d")
        result = bpy.ops.export_scene.x3d(filepath=cls.export_path, x3d_version="X3D41", use_selection=False)
        assert result == {"FINISHED"}, result
        cls.node = ET.parse(cls.export_path).getroot().find(".//GaussianSplats")

    @staticmethod
    def _floats(node, field):
        return [float(v) for v in node.attrib[field].split()]

    def test_pointcloud_layout_matches_blender_53(self):
        import bpy
        from splat_native import pointcloud_type_supported

        pointcloud = bpy.data.pointclouds["NativeSplats"]
        names = set(pointcloud.attributes.keys())
        self.assertLessEqual({"position", "scale", "rotation", "radiance:base"}, names)
        self.assertLessEqual({f"radiance:sh_{i}" for i in range(15)}, names)
        # FLOAT4 exists from Blender 5.2; 4.5 and 5.1 fall back to a four-channel colour
        expected = "FLOAT4" if bpy.app.version >= (5, 2, 0) else "FLOAT_COLOR"
        self.assertEqual(pointcloud.attributes["radiance:base"].data_type, expected)
        self.assertEqual(pointcloud.attributes["rotation"].data_type, "QUATERNION")
        if pointcloud_type_supported():
            self.assertEqual(pointcloud.type, "GAUSSIAN_SPLAT")

    def test_export_writes_every_field(self):
        self.assertIsNotNone(self.node)
        count = len(self.splats.positions)
        self.assertEqual(len(self._floats(self.node, "positions")), 3 * count)
        self.assertEqual(len(self._floats(self.node, "opacities")), count)
        for degree in range(self.DEGREE + 1):
            for coef in range(2 * degree + 1):
                field = f"sphericalHarmonicsDegree{degree}Coef{coef}"
                self.assertEqual(len(self._floats(self.node, field)), 3 * count, field)
        # quaternions leave Blender's (w, x, y, z) as X3D's (x, y, z, w)
        orientations = self._floats(self.node, "orientations")
        for i in (0, count // 2, count - 1):
            for a, b in zip(orientations[4 * i:4 * i + 4], self.splats.orientations[i]):
                self.assertAlmostEqual(a, b, places=5)
        opacities = self._floats(self.node, "opacities")
        for a, b in zip(opacities, self.splats.opacities):
            self.assertAlmostEqual(a, b, places=5)
        last = self._floats(self.node, "sphericalHarmonicsDegree3Coef6")[-3:]
        for a, b in zip(last, self.splats.sh[(3, 6)][-1]):
            self.assertAlmostEqual(a, b, places=5)

    def test_export_validates(self):
        from validate import validate_xml_file

        self.assertTrue(validate_xml_file(self.export_path).valid)

    def test_import_as_pointcloud_and_reexport_is_identical(self):
        import bpy

        _force_splat_import(self, "pointcloud")
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=self.export_path), {"FINISHED"})
        native = next((o for o in bpy.context.scene.objects if o.type == "POINTCLOUD"), None)
        self.assertIsNotNone(native, [(o.name, o.type) for o in bpy.context.scene.objects])
        self.assertEqual(len(native.data.points), len(self.splats.positions))
        self.assertIn("radiance:sh_14", native.data.attributes.keys())
        for a, b in zip(native.matrix_world.translation, self.world.translation):
            self.assertAlmostEqual(a, b, places=4)
        again = os.path.join(self.tmpdir, "native_again.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=again, x3d_version="X3D41", use_selection=False), {"FINISHED"})
        node = ET.parse(again).getroot().find(".//GaussianSplats")
        for field, value in self.node.attrib.items():
            if field in ("DEF", "USE"):
                continue
            first, second = value.split(), node.attrib.get(field, "").split()
            self.assertEqual(len(first), len(second), field)
            try:
                for a, b in zip(first, second):
                    self.assertAlmostEqual(float(a), float(b), places=5, msg=field)
            except ValueError:
                self.assertEqual(first, second, field)


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class InlineBridgeRoundTripTests(unittest.TestCase):
    """Inline of X3D, glTF and splat files: imported under a placeholder empty, exported back as Inline."""

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="x3d_inline_")
        _register_extension(cls.tmpdir)
        if str(TOOLS_DIR) not in sys.path:
            sys.path.insert(0, str(TOOLS_DIR))
        if str(SOURCE_DIR) not in sys.path:
            sys.path.insert(0, str(SOURCE_DIR))
        import bpy
        from splat_fixture import helix_splats
        from splat_io import write_ply

        # 1. a child X3D file with one cube
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.0, 0.0, 0.0))
        bpy.context.active_object.name = "Part"
        cls.part_path = os.path.join(cls.tmpdir, "part.x3d")
        assert bpy.ops.export_scene.x3d(filepath=cls.part_path, x3d_version="X3D40", use_selection=False) == {"FINISHED"}
        # 2. a glb with one cube one unit up
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.0, 0.0, 1.0))
        bpy.context.active_object.name = "Wheel"
        cls.glb_path = os.path.join(cls.tmpdir, "wheel.glb")
        assert bpy.ops.export_scene.gltf(filepath=cls.glb_path, export_format="GLB") == {"FINISHED"}
        # 3. a splat PLY
        cls.ply_path = os.path.join(cls.tmpdir, "cloud.ply")
        cls.cloud = helix_splats(16, sh_degree=0)
        write_ply(cls.ply_path, cls.cloud)

        # the master scene: three placeholder empties referencing the files
        bpy.ops.wm.read_factory_settings(use_empty=True)
        cls.placements = {}
        for name, url, location in (("PartRef", "part.x3d", (3.0, 0.0, 0.0)),
                                     ("WheelRef", "wheel.glb", (0.0, 3.0, 0.0)),
                                     ("CloudRef", "cloud.ply", (0.0, 0.0, 3.0))):
            empty = bpy.data.objects.new(name, None)
            empty.location = location
            empty.rotation_euler = (0.0, 0.0, 0.5)
            empty["x3d_inline_url"] = url
            bpy.context.scene.collection.objects.link(empty)
            bpy.context.view_layer.update()
            cls.placements[name] = empty.matrix_world.copy()
        cls.master_path = os.path.join(cls.tmpdir, "master.x3d")
        assert bpy.ops.export_scene.x3d(filepath=cls.master_path, x3d_version="X3D40", use_selection=False) == {"FINISHED"}
        cls.root = ET.parse(cls.master_path).getroot()

    def test_master_has_three_inlines_and_validates(self):
        from validate import validate_xml_file, validate_with_x3d_py

        inlines = self.root.findall(".//Inline")
        self.assertEqual(sorted(i.attrib["url"] for i in inlines), ['"cloud.ply"', '"part.x3d"', '"wheel.glb"'])
        self.assertTrue(validate_xml_file(self.master_path).valid)
        semantic = validate_with_x3d_py(self.master_path)
        if semantic is not None:
            self.assertTrue(semantic.valid, semantic.errors)

    def test_import_loads_assets_under_placeholders(self):
        import bpy
        from mathutils import Vector

        _force_splat_import(self, "mesh")
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=self.master_path), {"FINISHED"})
        objects = bpy.context.scene.objects
        for name in ("PartRef", "WheelRef", "CloudRef"):
            empty = objects.get(name)
            self.assertIsNotNone(empty, [o.name for o in objects])
            self.assertEqual(empty.type, "EMPTY")
            self.assertIn("x3d_inline_url", empty.keys())
            for a, b in zip(empty.matrix_world.translation, self.placements[name].translation):
                self.assertAlmostEqual(a, b, places=4)

        bpy.context.view_layer.update()
        part = next((o for o in objects if o.type == "MESH" and o.parent is not None and o.parent.name == "PartRef"), None)
        self.assertIsNotNone(part, [(o.name, o.parent and o.parent.name) for o in objects])
        self.assertEqual(len(part.data.polygons), 6)
        self.assertEqual(part.get("x3d_inline_source"), "part.x3d")
        self.assertLess((part.matrix_world.translation - Vector((3.0, 0.0, 0.0))).length, 1e-3)

        wheel = next((o for o in objects if o.type == "MESH" and o.parent is not None and o.parent.name == "WheelRef"), None)
        self.assertIsNotNone(wheel, [(o.name, o.parent and o.parent.name) for o in objects])
        self.assertIn(len(wheel.data.vertices), (8, 24))  # glTF may keep per-normal splits
        # the glb cube sat one unit up in Blender; it must land one unit above the WheelRef empty
        expected = self.placements["WheelRef"] @ Vector((0.0, 0.0, 1.0))
        centre = wheel.matrix_world @ (sum((v.co for v in wheel.data.vertices), Vector()) / 8.0)
        self.assertLess((centre - expected).length, 1e-3, (centre, expected))

        cloud = next((o for o in objects if o.type == "MESH" and o.parent is not None and o.parent.name == "CloudRef"), None)
        self.assertIsNotNone(cloud)
        self.assertTrue(cloud.data.get("x3d_gaussian_splats"))
        self.assertEqual(len(cloud.data.vertices), len(self.cloud))
        self.assertIn("splat_opacity", cloud.data.attributes.keys())

        # re-export: the loaded content stays behind the Inline references
        again = os.path.join(self.tmpdir, "master_again.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=again, x3d_version="X3D40", use_selection=False), {"FINISHED"})
        root = ET.parse(again).getroot()
        self.assertEqual(len(root.findall(".//Inline")), 3)
        self.assertEqual(len(root.findall(".//IndexedFaceSet")), 0)
        self.assertEqual(len(root.findall(".//PointSet")), 0)

    def test_self_inline_is_refused(self):
        import bpy

        looped = os.path.join(self.tmpdir, "loop.x3d")
        Path(looped).write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n<X3D version="4.0" profile="Immersive"><Scene>'
            "<Transform DEF=\"OB_Loop\"><Inline url='\"loop.x3d\"' /></Transform></Scene></X3D>\n",
            encoding="utf-8",
        )
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=looped), {"FINISHED"})
        empties = [o for o in bpy.context.scene.objects if o.type == "EMPTY"]
        self.assertEqual(len(empties), 1)



@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class WorldBackgroundExportTests(unittest.TestCase):
    """The X3D Background takes the colour the render shows: the world's node-tree Background, not World.color."""

    def test_background_follows_world_nodes(self):
        tmpdir = tempfile.mkdtemp(prefix="x3d_world_")
        _register_extension(tmpdir)
        import bpy

        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.mesh.primitive_cube_add(size=1.0)
        world = bpy.data.worlds.new("Night")
        bpy.context.scene.world = world
        world.use_nodes = True
        background = world.node_tree.nodes["Background"]
        background.inputs["Color"].default_value = (0.02, 0.01, 0.04, 1.0)
        background.inputs["Strength"].default_value = 2.0
        world.color = (0.5, 0.5, 0.5)
        path = os.path.join(tmpdir, "world.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=path, x3d_version="X3D40", use_selection=False), {"FINISHED"})
        sky = ET.parse(path).getroot().find("Scene/Background").attrib["skyColor"]
        self.assertEqual([round(float(v), 4) for v in sky.split()], [0.04, 0.02, 0.08])


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class LightEnergyRoundTripTests(unittest.TestCase):
    """Light strength survives export then import: point and spot divide by 1.75 out and multiply back in,
    sun is written unscaled on both export paths. X3D 4.0 sets no upper limit on intensity, so strong lights
    survive there; the X3D 3.x schemas limit intensity to [0, 1], so that path clamps at 1.75 (1.0 for sun)."""

    ENERGIES = {"POINT": 1.05, "SPOT": 0.7, "SUN": 0.6}
    # 1.067 is the campus Sun of the earth-twin scene that came back as 1.0
    BRIGHT = {"POINT": 3.5, "SPOT": 2.1, "SUN": 1.067}

    def _round_trip(self, version: str, energies=None):
        tmpdir = tempfile.mkdtemp(prefix="x3d_light_")
        _register_extension(tmpdir)
        import bpy

        bpy.ops.wm.read_factory_settings(use_empty=True)
        for kind, energy in (energies or self.ENERGIES).items():
            data = bpy.data.lights.new(kind.title(), kind)
            data.energy = energy
            bpy.context.scene.collection.objects.link(bpy.data.objects.new(kind.title(), data))
        path = os.path.join(tmpdir, "lights_%s.x3d" % version)
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=path, x3d_version=version, use_selection=False), {"FINISHED"})
        root = ET.parse(path).getroot()
        written = {tag: float(root.find(".//%s" % tag).attrib["intensity"])
                   for tag in ("PointLight", "SpotLight", "DirectionalLight")}
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=path), {"FINISHED"})
        back = {obj.data.type: obj.data.energy for obj in bpy.context.scene.objects if obj.type == "LIGHT"}
        return written, back

    def _check(self, version: str):
        written, back = self._round_trip(version)
        self.assertAlmostEqual(written["PointLight"], 1.05 / 1.75, places=3)
        self.assertAlmostEqual(written["SpotLight"], 0.7 / 1.75, places=3)
        self.assertAlmostEqual(written["DirectionalLight"], 0.6, places=3)
        for kind, energy in self.ENERGIES.items():
            self.assertAlmostEqual(back[kind], energy, places=3, msg="%s energy via %s" % (kind, version))

    def test_x3d40_path(self):
        self._check("X3D40")

    def test_legacy_path(self):
        self._check("X3D33")

    def test_x3d40_keeps_intensity_above_one(self):
        written, back = self._round_trip("X3D40", self.BRIGHT)
        self.assertAlmostEqual(written["PointLight"], 2.0, places=5)
        self.assertAlmostEqual(written["SpotLight"], 1.2, places=5)
        self.assertAlmostEqual(written["DirectionalLight"], 1.067, places=5)
        for kind, energy in self.BRIGHT.items():
            self.assertAlmostEqual(back[kind], energy, places=4, msg="%s energy via X3D40" % kind)

    def test_legacy_path_clamps_intensity_to_one(self):
        written, back = self._round_trip("X3D33", self.BRIGHT)
        self.assertEqual(written, {"PointLight": 1.0, "SpotLight": 1.0, "DirectionalLight": 1.0})
        self.assertAlmostEqual(back["SUN"], 1.0, places=4)
        self.assertAlmostEqual(back["POINT"], 1.75, places=4)


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class ExportImportExportTests(unittest.TestCase):
    """Export, import and export again for every fixture, comparing the node inventory of the two files.

    Generation two must equal generation three (the pair is a fixed point). Generation one may lose the nodes
    in KNOWN_LOSSES, which the importer maps to something else today (vertex colours and normals, UnlitMaterial as a Principled
    material, the Background node, one extra Transform per shared-mesh object); any other difference is a regression.
    Importing every fixture twice in one session also guards the importer's texture and material caches."""

    KNOWN_LOSSES = {
        "swatch": {"ColorRGBA", "Normal", "PhysicalMaterial", "UnlitMaterial", "Coordinate", "TextureCoordinate",
                   "Transform", "meta"},
        "scene": {"PhysicalMaterial", "Transform", "Background"},
        "hanim": set(),
        "splat": set(),
    }

    @classmethod
    def setUpClass(cls):
        if str(TOOLS_DIR) not in sys.path:
            sys.path.insert(0, str(TOOLS_DIR))

    @staticmethod
    def _inventory(path):
        from collections import Counter
        return Counter(element.tag for element in ET.parse(path).getroot().iter())

    def _check(self, name, build, version, **export_kwargs):
        tmpdir = tempfile.mkdtemp(prefix="x3d_eie_")
        _register_extension(tmpdir)
        if str(TOOLS_DIR) not in sys.path:
            sys.path.insert(0, str(TOOLS_DIR))
        import bpy

        bpy.ops.wm.read_factory_settings(use_empty=True)
        build(tmpdir)
        inventories = []
        for generation in range(3):
            path = os.path.join(tmpdir, "%s_%d.x3d" % (name, generation))
            self.assertEqual(
                bpy.ops.export_scene.x3d(filepath=path, x3d_version=version, use_selection=False, **export_kwargs),
                {"FINISHED"})
            inventories.append(self._inventory(path))
            bpy.ops.wm.read_factory_settings(use_empty=True)
            self.assertEqual(bpy.ops.import_scene.x3d(filepath=path), {"FINISHED"})
        first, second, third = inventories
        self.assertEqual(second, third, "%s: generation 2 and 3 differ" % name)
        changed = {tag for tag in set(first) | set(second) if first[tag] != second[tag]}
        self.assertLessEqual(changed, self.KNOWN_LOSSES[name], "%s: unexpected change in %s" % (
            name, sorted(changed - self.KNOWN_LOSSES[name])))

    def test_swatch_book(self):
        from swatch_book import build_swatch_book
        self._check("swatch", lambda tmpdir: build_swatch_book(texture_dir=tmpdir), "X3D40", use_normals=True)

    def test_scene_fixture(self):
        from scene_fixture import build_scene_fixture
        self._check("scene", lambda tmpdir: build_scene_fixture(), "X3D40", use_hierarchy=True, use_animation=True)

    def test_hanim_fixture(self):
        from hanim_fixture import build_hanim_fixture
        self._check("hanim", lambda tmpdir: build_hanim_fixture(), "X3D40", use_animation=True)

    def test_splat_fixture(self):
        from splat_fixture import build_splat_fixture
        self._check("splat", lambda tmpdir: build_splat_fixture(count=40), "X3D41")


if __name__ == "__main__":
    unittest.main()
