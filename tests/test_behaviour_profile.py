# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Speed without a change of answer (P7): each faster way of doing a sum in the simulator is held against the slow way it
replaced. Random inputs come from a seeded generator, so a failure repeats. No Blender; numpy is not used.

    python -m unittest tests.test_behaviour_profile
"""

from __future__ import annotations

import gc
import math
import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "source"))

import behaviour_graph as bg                     # noqa: E402
import behaviour_sim as bs                       # noqa: E402
import behaviour_world as bw                     # noqa: E402


def old_m_mul(a, b):
    return tuple(a[r * 4] * b[c] + a[r * 4 + 1] * b[4 + c] + a[r * 4 + 2] * b[8 + c] + a[r * 4 + 3] * b[12 + c]
                 for r in range(4) for c in range(4))


def old_separated(axes, points1, points2):
    for axis in axes:
        low1 = min(bw._dot(p, axis) for p in points1)
        high1 = max(bw._dot(p, axis) for p in points1)
        low2 = min(bw._dot(p, axis) for p in points2)
        high2 = max(bw._dot(p, axis) for p in points2)
        if not ((low1 <= low2 <= high1) or (low2 <= low1 <= high2)):
            return True
    return False


class ArithmeticIsTheSameTests(unittest.TestCase):

    def test_the_unrolled_matrix_product_has_the_same_bits(self):
        rng = random.Random(7)
        for _ in range(20000):
            a = tuple(rng.uniform(-1e3, 1e3) * rng.choice((1, 1, 1e-6, 1e6)) for _ in range(16))
            b = tuple(rng.uniform(-1e3, 1e3) for _ in range(16))
            self.assertEqual(bw.m_mul(a, b), old_m_mul(a, b))

    def test_the_separating_axis_loop_gives_the_same_verdict(self):
        rng = random.Random(8)
        for _ in range(3000):
            points1 = [tuple(rng.uniform(-5, 5) for _ in range(3)) for _ in range(8)]
            points2 = [tuple(rng.uniform(-5, 5) + 4 for _ in range(3)) for _ in range(8)]
            axes = [tuple(rng.uniform(-1, 1) for _ in range(3)) for _ in range(5)]
            self.assertEqual(bw._separated(axes, points1, points2), old_separated(axes, points1, points2))


class FrustumRejectIsExactTests(unittest.TestCase):
    """``World.sees_box`` settles a box that is wholly outside a plane of the view volume, or wholly inside all six, without the
    separating-axis test. It must answer what ``frustum_meets_box`` answers, for every box."""

    @staticmethod
    def world():
        text = '<X3D profile="Immersive" version="4.0"><head/><Scene><Transform DEF="T"><VisibilitySensor DEF="V" size="1 1 1"/></Transform></Scene></X3D>'
        return bw.World.from_x3d(text)

    @staticmethod
    def reference(world, center, size):
        """What ``sees_box`` was before: the full test for every box that is not size -1."""
        camera_inverse = world.camera()[1]
        m = bw.m_mul(camera_inverse, world.sensor_matrix("V"))
        half_axes = tuple(bw.m_dir(m, tuple(size[k] / 2 if j == k else 0.0 for k in range(3))) for j in range(3))
        corners, _planes = world.frustum()
        return bw.frustum_meets_box(corners, bw.m_point(m, center), half_axes)

    def check(self, world, center, size):
        self.assertEqual(world.sees_box("V", center, size), self.reference(world, center, size), (center, size))

    def test_a_hundred_thousand_random_boxes(self):
        rng = random.Random(2026)
        world = self.world()
        counts = {True: 0, False: 0}
        for trial in range(100_000):
            if trial % 50 == 0:        # a new camera and a new place for the sensor's frame now and then
                position = tuple(rng.uniform(-8, 8) for _ in range(3))
                axis = [rng.uniform(-1, 1) for _ in range(3)]
                length = math.sqrt(sum(c * c for c in axis)) or 1.0
                world.set_viewer(position, (*[c / length for c in axis], rng.uniform(-math.pi, math.pi)),
                                 field_of_view=rng.choice((math.pi / 4, 1.0, 2.0)), aspect=rng.choice((1.6, 1.0, 0.6)))
                world.apply("T", "translation", tuple(rng.uniform(-6, 6) for _ in range(3)))
                axis = [rng.uniform(-1, 1) for _ in range(3)]
                length = math.sqrt(sum(c * c for c in axis)) or 1.0
                world.apply("T", "rotation", (*[c / length for c in axis], rng.uniform(-math.pi, math.pi)))
            center = tuple(rng.uniform(-14, 14) for _ in range(3))
            size = tuple(rng.choice((0.0, rng.uniform(0, 8), rng.uniform(0, 0.5))) for _ in range(3))
            expected = self.reference(world, center, size)
            counts[expected] += 1
            self.assertEqual(world.sees_box("V", center, size), expected, (trial, center, size))
        self.assertGreater(min(counts.values()), 5000, counts)      # both answers are well represented

    def test_the_three_tilt_probes_of_probe_world(self):
        # boxes a plane cannot settle that the recording of X_ITE 16.8.1 (Tilt1 to Tilt3, probe-world.x3d) decides by the
        # edge axes; the one box of FrustumTests whose edge axis is lost is the first
        world = self.world()
        world.set_viewer((0.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0), field_of_view=math.pi / 4, aspect=1.6, near=0.125, far=1e5)
        center = (8.631316465059008, 4.928101777844059, -10.6240057606209)
        turn = (0.10736909890728152, -0.17561050934733058, 0.4312866688319401, 0.8435011118533233)
        angle = 2 * math.acos(turn[3])
        s = math.sin(angle / 2)
        world.apply("T", "translation", center)
        world.apply("T", "rotation", (turn[0] / s, turn[1] / s, turn[2] / s, angle))
        size = (0.36960700697205084, 2.7627097636551996, 3.5885882632767694)
        self.check(world, (0.0, 0.0, 0.0), size)
        self.assertTrue(world.sees_box("V", (0.0, 0.0, 0.0), size))          # X_ITE's answer, which the exact test would not give

    def test_size_minus_one_is_always_in(self):
        self.assertTrue(self.world().sees_box("V", (100.0, 0.0, 0.0), (-1.0, -1.0, -1.0)))


class ListFollowerSpeedTests(unittest.TestCase):

    def test_points_made_from_floats_are_a_plain_list_to_everything_but_the_two_checks(self):
        damper = bs._CoordinateDamper.__new__(bs._CoordinateDamper)
        flat = [0.5, 1.5, -2.0, 3.0, 4.0, 5.0]
        marked, plain = damper.points(flat, floats=True), damper.points(flat)
        self.assertIs(type(marked), bs._Points)
        self.assertIs(type(plain), list)
        self.assertEqual(marked, plain)
        self.assertEqual(repr(marked), repr(plain))
        self.assertEqual(marked, [(0.5, 1.5, -2.0), (3.0, 4.0, 5.0)])
        self.assertTrue(bs._finite(marked))
        self.assertTrue(bs._fitter("MFVec3f")(marked))
        self.assertFalse(bs._fitter("MFVec2f")(marked))          # three numbers a point do not fit a list of Vec2f

    def test_a_list_with_an_infinity_or_a_nan_is_never_marked_so_the_checks_still_drop_it(self):
        damper = bs._CoordinateDamper.__new__(bs._CoordinateDamper)
        for bad in (math.inf, -math.inf, math.nan):
            found = damper.points([1.0, 2.0, bad], floats=True)
            self.assertIs(type(found), list)
            self.assertFalse(bs._finite(found))
        found = damper.points([1e308, 1e308, 1.0], floats=True)      # finite numbers whose sum overflows: the slow check, right answer
        self.assertTrue(bs._finite(found))

    def test_a_follower_whose_values_overflow_still_drops_what_is_not_a_number(self):
        g = bg.Behaviour()
        g.add("CoordinateDamper", "D", initialDestination="0 0 0", initialValue="0 0 0", tau=0.3)
        g.target("Coordinate", "C")
        g.route("D", "value_changed", "C", "point")
        sim = bs.Simulation(g)
        sim.start(0.0)
        sim.post("D", "value_changed", [(1.0, 2.0, 3.0)])
        self.assertEqual(sim.outputs[("C", "point")], [(1.0, 2.0, 3.0)])
        for k in range(1, 5):
            sim.step(k / 60)
        self.assertEqual(sim.faults, [])
        sim.post("D", "value_changed", [(math.inf, 0.0, 0.0)])
        self.assertEqual(sim.outputs[("C", "point")], [(1.0, 2.0, 3.0)])      # an infinity is dropped, the last value stands
        self.assertEqual(sim.dropped["non-finite"], 1)


class CollectorTests(unittest.TestCase):

    def test_the_collector_is_off_for_a_step_and_back_as_it_was(self):
        sim = bs.Simulation(bg.Behaviour())
        seen = []
        original = sim._advance
        sim._advance = lambda now: seen.append(gc.isenabled()) or original(now)
        for before in (True, False):
            (gc.enable if before else gc.disable)()
            try:
                sim.step(0.0)
                self.assertIs(gc.isenabled(), before)
            finally:
                gc.enable()
        self.assertEqual(seen, [False, False])

    def test_an_error_in_a_step_leaves_the_collector_on(self):
        sim = bs.Simulation(bg.Behaviour())
        sim._advance = lambda now: 1 / 0
        gc.enable()
        with self.assertRaises(ZeroDivisionError):
            sim.step(0.0)
        self.assertTrue(gc.isenabled())


if __name__ == "__main__":
    unittest.main()
