# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Bone name -> H-Anim 2.0 joint name mapping (no bpy)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "source"))

from hanim_names import STANDARD_JOINTS, map_bones, standard_joint_name  # noqa: E402


class StandardJointNameTests(unittest.TestCase):
    def test_mixamo(self):
        cases = {"mixamorig:Hips": "humanoid_root", "mixamorig:Head": "skullbase", "mixamorig:LeftArm": "l_shoulder",
                 "mixamorig:RightForeArm": "r_elbow", "mixamorig:LeftHand": "l_wrist", "mixamorig:RightUpLeg": "r_hip",
                 "mixamorig:LeftLeg": "l_knee", "mixamorig:RightFoot": "r_ankle", "mixamorig:LeftToeBase": "l_metatarsal",
                 "mixamorig:LeftShoulder": "l_acromioclavicular", "mixamorig:LeftHandIndex2": "l_index2",
                 "mixamorig:RightHandThumb1": "r_thumb1"}
        for bone, joint in cases.items():
            self.assertEqual(standard_joint_name(bone), joint, bone)

    def test_rigify_and_plain(self):
        cases = {"upper_arm.L": "l_shoulder", "forearm.R": "r_elbow", "hand.L": "l_wrist", "thigh.R": "r_hip",
                 "shin.L": "l_knee", "foot.R": "r_ankle", "head": "skullbase", "l_upper_arm": "l_shoulder",
                 "DEF-upper_arm.L": "l_shoulder", "pelvis": "humanoid_root"}
        for bone, joint in cases.items():
            self.assertEqual(standard_joint_name(bone), joint, bone)

    def test_ambiguous_bones_are_left_alone(self):
        for bone in ("Spine", "Spine1", "Neck", "lower", "upper", "Armature", "root"):
            self.assertIsNone(standard_joint_name(bone), bone)

    def test_every_mapped_name_is_a_standard_joint(self):
        for bone in ("mixamorig:LeftArm", "thigh.R", "mixamorig:LeftHandPinky3", "Head"):
            self.assertIn(standard_joint_name(bone), STANDARD_JOINTS)

    def test_override_wins_and_unknown_override_is_reported(self):
        self.assertEqual(standard_joint_name("Spine", "vl5"), "vl5")
        mapping, problems = map_bones([("Spine", "vl5"), ("Odd", "tail_tip")])
        self.assertEqual(mapping, {"Spine": "vl5", "Odd": "tail_tip"})
        self.assertEqual(len(problems), 1)
        self.assertIn("tail_tip", problems[0])

    def test_duplicate_claim_keeps_the_first_and_reports(self):
        mapping, problems = map_bones([("Hips", None), ("pelvis", None)])
        self.assertEqual(mapping, {"Hips": "humanoid_root"})
        self.assertEqual(len(problems), 1)


if __name__ == "__main__":
    unittest.main()
