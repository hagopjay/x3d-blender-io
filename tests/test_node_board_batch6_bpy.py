# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The node board's sixth batch: RigidBodyCollection, RigidBody, CollidableShape, CollidableOffset and
SingleAxisHingeJoint as Blender rigid bodies (docs/NODE_BOARD_PRIORITIES.md, batch 6 plus the hinge from batch 7).

The import makes the scene's rigid body world (gravity, iterations), a Blender rigid body on each body's object (fixed is
PASSIVE, mass, damping, the collision shape from the primitive) and an empty with a HINGE constraint for the joint; the
export writes the physics back from Blender's values, so an edit in Blender reaches the file, and keeps every other field
as the file wrote it. A rigid body made in Blender is written too, with a CollisionCollection so it collides.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_node_board_batch6_bpy
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
FIXTURE = ROOT / "tests" / "node_board" / "gap_batch_6.x3d"


def _floats(text):
    return [float(v) for v in text.split()]


@unittest.skipUnless(HAVE_BPY, "bpy not available")
class NodeBoardBatch6Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):   # the node board's batch 6/7 importer, kept behind BLENDER_X3D_PHYSICS=legacy (docs/PHYSICS.md)
        cls._physics_env = os.environ.get("BLENDER_X3D_PHYSICS")
        os.environ["BLENDER_X3D_PHYSICS"] = "legacy"

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "_physics_env", None) is None:
            os.environ.pop("BLENDER_X3D_PHYSICS", None)
        else:
            os.environ["BLENDER_X3D_PHYSICS"] = cls._physics_env

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="x3d_node_board6_")
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

    def _bodies(self, root):
        return {b.get("DEF"): b for b in root.iter("RigidBody") if b.get("DEF")}

    # --- what Blender holds ---------------------------------------------------------------------------------------

    def test_the_import_makes_blender_rigid_bodies(self):
        self._import()
        scene = bpy.context.scene
        self.assertIsNotNone(scene.rigidbody_world)
        self.assertEqual(scene.rigidbody_world.solver_iterations, 20)
        self.assertAlmostEqual(scene.gravity[2], -1.62, places=5, msg="X3D -Y gravity is Blender -Z")
        bodies = {o.rigid_body and o.name: o for o in bpy.data.objects if o.rigid_body}
        kinds = {o.name: (o.rigid_body.type, round(o.rigid_body.mass, 3), o.rigid_body.collision_shape)
                 for o in bodies.values()}
        self.assertEqual(kinds["GroundShape"], ("PASSIVE", 1.0, "BOX"))
        self.assertEqual(kinds["BallShape"], ("ACTIVE", 2.5, "SPHERE"))
        self.assertEqual(kinds["ArmShape"][0], "ACTIVE")
        self.assertAlmostEqual(bpy.data.objects["ArmShape"].rigid_body.linear_damping, 0.05, places=5)
        hinge = bpy.data.objects["Hinge"].rigid_body_constraint
        self.assertEqual((hinge.type, hinge.object1.name, hinge.object2.name), ("HINGE", "PivotShape", "ArmShape"))
        self.assertTrue(hinge.use_limit_ang_z)
        self.assertAlmostEqual(hinge.limit_ang_z_lower, -0.8, places=5)

    # --- what is written back -------------------------------------------------------------------------------------

    def test_the_physics_is_written_back(self):
        self._import()
        root = self._export()[1]
        world = root.find(".//RigidBodyCollection")
        self.assertIsNotNone(world)
        self.assertEqual((world.get("DEF"), world.get("iterations")), ("World", "20"))
        self.assertEqual([round(v, 4) for v in _floats(world.get("gravity"))], [0.0, -1.62, 0.0])
        bodies = self._bodies(root)
        self.assertEqual(set(bodies), {"Ground", "Ball", "Pivot", "Arm"})
        self.assertEqual(bodies["Ground"].get("fixed"), "true")
        self.assertEqual([round(v, 4) for v in _floats(bodies["Ball"].get("position"))], [-2.0, 3.0, 0.0],
                         "the body, not the shape inside its CollidableOffset")
        self.assertEqual((bodies["Ball"].get("mass"), bodies["Ball"].get("linearVelocity")), ("2.500000", "1 0 0"))
        offset = bodies["Ball"].find("CollidableOffset")
        self.assertEqual((offset.get("DEF"), offset.get("translation")), ("BallOffset", "0 -0.5 0"))
        self.assertEqual(offset.find("CollidableShape").find("Shape").get("containerField"), "shape")
        self.assertEqual(bodies["Arm"].get("autoDamp"), "true")
        self.assertEqual(bpy.data.objects.get("Hinge") is not None, True)
        self.assertNotIn("OB_Hinge", {t.get("DEF") for t in root.iter("Transform")}, "a joint's empty is not a Transform")
        self.assertFalse({"OB_BallShape", "OB_GroundShape"} & {t.get("DEF") for t in root.iter("Transform")},
                         "a body's shapes are written in its RigidBody, not a second time")
        collider = world.find("CollisionCollection")
        self.assertEqual((collider.get("DEF"), collider.get("bounce")), ("Contacts", "0.2"))
        self.assertEqual(sorted((c.tag, c.get("USE")) for c in collider),
                         [("CollidableOffset", "BallOffset"), ("CollidableShape", "ArmShape"),
                          ("CollidableShape", "GroundShape")])
        hinge = world.find("SingleAxisHingeJoint")
        self.assertEqual([round(v, 4) for v in _floats(hinge.get("anchorPoint"))], [2.0, 3.0, 0.0])
        self.assertEqual([round(v, 4) for v in _floats(hinge.get("axis"))], [0.0, 0.0, 1.0])
        self.assertEqual((float(hinge.get("minAngle")), float(hinge.get("maxAngle")), hinge.get("forceOutput")),
                         (-0.8, 0.8, '"angle"'))
        self.assertEqual([(b.get("USE"), b.get("containerField")) for b in hinge.findall("RigidBody")],
                         [("Pivot", "body1"), ("Arm", "body2")])
        self.assertIn(("RigidBodyPhysics", "2"), [(c.get("name"), c.get("level")) for c in root.iter("component")])

    def test_edits_in_blender_reach_the_file(self):
        self._import()
        bpy.context.scene.gravity = (0.0, 0.0, -9.8)
        bpy.data.objects["BallShape"].rigid_body.mass = 4.0
        bpy.data.objects["ArmShape"].rigid_body.type = "PASSIVE"
        bpy.data.objects["Hinge"].rigid_body_constraint.limit_ang_z_upper = 1.2
        root = self._export()[1]
        world = root.find(".//RigidBodyCollection")
        self.assertIsNone(world.get("gravity"), "Earth gravity is X3D's default")
        bodies = self._bodies(root)
        self.assertEqual(bodies["Ball"].get("mass"), "4.000000")
        self.assertEqual(bodies["Arm"].get("fixed"), "true")
        self.assertEqual(float(world.find("SingleAxisHingeJoint").get("maxAngle")), 1.2)

    def test_a_rigid_body_made_in_blender_is_written(self):
        bpy.ops.mesh.primitive_cube_add(location=(0.0, 0.0, 2.0))
        cube = bpy.context.active_object
        bpy.ops.rigidbody.object_add(type="ACTIVE")
        cube.rigid_body.mass = 3.0
        root = self._export()[1]
        body = root.find(".//RigidBodyCollection/RigidBody")
        self.assertIsNotNone(body)
        self.assertEqual(float(body.get("mass")), 3.0)      # physics_export writes the shortest spelling
        self.assertEqual([round(v, 4) for v in _floats(body.get("position"))], [0.0, 2.0, 0.0], "Blender Z is X3D Y")
        # physics_export keeps the shape inside the RigidBody's geometry and leaves the CollisionCollection's list empty
        # (X_ITE 16.8.1 collides a body by its geometry); batch 6 listed it by USE. Which reading the standard intends is
        # one of the questions held for Web3D (docs/PHYSICS.md).
        self.assertIsNotNone(body.find("CollidableShape"))

    def test_a_scaled_rigid_body_is_written_with_its_scale_in_the_shape(self):
        bpy.ops.mesh.primitive_cube_add(location=(0.0, 0.0, 2.0))
        cube = bpy.context.active_object
        cube.scale = (2.0, 1.0, 1.0)
        bpy.ops.rigidbody.object_add(type="ACTIVE")
        root = self._export()[1]
        # physics_export (RigidBodyPhysics change) writes the body and bakes the scale into the collision shape, where the
        # node board's batch 6 left such a body as a plain Transform. A RigidBody has no scale field either way.
        self.assertEqual(len(list(root.iterfind(".//RigidBodyCollection/RigidBody"))), 1)
        self.assertTrue(all(b.get("scale") is None for b in root.iter("RigidBody")))

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
