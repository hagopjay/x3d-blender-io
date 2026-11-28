# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The node board's eleventh batch, HAnim completion: HAnimSegment, HAnimSite, HAnimMotion and HAnimDisplacer
(docs/NODE_BOARD_PRIORITIES.md ranks 29 to 32, batch 11; source/hanim_parts.py).

A segment's Shapes become mesh objects bone-parented to the joint's bone, its name, mass, centerOfMass and
momentsOfInertia props on the bone; a site becomes an Empty bone-parented to its segment's bone; a joint's displacer a
shape key on the skin (weight = key value); a motion a Blender Action on the armature, one key per frame per joint.
The export writes each back from Blender's values.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_node_board_batch11_bpy
"""

from __future__ import annotations

import math
import os
import re
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    import bpy
    from mathutils import Matrix, Vector
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

from test_roundtrip_bpy import _register_extension
from test_node_board_batch_bpy import _valid

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "node_board" / "gap_batch_11.x3d"
FIXTURE_VALUES = [float(v) for v in "0 0 0 0 0 0 0 0 0 0 0.1 0 0 0 0 0 0.4 0 0 0 0 0 0 0 0 0.2 0".split()]


def _floats(text):
    return [round(float(v), 4) for v in text.split()]


@unittest.skipUnless(HAVE_BPY, "bpy not available")
class NodeBoardBatch11Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="x3d_node_board11_")
        _register_extension(self.tmp)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        _register_extension(self.tmp)

    def _export(self, name="out.x3d", **options):
        out = os.path.join(self.tmp, name)
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=out, x3d_version="X3D40", use_selection=False, **options),
                         {"FINISHED"})
        structural, errors = _valid(out)
        self.assertTrue(structural.valid, structural.errors)
        self.assertEqual(errors or [], [], "does not validate against x3d-4.0.xsd")
        return out, ET.parse(out).getroot()

    def _import(self, path=FIXTURE):
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=str(path)), {"FINISHED"})
        return bpy.data.objects["Walker"]

    @staticmethod
    def _joint_matrix(armature, bone_name):
        """The HAnim joint transform J = L basis L^-1 of a bone at the current frame."""
        bone = armature.data.bones[bone_name]
        basis = armature.pose.bones[bone_name].matrix_basis
        return bone.matrix_local @ basis @ bone.matrix_local.inverted()

    def _humanoid_part(self, root, path):
        node = root.find(f".//HAnimHumanoid/{path}")
        self.assertIsNotNone(node, path)
        return node

    def test_the_import_makes_bone_parented_objects_a_shape_key_and_an_action(self):
        armature = self._import()
        pelvis, head, crown = (bpy.data.objects[n] for n in ("PelvisShape", "Head", "crown"))
        self.assertEqual([(o.type, o.parent, o.parent_type, o.parent_bone) for o in (pelvis, head, crown)],
                         [("MESH", armature, "BONE", "HumanoidRoot"), ("MESH", armature, "BONE", "skullbase"),
                          ("EMPTY", armature, "BONE", "skullbase")])
        bpy.context.view_layer.update()
        to_x3d = armature.matrix_world.inverted()
        self.assertEqual([round(v, 4) for v in (to_x3d @ head.matrix_world).translation], [0.0, 1.75, 0.0])
        crown_x3d = to_x3d @ crown.matrix_world
        self.assertEqual([round(v, 4) for v in crown_x3d.translation], [0.0, 1.9, 0.0])
        self.assertAlmostEqual(crown_x3d.to_quaternion().angle, 1.5708, places=4)
        root_bone = armature.data.bones["HumanoidRoot"]
        self.assertEqual(root_bone["x3d_hanim_segment_mass"], 12.0)
        self.assertEqual([round(v, 4) for v in root_bone["x3d_hanim_segment_centerOfMass"]], [0.0, 1.05, 0.0])
        self.assertEqual(len(root_bone["x3d_hanim_segment_momentsOfInertia"]), 9)
        self.assertIn('"name": "pelvis"', root_bone["x3d_hanim_segment"])
        self.assertIn('"name": "crown_pt"', crown["x3d_hanim_site"])

        face = bpy.data.objects["Face"]
        keys = face.data.shape_keys.key_blocks
        self.assertEqual([k.name for k in keys], ["Basis", "brow_raise"])
        self.assertAlmostEqual(keys["brow_raise"].value, 0.5, places=6)
        moved = [i for i, (p, b) in enumerate(zip(keys["brow_raise"].data, keys["Basis"].data)) if (p.co - b.co).length > 1e-6]
        self.assertEqual(moved, [2, 3])
        self.assertAlmostEqual((keys["brow_raise"].data[2].co - keys["Basis"].data[2].co).y, 0.05, places=5)

        action = armature.animation_data.action
        self.assertEqual(action.name, "nod")
        scene = bpy.context.scene
        fps = scene.render.fps / scene.render.fps_base
        scene.frame_set(scene.frame_start + round(0.5 * fps))       # frame 1 of the motion
        self.assertEqual([round(v, 4) for v in self._joint_matrix(armature, "HumanoidRoot").translation], [0.0, 0.1, 0.0])
        scene.frame_set(scene.frame_start + round(1.0 * fps))       # frame 2: skullbase turned 0.2 about X
        turn = self._joint_matrix(armature, "skullbase").to_quaternion()
        self.assertAlmostEqual(turn.angle, 0.2, places=4)
        self.assertEqual([round(abs(v), 4) for v in turn.axis], [1.0, 0.0, 0.0])
        self.assertEqual([round(v, 4) for v in self._joint_matrix(armature, "HumanoidRoot").translation], [0.0, 0.0, 0.0])

    def test_each_node_is_written_back_as_itself(self):
        self._import()
        root = self._export()[1]
        pelvis = self._humanoid_part(root, "HAnimJoint[@name='HumanoidRoot']/HAnimSegment")
        self.assertEqual((pelvis.get("name"), pelvis.get("mass"), _floats(pelvis.get("centerOfMass")),
                          _floats(pelvis.get("momentsOfInertia"))),
                         ("pelvis", "12", [0.0, 1.05, 0.0], [0.1, 0, 0, 0, 0.2, 0, 0, 0, 0.1]))
        self.assertIsNotNone(pelvis.find("Transform/Shape/Box"))
        skull = self._humanoid_part(root, ".//HAnimJoint[@name='skullbase']/HAnimSegment")
        head = skull.find("Transform")
        self.assertEqual((head.get("DEF"), _floats(head.get("translation"))), ("OB_Head", [0.0, 1.75, 0.0]))
        self.assertIsNotNone(head.find("Shape/Sphere"))
        site = skull.find("HAnimSite")
        self.assertEqual((site.get("name"), site.get("description"), _floats(site.get("translation"))),
                         ("crown_pt", "top of the head", [0.0, 1.9, 0.0]))
        self.assertEqual(_floats(site.get("rotation")), [0.0, 1.0, 0.0, 1.5708])
        displacer = self._humanoid_part(root, ".//HAnimJoint[@name='skullbase']/HAnimDisplacer")
        self.assertEqual((displacer.get("name"), displacer.get("coordIndex"), _floats(displacer.get("displacements")),
                          displacer.get("weight")), ("brow_raise", "2 3", [0, 0.05, 0, 0, 0.05, 0], "0.5"))
        motion = self._humanoid_part(root, "HAnimMotion")
        self.assertEqual({k: motion.get(k) for k in ("name", "loop", "frameDuration", "joints", "containerField")},
                         {"name": "nod", "loop": "true", "frameDuration": "0.5", "joints": "HumanoidRoot skullbase",
                          "containerField": "motions"})
        self.assertEqual(motion.get("channels").split(), "6 Xposition Yposition Zposition Xrotation Yrotation Zrotation "
                         "3 Zrotation Xrotation Yrotation".split())
        self.assertEqual([float(v) for v in motion.get("values").split()], FIXTURE_VALUES)
        humanoid = root.find(".//HAnimHumanoid")
        uses = [(child.tag, child.get("containerField")) for child in humanoid if child.get("USE")]
        self.assertEqual(uses.count(("HAnimSegment", "segments")), 2)
        self.assertEqual(uses.count(("HAnimSite", "sites")), 1)
        self.assertEqual(root.find(".//component[@name='HAnim']").get("level"), "2", "HAnimMotion is HAnim level 2")

    def test_edits_in_blender_reach_the_file(self):
        armature = self._import()
        armature.data.bones["HumanoidRoot"]["x3d_hanim_segment_mass"] = 20.0
        crown = bpy.data.objects["crown"]
        crown.matrix_basis = Matrix.Translation((0.0, 2.0, 0.0))            # humanoid space, rest pose
        keys = bpy.data.objects["Face"].data.shape_keys.key_blocks
        keys["brow_raise"].value = 0.8
        keys["brow_raise"].data[3].co = keys["Basis"].data[3].co + Vector((0.0, 0.1, 0.0))
        # the motion's frame 1: HumanoidRoot up 0.3 instead of 0.1
        scene = bpy.context.scene
        fps = scene.render.fps / scene.render.fps_base
        frame = scene.frame_start + 0.5 * fps
        bone = armature.data.bones["HumanoidRoot"]
        basis = bone.matrix_local.inverted() @ Matrix.Translation((0.0, 0.3, 0.0)) @ bone.matrix_local
        pose_bone = armature.pose.bones["HumanoidRoot"]
        pose_bone.location = basis.to_translation()
        pose_bone.keyframe_insert("location", frame=frame)
        root = self._export()[1]
        self.assertEqual(self._humanoid_part(root, "HAnimJoint[@name='HumanoidRoot']/HAnimSegment").get("mass"), "20")
        site = self._humanoid_part(root, ".//HAnimSite[@name='crown_pt']")
        self.assertEqual((_floats(site.get("translation")), _floats(site.get("rotation"))[3]), ([0.0, 2.0, 0.0], 0.0))
        displacer = self._humanoid_part(root, ".//HAnimDisplacer")
        self.assertEqual((displacer.get("weight"), _floats(displacer.get("displacements"))),
                         ("0.8", [0, 0.05, 0, 0, 0.1, 0]))
        values = [float(v) for v in self._humanoid_part(root, "HAnimMotion").get("values").split()]
        expected = list(FIXTURE_VALUES)
        expected[10] = 0.3
        self.assertEqual([round(v, 4) for v in values], expected)

    def test_parts_made_in_blender_are_written(self):
        armature = self._import()
        bpy.ops.mesh.primitive_cube_add(size=0.1)
        cube = bpy.context.active_object
        cube.name = "Badge"
        for obj in (cube, bpy.data.objects.new("Hip_pt", None)):
            if obj.name not in bpy.context.scene.collection.objects:
                bpy.context.scene.collection.objects.link(obj)
            obj.parent, obj.parent_type, obj.parent_bone = armature, "BONE", "HumanoidRoot"
            bone = armature.data.bones["HumanoidRoot"]
            obj.matrix_parent_inverse = (bone.matrix_local @ Matrix.Translation((0.0, bone.length, 0.0))).inverted()
            obj.matrix_basis = Matrix.Translation((0.1, 1.0, 0.0))
        face = bpy.data.objects["Face"]
        smile = face.shape_key_add(name="smile", from_mix=False)
        smile.data[0].co = smile.data[0].co + Vector((0.0, -0.02, 0.0))
        smile.value = 1.0
        root = self._export()[1]
        pelvis = self._humanoid_part(root, "HAnimJoint[@name='HumanoidRoot']/HAnimSegment")
        badge = pelvis.find("Transform[@DEF='OB_Badge']")
        self.assertIsNotNone(badge)
        self.assertEqual(_floats(badge.get("translation")), [0.1, 1.0, 0.0])
        self.assertIsNotNone(pelvis.find("HAnimSite[@name='Hip_pt']"))
        smile_node = self._humanoid_part(root, "HAnimJoint[@name='HumanoidRoot']/HAnimDisplacer")
        self.assertEqual((smile_node.get("name"), smile_node.get("coordIndex"), smile_node.get("weight")), ("smile", "0", "1"))
        self.assertIsNone(root.find(".//Scene/Transform[@DEF='OB_Badge']"), "a segment Shape is not also a plain Transform")

    def test_the_motion_is_not_also_written_as_interpolators(self):
        self._import()
        root = self._export(use_animation=True)[1]
        self.assertIsNotNone(root.find(".//HAnimMotion"))
        self.assertEqual([r.get("toNode") for r in root.iter("ROUTE") if r.get("toNode", "").startswith("hanim_")], [])

    def test_a_second_round_trip_writes_the_same_file(self):
        self._import()
        first_path, _ = self._export()
        first_text = Path(first_path).read_text(encoding="utf-8")
        bpy.ops.wm.read_factory_settings(use_empty=True)
        _register_extension(self.tmp)
        self._import(first_path)
        second_path, _ = self._export("out2.x3d")
        strip = lambda text: re.sub(r'<meta name="(created|modified|generator|filename)"[^>]*>', "", text)
        self.assertEqual(strip(Path(second_path).read_text(encoding="utf-8")), strip(first_text))


if __name__ == "__main__":
    unittest.main()
