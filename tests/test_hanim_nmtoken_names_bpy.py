# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""HAnimHumanoid and HAnimJoint ``name`` are xs:NMTOKEN in the X3D 4.0 XSD: no whitespace.

Found by the NEXUS X3D Hub Observatory brag page: a rig called "Articulation study"
exported ``name="Articulation study"``, which the Web3D x3d.py field check accepts
but the X3D 4.0 XSD (x3d_mcp validator) rejects. The round trip already wrote
"Articulation_study", so only the first trip was invalid.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_hanim_nmtoken_names_bpy
"""

from __future__ import annotations

import os
import re
import tempfile
import unittest
import xml.etree.ElementTree as ET

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

from test_roundtrip_bpy import _register_extension

_NMTOKEN = re.compile(r"^[\w.:-]+$")


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class HAnimNmtokenNameTests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="x3d_hanim_nmtoken_")
        _register_extension(self.tmpdir)
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def _rig(self):
        bpy.ops.object.armature_add(enter_editmode=True)
        armature = bpy.context.active_object
        armature.name = "Articulation study"
        edit = armature.data.edit_bones
        edit.remove(edit[0])
        for name, parent, z in (("Base joint", None, 0.0), ("Upper arm", "Base joint", 0.5), ("Fore arm", "Upper arm", 1.0)):
            bone = edit.new(name)
            bone.head, bone.tail = (0, 0, z), (0, 0, z + 0.5)
            if parent:
                bone.parent = edit[parent]
        bpy.ops.object.mode_set(mode="OBJECT")

    def test_names_with_spaces_become_nmtokens(self):
        self._rig()
        path = os.path.join(self.tmpdir, "rig.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=path, x3d_version="X3D40", use_selection=False), {"FINISHED"})
        root = ET.parse(path).getroot()
        humanoid = root.find(".//HAnimHumanoid")
        self.assertEqual(humanoid.get("name"), "Articulation_study")
        names = [j.get("name") for j in root.iter("HAnimJoint") if j.get("DEF")]
        self.assertEqual(names, ["Base_joint", "Upper_arm", "Fore_arm"])
        for name in names + [humanoid.get("name")]:
            self.assertRegex(name, _NMTOKEN)
        # DEF names are unchanged, so USE and ROUTE references still match.
        defs = {j.get("DEF") for j in root.iter("HAnimJoint") if j.get("DEF")}
        uses = {j.get("USE") for j in root.iter("HAnimJoint") if j.get("USE")}
        self.assertEqual(uses, defs)


if __name__ == "__main__":
    unittest.main()
