# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""HAnimJoint names: standard H-Anim 2.0 names for known rig conventions, Blender names otherwise.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_export_hanim_names_bpy
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

from test_roundtrip_bpy import _register_extension, SOURCE_DIR


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class ExportHAnimNamesTests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="x3d_hanim_names_")
        _register_extension(self.tmpdir)
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def _rig(self, bones):
        """bones: list of (name, parent name or None, head z). One chain of 0.5 m bones."""
        bpy.ops.object.armature_add(enter_editmode=True)
        armature = bpy.context.active_object
        armature.name = "Rig"
        edit = armature.data.edit_bones
        edit.remove(edit[0])
        for name, parent, z in bones:
            bone = edit.new(name)
            bone.head, bone.tail = (0, 0, z), (0, 0, z + 0.5)
            if parent:
                bone.parent = edit[parent]
        bpy.ops.object.mode_set(mode="OBJECT")
        return armature

    def _export(self):
        path = os.path.join(self.tmpdir, "rig.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=path, x3d_version="X3D40", use_selection=False),
                         {"FINISHED"})
        return ET.parse(path).getroot(), path

    def test_mixamo_bones_get_standard_names_and_keep_their_def(self):
        self._rig([("mixamorig:Hips", None, 1.0), ("mixamorig:Spine", "mixamorig:Hips", 1.5),
                   ("mixamorig:LeftArm", "mixamorig:Spine", 2.0), ("mixamorig:LeftForeArm", "mixamorig:LeftArm", 2.5)])
        root, _path = self._export()
        joints = {j.get("DEF"): j.get("name") for j in root.iter("HAnimJoint") if j.get("DEF")}
        self.assertEqual(joints["hanim_Rig_mixamorig_Hips"], "humanoid_root")
        self.assertEqual(joints["hanim_Rig_mixamorig_LeftArm"], "l_shoulder")
        self.assertEqual(joints["hanim_Rig_mixamorig_LeftForeArm"], "l_elbow")
        self.assertEqual(joints["hanim_Rig_mixamorig_Spine"], "mixamorig:Spine")      # ambiguous: left alone
        info = root.find(".//HAnimHumanoid").get("info")
        self.assertIn("3 of 4 joints carry standard H-Anim 2.0 names", info)

    def test_override_property_and_conflict_diagnostic(self):
        rig = self._rig([("Hips", None, 1.0), ("pelvis", "Hips", 1.2), ("Chest", "pelvis", 1.6)])
        rig.data.bones["Chest"]["x3d_hanim_joint"] = "vt1"
        root, _path = self._export()
        names = [j.get("name") for j in root.iter("HAnimJoint") if j.get("DEF")]
        self.assertEqual(names, ["humanoid_root", "pelvis", "vt1"])
        info = " ".join(m.get("content", "") for m in root.iter("meta"))
        self.assertIn("both map to H-Anim joint 'humanoid_root'", info)

    def test_output_validates(self):
        try:
            import x3d  # noqa: F401
        except ImportError:
            self.skipTest("x3d package not installed")
        self._rig([("mixamorig:Hips", None, 1.0), ("mixamorig:LeftArm", "mixamorig:Hips", 1.5)])
        _root, path = self._export()
        sys.path.insert(0, str(SOURCE_DIR))
        from validate import validate_with_x3d_py
        result = validate_with_x3d_py(path)
        self.assertTrue(result.valid, result.errors)
        self.assertEqual(result.warnings, [])


if __name__ == "__main__":
    unittest.main()
