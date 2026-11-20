# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Metadata* nodes on hosts other than a Shape (Transform, material, WorldInfo, anything else) through
import and the X3D 4.0 export. Skipped when ``bpy`` is not importable.

    cd tests && python -m unittest test_metadata_hosts_bpy
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
    "<WorldInfo DEF='Info' title='Shaft study' info='\"one\" \"two &amp; three\"'>"
    "<MetadataString containerField='metadata' name='survey' value='\"ASAE 36\"'/></WorldInfo>\n"
    "<Transform DEF='ShaftA' translation='0 -4.81 0'>"
    "<MetadataSet DEF='M_ShaftA' containerField='metadata' name='CidocCrm' reference='http://www.cidoc-crm.org/cidoc-crm/E25_Human-Made_Feature'>"
    "<MetadataString name='label' value='\"Shaft A\"'/><MetadataDouble name='depth_m' value='9.62'/></MetadataSet>"
    "<Shape DEF='ShaftA_Shape'><Appearance><PhysicalMaterial DEF='Mat_A' baseColor='0.2 0.9 0.8'>"
    "<MetadataString containerField='metadata' name='colour_key' value='\"teal = documented\"'/>"
    "</PhysicalMaterial></Appearance><Box size='1 9.62 1'/></Shape></Transform>\n"
    "<Transform DEF='Plain' translation='4 0 0'><Shape><Appearance><Material DEF='Mat_Classic' diffuseColor='1 0 0'>"
    "<MetadataInteger containerField='metadata' name='rank' value='3'/></Material></Appearance><Sphere/></Shape></Transform>\n"
    "<Group DEF='Loose'><MetadataBoolean containerField='metadata' name='draft' value='true'/></Group>\n"
    "</Scene></X3D>\n"
)


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class MetadataHostTests(unittest.TestCase):
    def _round_trip(self):
        tmpdir = tempfile.mkdtemp(prefix="x3d_metadata_hosts_")
        _register_extension(tmpdir)
        if str(SOURCE_DIR) not in sys.path:
            sys.path.insert(0, str(SOURCE_DIR))
        import bpy

        source = os.path.join(tmpdir, "hosts.x3d")
        Path(source).write_text(FIXTURE, encoding="utf-8")
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=source), {"FINISHED"})
        path = os.path.join(tmpdir, "hosts_again.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=path, x3d_version="X3D40", use_selection=False), {"FINISHED"})
        return bpy, path

    def test_transform_metadata_is_kept_on_the_object_that_stands_for_it(self):
        bpy, _path = self._round_trip()
        owners = [ob for ob in bpy.context.scene.objects if "x3d_transform_metadata" in ob.keys()]
        self.assertEqual(len(owners), 1)
        kept = owners[0]["x3d_transform_metadata"]
        self.assertEqual((kept["node"], kept["def"], kept["name"]), ("MetadataSet", "M_ShaftA", "CidocCrm"))
        self.assertEqual([(m["node"], m["name"], m["value"]) for m in kept["value"]],
                         [("MetadataString", "label", '"Shaft A"'), ("MetadataDouble", "depth_m", "9.62")])
        self.assertNotIn("x3d_metadata", owners[0].keys())   # the Shape itself had none

    def test_material_metadata_is_kept_on_the_blender_material(self):
        bpy, _path = self._round_trip()
        kept = {mat.get("x3d_def"): mat["x3d_metadata"] for mat in bpy.data.materials if "x3d_metadata" in mat.keys()}
        self.assertEqual(sorted(kept), ["Mat_A", "Mat_Classic"])
        self.assertEqual((kept["Mat_A"]["node"], kept["Mat_A"]["name"], kept["Mat_A"]["value"]),
                         ("MetadataString", "colour_key", '"teal = documented"'))
        self.assertEqual((kept["Mat_Classic"]["node"], kept["Mat_Classic"]["value"]), ("MetadataInteger", "3"))

    def test_other_hosts_are_kept_on_the_scene_never_dropped(self):
        bpy, _path = self._round_trip()
        kept = {item["host"]: item for item in bpy.context.scene["x3d_scene_metadata"]}
        self.assertEqual(sorted(kept), ["Group", "WorldInfo"])
        self.assertEqual((kept["WorldInfo"]["def"], kept["WorldInfo"]["title"]), ("Info", "Shaft study"))
        self.assertEqual((kept["Group"]["def"], kept["Group"]["metadata"]["name"]), ("Loose", "draft"))

    def test_export_writes_each_tree_back_on_its_host(self):
        _bpy, path = self._round_trip()
        from validate import validate_xml_file, validate_with_x3d_py

        root = ET.parse(path).getroot()
        info = root.find(".//WorldInfo")
        self.assertEqual((info.get("DEF"), info.get("title"), info.get("info")), ("Info", "Shaft study", '"one" "two & three"'))
        self.assertEqual(info.find("MetadataString").attrib, {"containerField": "metadata", "name": "survey", "value": '"ASAE 36"'})
        sets = root.findall(".//Transform/MetadataSet")
        self.assertEqual(len(sets), 1)
        self.assertEqual({k: sets[0].get(k) for k in ("DEF", "containerField", "name")},
                         {"DEF": "M_ShaftA", "containerField": "metadata", "name": "CidocCrm"})
        self.assertEqual([(m.tag, m.get("name"), m.get("value")) for m in sets[0]],
                         [("MetadataString", "label", '"Shaft A"'), ("MetadataDouble", "depth_m", "9.62")])
        physical = root.find(".//PhysicalMaterial/MetadataString")
        self.assertEqual((physical.get("containerField"), physical.get("name")), ("metadata", "colour_key"))
        classic = root.find(".//Material/MetadataInteger")
        self.assertEqual((classic.get("containerField"), classic.get("value")), ("metadata", "3"))
        # the Group has no Blender object: its tree stays in the .blend and is not written
        self.assertIsNone(root.find(".//MetadataBoolean"))
        self.assertTrue(validate_xml_file(path).valid)
        semantic = validate_with_x3d_py(path)
        if semantic is not None:
            self.assertTrue(semantic.valid, semantic.errors)

    def test_a_scene_made_in_blender_writes_no_worldinfo(self):
        tmpdir = tempfile.mkdtemp(prefix="x3d_metadata_hosts_")
        _register_extension(tmpdir)
        import bpy

        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.mesh.primitive_cube_add()
        path = os.path.join(tmpdir, "cube.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=path, x3d_version="X3D40", use_selection=False), {"FINISHED"})
        root = ET.parse(path).getroot()
        self.assertIsNone(root.find(".//WorldInfo"))
        self.assertEqual([el.tag for el in root.iter() if el.tag.startswith("Metadata")], [])


if __name__ == "__main__":
    unittest.main()
