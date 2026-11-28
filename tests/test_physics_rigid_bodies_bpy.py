# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""X3D RigidBodyPhysics as Blender's rigid body world (source/physics_blender.py), judged on the analytic ladder.

Each fixture of tests/physics/fixtures is imported with the operator, simulated in Blender, and measured by
tools/physics_judge.py against tests/physics/limits.json (committed before the measured run; docs/PHYSICS.md). The
wrong twins below change one thing after the import (Blender's default damping, friction not square-rooted, no
start-up impulse, no hinge stop) and must fail the same gates: a gate that cannot fail says nothing. Skipped when bpy is
not importable::

    cd tests && python -m unittest test_physics_rigid_bodies_bpy
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))
FIXTURES = ROOT / "tests" / "physics" / "fixtures"
LIMITS = json.loads((ROOT / "tests" / "physics" / "limits.json").read_text())
RECEIPTS = json.loads((ROOT / "tests" / "physics" / "receipts.json").read_text())

if HAVE_BPY:
    from test_roundtrip_bpy import _register_extension
    from physics_blender_record import record
    from physics_judge import SCENES, free_fall_error, judge
    from physics_receipt import verdict


def run(fixture, after_import=None, options=None, seconds=None):
    seconds = seconds if seconds is not None else SCENES[fixture][1]
    tr = record(str(FIXTURES / fixture), seconds, 60, options=options, after_import=after_import)
    tr.update(file=fixture, dt=1 / 60, fps=60, engine="blender")
    return tr


def failures(fixture, metrics):
    return {k for k, lim in LIMITS[fixture].items() if verdict(metrics.get(k), lim) == "fail"}


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class Ladder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _register_extension(tempfile.mkdtemp(prefix="x3d_physics_"))

    def check(self, fixture):
        metrics = judge(run(fixture))
        expected = {k for k, lim in LIMITS[fixture].items() if lim.get("expect") == "fail"}
        self.assertEqual(failures(fixture, metrics), expected, metrics)
        return metrics

    def test_stack_rests(self):
        self.check("stack3.x3d")

    def test_slope_slides_with_the_authored_friction(self):
        self.check("slope-mu0.2.x3d")

    def test_pendulum_keeps_its_period_and_amplitude(self):
        self.check("pendulum-ball.x3d")

    def test_hinge_stops_at_its_limit(self):
        self.check("hinge-limit.x3d")

    def test_slider_stops_at_its_separation(self):
        self.check("slider-limit.x3d")

    def test_billiards_exchange_velocities(self):
        self.check("billiards-head-on.x3d")

    def test_drop_lands_but_loses_its_bounce(self):
        # the apex gate is expected to fail (Blender 5.3's restitution at small steps, docs/PHYSICS.md); if Blender
        # starts keeping the bounce, this test says so and the limit's "expect" should be dropped
        self.check("drop-bounce.x3d")

    def test_free_fall_is_the_discrete_answer_and_x_ites(self):
        tr = run("drop-bounce.x3d")
        self.assertLessEqual(free_fall_error(tr, "S", 5.0, 10), LIMITS["free_fall"]["discrete_euler_max_m"])
        theirs = RECEIPTS["fixtures"]["drop-bounce.x3d"]["x_ite"]["drop_y_first_55_frames"]
        ours = [p[1] for p in tr["trajectories"]["S"]["p"][:55]]
        self.assertLessEqual(max(abs(a - b) for a, b in zip(ours, theirs)),
                             LIMITS["free_fall"]["x_ite_agreement_before_contact_m"])

    def test_a_second_import_replays_the_same_states(self):
        a, b = run("pendulum-ball.x3d", seconds=3), run("pendulum-ball.x3d", seconds=3)
        self.assertEqual(sum(x != y for x, y in zip(a["hashes"], b["hashes"])), LIMITS["determinism"]["replay_mismatches"])


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class WrongTwins(unittest.TestCase):
    """Each changes one mapping back to what a naive import would do; each must fail its gate."""

    @classmethod
    def setUpClass(cls):
        _register_extension(tempfile.mkdtemp(prefix="x3d_physics_"))

    def bodies(self):
        return [ob for ob in bpy.data.objects if ob.rigid_body is not None and "x3d_rigid_body" in ob.keys()]

    def test_blenders_default_damping_fails_the_pendulum(self):
        def damp(_scene):
            for ob in self.bodies():
                ob.rigid_body.linear_damping, ob.rigid_body.angular_damping = 0.04, 0.1
        self.assertIn("amplitude in the last 3 s (m), start 0.347",
                      failures("pendulum-ball.x3d", judge(run("pendulum-ball.x3d", damp))))

    def test_friction_given_whole_to_each_body_fails_the_slope(self):
        def whole(_scene):
            for ob in self.bodies():
                ob.rigid_body.friction = 0.2       # Bullet multiplies: the contact gets 0.04
        self.assertIn("acceleration (m/s2), analytic 3.19",
                      failures("slope-mu0.2.x3d", judge(run("slope-mu0.2.x3d", whole))))

    def test_no_start_up_impulse_fails_the_billiards(self):
        def drop_launch(_scene):
            for ob in [o for o in bpy.data.objects if str(o.get("x3d_physics_helper", "")).startswith("launch")]:
                bpy.data.objects.remove(ob)
        self.assertIn("B speed after (m/s), analytic 3",
                      failures("billiards-head-on.x3d", judge(run("billiards-head-on.x3d", drop_launch))))

    def test_no_hinge_stop_fails_the_hinge(self):
        def free(_scene):
            for ob in bpy.data.objects:
                if ob.rigid_body_constraint is not None and ob.rigid_body_constraint.type == "HINGE":
                    ob.rigid_body_constraint.use_limit_ang_z = False
        self.assertIn("max angle (rad), limit 1.0",
                      failures("hinge-limit.x3d", judge(run("hinge-limit.x3d", free))))


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class Import(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _register_extension(tempfile.mkdtemp(prefix="x3d_physics_"))

    def load(self, name, **options):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.context.scene.render.fps = 60
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=str(FIXTURES / name), **options), {"FINISHED"})
        return bpy.context.scene

    def test_physics_off_keeps_only_the_geometry(self):
        scene = self.load("drop-bounce.x3d", physics=False)
        self.assertIsNone(scene.rigidbody_world)
        self.assertFalse(any(ob.rigid_body for ob in bpy.data.objects))

    def test_world_settings(self):
        scene = self.load("drop-bounce.x3d")
        world = scene.rigidbody_world
        self.assertEqual(world.substeps_per_frame, 10)        # 1/600 s, X_ITE's step at 60 frames a second
        self.assertEqual(world.solver_iterations, 10)
        self.assertAlmostEqual(scene.gravity[2], -9.8, places=5)     # Y up in the file, Z up here
        sphere = bpy.data.objects["S"].rigid_body
        self.assertEqual((sphere.type, sphere.collision_shape), ("ACTIVE", "SPHERE"))
        self.assertAlmostEqual(sphere.restitution ** 2, 0.5, places=6)   # Bullet multiplies the two bodies' values
        self.assertEqual((sphere.linear_damping, sphere.angular_damping), (0.0, 0.0))
        self.assertEqual(bpy.data.objects["G"].rigid_body.type, "PASSIVE")

    def test_the_step_stays_x_ites_at_24_frames_a_second(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.context.scene.render.fps = 24
        bpy.ops.import_scene.x3d(filepath=str(FIXTURES / "drop-bounce.x3d"))
        self.assertEqual(bpy.context.scene.rigidbody_world.substeps_per_frame, 25)

    def test_a_routed_transform_follows_its_body_and_the_route_is_not_a_loss(self):
        scene = self.load("route-follow.x3d")
        losses = json.loads(scene.get("x3d_import_losses", "[]"))
        self.assertFalse([r for r in losses if r["kind"] == "route"], losses)
        body = next(ob for ob in bpy.data.objects if "x3d_rigid_body" in ob.keys()
                    and json.loads(ob["x3d_rigid_body"])["name"] == "BoxBody")
        self.assertTrue(body.hide_render)          # the collidable is a stand-in once a Transform shows the body
        followers = [ob for ob in bpy.data.objects if any(c.target is body for c in ob.constraints)]
        self.assertEqual(len(followers), 1)
        scene.frame_start, scene.frame_end = 1, 90
        scene.rigidbody_world.point_cache.frame_end = 90
        for f in range(1, 91):
            scene.frame_set(f)
        moved = body.matrix_world.translation
        self.assertLess(moved.z, 1.0)              # it fell from 3 m
        self.assertLess((followers[0].matrix_world.translation - moved).length, 1e-5)
        self.assertLess(followers[0].matrix_world.to_quaternion().rotation_difference(
            body.matrix_world.to_quaternion()).angle, 1e-5)

    def test_a_flat_import_follows_with_the_children_offsets(self):
        scene = self.load("route-follow.x3d", keep_hierarchy=False)
        followers = [ob for ob in bpy.data.objects if any(c.type == "CHILD_OF" for c in ob.constraints)]
        self.assertEqual(len(followers), 2)        # the box and the sphere above it
        sphere = next(ob for ob in followers if ob.dimensions.x < 0.6)
        body = next(c.target for c in sphere.constraints)
        offset = (body.matrix_world.inverted() @ sphere.matrix_world).translation.copy()
        scene.frame_start, scene.frame_end = 1, 60
        scene.rigidbody_world.point_cache.frame_end = 60
        for f in range(1, 61):
            scene.frame_set(f)
        self.assertLess(((body.matrix_world.inverted() @ sphere.matrix_world).translation - offset).length, 1e-5)

    def test_losses_name_the_fields_blender_cannot_honour(self):
        scene = self.load("ode-only-fields.x3d")
        details = " ".join(r["detail"] for r in json.loads(scene.get("x3d_import_losses", "[]")) if r["kind"] == "physics")
        for name in ("errorCorrection", "useFiniteRotation", "slipFactors", "stopErrorCorrection"):
            self.assertIn(name, details)


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class RoundTrip(unittest.TestCase):
    """Import, export as X3D 4.0 (schema and x3d.py checked by the export itself), import again: the same ladder."""

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="x3d_physics_rt_")
        _register_extension(cls.tmpdir)

    def roundtrip(self, fixture):
        first = run(fixture)
        bpy.context.scene.frame_set(1)
        out = os.path.join(self.tmpdir, fixture)
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=out, x3d_version="X3D40", use_selection=False), {"FINISHED"})
        tr = record(out, SCENES[fixture][1], 60)
        tr.update(file=fixture, dt=1 / 60, fps=60, engine="blender")
        self.assertEqual(judge(tr), judge(first))
        return Path(out).read_text(encoding="utf-8")

    def test_hinge_with_its_stop_and_start_velocities(self):
        text = self.roundtrip("hinge-limit.x3d")
        self.assertIn('minAngle="-1" maxAngle="1"', text)
        self.assertIn('angularVelocity="0 3 0"', text)
        self.assertIn('toField="set_translation"', text)
        self.assertNotIn("X3D physics anchor", text)      # the import's helpers are not written

    def test_slope_keeps_the_contact_friction(self):
        text = self.roundtrip("slope-mu0.2.x3d")
        self.assertIn('frictionCoefficients="0.2 0.2"', text)

    def test_pendulum_and_billiards(self):
        self.roundtrip("pendulum-ball.x3d")
        self.roundtrip("billiards-head-on.x3d")


if __name__ == "__main__":
    unittest.main()
