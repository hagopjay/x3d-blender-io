# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The import keeps the file's Transform hierarchy (import option keep_hierarchy, on by default).

Before, every object came in at its world matrix with no parent: positions were right, but an articulated model came
apart into loose parts, a parent's own animation had nowhere to live (it was baked into each child's world keys), and
the re-export wrote the scene flat. Now each Transform has one Blender object (its only object, an Empty for several or
none, or the export's material parts of one mesh joined back) and objects are parented as the Transforms nest.

Expected positions come from the X3D text, not from Blender. Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_import_hierarchy_bpy
"""

from __future__ import annotations

import math
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET

try:
    import bpy  # noqa: F401
    from mathutils import Matrix, Vector
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

from test_roundtrip_bpy import _register_extension

QUAD = '<IndexedFaceSet coordIndex="0 1 2 3 -1"><Coordinate point="0 0 0 1 0 0 1 1 0 0 1 0"/></IndexedFaceSet>'


def _shape(material="0.5 0.5 0.5", geometry=QUAD):
    return f'<Shape><Appearance><PhysicalMaterial baseColor="{material}"/></Appearance>{geometry}</Shape>'


CHAIN_DOC = ('<X3D version="4.0"><Scene>'
             '<Transform DEF="OB_Base" translation="1 0 0">' + _shape() +
             '<Transform DEF="OB_Arm" translation="0 2 0" rotation="0 0 1 0.5">' + _shape() +
             '<Transform DEF="OB_Hand" translation="0 3 0" scale="2 2 2">' + _shape() +
             '</Transform></Transform></Transform>'
             '<Transform DEF="OB_Pivot" translation="0 0 5"/>'
             '</Scene></X3D>')

GROUPED_DOC = ('<X3D version="4.0"><Scene><Transform DEF="Car" translation="4 0 0">'
               '<Shape DEF="Body"><Appearance><PhysicalMaterial/></Appearance>' + QUAD.replace('<IndexedFaceSet', '<IndexedFaceSet DEF="BodyGeo"') + '</Shape>'
               '<Shape DEF="Wheel"><Appearance><PhysicalMaterial/></Appearance>' + QUAD.replace('<IndexedFaceSet', '<IndexedFaceSet DEF="WheelGeo"') + '</Shape>'
               '</Transform></Scene></X3D>')

MULTI_DOC = ('<X3D version="4.0"><Scene><Transform DEF="OB_Two" translation="0 1 0">'
             '<Shape><Appearance DEF="APP_Red"><PhysicalMaterial DEF="MA_Red" baseColor="1 0 0"/></Appearance>'
             + QUAD.replace('<IndexedFaceSet', '<IndexedFaceSet DEF="ME_Two_m0"') + '</Shape>'
             '<Shape><Appearance DEF="APP_Blue"><PhysicalMaterial DEF="MA_Blue" baseColor="0 0 1"/></Appearance>'
             + QUAD.replace('<IndexedFaceSet', '<IndexedFaceSet DEF="ME_Two_m1"').replace('0 0 0 1 0 0 1 1 0 0 1 0', '2 0 0 3 0 0 3 1 0 2 1 0') + '</Shape>'
             '</Transform></Scene></X3D>')

ORBIT_DOC = ('<X3D version="4.0"><Scene>'
             '<Transform DEF="OB_Planet">' + _shape() +
             '<Transform DEF="OB_Moon" translation="5 0 0">' + _shape() + '</Transform></Transform>'
             '<TimeSensor DEF="Clock" cycleInterval="2" loop="true"/>'
             '<OrientationInterpolator DEF="Spin" key="0 0.5 1" keyValue="0 1 0 0 0 1 0 3.14159 0 1 0 6.28318"/>'
             '<ROUTE fromNode="Clock" fromField="fraction_changed" toNode="Spin" toField="set_fraction"/>'
             '<ROUTE fromNode="Spin" fromField="value_changed" toNode="OB_Planet" toField="set_rotation"/>'
             '</Scene></X3D>')

SHEAR_DOC = ('<X3D version="4.0"><Scene><Transform DEF="OB_Squash" scale="3 1 1">' + _shape() +
             '<Transform DEF="OB_Tilted" rotation="0 0 1 0.7853982">' + _shape() + '</Transform>'
             '</Transform></Scene></X3D>')


def _x3d_to_blender(v):
    """X3D is Y-up, Blender Z-up: the importer's default axis conversion."""
    return Vector((v[0], -v[2], v[1]))


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class ImportHierarchyTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addon = tempfile.TemporaryDirectory()
        _register_extension(cls.addon.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()
        cls.addon.cleanup()

    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def _import(self, name, text, **options):
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write('<?xml version="1.0" encoding="UTF-8"?>\n' + text)
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=path, **options), {"FINISHED"})
        bpy.context.view_layer.update()
        return path

    def _export(self, name, **options):
        path = os.path.join(self.tmp.name, name)
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=path, x3d_version="X3D40", use_selection=False,
                                                  use_hierarchy=True, **options), {"FINISHED"})
        return ET.parse(path).getroot()

    def _ob(self, name):
        return bpy.context.scene.objects[name]

    def test_nested_transforms_become_a_parent_chain(self):
        self._import("chain.x3d", CHAIN_DOC)
        self.assertIsNone(self._ob("Base").parent)
        self.assertEqual(self._ob("Arm").parent, self._ob("Base"))
        self.assertEqual(self._ob("Hand").parent, self._ob("Arm"))

    def test_parented_objects_keep_the_file_world_positions(self):
        self._import("chain.x3d", CHAIN_DOC)
        # Hand origin in X3D: Base (1,0,0) + Arm (0,2,0) + rotate(0.5 about z) applied to (0,3,0)
        c, s = math.cos(0.5), math.sin(0.5)
        expected = _x3d_to_blender((1 - 3 * s, 2 + 3 * c, 0))
        got = self._ob("Hand").matrix_world.translation
        self.assertLess((got - expected).length, 1e-5, (got, expected))
        self.assertAlmostEqual(self._ob("Hand").matrix_world.to_scale()[0], 2.0, places=5)

    def test_local_matrices_are_the_file_transforms(self):
        # the axis conversion sits on the root alone, so a child's location / rotation / scale are the file's numbers
        self._import("chain.x3d", CHAIN_DOC)
        arm, hand = self._ob("Arm"), self._ob("Hand")
        self.assertEqual(tuple(arm.matrix_parent_inverse), tuple(Matrix()))
        self.assertLess((arm.location - Vector((0, 2, 0))).length, 1e-6)
        self.assertAlmostEqual(arm.rotation_euler.z, 0.5, places=6)
        self.assertLess((hand.scale - Vector((2, 2, 2))).length, 1e-6)

    def test_an_exported_empty_comes_back_as_an_empty(self):
        self._import("chain.x3d", CHAIN_DOC)
        pivot = self._ob("Pivot")
        self.assertEqual(pivot.type, 'EMPTY')
        self.assertLess((pivot.matrix_world.translation - _x3d_to_blender((0, 0, 5))).length, 1e-6)

    def test_several_shapes_of_a_hand_written_transform_go_under_an_empty(self):
        self._import("car.x3d", GROUPED_DOC)
        car = self._ob("Car")
        self.assertEqual(car.type, 'EMPTY')
        self.assertEqual(sorted(child.name for child in car.children), ["Body", "Wheel"])

    def test_the_export_material_parts_join_into_one_object(self):
        self._import("two.x3d", MULTI_DOC)
        meshes = [ob for ob in bpy.context.scene.objects if ob.type == 'MESH']
        self.assertEqual([ob.name for ob in meshes], ["Two"])
        self.assertEqual([m.name for m in meshes[0].data.materials], ["Red", "Blue"])
        self.assertEqual(len(meshes[0].data.polygons), 2)

    def test_joined_parts_re_export_as_the_same_shapes(self):
        self._import("two.x3d", MULTI_DOC)
        root = self._export("two_again.x3d")
        transform = next(t for t in root.iter("Transform") if t.get("DEF") == "OB_Two")
        defs = sorted(g.get("DEF") for g in transform.iter("IndexedFaceSet"))
        self.assertEqual(defs, ["ME_Two_m0", "ME_Two_m1"])

    def test_a_parent_animation_lives_on_the_parent_only(self):
        self._import("orbit.x3d", ORBIT_DOC)
        planet, moon = self._ob("Planet"), self._ob("Moon")
        self.assertEqual(moon.parent, planet)
        self.assertIsNotNone(planet.animation_data and planet.animation_data.action)
        self.assertTrue(moon.animation_data is None or moon.animation_data.action is None)
        scene = bpy.context.scene
        half = scene.frame_start + round((scene.frame_end - scene.frame_start) / 2)
        scene.frame_set(half)
        # half a turn about X3D +Y: the moon at X3D (5,0,0) goes to (-5,0,0)
        self.assertLess((moon.matrix_world.translation - _x3d_to_blender((-5, 0, 0))).length, 1e-3)

    def test_a_round_trip_keeps_the_nesting(self):
        self._import("chain.x3d", CHAIN_DOC)
        root = self._export("chain_again.x3d")
        base = next(t for t in root.iter("Transform") if t.get("DEF") == "OB_Base")
        nested = [t.get("DEF") for t in base.iter("Transform")]
        self.assertEqual(nested, ["OB_Base", "OB_Arm", "OB_Hand"])

    def test_shear_from_the_parent_is_not_baked_into_the_child(self):
        self._import("shear.x3d", SHEAR_DOC)
        tilted = self._ob("Tilted")
        self.assertEqual(tilted.parent, self._ob("Squash"))
        # the mesh holds the file's points (Y-up; the axis conversion is on the root object)
        coords = sorted(tuple(round(c, 6) + 0.0 for c in v.co) for v in tilted.data.vertices)
        self.assertEqual(coords, sorted([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]))
        # world: scale 3 on X3D x after a 45 degree turn: vertex (1,0,0) -> (3 cos45, sin45, 0)
        world = sorted(tuple(round(c, 5) for c in tilted.matrix_world @ v.co) for v in tilted.data.vertices)
        r = math.sqrt(0.5)
        expected = sorted(tuple(round(c, 5) for c in _x3d_to_blender(p)) for p in
                          [(0, 0, 0), (3 * r, r, 0), (3 * r - 3 * r, r + r, 0), (-3 * r, r, 0)])
        self.assertEqual(world, expected)

    def test_shear_is_undone_when_an_inline_loads_later_in_the_file(self):
        # an Inline's own load used to wipe the parent file's record of baked meshes
        self._import("inner.x3d", '<X3D version="4.0"><Scene>' + _shape() + '</Scene></X3D>')
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self._import("shear_inline.x3d", SHEAR_DOC.replace('</Scene>', '<Inline url=\'"inner.x3d"\'/></Scene>'))
        tilted = self._ob("Tilted")
        self.assertEqual(tuple(tilted.matrix_parent_inverse), tuple(Matrix()))
        coords = sorted(tuple(round(c, 6) + 0.0 for c in v.co) for v in tilted.data.vertices)
        self.assertEqual(coords, sorted([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]))

    def test_flat_import_is_still_available(self):
        self._import("chain.x3d", CHAIN_DOC, keep_hierarchy=False)
        self.assertTrue(all(ob.parent is None for ob in bpy.context.scene.objects))
        c, s = math.cos(0.5), math.sin(0.5)
        expected = _x3d_to_blender((1 - 3 * s, 2 + 3 * c, 0))
        self.assertLess((self._ob("Hand").matrix_world.translation - expected).length, 1e-5)


if __name__ == "__main__":
    unittest.main()
