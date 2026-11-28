# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The node board's seventh batch: BallJoint, SliderJoint, DoubleAxisHingeJoint and UniversalJoint as Blender rigid
body constraints (docs/NODE_BOARD_PRIORITIES.md, batch 7; SingleAxisHingeJoint came with batch 6).

Each joint becomes an empty with a constraint between its two bodies, turned so the constraint's own axes are the
joint's: POINT for a ball; SLIDER along X (axis), its limits the joint's min/maxSeparation less how far apart the bodies
start (X3D measures separation, Blender travel); GENERIC with Z (axis1) and X (axis2) free and everything else locked,
Z limited by a DoubleAxisHingeJoint's min/maxAngle1. The export writes each back from Blender's values.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_node_board_batch7_bpy
"""

from __future__ import annotations

import os
import re
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    import bpy
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

from test_roundtrip_bpy import _register_extension
from test_node_board_batch_bpy import _valid

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "node_board" / "gap_batch_7.x3d"


def _floats(text):
    return [round(float(v), 4) for v in text.split()]


@unittest.skipUnless(HAVE_BPY, "bpy not available")
class NodeBoardBatch7Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="x3d_node_board7_")
        _register_extension(self.tmp)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        _register_extension(self.tmp)

    def _export(self, name="out.x3d"):
        out = os.path.join(self.tmp, name)
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=out, x3d_version="X3D40", use_selection=False), {"FINISHED"})
        structural, errors = _valid(out)
        self.assertTrue(structural.valid, structural.errors)
        self.assertEqual(errors or [], [], "does not validate against x3d-4.0.xsd")
        return out, ET.parse(out).getroot()

    def _import(self):
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=str(FIXTURE)), {"FINISHED"})

    def _joint(self, root, tag):
        node = root.find(f".//RigidBodyCollection/{tag}")
        self.assertIsNotNone(node, tag)
        return node

    def test_the_import_makes_blender_constraints(self):
        self._import()
        cons = {name: bpy.data.objects[name].rigid_body_constraint for name in ("Ball", "Rail", "Gimbal", "Cardan")}
        self.assertEqual({n: c.type for n, c in cons.items()},
                         {"Ball": "POINT", "Rail": "SLIDER", "Gimbal": "GENERIC", "Cardan": "GENERIC"})
        rail = cons["Rail"]
        self.assertTrue(rail.use_limit_lin_x)
        self.assertEqual((round(rail.limit_lin_x_lower, 4), round(rail.limit_lin_x_upper, 4)), (-1.0, 1.0),
                         "separation 1 to 3 for bodies starting 2 apart is travel -1 to 1")
        gimbal = cons["Gimbal"]
        self.assertTrue(gimbal.use_limit_ang_z and gimbal.use_limit_ang_y and gimbal.use_limit_lin_x)
        self.assertFalse(gimbal.use_limit_ang_x, "axis2 turns freely")
        self.assertAlmostEqual(gimbal.limit_ang_z_upper, 0.6, places=5)
        self.assertFalse(cons["Cardan"].use_limit_ang_z, "a UniversalJoint has no angle stops")

    def test_each_joint_is_written_back_as_itself(self):
        self._import()
        root = self._export()[1]
        ball = self._joint(root, "BallJoint")
        self.assertEqual((_floats(ball.get("anchorPoint")), ball.get("forceOutput")), ([-6.0, 2.0, 0.0], '"ALL"'))
        rail = self._joint(root, "SliderJoint")
        self.assertEqual((_floats(rail.get("axis")), float(rail.get("minSeparation")), float(rail.get("maxSeparation"))),
                         ([1.0, 0.0, 0.0], 1.0, 3.0))
        self.assertIsNone(rail.get("anchorPoint"), "a SliderJoint has no anchor")
        gimbal = self._joint(root, "DoubleAxisHingeJoint")
        self.assertEqual((_floats(gimbal.get("axis1")), _floats(gimbal.get("axis2")), float(gimbal.get("minAngle1")),
                          gimbal.get("suspensionForce")), ([0.0, 0.0, 1.0], [1.0, 0.0, 0.0], -0.6, "2"))
        cardan = self._joint(root, "UniversalJoint")
        self.assertEqual((_floats(cardan.get("axis1")), _floats(cardan.get("axis2")), cardan.get("stop1Bounce")),
                         ([0.0, 1.0, 0.0], [1.0, 0.0, 0.0], "0.1"))
        for joint in (ball, rail, gimbal, cardan):
            self.assertEqual([b.get("containerField") for b in joint.findall("RigidBody")], ["body1", "body2"])

    def test_edits_in_blender_reach_the_file(self):
        self._import()
        bpy.data.objects["Rail"].rigid_body_constraint.limit_lin_x_upper = 2.0
        bpy.data.objects["Gimbal"].rigid_body_constraint.limit_ang_z_upper = 1.0
        root = self._export()[1]
        self.assertEqual(float(self._joint(root, "SliderJoint").get("maxSeparation")), 4.0, "travel 2 from 2 apart")
        self.assertEqual(float(self._joint(root, "DoubleAxisHingeJoint").get("maxAngle1")), 1.0)

    def test_joints_made_in_blender_are_written(self):
        for x in (0.0, 2.0):
            bpy.ops.mesh.primitive_cube_add(location=(x, 0.0, 2.0), size=0.5)
            bpy.ops.rigidbody.object_add(type="ACTIVE")
        a, b = [o for o in bpy.data.objects if o.rigid_body]
        for kind in ("POINT", "GENERIC"):
            empty = bpy.data.objects.new(f"My{kind}", None)
            bpy.context.scene.collection.objects.link(empty)
            bpy.context.view_layer.objects.active = empty
            empty.select_set(True)
            bpy.ops.rigidbody.constraint_add(type=kind)
            empty.rigid_body_constraint.object1, empty.rigid_body_constraint.object2 = a, b
        root = self._export()[1]
        self.assertIsNotNone(root.find(".//RigidBodyCollection/BallJoint"))
        self.assertIsNotNone(root.find(".//RigidBodyCollection/DoubleAxisHingeJoint"),
                             "a GENERIC constraint made in Blender is written as a DoubleAxisHingeJoint")

    def test_a_second_round_trip_writes_the_same_file(self):
        self._import()
        first_path, _ = self._export()
        first_text = Path(first_path).read_text(encoding="utf-8")
        bpy.ops.wm.read_factory_settings(use_empty=True)
        _register_extension(self.tmp)
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=first_path), {"FINISHED"})
        second_path, _ = self._export("out2.x3d")
        strip = lambda text: re.sub(r'<meta name="(created|modified|generator|filename)"[^>]*>', "", text)
        self.assertEqual(strip(Path(second_path).read_text(encoding="utf-8")), strip(first_text))


if __name__ == "__main__":
    unittest.main()
