# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A Group that carries its own Metadata gets an Empty on import, so its Metadata and its place in the tree survive
the X3D 4.0 export. This is how an IFC spatial tree (Project, Site, Building, Storey as nested Groups) travels
through Blender (x3d.loom x3d.engineering/ifc-loop). A Group without Metadata still gets no object, and a Group with
Metadata but nothing under it stays on the scene property as before. Skipped when ``bpy`` is not importable.

    cd tests && python -m unittest test_metadata_group_hierarchy_bpy
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from test_roundtrip_bpy import HAVE_BPY, SOURCE_DIR, _register_extension

FIXTURE = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    "<X3D profile='Immersive' version='4.0'><Scene>\n"
    "<Group DEF='Site'><MetadataSet containerField='metadata' name='IFC'>"
    "<MetadataString name='class' value='\"IfcSite\"'/></MetadataSet>\n"
    " <Group DEF='Storey'><MetadataSet containerField='metadata' name='IFC'>"
    "<MetadataString name='class' value='\"IfcBuildingStorey\"'/><MetadataDouble name='Elevation' value='3.5'/></MetadataSet>\n"
    "  <Group DEF='Plain'>\n"
    "   <Transform DEF='Wall' translation='1 2 3'><MetadataString containerField='metadata' name='class' value='\"IfcWall\"'/>"
    "<Shape><Box size='4 0.2 3'/></Shape></Transform>\n"
    "   <Transform DEF='Slab' translation='0 0 -1'><Shape><Box size='6 6 0.2'/></Shape></Transform>\n"
    "  </Group>\n"
    " </Group>\n"
    "</Group>\n"
    "<Group DEF='Loose'><MetadataBoolean containerField='metadata' name='draft' value='true'/></Group>\n"
    "</Scene></X3D>\n"
)


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class MetadataGroupHierarchyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmpdir = tempfile.mkdtemp(prefix="x3d_meta_group_")
        _register_extension(tmpdir)
        if str(SOURCE_DIR) not in sys.path:
            sys.path.insert(0, str(SOURCE_DIR))
        import bpy

        source = os.path.join(tmpdir, "groups.x3d")
        Path(source).write_text(FIXTURE, encoding="utf-8")
        bpy.ops.wm.read_factory_settings(use_empty=True)
        assert bpy.ops.import_scene.x3d(filepath=source) == {"FINISHED"}
        cls.bpy = bpy
        cls.objects = {ob.name: ob for ob in bpy.context.scene.objects}
        cls.path = os.path.join(tmpdir, "groups_again.x3d")
        assert bpy.ops.export_scene.x3d(filepath=cls.path, x3d_version="X3D40", use_selection=False,
                                        use_hierarchy=True) == {"FINISHED"}
        cls.root = ET.parse(cls.path).getroot()

    def test_a_group_with_metadata_becomes_an_empty_with_its_tree(self):
        for name, cls_name in (("Site", '"IfcSite"'), ("Storey", '"IfcBuildingStorey"')):
            ob = self.objects[name]
            self.assertEqual(ob.type, "EMPTY")
            kept = ob["x3d_transform_metadata"]
            self.assertEqual((kept["node"], kept["name"]), ("MetadataSet", "IFC"))
            self.assertEqual(kept["value"][0]["value"], cls_name)

    def test_the_tree_is_kept_and_a_plain_group_adds_no_object(self):
        self.assertIs(self.objects["Storey"].parent, self.objects["Site"])
        self.assertIs(self.objects["Wall"].parent, self.objects["Storey"])
        self.assertIs(self.objects["Slab"].parent, self.objects["Storey"])
        self.assertNotIn("Plain", self.objects)

    def test_world_placement_is_unchanged(self):
        wall = self.objects["Wall"].matrix_world.translation
        # Y-up X3D (1, 2, 3) is Blender Z-up (1, -3, 2)
        self.assertAlmostEqual(wall.x, 1.0, places=6)
        self.assertAlmostEqual(wall.y, -3.0, places=6)
        self.assertAlmostEqual(wall.z, 2.0, places=6)

    def test_a_group_with_metadata_and_no_content_stays_on_the_scene(self):
        hosts = {item["def"]: item["host"] for item in self.bpy.context.scene.get("x3d_scene_metadata", ())}
        self.assertEqual(hosts, {"Loose": "Group"})

    def test_export_writes_the_groups_back_with_their_metadata_and_nesting(self):
        from validate import validate_xml_file
        defs = {t.get("DEF"): t for t in self.root.iter("Transform")}
        site, storey = defs["OB_Site"], defs["OB_Storey"]
        self.assertIn(storey, list(site))
        self.assertIn(defs["OB_Wall"], list(storey))
        self.assertEqual([m.get("name") for m in storey if m.tag == "MetadataSet"], ["IFC"])
        self.assertTrue(validate_xml_file(self.path).valid)


if __name__ == "__main__":
    unittest.main()
