# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The scene-level flags an X3D import leaves (headlight, lighting model, colour space, Background, head meta, the
animation mark) describe the imported content; they stop applying to the export once that content is gone, and the next
import starts from a clean scene (review round 1, emitter F8).

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_export_stale_import_flags_bpy
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

HEAD = "<head><meta name='title' content='{title}'/></head>"
BOX = "<Shape><Appearance>{material}</Appearance><Box/></Shape>"
CLASSIC = "<Material diffuseColor='0.8 0.4 0.2'/>"
ANIMATION = ("<TimeSensor DEF='Clock' cycleInterval='2' loop='true'/>"
             "<PositionInterpolator DEF='Move' key='0 1' keyValue='0 0 0 1 0 0'/>"
             "<Transform DEF='Ball'><Shape><Box/></Shape></Transform>"
             "<ROUTE fromNode='Clock' fromField='fraction_changed' toNode='Move' toField='set_fraction'/>"
             "<ROUTE fromNode='Move' fromField='value_changed' toNode='Ball' toField='set_translation'/>")


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class StaleImportFlagTests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="x3d_stale_flags_")
        _register_extension(self.tmpdir)
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def _import(self, body, head="", **options):
        path = os.path.join(self.tmpdir, "in_%d.x3d" % len(os.listdir(self.tmpdir)))
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("<?xml version='1.0' encoding='UTF-8'?>\n<X3D profile='Immersive' version='4.0'>" + head
                         + "<Scene>\n" + body + "\n</Scene></X3D>\n")
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=path, **options), {"FINISHED"})

    def _export(self, **options):
        path = os.path.join(self.tmpdir, "out_%d.x3d" % len(os.listdir(self.tmpdir)))
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=path, x3d_version="X3D40", use_selection=False, **options),
                         {"FINISHED"})
        return ET.parse(path).getroot()

    @staticmethod
    def _delete_everything():
        for ob in list(bpy.data.objects):
            bpy.data.objects.remove(ob)

    @staticmethod
    def _blender_scene_with_a_light():
        bpy.ops.mesh.primitive_cube_add()
        bpy.context.object.data.materials.append(bpy.data.materials.new("Grey"))
        lamp = bpy.data.objects.new("Lamp", bpy.data.lights.new("Lamp", 'POINT'))
        bpy.context.scene.collection.objects.link(lamp)

    def test_a_stale_headlight_does_not_apply_to_a_scene_modelled_afterwards(self):
        # the file has no NavigationInfo: headlight on is recorded; a Blender scene with lights writes headlight false
        self._import(BOX.format(material=CLASSIC))
        self.assertIs(bpy.context.scene["x3d_headlight"], True)
        self.assertEqual(self._export().find(".//NavigationInfo").attrib["headlight"], "true")    # imported: as the file had it
        self._delete_everything()
        self._blender_scene_with_a_light()
        self.assertEqual(self._export().find(".//NavigationInfo").attrib["headlight"], "false")

    def test_a_stale_lighting_model_does_not_apply_either(self):
        self._import("<NavigationInfo headlight='false'/><PointLight location='0 0 5'/>" + BOX.format(material=CLASSIC))
        self.assertEqual(bpy.context.scene["x3d_lighting_model"], "classic")
        self._delete_everything()
        self._blender_scene_with_a_light()
        root = self._export()
        self.assertIsNotNone(root.find(".//PhysicalMaterial"))
        self.assertIsNone(root.find(".//Material"))

    def test_a_stale_colour_space_does_not_apply(self):
        from io_scene_x3d import extract
        self._import(BOX.format(material=CLASSIC), color_space='AS_IS')
        self.assertEqual(extract.resolve_export_colour_space(None, bpy.context.scene), 'AS_IS')
        self._delete_everything()
        self.assertEqual(extract.resolve_export_colour_space(None, bpy.context.scene), 'SRGB')

    def test_a_stale_background_and_head_meta_do_not_apply(self):
        from io_scene_x3d import extract
        self._import("<Background skyColor='1 0 0'/>" + BOX.format(material=CLASSIC), head=HEAD.format(title="First"))
        self.assertIsNotNone(extract.scene_background(bpy.context.scene))
        self.assertEqual(extract.scene_head_meta(bpy.context.scene), [("title", "First")])
        self._delete_everything()
        self.assertIsNone(extract.scene_background(bpy.context.scene))
        self.assertEqual(extract.scene_head_meta(bpy.context.scene), [])

    def test_the_next_import_does_not_inherit_what_the_earlier_file_set(self):
        from io_scene_x3d import extract
        self._import("<Background skyColor='1 0 0'/>" + ANIMATION + BOX.format(material=CLASSIC),
                     head=HEAD.format(title="First"))
        scene = bpy.context.scene
        self.assertTrue(scene["x3d_imported_animation"])
        self._delete_everything()
        self._import("<NavigationInfo headlight='false'/>" + BOX.format(material=CLASSIC))       # no Background, head or animation
        for key in ("x3d_background", "x3d_head_meta", "x3d_imported_animation"):
            self.assertNotIn(key, scene.keys(), key)
        self.assertIs(scene["x3d_headlight"], False)
        root = self._export()
        self.assertEqual(root.find(".//NavigationInfo").attrib["headlight"], "false")
        self.assertIsNone(root.find(".//TimeSensor"))
        self.assertNotIn("1 0 0", (root.find(".//Background").attrib.get("skyColor", "") if root.find(".//Background") is not None else ""))
        self.assertEqual(extract.scene_head_meta(scene), [])

    def test_the_animation_mark_does_not_turn_on_the_export_of_a_scene_keyframed_afterwards(self):
        from io_scene_x3d import _scene_imported_animation
        self._import(ANIMATION)
        self.assertTrue(_scene_imported_animation(bpy.context.scene))
        self.assertIsNotNone(self._export().find(".//TimeSensor"))
        self._delete_everything()
        bpy.ops.mesh.primitive_cube_add()
        cube = bpy.context.object
        cube.keyframe_insert("location", frame=1)
        cube.location.x = 3
        cube.keyframe_insert("location", frame=24)
        self.assertFalse(_scene_imported_animation(bpy.context.scene))
        self.assertIsNone(self._export().find(".//TimeSensor"))

    def test_the_flags_apply_while_any_imported_object_is_left(self):
        self._import("<NavigationInfo headlight='false'/>" + BOX.format(material=CLASSIC)
                     + "<Transform translation='3 0 0'>" + BOX.format(material=CLASSIC) + "</Transform>")
        meshes = [ob for ob in bpy.data.objects if ob.type == 'MESH']
        bpy.data.objects.remove(meshes[0])
        self.assertEqual(self._export().find(".//NavigationInfo").attrib["headlight"], "false")

    def test_lines_and_points_alone_still_count_as_imported_content(self):
        # an anonymous PointSet carries no DEF, primitive or solid record: the importer's own mark is what keeps it
        self._import("<NavigationInfo headlight='false'/><Shape><PointSet><Coordinate point='0 0 0 1 0 0 0 1 0'/></PointSet></Shape>")
        points = [ob for ob in bpy.data.objects if ob.type == 'MESH']
        self.assertEqual(len(points), 1)
        self.assertEqual(sorted(points[0].keys()), ["x3d_imported"])
        self.assertEqual(self._export().find(".//NavigationInfo").attrib["headlight"], "false")

    def test_a_file_imported_before_the_mark_existed_is_recognised_by_its_older_records(self):
        from io_scene_x3d import extract
        self._import("<NavigationInfo headlight='false'/>" + BOX.format(material=CLASSIC))
        for ob in bpy.data.objects:
            del ob["x3d_imported"]
        self.assertTrue(extract.scene_has_imported_content(bpy.context.scene))      # the Box mesh keeps x3d_primitive and x3d_solid
        self.assertEqual(self._export().find(".//NavigationInfo").attrib["headlight"], "false")


if __name__ == "__main__":
    unittest.main()
