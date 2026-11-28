# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Reading X3D RigidBodyPhysics into plain data (source/physics_model.py; no bpy)."""

from __future__ import annotations

import math
import sys
import unittest
import xml.dom.minidom
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "source"))

import physics_model as pm  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "physics" / "fixtures"


def read(text):
    return pm.read_physics(xml.dom.minidom.parseString(text).documentElement)


def scene(body):
    return f"<X3D profile='Full' version='4.0'><Scene>{body}</Scene></X3D>"


class Defaults(unittest.TestCase):
    def test_unset_fields_take_the_standards_defaults(self):
        ph = read(scene("<RigidBodyCollection><RigidBody DEF='B'><CollidableShape containerField='geometry'>"
                        "<Shape containerField='shape'><Box/></Shape></CollidableShape></RigidBody></RigidBodyCollection>"))
        col = ph.collections[0]
        self.assertEqual(col.fields["gravity"], (0.0, -9.8, 0.0))
        self.assertEqual(col.fields["iterations"], 10)
        body = col.bodies[0]
        self.assertEqual(body.fields["mass"], 1.0)
        self.assertFalse(body.fields["autoDamp"])
        self.assertEqual(body.fields["orientation"], (0.0, 0.0, 1.0, 0.0))
        self.assertEqual([s.kind for s in body.shapes], ["Box"])
        self.assertEqual(ph.losses, [])

    def test_a_wrong_count_of_numbers_keeps_the_default(self):
        ph = read(scene("<RigidBodyCollection gravity='0 -1'/>"))
        self.assertEqual(ph.collections[0].fields["gravity"], (0.0, -9.8, 0.0))


class Contact(unittest.TestCase):
    def collider(self, attrs):
        return read(scene(f"<RigidBodyCollection><CollisionCollection containerField='collider' {attrs}/>"
                          "</RigidBodyCollection>")).collections[0]

    def test_bounce_counts_only_when_applied(self):
        self.assertEqual(self.collider("bounce='0.5'").contact()[0], 0.5)          # BOUNCE is the default
        self.assertEqual(self.collider("bounce='0.5' appliedParameters='\"FRICTION_COEFFICIENT-2\"'").contact()[0], 0.0)

    def test_friction_is_the_first_coefficient_when_applied_and_0_25_otherwise(self):
        self.assertEqual(self.collider("frictionCoefficients='0.2 0.2' appliedParameters='\"FRICTION_COEFFICIENT-2\"'")
                         .contact()[1], 0.2)
        self.assertEqual(self.collider("frictionCoefficients='0.2 0.2' appliedParameters='\"USER_FRICTION\"'")
                         .contact()[1], 0.2)
        self.assertEqual(self.collider("frictionCoefficients='0.2 0.2'").contact()[1], pm.UNSET_FRICTION)

    def test_both_spellings_of_the_friction_parameter_are_read(self):
        # the standard's text and XSD documentation: FRICTION_COEFFICIENT-2; x3d.py, X3DJSAIL and X_ITE: ..._2
        for spelling in ("FRICTION_COEFFICIENT-2", "FRICTION_COEFFICIENT_2"):
            ph = read(scene("<RigidBodyCollection><CollisionCollection containerField='collider' "
                            f"frictionCoefficients='0.3 0.3' appliedParameters='\"{spelling}\"'/></RigidBodyCollection>"))
            self.assertEqual(ph.collections[0].contact()[1], 0.3)
            self.assertEqual(ph.losses, [])

    def test_a_disabled_collider_applies_nothing(self):
        self.assertEqual(self.collider("enabled='false' bounce='0.9'").contact()[:2], (0.0, pm.UNSET_FRICTION))


class Structure(unittest.TestCase):
    def test_use_is_a_reference_and_offsets_nest(self):
        ph = read(scene(
            "<Transform><Shape DEF='S'><Sphere radius='0.2'/></Shape></Transform>"
            "<RigidBodyCollection><RigidBody DEF='B' position='1 2 3'>"
            "<CollidableOffset containerField='geometry' translation='0 1 0'>"
            "<CollidableShape containerField='collidable' translation='1 0 0'><Shape USE='S' containerField='shape'/>"
            "</CollidableShape></CollidableOffset></RigidBody>"
            "<BallJoint containerField='joints'><RigidBody USE='B' containerField='body1'/>"
            "<RigidBody USE='B' containerField='body2'/></BallJoint></RigidBodyCollection>"))
        body = ph.collections[0].bodies[0]
        self.assertEqual(len(ph.collections[0].bodies), 1)          # the joint's USEs made no second body
        (shape,) = body.shapes
        self.assertEqual(shape.kind, "Sphere")
        self.assertEqual((shape.local[0][3], shape.local[1][3], shape.local[2][3]), (1.0, 1.0, 0.0))
        joint = ph.collections[0].joints[0]
        self.assertEqual((joint.body1, joint.body2), ("B", "B"))

    def test_a_joint_with_one_body_is_a_loss(self):
        ph = read(scene("<RigidBodyCollection><RigidBody DEF='B'><CollidableShape containerField='geometry'>"
                        "<Shape containerField='shape'><Box/></Shape></CollidableShape></RigidBody>"
                        "<SingleAxisHingeJoint containerField='joints'><RigidBody USE='B' containerField='body1'/>"
                        "</SingleAxisHingeJoint></RigidBodyCollection>"))
        self.assertTrue(any(w.startswith("SingleAxisHingeJoint") for w, _f, _y in ph.losses))

    def test_two_collections_share_one_world(self):
        ph = read(scene("<RigidBodyCollection/><RigidBodyCollection gravity='0 0 0'/>"))
        self.assertEqual(len(ph.collections), 2)
        self.assertTrue(any("one rigid body world" in why for _w, _f, why in ph.losses))


class Losses(unittest.TestCase):
    def test_every_ode_only_field_of_the_physx_bridges_experiment_is_listed(self):
        # x3d.loom physx-bridge scenes/experiments/ode-only-fields.x3d: the fields PhysX could not honour
        doc = xml.dom.minidom.parse(str(FIXTURES / "ode-only-fields.x3d")).documentElement
        ph = pm.read_physics(doc)
        fields = {f for _w, f, _y in ph.losses}
        for expected in ("errorCorrection", "constantForceMix", "useFiniteRotation", "disableTime", "slipFactors",
                         "softnessErrorCorrection"):
            self.assertIn(expected, fields)

    def test_defaults_written_out_are_not_losses(self):
        ph = read(scene("<RigidBodyCollection errorCorrection='0.8' preferAccuracy='false'><RigidBody DEF='B' "
                        "inertia='1 0 0 0 1 0 0 0 1'><CollidableShape containerField='geometry'><Shape containerField='shape'>"
                        "<Box/></Shape></CollidableShape></RigidBody></RigidBodyCollection>"))
        self.assertEqual(ph.losses, [])


class Inertia(unittest.TestCase):
    def test_bullets_formulas(self):
        self.assertAlmostEqual(pm.principal_inertia("SPHERE", (1, 1, 1), 2.0)[0], 0.4 * 2 * 0.25)
        ix, iy, iz = pm.principal_inertia("BOX", (0.8, 2.0, 0.1), 1.0)
        self.assertAlmostEqual(iy, (0.8 ** 2 + 0.1 ** 2) / 12)
        hull = pm.principal_inertia("CONVEX_HULL", (1, 1, 1), 1.0, margin=0.04)
        self.assertAlmostEqual(hull[0], (1.08 ** 2 * 2) / 12)

    def test_rotation_matrix_is_a_rotation(self):
        r = pm.rotation_matrix((0, 0, 1, math.pi / 2))
        self.assertAlmostEqual(r[0][1], -1.0)
        self.assertAlmostEqual(r[1][0], 1.0)


class ExportValidation(unittest.TestCase):
    def test_several_applied_parameters_are_valid_and_a_wrong_one_is_not(self):
        try:
            import x3d.x3d as x3d_module
        except Exception:
            self.skipTest("x3d.py is not installed")
        import xml.etree.ElementTree as ET
        import validate

        def check(value):
            root = ET.fromstring("<X3D version='4.0'><Scene><RigidBodyCollection><CollisionCollection containerField="
                                 f"'collider' appliedParameters='{value}'/></RigidBodyCollection></Scene></X3D>")
            return validate.validate_tree_with_x3d_py(root, x3d_module).valid
        self.assertTrue(check('"BOUNCE" "FRICTION_COEFFICIENT_2"'))
        self.assertTrue(check('"BOUNCE"'))
        self.assertFalse(check('"BOUNCE" "NOT_A_PARAMETER"'))


if __name__ == "__main__":
    unittest.main()
