# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Faults the hostile fuzzer found in the older machines, each now an answer instead of an isolated node.

A contained fault is allowed (the simulator isolates the node and counts it in ``sim.faults``), but each one is a place
where it stops answering. Every case here ran into a ZeroDivisionError, an OverflowError or a ValueError at one line of
``behaviour_sim`` before the fix; the line is named in the test. ::

    python -m unittest tests.test_behaviour_faults
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "source"))

sys.path.insert(0, str(ROOT / "tools"))

import behaviour_graph as bg                     # noqa: E402
import behaviour_sim as bs                       # noqa: E402
import behaviour_sim_judge_mf as judge_mf        # noqa: E402


def run(kind, destination, steps=12, **fields):
    g = bg.Behaviour()
    g.add(kind, "F", **fields)
    sim = bs.Simulation(g)
    sim.start(0.0)
    sim.send("F", "set_destination", destination, 0.0)
    for k in range(1, steps):
        sim.step(k / 60)
    return sim


DESTINATIONS = {"PositionChaser": (1.0, 2.0, 3.0), "PositionChaser2D": (1.0, 2.0), "ColorChaser": (0.2, 0.4, 0.8),
                "OrientationChaser": (0.0, 1.0, 0.0, 1.0)}


class ZeroDurationTests(unittest.TestCase):
    """_BufferChaser._shift divided by ``duration / 60``: 0 (and an underflowed 1e-320) is zero."""

    def test_a_chaser_with_no_duration_arrives_at_once_as_the_scalar_chaser_does(self):
        for kind, destination in DESTINATIONS.items():
            for duration in (0, 1e-320, -1):
                with self.subTest(kind=kind, duration=duration):
                    sim = run(kind, destination, duration=duration)
                    self.assertEqual(sim.faults, [])
                    value = sim.outputs[("F", "value_changed")]
                    for got, want in zip(value, destination):
                        self.assertAlmostEqual(got, want, places=6)
                    self.assertIs(sim.outputs[("F", "isActive")], False)

    def test_a_duration_so_small_that_one_step_is_infinite_jumps_too(self):
        for kind, destination in DESTINATIONS.items():
            with self.subTest(kind=kind):
                sim = run(kind, destination, duration=1e-300)
                self.assertEqual(sim.faults, [])
                self.assertIs(sim.outputs[("F", "isActive")], False)

    def test_an_ordinary_duration_is_untouched(self):
        sim = run("PositionChaser", (1.0, 2.0, 3.0), steps=6, duration=1.0)
        self.assertEqual(sim.faults, [])
        self.assertIs(sim.outputs[("F", "isActive")], True)
        self.assertTrue(0 < sim.outputs[("F", "value_changed")][0] < 1)


class ColourTests(unittest.TestCase):
    def test_a_colour_with_a_zero_top_and_a_negative_part_is_a_grey_not_a_division(self):
        # colorsys.rgb_to_hsv divided by the top (0) at ``s = rangec / maxc``
        self.assertEqual(bs._hsv_of((0.0, -1.0, -1.0)), (0.0, 0.0, 0.0))
        self.assertEqual(bs.hsv_lerp((0.0, -1.0, -1.0), (0.0, -1.0, -1.0), 0.5), (0.0, 0.0, 0.0))
        g = bg.Behaviour()
        g.add("ColorDamper", "D", initialDestination="0 -1 -1", initialValue="0.5 0.5 0.5")
        sim = bs.Simulation(g)
        sim.start(0.0)
        for k in range(1, 20):
            sim.step(k / 60)
        self.assertEqual(sim.faults, [])

    def test_a_colour_of_1e308_has_no_hue_and_is_not_a_number_not_an_exception(self):
        # colorsys.hsv_to_rgb raised ValueError (NaN to integer); the drain drops a non-finite value and counts it
        out = bs.hsv_lerp((-1.0, 1.5, -0.9), (-1e308, 1e308, 1e308), 0.5)
        self.assertEqual(len(out), 3)
        self.assertTrue(all(isinstance(c, float) for c in out))


class CylinderTests(unittest.TestCase):
    def test_a_press_on_the_axis_has_radius_zero_and_no_track_not_a_division(self):
        # CylinderSensor._cylinder_track: ``distance = ... / self.radius``
        b = bg.Behaviour()
        b.add("CylinderSensor", "C")
        sim = bs.Simulation(b)
        sim.start(0.0)
        out = sim.press("C", 0.0, (0, 0, 0), ((0, 0, 5), (0, 0, -1)), ((0, 0, 5), (0, 0, 1)))
        self.assertEqual(sim.faults, [])
        self.assertIsInstance(out, list)
        sim.release("C", 1.0)
        self.assertEqual(sim.faults, [])

    def test_interval_of_an_infinity_is_not_a_number_as_in_javascript(self):
        self.assertTrue(math.isnan(bs._interval(math.inf, -1, 1)))
        self.assertTrue(math.isnan(bs._interval(-math.inf, -1, 1)))
        self.assertEqual(bs._interval(2.5, -1, 1), 0.5)


class HandlerTests(unittest.TestCase):
    def test_a_handler_that_answers_with_a_number_is_dropped_and_counted(self):
        b = bg.Behaviour()
        b.add("Script", "S", declared=[("x", "SFFloat", "inputOnly"), ("y", "SFFloat", "outputOnly")])
        sim = bs.Simulation(b)
        sim.host("S", lambda field, value, now, state: 7)
        sim.start(0.0)
        sim.send("S", "x", 1.0, 0.0)
        self.assertEqual(sim.faults, [])
        self.assertGreaterEqual(sim.dropped.get("mismatch", 0), 1)


class FollowerEventCountTests(unittest.TestCase):
    """The list followers send isActive false and true in one time stamp, and so does X_ITE 16.8.1. The judge merged X_ITE's
    events of one stamp (131 to 138 per stream) but counted the simulator's raw (252 to 270): the same behaviour looked like
    two to one. The judge now reports X_ITE's raw count, and the stamps where the two sent another number of events."""

    def setUp(self):
        import json
        trace = json.loads((ROOT / "tests" / "behaviour" / "x_ite_traces" / "probe-list-followers.json").read_text(encoding="utf-8"))
        result = judge_mf.judge(ROOT / "tests" / "behaviour" / "probe-list-followers.x3d", trace)
        self.streams = {s["source"]: s for s in result["streams"]}
        self.trace = trace

    def test_x_ite_sends_the_same_stamp_pairs_and_the_raw_counts_are_close(self):
        for name in ("Chase3", "Chase2", "Damp3", "Damp2"):
            with self.subTest(stream=name):
                s = self.streams[f"{name}.isActive"]
                self.assertTrue(s["agree"])
                self.assertLess(s["x_ite_events"], 140)                       # merged: what the judge always compared
                self.assertGreater(s["x_ite_raw_events"], 250)                # as X_ITE sent them
                self.assertLessEqual(abs(s["simulator_events"] - s["x_ite_raw_events"]), 8)
                self.assertLessEqual(s["stamps_with_other_event_count"], 3)   # the start of the recording, one frame of a damper

    def test_x_ite_itself_sends_false_then_true_in_one_time_stamp(self):
        stamps = [e[0] for e in self.trace["events"] if e[1] == "Chase3" and e[2] == "isActive"]
        self.assertGreater(len(stamps) - len(set(stamps)), 100)

    def test_a_stream_the_simulator_sends_twice_as_often_is_visible(self):
        theirs, ours = [(1.0, True), (2.0, False)], [(1.0, True), (1.0, False), (2.0, False), (2.0, False)]
        self.assertEqual(judge_mf._judge._stamps_that_differ(theirs, ours), 2)
        self.assertEqual(judge_mf._judge._stamps_that_differ(theirs, theirs), 0)


if __name__ == "__main__":
    unittest.main()
