# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""X3D 4.0 export of the NavigationInfo an imported scene had (round-trip audit D6, D2).

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_export_navigation_bpy
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

BOX = "<Shape><Appearance><Material diffuseColor='0.8 0.8 0.8'/></Appearance><Box/></Shape>"


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class ExportNavigationTests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="x3d_navigation_")
        _register_extension(self.tmpdir)
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def _import(self, body):
        path = os.path.join(self.tmpdir, "in.x3d")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("<?xml version='1.0' encoding='UTF-8'?>\n<X3D profile='Immersive' version='4.0'><Scene>\n"
                         + body + "\n</Scene></X3D>\n")
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=path), {"FINISHED"})

    def _export(self):
        path = os.path.join(self.tmpdir, "out_%d.x3d" % len(os.listdir(self.tmpdir)))
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=path, x3d_version="X3D40", use_selection=False),
                         {"FINISHED"})
        return ET.parse(path).getroot()

    def test_headlight_default_with_lights_comes_back_on(self):
        # no NavigationInfo: X3D's headlight is on, whatever lights the file has (D6: the export wrote false)
        self._import("<PointLight location='0 0 3' global='true'/>" + BOX)
        self.assertIs(bpy.context.scene["x3d_headlight"], True)
        self.assertEqual(self._export().find(".//NavigationInfo").attrib["headlight"], "true")

    def test_headlight_off_without_lights_comes_back_off(self):
        self._import("<NavigationInfo headlight='false'/>" + BOX)
        self.assertIs(bpy.context.scene["x3d_headlight"], False)
        self.assertEqual(self._export().find(".//NavigationInfo").attrib["headlight"], "false")

    def test_a_scene_made_in_blender_has_no_headlight_when_it_has_lights(self):
        bpy.ops.mesh.primitive_cube_add()
        light = bpy.data.objects.new("Lamp", bpy.data.lights.new("Lamp", 'POINT'))
        bpy.context.scene.collection.objects.link(light)
        self.assertEqual(self._export().find(".//NavigationInfo").attrib["headlight"], "false")

    def test_planet_scale_geo_viewpoint_keeps_its_clip_range(self):
        # D2: GeoViewpoint 2.5e7 m above a 6.4e6 m globe; X_ITE 16.7.1 draws out to 1e5 at most without a farDistance
        self._import("<GeoViewpoint description='Globe' geoSystem='\"GD\" \"WE\"' position='20 -40 25000000' "
                     "orientation='1 0 0 -1.5708' fieldOfView='0.6'/>" + BOX)
        viewpoint = self._export().find(".//Viewpoint")
        near, far = float(viewpoint.attrib["nearDistance"]), float(viewpoint.attrib["farDistance"])
        self.assertAlmostEqual(near, 2.5e5, delta=1e3)                  # 1 % of the height above the ellipsoid
        self.assertGreater(far, 2.5e7 + 6.3e6)                            # out past the far side of the globe

    def test_a_default_camera_writes_no_clip_distances(self):
        self._import("<Viewpoint position='0 0 10'/>" + BOX)
        viewpoint = self._export().find(".//Viewpoint")
        self.assertNotIn("nearDistance", viewpoint.attrib)
        self.assertNotIn("farDistance", viewpoint.attrib)

    def test_a_camera_clip_range_set_in_blender_is_written(self):
        self._import("<Viewpoint position='0 0 10'/>" + BOX)
        camera = next(ob for ob in bpy.context.scene.objects if ob.type == 'CAMERA')
        camera.data.clip_start, camera.data.clip_end = 2.0, 50000.0
        viewpoint = self._export().find(".//Viewpoint")
        self.assertAlmostEqual(float(viewpoint.attrib["nearDistance"]), 2.0, places=4)
        self.assertAlmostEqual(float(viewpoint.attrib["farDistance"]), 50000.0, places=1)

    def test_hidden_switch_choices_are_written_invisible_not_visible(self):
        # a Switch's other choices are imported hidden; the export wrote them visible, so every choice was drawn
        # (habsburg-unlit-color: the silver marks of the cards the page had switched off)
        self._import("<Switch whichChoice='0'><Shape DEF='Shown'><Box/></Shape><Shape DEF='Hidden'><Box/></Shape></Switch>")
        root = self._export()
        flags = {t.attrib["DEF"]: t.attrib.get("visible", "true") for t in root.iter("Transform")
                 if t.attrib.get("DEF") in ("OB_Shown", "OB_Hidden")}
        self.assertEqual(flags, {"OB_Shown": "true", "OB_Hidden": "false"})

    def test_hide_render_on_a_plain_blender_object_is_not_written_and_does_not_hide_its_children(self):
        # review round 1 (emitter F2, importer F3): a hidden parent of a rendering child exported visible="false" on the
        # parent Transform, which hides the child as well; objects the import did not hide keep exporting visible
        parent = bpy.data.objects.new("Holder", None)
        bpy.context.scene.collection.objects.link(parent)
        bpy.ops.mesh.primitive_cube_add()
        cube = bpy.context.object
        cube.parent = parent
        parent.hide_render = True
        root = self._export()
        flags = {t.attrib["DEF"]: t.attrib.get("visible", "true") for t in root.iter("Transform")
                 if t.attrib.get("DEF") in ("OB_Holder", "OB_Cube")}
        self.assertEqual(flags, {"OB_Holder": "true", "OB_Cube": "true"})

    def test_a_hidden_switch_choice_keeps_a_visible_child_visible(self):
        self._import("<Switch whichChoice='0'><Shape DEF='Shown'><Box/></Shape><Shape DEF='Hidden'><Box/></Shape></Switch>")
        hidden = bpy.data.objects["Hidden"]
        child = bpy.data.objects.new("Added", None)
        bpy.context.scene.collection.objects.link(child)
        child.parent = hidden            # modelled later: not hidden, not marked by the import
        root = self._export()
        transforms = {t.attrib["DEF"]: t for t in root.iter("Transform") if t.attrib.get("DEF", "").startswith("OB_")}
        self.assertNotIn("visible", transforms["OB_Added"].attrib)
        self.assertNotIn("visible", transforms["OB_Hidden"].attrib)           # the subtree is not all hidden
        self.assertEqual([s.attrib.get("visible") for s in transforms["OB_Hidden"].findall("Shape")], ["false"])
        self.assertEqual(transforms["OB_Shown"].attrib.get("visible", "true"), "true")


if __name__ == "__main__":
    unittest.main()
