# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The behaviour simulator (source/behaviour_sim.py): plain Python, no Blender, no browser.

Two kinds of test. The first states what each node must do, from ISO/IEC 19775-1:2023. The second replays what X_ITE
16.7.1 did with five files (tests/behaviour/x_ite_traces/, recorded by tools/behaviour_sim_judge.cjs with real mouse
clicks) and requires the simulator to send the same events::

    cd tests && python -m unittest test_behaviour_sim
"""

from __future__ import annotations

import importlib
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "source"))
sys.path.insert(0, str(ROOT / "tools"))

import behaviour_graph as bg          # noqa: E402
import behaviour_sim as bs            # noqa: E402
import behaviour_sim_judge as judge   # noqa: E402
import behaviour_sim_judge_mf as judge_mf   # noqa: E402

WORLDS = ROOT / "tests" / "behaviour"


def sent(sim, node_id, field_name):
    """The last value ``node_id`` sent from ``field_name`` (the simulation's log)."""
    return [event[3] for event in sim.log if event[1] == node_id and event[2] == field_name][-1]


def world(name):
    return bg.Behaviour.from_x3d((WORLDS / f"{name}.x3d").read_text(encoding="utf-8"))


class ValueTests(unittest.TestCase):

    def test_text_becomes_python_values(self):
        self.assertIs(bs.parse_value("true", "SFBool"), True)
        self.assertEqual(bs.parse_value("3", "SFInt32"), 3)
        self.assertEqual(bs.parse_value("0 1.5 -2", "SFVec3f"), (0.0, 1.5, -2.0))
        self.assertEqual(bs.parse_value("0 0 0, 1 2 3", "MFVec3f"), [(0.0, 0.0, 0.0), (1.0, 2.0, 3.0)])
        self.assertEqual(bs.parse_value('"a b" "c\\"d"', "MFString"), ["a b", 'c"d'])
        self.assertEqual(bs.parse_value(None, "SFVec3f"), (0.0, 0.0, 0.0))
        self.assertEqual(bs.parse_value("", "MFFloat"), [])

    def test_a_rotation_survives_the_trip_through_a_quaternion(self):
        for rotation in ((0, 1, 0, 1.2), (1, 0, 0, 3.0), (0.6, 0.8, 0, 0.4)):
            back = bs.axis_angle(bs.quaternion(rotation))
            self.assertLess(bs._rotation_distance(rotation, back), 1e-9)

    def test_slerp_goes_the_short_way_and_hits_both_ends(self):
        a, b = (0, 1, 0, 0.2), (0, 1, 0, 1.0)
        self.assertAlmostEqual(bs.slerp(a, b, 0.5)[3], 0.6, places=6)
        self.assertLess(bs._rotation_distance(bs.slerp(a, b, 0), a), 1e-6)
        self.assertLess(bs._rotation_distance(bs.slerp(a, b, 1), b), 1e-6)

    def test_colour_is_mixed_through_hue(self):
        middle = bs.hsv_lerp((1, 0, 0), (0, 1, 0), 0.5)          # red to green passes yellow, not dark olive
        self.assertAlmostEqual(middle[0], 1.0, places=6)
        self.assertAlmostEqual(middle[1], 1.0, places=6)


class NodeTests(unittest.TestCase):

    def graph(self):
        return bg.Behaviour()

    def test_a_click_is_a_time_and_starts_the_timer(self):
        sim = bs.Simulation(world("door"))
        sim.start(0.0)
        self.assertEqual(sim.step(0.5), [])                       # nothing moves before the click
        sim.press("Click", 1.0)
        changes = sim.release("Click", 1.1)
        self.assertEqual(changes, [("Door", "translation", (0.0, 1.2, 0.0))])
        self.assertEqual(sim.outputs[("Click", "touchTime")], 1.1)
        (_, _, at_half), = sim.step(1.1 + 1.5)                    # half of 3 s: between keys 0.4 and 0.6
        self.assertEqual(at_half, (0.0, 3.7, 0.0))
        (_, _, at_end), = sim.step(1.1 + 3.05)                    # the step that passes the end reports the end
        self.assertAlmostEqual(at_end[1], 1.2, places=9)
        self.assertIs(sim.outputs[("Timer", "isActive")], False)
        self.assertEqual(sim.step(6.0), [])                       # one cycle, then still

    def test_a_running_timer_ignores_a_new_start(self):
        sim = bs.Simulation(world("door"))
        sim.start(0.0)
        sim.click("Click", 1.0)
        sim.step(2.0)
        sim.click("Click", 2.0)                                   # 8.2.4.4: startTime is ignored while active
        (_, _, value), = sim.step(2.5)
        self.assertEqual(value, (0.0, 3.7, 0.0))                  # still 1.5 s into the first cycle

    def test_a_looping_timer_counts_its_cycles_from_start_time(self):
        g = self.graph()
        clock = g.add("TimeSensor", "Clock", cycleInterval=4, loop=True)
        level = g.add("ScalarInterpolator", "Level", key=[0, 1], keyValue=[0, 1])
        clock.fraction_changed >> level.set_fraction
        sim = bs.Simulation(g)
        sim.start(1003.0)                                         # loaded 1003 s after startTime 0
        self.assertAlmostEqual(sim.outputs[("Clock", "fraction_changed")], 0.75)
        sim.step(1005.0)
        self.assertAlmostEqual(sim.outputs[("Clock", "fraction_changed")], 0.25)

    def test_the_counter_counts_in_binary(self):
        g = self.graph()
        press = g.add("TouchSensor", "Press")
        previous = press.isActive
        for bit in range(4):
            flip = g.add("BooleanToggle", f"Flip{bit}")
            previous >> flip.set_boolean
            flip.toggle >> g.target("Transform", f"Bit{bit}").visible
            carry = g.add("BooleanFilter", f"Carry{bit}")
            flip.toggle >> carry.set_boolean
            previous = carry.inputNegate
        sim = bs.Simulation(g)
        sim.start(0.0)
        for presses in range(1, 20):
            sim.click("Press", float(presses), held=0.1)
            number = sum(1 << bit for bit in range(4) if sim.values.get((f"Bit{bit}", "visible")))
            self.assertEqual(number, presses % 16)

    def test_triggers_answer_true_only(self):
        g = self.graph()
        touch = g.add("TouchSensor", "Touch")
        when = g.add("TimeTrigger", "When")
        timer = g.add("TimeSensor", "Timer", cycleInterval=1)
        number = g.add("IntegerTrigger", "Number", integerKey=7)
        touch.isActive >> when.set_boolean
        when.triggerTime >> timer.startTime
        touch.isActive >> number.set_boolean
        number.triggerValue >> g.target("Switch", "Pick").whichChoice
        sim = bs.Simulation(g)
        sim.start(0.0)
        sim.press("Touch", 1.0)
        sim.release("Touch", 1.2)
        sent = [(e[1], e[2]) for e in sim.log]
        self.assertEqual(sent.count(("When", "triggerTime")), 1)
        self.assertEqual(sent.count(("Number", "triggerValue")), 1)
        self.assertEqual(sim.values[("Pick", "whichChoice")], 7)

    def test_a_timer_started_with_a_start_time_in_the_past_counts_its_cycles_from_it(self):
        # X_ITE (setRange): fraction = fract((now - startTime) / cycleInterval) at the start, looping or not, and a
        # sensor that does not loop ends when that cycle does
        def run(start_time, now):
            g = self.graph()
            timer = g.add("TimeSensor", "Timer", cycleInterval=3)
            g.add("TouchSensor", "Touch")
            sim = bs.Simulation(g)
            sim.start(0.0)
            sim.send("Timer", "startTime", start_time, now)
            fractions = [e[3] for e in sim.log if e[1] == "Timer" and e[2] == "fraction_changed"]
            t = now
            while t < now + 4 and sim.machines["Timer"].active:
                t += 1 / 60
                sim.step(t)
            return fractions[0], t - now
        first, ran = run(100.0, 100.0)                     # the ordinary case: now, a whole cycle
        self.assertEqual(first, 0.0)
        self.assertAlmostEqual(ran, 3.0, delta=0.02)
        first, ran = run(100.0 - 1 / 60, 100.0)            # one frame ago
        self.assertAlmostEqual(first, 1 / 180, places=6)
        self.assertAlmostEqual(ran, 3.0 - 1 / 60, delta=0.02)
        first, ran = run(0.0, 4.5)                         # long ago: the rest of the cycle only
        self.assertAlmostEqual(first, 0.5)
        self.assertAlmostEqual(ran, 1.5, delta=0.02)

    def test_a_sequencer_sends_only_when_its_value_changes(self):
        g = self.graph()
        clock = g.add("TimeSensor", "Clock", cycleInterval=1)
        steps = g.add("IntegerSequencer", "Steps", key=[0, 0.5], keyValue=[3, 9])
        clock.fraction_changed >> steps.set_fraction
        steps.value_changed >> g.target("Switch", "Pick").whichChoice
        touch = g.add("TouchSensor", "Touch")
        touch.touchTime >> clock.startTime
        sim = bs.Simulation(g)
        sim.start(0.0)
        sim.click("Touch", 1.0)
        for i in range(1, 11):
            sim.step(1.0 + i / 10)
        self.assertEqual([e[3] for e in sim.log if e[1] == "Steps"], [3, 9])

    def test_a_damper_closes_in_and_comes_to_rest(self):
        g = self.graph()
        damper = g.add("PositionDamper", "Soft", tau=0.2, order=1)
        damper.value_changed >> g.target("Transform", "Ball").translation
        sim = bs.Simulation(g)
        sim.start(0.0)
        sim.send("Soft", "set_destination", (1.0, 0.0, 0.0), 0.0)
        self.assertIs(sim.outputs[("Soft", "isActive")], True)
        sim.step(0.2)                                             # one tau: 1 - 1/e of the way
        self.assertAlmostEqual(sim.values[("Ball", "translation")][0], 1 - math.exp(-1), places=6)
        t = 0.2
        while sim.machines["Soft"].active and t < 20:
            t += 0.05
            sim.step(t)
        self.assertIs(sim.outputs[("Soft", "isActive")], False)
        self.assertAlmostEqual(sim.values[("Ball", "translation")][0], 1.0, delta=1e-4)   # the default tolerance
        self.assertLess(t, 3.0)

    def test_a_chaser_arrives_exactly_after_its_duration(self):
        g = self.graph()
        chaser = g.add("ScalarChaser", "Chase", duration=0.5)
        chaser.value_changed >> g.target("Material", "Paint").transparency
        sim = bs.Simulation(g)
        sim.start(0.0)
        sim.send("Chase", "set_destination", 1.0, 0.0)
        sim.step(0.25)
        self.assertAlmostEqual(sim.values[("Paint", "transparency")], 0.5, places=6)   # half way at half time
        sim.step(0.5)
        self.assertEqual(sim.values[("Paint", "transparency")], 1.0)
        self.assertIs(sim.outputs[("Chase", "isActive")], False)

    def test_a_loop_of_routes_ends(self):
        g = self.graph()
        a, b = g.add("BooleanFilter", "A"), g.add("BooleanFilter", "B")
        a.inputNegate >> b.set_boolean
        b.inputNegate >> a.set_boolean
        sim = bs.Simulation(g)
        sim.start(0.0)
        sim.send("A", "set_boolean", True, 1.0)                   # 4.4.8.3: each ROUTE once per time stamp
        self.assertEqual(len([e for e in sim.log if e[2] == "inputNegate"]), 3)

    def test_a_plane_sensor_reports_the_drag_and_remembers_it(self):
        g = self.graph()
        grab = g.add("PlaneSensor", "Grab")
        grab.translation_changed >> g.target("Transform", "Head").translation
        sim = bs.Simulation(g)
        sim.start(0.0)
        sim.press("Grab", 1.0, (1.0, 1.0, 0.0))
        sim.drag("Grab", (3.0, 2.0, 0.0), 1.1)
        self.assertEqual(sim.values[("Head", "translation")], (2.0, 1.0, 0.0))
        sim.release("Grab", 1.2)
        sim.press("Grab", 2.0, (0.0, 0.0, 0.0))
        sim.drag("Grab", (1.0, 0.0, 0.0), 2.1)                    # autoOffset: the next drag starts where this ended
        self.assertEqual(sim.values[("Head", "translation")], (3.0, 1.0, 0.0))

    def test_what_is_not_run_is_named(self):
        g = self.graph()
        # the example is whichever wired behaviour node has no machine yet (the examples kept being simulated); when every
        # node has one, a graph has nothing to name
        import behaviour_catalogue as catalogue
        import behaviour_graph as graph_module
        left = sorted(name for name in catalogue.NODES if name not in bs.SIMULATED and name not in graph_module.IN_PLACE)
        if left:
            g.add(left[0], "Mesh")
        g.add("TimeSensor", "Clock")
        self.assertEqual(bs.Simulation(g).not_simulated, [f"{left[0]} Mesh"] if left else [])

    def _drag_world(self, kind, **fields):
        g = self.graph()
        g.add(kind, "S", **fields)
        sim = bs.Simulation(g)
        sim.start(0.0)
        return sim

    @staticmethod
    def _toward(point, eye=(0.0, 0.0, 10.0)):
        return eye, bs._v_unit(bs._v_sub(point, eye))

    def test_a_sphere_sensor_turns_the_way_the_pointer_goes(self):
        sim = self._drag_world("SphereSensor")
        eye = ((0.0, 0.0, 10.0), (0.0, 0.0, 1.0))
        sim.press("S", 0.0, (0.0, 0.0, 1.0), ray=self._toward((0.0, 0.0, 1.0)), eye=eye)
        angle = 0.4
        sim.drag("S", None, 0.1, ray=self._toward((math.sin(angle), 0.0, math.cos(angle))))
        self.assertLess(bs._rotation_distance(sent(sim, "S", "rotation_changed"), (0, 1, 0, angle)), 1e-6)

    def test_a_sphere_pressed_behind_its_centre_turns_the_other_way(self):
        sim = self._drag_world("SphereSensor")
        eye = ((0.0, 0.0, 10.0), (0.0, 0.0, 1.0))
        hit = (0.0, 0.0, -1.0)                       # geometry behind the sensor's origin
        sim.press("S", 0.0, hit, ray=self._toward(hit), eye=eye)
        angle = 0.4
        target = (math.sin(angle), 0.0, -math.cos(angle))
        sim.drag("S", None, 0.1, ray=self._toward(target))
        self.assertLess(bs._rotation_distance(sent(sim, "S", "rotation_changed"), (0, 1, 0, angle)), 1e-6)

    def test_a_cylinder_sensor_turns_about_its_axis_and_stops_at_its_limit(self):
        free = self._drag_world("CylinderSensor")
        held = self._drag_world("CylinderSensor", minAngle=-0.2, maxAngle=0.2)
        eye = ((0.0, 0.0, 10.0), (0.0, 0.0, 1.0))
        for sim in (free, held):
            sim.press("S", 0.0, (0.0, 0.0, 1.0), ray=self._toward((0.0, 0.0, 1.0)), eye=eye)
            sim.drag("S", None, 0.1, ray=self._toward((0.5, 0.0, 1.0)))
        x, y, z, angle = sent(free, "S", "rotation_changed")
        self.assertAlmostEqual(abs(y), 1.0, places=6)
        self.assertAlmostEqual(angle, math.asin(0.5), places=6)
        self.assertLess(bs._rotation_distance(sent(held, "S", "rotation_changed"), (0, 1, 0, 0.2)), 1e-9)

    def test_a_proximity_sensor_enters_reports_and_leaves(self):
        g = bg.Behaviour()
        g.add("ProximitySensor", "Box", size=(2, 2, 2), center=(1, 0, 0))
        sim = bs.Simulation(g)
        sim.start(0.0)
        turn = (0.0, 1.0, 0.0, 0.3)
        sim.viewer("Box", (5.0, 0.0, 0.0), turn, 0.1)
        self.assertEqual([e[2] for e in sim.log if e[1] == "Box"], [])
        sim.viewer("Box", (1.5, 0.5, 0.0), turn, 0.2)
        self.assertEqual([e[2] for e in sim.log if e[1] == "Box"][:2], ["isActive", "enterTime"])
        sim.viewer("Box", (1.5, 0.5, 0.0), turn, 0.3)         # nothing changed: nothing sent
        sim.viewer("Box", (-0.5, 0.0, 0.0), turn, 0.4)
        self.assertEqual([e[2:] for e in sim.log if e[1] == "Box"][-2:], [("isActive", False), ("exitTime", 0.4)])

    def test_ease_in_ease_out_sends_the_eased_weight_of_the_segment(self):
        # X_ITE: the output is the eased weight within the segment (0 to 1), not a fraction mapped onto the keys
        g = self.graph()
        ease = g.add("EaseInEaseOut", "Ease", key=[0, 0.5, 1], easeInEaseOut=[(0, 0), (0, 0), (0, 0)])
        sim = bs.Simulation(g)
        sim.start(0.0)
        sim.send("Ease", "set_fraction", 0.75, 0.0)
        self.assertAlmostEqual(sent(sim, "Ease", "modifiedFraction_changed"), 0.5)   # no easing: the weight

    def test_a_spline_passes_through_its_keys(self):
        g = self.graph()
        g.add("SplinePositionInterpolator", "Path", key=[0, 0.3, 1], keyValue=[(0, 0, 0), (1, 2, 0), (3, 0, 1)])
        sim = bs.Simulation(g)
        sim.start(0.0)
        for fraction, expected in ((0.0, (0, 0, 0)), (0.3, (1, 2, 0)), (1.0, (3, 0, 1))):
            sim.send("Path", "set_fraction", fraction, 0.0)
            for got, want in zip(sent(sim, "Path", "value_changed"), expected):
                self.assertAlmostEqual(got, want)

    def test_squad_passes_through_its_keys(self):
        g = self.graph()
        g.add("SquadOrientationInterpolator", "Swing", key=[0, 0.5, 1],
              keyValue=[(0, 1, 0, 0), (0, 1, 0, 1.5), (1, 0, 0, 1.2)])
        sim = bs.Simulation(g)
        sim.start(0.0)
        sim.send("Swing", "set_fraction", 0.5, 0.0)
        self.assertLess(bs._rotation_distance(sent(sim, "Swing", "value_changed"), (0, 1, 0, 1.5)), 1e-9)

    def test_a_coordinate_interpolator_mixes_whole_lists_and_clamps(self):
        g = self.graph()
        g.add("CoordinateInterpolator", "Morph", key=[0, 0.5, 1],
              keyValue=[(0, 0, 0), (1, 1, 1), (0, 0, 2), (2, 2, 2), (0, 0, 4), (3, 3, 3)])
        sim = bs.Simulation(g)
        sim.start(0.0)
        for fraction, expected in ((-1.0, [(0, 0, 0), (1, 1, 1)]), (0.25, [(0, 0, 1), (1.5, 1.5, 1.5)]),
                                   (0.5, [(0, 0, 2), (2, 2, 2)]), (2.0, [(0, 0, 4), (3, 3, 3)])):
            sim.send("Morph", "set_fraction", fraction, 0.0)
            self.assertEqual(sent(sim, "Morph", "value_changed"), expected)
        self.assertEqual(sim.dropped, {})

    def test_a_coordinate_interpolator_with_a_ragged_keyvalue_does_what_x_ite_does(self):
        # X_ITE 16.8.1 (tests/behaviour/probe-coord.x3d): len(keyValue) // len(key) vectors per key, the rest ignored,
        # and an empty list when keyValue is shorter than key; the simulator counts it and never raises
        g = self.graph()
        g.add("CoordinateInterpolator", "Ragged", key=[0, 1], keyValue=[(0, 0, 0), (1, 1, 1), (2, 2, 2)])
        g.add("CoordinateInterpolator", "Short", key=[0, 0.5, 1], keyValue=[(0, 0, 0), (1, 1, 1)])
        g.add("CoordinateInterpolator", "NoKeys", keyValue=[(0, 0, 0)])
        sim = bs.Simulation(g)
        sim.start(0.0)
        for name in ("Ragged", "Short", "NoKeys"):
            sim.send(name, "set_fraction", 0.5, 0.0)
        self.assertEqual(sent(sim, "Ragged", "value_changed"), [(0.5, 0.5, 0.5)])
        self.assertEqual(sent(sim, "Short", "value_changed"), [])
        self.assertEqual([e for e in sim.log if e[1] == "NoKeys"], [])
        self.assertEqual(sim.noted, {"bad-count": 2})
        self.assertEqual(sim.dropped, {})
        self.assertEqual(sim.faults, [])

    def test_a_coordinate_interpolator_never_sends_a_non_finite_point(self):
        g = self.graph()
        g.add("CoordinateInterpolator", "Morph", key=[0, 1], keyValue=[(0, 0, 0), (math.inf, 0, 0)])
        g.add("CoordinateInterpolator", "Far", key=[0, 1], keyValue=[(0, 0, 0), (1e308, 0, 0)])
        sim = bs.Simulation(g)
        sim.start(0.0)
        sim.send("Morph", "set_fraction", 0.5, 0.0)       # inf in the field text: the field is the default, empty
        self.assertEqual(sent(sim, "Morph", "value_changed"), [])
        sim.machines["Far"].f["keyValue"] = [(0, 0, 0), (math.inf, 0, 0)]
        sim.send("Far", "set_fraction", 0.5, 0.0)          # inf reached at run time: dropped before it leaves the node
        self.assertEqual(sim.dropped.get("non-finite"), 1)
        self.assertEqual(sim.faults, [])

    def test_a_normal_interpolator_goes_round_the_unit_sphere(self):
        g = self.graph()
        g.add("NormalInterpolator", "Tilt", key=[0, 1], keyValue=[(1, 0, 0), (0, 1, 0)])
        sim = bs.Simulation(g)
        sim.start(0.0)
        sim.send("Tilt", "set_fraction", 0.5, 0.0)
        (x, y, z), = sent(sim, "Tilt", "value_changed")
        self.assertAlmostEqual(x, math.sqrt(0.5))
        self.assertAlmostEqual(y, math.sqrt(0.5))
        self.assertEqual(z, 0.0)

    def test_a_two_d_coordinate_interpolator_mixes_pairs(self):
        g = self.graph()
        g.add("CoordinateInterpolator2D", "Slide", key=[0, 1], keyValue=[(0, 0), (1, 0), (2, 2), (1, 4)])
        sim = bs.Simulation(g)
        sim.start(0.0)
        sim.send("Slide", "set_fraction", 0.5, 0.0)
        self.assertEqual(sent(sim, "Slide", "value_changed"), [(1.0, 1.0), (1.0, 2.0)])


class ListFollowerTests(unittest.TestCase):
    """CoordinateChaser, CoordinateDamper, TexCoordChaser2D and TexCoordDamper2D (source/behaviour_sim.py): what X_ITE
    16.8.1 does with lists, and what the simulator does with lists it should not have been given. The agreement with
    X_ITE's own event trace is in XiteAgreementTests.test_followers_of_lists."""

    KINDS = (("CoordinateChaser", 3), ("CoordinateDamper", 3), ("TexCoordChaser2D", 2), ("TexCoordDamper2D", 2))

    def run_follower(self, kind, destination, seconds=9.0, **fields):
        g = bg.Behaviour()
        g.add(kind, "F", **fields)
        sim = bs.Simulation(g, log_size=100_000)
        sim.start(0.0)
        sim.send("F", "set_destination", destination, 0.0)
        t = 0.0
        while t < seconds:
            t += 1 / 60
            sim.step(t)
        return sim

    def test_all_four_are_simulated(self):
        for kind, _size in self.KINDS:
            self.assertIn(kind, bs.SIMULATED)

    def test_each_follower_arrives_at_its_destination_and_says_when_it_is_at_rest(self):
        for kind, size in self.KINDS:
            with self.subTest(kind=kind):
                points = [tuple(float(i + j) for j in range(size)) for i in range(4)]
                sim = self.run_follower(kind, points)
                last = sent(sim, "F", "value_changed")
                for got, want in zip(last, points):
                    self.assertTrue(all(abs(a - b) < 1e-3 for a, b in zip(got, want)), (got, want))
                self.assertEqual(len(last), 4)
                self.assertEqual([e[3] for e in sim.log if e[2] == "isActive"], [True, False])
                self.assertEqual(sim.dropped, {})

    def test_a_destination_of_another_length_is_followed_with_zero_for_the_missing_points(self):
        # X_ITE 16.8.1 (tools/behaviour_sim_judge.cjs, a world of its own): a point one list lacks is the zero vector, the
        # damper's first output is as long as its destination, the chaser's as long as the value it started from
        g = bg.Behaviour()
        g.add("CoordinateDamper", "D", tau=1.5, initialValue=[(0, 0, 0)], initialDestination=[(1, 1, 1), (2, 2, 2), (3, 3, 3)])
        g.add("CoordinateChaser", "C", duration=3, initialValue=[(0, 0, 0)], initialDestination=[(1, 1, 1), (2, 2, 2), (3, 3, 3)])
        sim = bs.Simulation(g, log_size=100_000)
        sim.start(0.0)
        sim.step(1 / 60)
        self.assertEqual(len(sent(sim, "D", "value_changed")), 3)
        self.assertEqual(len(sent(sim, "C", "value_changed")), 1)
        t = 1 / 60
        while t < 30:                      # tau 1.5 and order 3: a long way to within 1e-4
            t += 1 / 60
            sim.step(t)
        for name in ("D", "C"):
            self.assertEqual([round(c) for p in sent(sim, name, "value_changed") for c in p], [1, 1, 1, 2, 2, 2, 3, 3, 3])
            self.assertEqual([e[3] for e in sim.log if e[1] == name and e[2] == "isActive"][-1], False)

    def test_an_empty_list_after_an_empty_list_is_no_event_but_a_set_value_always_is(self):
        # X_ITE 16.8.1: what a follower works out is written point by point and cut to length, so nothing changes (and
        # nothing is sent) for an empty list after an empty list; a list it is given, set_value, is assigned whole
        for kind, size in self.KINDS:
            with self.subTest(kind=kind):
                g = bg.Behaviour()
                g.add(kind, "F", initialDestination="", initialValue="")
                sim = bs.Simulation(g)
                sim.start(0.0)
                self.assertEqual([e for e in sim.log if e[2] == "value_changed"], [(0.0, "F", "value_changed", [])])    # the initial value, whole
                sim.log.clear()
                sim.send("F", "set_destination", [], 0.1)
                for k in range(1, 130):
                    sim.step(0.1 + k / 60)
                self.assertEqual([e[2:] for e in sim.log], [("isActive", True), ("isActive", False)])
                sim.log.clear()
                sim.send("F", "set_value", [], 3.0)
                self.assertEqual([e[2:] for e in sim.log if e[2] == "value_changed"], [("value_changed", [])])

    def test_a_list_that_is_not_a_list_of_vectors_is_refused_or_dropped_and_nothing_raises(self):
        for kind, size in self.KINDS:
            with self.subTest(kind=kind):
                g = bg.Behaviour()
                g.add(kind, "F")
                sim = bs.Simulation(g)
                sim.start(0.0)
                for bad in (1.0, "x", None, [1.0, 2.0], [(1.0,)], [(1.0,) * (size + 1)], [(math.nan,) * size],
                            [(math.inf,) * size], [(1.0,) * size, (2.0,)], ((1.0,) * size,), [[1.0] * size]):
                    for field in ("set_destination", "set_value"):
                        with self.assertRaises(bg.BehaviourError, msg=repr(bad)):
                            sim.send("F", field, bad, 0.0)
                for k in range(1, 30):
                    sim.step(k / 60)
                self.assertEqual((sim.faults, sim.dropped), ([], {}))

    def test_the_same_through_a_route_is_counted_in_dropped(self):
        g = bg.Behaviour()
        g.add("CoordinateInterpolator", "Morph", key=[0, 1], keyValue=[(0, 0, 0), (1, 1, 1), (1, 1, 1), (2, 2, 2)])
        g.add("TexCoordDamper2D", "Map")
        g.add("CoordinateDamper", "Verts")
        g.route("Morph", "value_changed", "Map", "set_destination", check=False)      # 3-vectors into a 2-vector list
        g.route("Morph", "value_changed", "Verts", "set_destination")
        sim = bs.Simulation(g)
        sim.start(0.0)
        sim.send("Morph", "set_fraction", 0.5, 0.1)
        self.assertEqual(sim.dropped, {"mismatch": 1})
        self.assertEqual(sim.faults, [])
        self.assertEqual(sim.outputs[("Verts", "isActive")], True)

    def test_a_huge_list_is_cut_to_the_cap_and_counted(self):
        for kind, size in self.KINDS:
            with self.subTest(kind=kind):
                g = bg.Behaviour()
                g.add(kind, "F")
                sim = bs.Simulation(g)
                sim.start(0.0)
                sim.send("F", "set_destination", [(0.5,) * size] * (bs._MAX_POINTS + 7), 0.0)
                sim.send("F", "set_value", [(0.25,) * size] * (bs._MAX_POINTS + 7), 0.0)
                sim.step(0.5)
                self.assertEqual(len(sent(sim, "F", "value_changed")), bs._MAX_POINTS)
                self.assertGreaterEqual(sim.noted.get("capped", 0), 2)
                self.assertEqual((sim.faults, sim.dropped), ([], {}))

    def test_the_order_of_a_damper_is_clamped_to_0_to_5(self):
        for order, stages in ((-4, 0), (0, 0), (2, 2), (5, 5), (6, 5), (10 ** 9, 5)):
            g = bg.Behaviour()
            g.add("CoordinateDamper", "D", order=order)
            self.assertEqual(len(bs.Simulation(g).machines["D"].buffer) - 1, stages, order)
        g = bg.Behaviour()
        g.add("CoordinateDamper", "D", order=0, initialDestination=[(1, 2, 3)], initialValue=[(1, 2, 3)])
        sim = bs.Simulation(g)
        sim.start(0.0)
        sim.send("D", "set_destination", [(4.0, 5.0, 6.0)], 0.0)
        sim.step(1 / 60)
        self.assertEqual(sent(sim, "D", "value_changed"), [(4.0, 5.0, 6.0)])           # order 0 does not follow: it jumps
        self.assertEqual(sent(sim, "D", "isActive"), False)

    def test_a_damper_with_no_tau_jumps_and_a_chaser_with_no_duration_arrives_at_once(self):
        for kind in ("CoordinateDamper", "CoordinateChaser"):
            g = bg.Behaviour()
            g.add(kind, "F", **({"tau": 0} if kind == "CoordinateDamper" else {"duration": 0}))
            sim = bs.Simulation(g)
            sim.start(0.0)
            sim.send("F", "set_destination", [(1.0, 2.0, 3.0)], 0.0)
            for k in range(1, 5):
                sim.step(k / 60)
            self.assertEqual(sent(sim, "F", "value_changed"), [(1.0, 2.0, 3.0)], kind)
            self.assertEqual(sent(sim, "F", "isActive"), False, kind)

    def test_bad_field_text_is_replaced_by_the_default_and_counted(self):
        g = bg.Behaviour()
        g.add("CoordinateDamper", "D", initialValue="1 2", tau="nan", tolerance="inf", order="x")
        g.add("TexCoordChaser2D", "C", initialDestination="1 2 3", duration="-inf")
        sim = bs.Simulation(g)
        sim.start(0.0)
        for k in range(1, 30):
            sim.step(k / 60)
        self.assertEqual(sim.dropped, {"bad-field": 4})            # tau, tolerance, order, duration; a trailing odd number of a list is left off
        self.assertEqual(sim.faults, [])

    def test_the_player_lists_the_points_it_does_not_show(self):
        # no Blender needed for the simulation half: the targets are reached, and are the targets the player has no
        # datablock for (the Blender half is PlayerListsFollowerPointsTests)
        graph = world("probe-list-followers")
        sim = bs.Simulation(graph)
        self.assertEqual(sim.not_simulated, [])
        sim.start(0.0)
        sim.click("TouchA", 1.0)
        for k in range(1, 200):
            sim.step(1.0 + k / 60)
        self.assertEqual(sorted({(k[0], k[1]) for k in sim.values}),      # and the Spinner that keeps X_ITE drawing
                         [("ChasedMap", "point"), ("ChasedVerts", "point"), ("DampedMap", "point"), ("DampedVerts", "point"),
                          ("Spinner", "rotation")])


@unittest.skipUnless(HAVE_BPY, "bpy is not available (this test plays the world in Blender's own Player)")
class PlayerListsFollowerPointsTests(unittest.TestCase):
    """The four list followers drive Coordinate.point and TextureCoordinate.point, which the Player has no datablock for:
    they run, and each is listed as not shown (docs/BEHAVIOUR_GRAPH.md), as the points of the interpolators already were."""

    def test_the_points_are_listed_as_not_shown(self):
        sys.path.insert(0, str(ROOT / "tests"))
        from test_roundtrip_bpy import _register_extension
        _register_extension(tempfile.mkdtemp(prefix="x3d_list_followers_"))
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bn = importlib.import_module("io_scene_x3d.behaviour_nodes")
        bp = importlib.import_module("io_scene_x3d.behaviour_play")
        bn.ensure_registered()
        bp.ensure_axes_properties()
        bpy.ops.import_scene.x3d(filepath=str(WORLDS / "probe-list-followers.x3d"), use_behaviour_graph=True)
        scene = bpy.context.scene
        # the importer leaves a ROUTE that ends at a Coordinate out of the node tree ("neither a Blender object nor a
        # top-level node"), so the graph is handed to the Player as the file wrote it
        player = bp.Player(scene, world("probe-list-followers"))
        self.assertEqual(player.sim.not_simulated, [])
        player.start(0.0)
        player.click(scene.objects["PadA"], 0.0, held=0.0)
        player.step(1.5)
        player.stop()
        self.assertEqual(sorted(player.not_applied),
                         ["Coordinate.point", "TextureCoordinate.point"])
        self.assertEqual({key for key in player.sim.values}, {("ChasedVerts", "point"), ("DampedVerts", "point"),
                                                               ("ChasedMap", "point"), ("DampedMap", "point"),
                                                               ("Spinner", "rotation")})


class XiteAgreementTests(unittest.TestCase):
    """The simulator against X_ITE 16.7.1's own event traces (headless Chromium, software GL, real mouse clicks)."""

    def agree(self, name, streams, judge=judge):
        trace = json.loads((WORLDS / "x_ite_traces" / f"{name}.json").read_text(encoding="utf-8"))
        self.assertEqual(trace["pageErrors"], [])
        result = judge.judge(WORLDS / f"{name}.x3d", trace)
        failed = [s for s in result["streams"] if not s["agree"]]
        self.assertEqual(failed, [])
        self.assertEqual(len(result["streams"]), streams)
        self.assertTrue(all(s["x_ite_events"] > 0 for s in result["streams"]), "a stream X_ITE never sent proves nothing")

    def test_door(self):
        self.agree("door", 2)

    def test_counter(self):
        self.agree("counter", 3)

    def test_follower(self):
        self.agree("snake", 6)

    def test_probe_of_every_simulated_kind(self):
        self.agree("probe", 25)

    def test_splines_easing_and_squad(self):
        # EaseInEaseOut, the three Spline interpolators, Squad and PositionDamper2D (tools/behaviour_probe.py)
        self.agree("probe-spline", 12)

    def test_drag_sensors_from_the_recorded_pointer(self):
        # CylinderSensor (side on, seen down its axis as a disk, pressed behind its axis) and SphereSensor (with an
        # offset, pressed behind its centre, dragged off the sphere), run from X_ITE's recorded pointer and compared
        # event for event
        self.agree("probe-drag", 7)

    def test_proximity_from_the_viewer_x_ite_reported(self):
        # a camera flight (a TimeSensor driving the Viewpoint) through a gate and a turned room with an off-centre box;
        # X_ITE's own report of the viewer (a root ProximitySensor of size -1) drives the simulator's other sensors
        self.agree("probe-proximity", 13)

    def test_a_timer_started_in_the_past_from_a_held_press(self):
        # TouchSensor.isActive -> TimeSensor.loop, its elapsedTime (or cycleTime) -> a second TimeSensor's startTime
        # (a startTime in the past, so it starts part way through a cycle and stops after the rest of it), a touchTime
        # -> startTime and a touchTime -> stopTime; pressed for 0.3 s and for 4.5 s (tools/behaviour_probe.py;
        # recorded on X_ITE 16.8.1, the older traces on 16.7.1)
        self.agree("probe-timer", 14)

    def test_coordinate_2d_coordinate_and_normal_interpolators(self):
        # key 0 0.4 1 over four vectors each, into a Coordinate, a TextureCoordinate and a Normal; two with a keyValue
        # that is not a whole number of lists (13 vectors for 3 keys: the last is ignored; 2 for 3: empty lists, which
        # X_ITE sends and the simulator now sends too). Recorded on X_ITE 16.8.1 (tests/behaviour/probe-coord.x3d)
        # and judged with the MF-aware wrapper: the judge's own reader takes lists of numbers, not lists of vectors.
        self.agree("probe-coord", 6, judge_mf)

    def test_followers_of_lists(self):
        # CoordinateChaser, CoordinateDamper, TexCoordChaser2D, TexCoordDamper2D, each fed by a Coordinate or Coordinate2D
        # interpolator: 4 points (and from 4 to 6 points, to 2, to none, back to 4, then lists given to set_value), the
        # clicks and the timers on X_ITE 16.8.1 (tests/behaviour/probe-list-followers.x3d), judged with the MF-aware
        # wrapper: the 4 value_changed streams and the 4 isActive streams, among 28
        self.agree("probe-list-followers", 28, judge_mf)

    def test_the_judge_rejects_wrong_list_followers(self):
        # the same trace against simulators that are wrong on purpose: each must be refused, or the test above says nothing
        name = "probe-list-followers"
        trace = json.loads((WORLDS / "x_ite_traces" / f"{name}.json").read_text(encoding="utf-8"))

        def refused():
            result = judge_mf.judge(WORLDS / f"{name}.x3d", trace)
            return sorted(s["source"] for s in result["streams"] if not s["agree"])

        self.assertEqual(refused(), [])
        damper, ramp, fitted, blend = bs._ListDamper.tick, bs._ListChaser.ramp, bs._ListMixin.fitted, bs._blend
        try:
            bs._ListDamper.tick = lambda self, now, dt: damper(self, now, dt * 1.25)          # a damper 25% too quick
            self.assertIn("Damp3.value_changed", refused())
            self.assertIn("Damp2.value_changed", refused())
            bs._ListDamper.tick = damper
            bs._ListChaser.ramp = lambda self, age: ramp(self, age * 1.15)                    # a chaser 15% too quick
            self.assertIn("Chase3.value_changed", refused())
            bs._ListChaser.ramp = ramp
            bs._ListMixin.fitted = lambda self, flat, count: flat                             # buffers not made as long as the destination
            self.assertIn("Chase3.value_changed", refused())
            bs._ListMixin.fitted = fitted

            def pad_with_the_last_point(source, target, t):                                   # a point one list lacks is not zero
                spare = len(source) - len(target)
                if spare > 0:
                    target = target + (target[-3:] * (spare // 3) if spare % 3 == 0 else [0.0] * spare)
                return [x + (y - x) * t for x, y in zip(source, target)]
            bs._blend = pad_with_the_last_point
            self.assertIn("Chase3.value_changed", refused())
        finally:
            bs._ListDamper.tick, bs._ListChaser.ramp, bs._ListMixin.fitted, bs._blend = damper, ramp, fitted, blend
        self.assertEqual(refused(), [])

    def test_a_turn_written_as_0_pi_2pi_rocks_in_x_ite_and_in_the_simulator(self):
        # OrientationInterpolator, key 0 0.5 1, keyValue 0, pi, 2 pi about y (tests/behaviour/probe-turn.x3d, X_ITE 16.8.1):
        # (a) pi and 2 pi as 3.14159265 and 6.28318531 (a hair under both) turns up to pi and back (shortest path both ways);
        # (b) 3.141593 and 6.283185 (a hair over) turns the other way round, then on: one continuous turn; (c) five keys:
        # a turn. The judge compares rotations (through quaternions, so q and -q and an axis flip are one rotation) and the
        # simulator agrees at every sample, so what X_ITE does is what the simulator does.
        self.agree("probe-turn", 5)       # the fifth stream: a PositionInterpolator written as "0 5e-01 1" and "1e-05 2.5E+0 -3.0e-1"
        trace = json.loads((WORLDS / "x_ite_traces" / "probe-turn.json").read_text(encoding="utf-8"))

        def angles(name):          # the turn about y, as a signed angle, from X_ITE's own events
            out = []
            for _when, node, field, value in trace["events"]:
                if node == name and field == "value_changed":
                    x, y, z, a = (float(v) for v in value.split())
                    out.append(a if y >= 0 else -a)
            return out
        rocking, over, safe = angles("ExactPi"), angles("JustOver"), angles("Safe")
        self.assertLess(max(rocking), math.pi + 0.01)           # never gets past pi
        self.assertLess(rocking[-1], 0.1)                       # and is back where it started
        self.assertLess(min(over), -2.9)                        # (b) goes round the other way to nearly -pi ...
        self.assertGreater(max(over), 6.0)                      # ... and on, to a full turn by the end
        self.assertGreater(max(safe), 6.1)

    def test_hanim_joint_site_and_segment_receive_and_echo_as_in_x_ite(self):
        # HAnimJoint rotation, translation, scale and center, HAnimSite rotation and translation, HAnimSegment centerOfMass and
        # mass, each fed by an interpolator and echoed by its *_changed (tests/behaviour/probe-hanim.x3d, X_ITE 16.8.1): 16
        # streams, the six echoes among them, all the same event for event.
        self.agree("probe-hanim", 16)

    def test_a_plane_sensor_pressed_by_a_ray_that_misses_the_plane_has_nothing_to_drag(self):
        # found by the hostile fuzz once HAnim targets changed which graphs it draws (seed 1, graph 246, minimised): the
        # press's ray (a direction of 1e308) never met the plane, so no start point was set and the next drag raised
        # AttributeError out of Simulation
        b = bg.Behaviour()
        b.add("PlaneSensor", "Pan", parent="T0", minPosition="0.4067", maxPosition="2 2", offset="")
        b.target("Transform", "T0")
        sim = bs.Simulation(b)
        sim.start(0.0)
        sim.press("Pan", 0.032, point=(2.06, 2.65, 1.04), ray=((2.67, 2.61, 1.07), (1e308, 0.0, 0.0)),
                  eye=((-0.95, 2.69, 0.67), (2.65, -2.97, -1.21)))
        sim.drag("Pan", (-1.9, 1.49, -2.31), 999994.532, ray=((-1.94, -1.0, -2.36), (1.51, -0.52, -2.69)))
        self.assertEqual(sim.faults, [])

    def test_switch_whichChoice_is_delivered_and_echoed_as_in_x_ite(self):
        # IntegerSequencer 2, 1, -1, 5 into Switch.whichChoice (an index past the last child, and -1, are delivered as
        # they are), echoed from whichChoice_changed (tests/behaviour/probe-switch.x3d, X_ITE 16.8.1): 3 streams
        self.agree("probe-switch", 3)

    def test_a_composed_shader_s_declared_fields_receive_and_echo_as_in_x_ite(self):
        # uTime SFFloat, uTint SFColor, uSteps SFInt32, uFlag SFBool and uOffset SFVec3f, all inputOutput, each fed by an
        # interpolator or sequencer and echoed from its *_changed (tests/behaviour/probe-shader.x3d, X_ITE 16.8.1): 12
        # streams, the five echoes among them, all the same event for event. uScale (SFVec2f, inputOnly) cannot be heard.
        self.agree("probe-shader", 12)

    def test_a_composed_shader_s_fields_are_kept_in_values_and_typed_from_the_declaration(self):
        graph = world("probe-shader")
        sim = bs.Simulation(graph)
        self.assertEqual(sim.not_simulated, [])
        sim.start(0.0)
        sim.click("Touch", 0.1, held=0.0)
        for now in (0.2, 1.0, 2.0, 3.2):
            sim.step(now)
        self.assertEqual(sim.values[("Glow", "uTime")], 7.5)
        self.assertEqual(sim.values[("Glow", "uTint")], (0.0, 0.0, 1.0))
        self.assertEqual(sim.values[("Glow", "uSteps")], 0)
        self.assertIs(sim.values[("Glow", "uFlag")], True)
        self.assertEqual(sim.values[("Glow", "uOffset")], (1.0, -2.0, 0.5))
        self.assertEqual(sim.values[("Glow", "uScale")], (3.0, 0.5))
        self.assertEqual(sim.values[("Echoed", "diffuseColor")], (0.0, 0.0, 1.0))                # an echo reaches on
        self.assertEqual(sim.dropped, {})

    def test_a_shader_field_of_the_wrong_shape_is_dropped_not_delivered(self):
        # a ROUTE the graph's own check refuses (a float into a declared SFVec3f), written past it: judged by the declaration
        b = bg.Behaviour()
        shader = b.target("ComposedShader", "Glow", declared=[("uTime", "SFFloat", "inputOutput"), ("uOffset", "SFVec3f", "inputOutput")])
        timer = b.add("TimeSensor", "Timer", cycleInterval=1, loop=True)
        timer.fraction_changed >> shader.uTime
        b.route("Timer", "fraction_changed", "Glow", "uOffset", check=False)
        sim = bs.Simulation(b)
        sim.start(0.0)
        sim.step(0.5)
        self.assertEqual(sim.values[("Glow", "uTime")], 0.5)
        self.assertNotIn(("Glow", "uOffset"), sim.values)
        self.assertGreater(sim.dropped["mismatch"], 0)

    def test_switch_whichChoice_is_kept_in_values(self):
        sim = bs.Simulation(world("probe-switch"))
        sim.start(0.0)
        sim.click("Touch", 0.1, held=0.0)
        seen = []
        for now in (0.2, 1.0, 2.0, 3.0):
            sim.step(now)
            seen.append(sim.values[("Pick", "whichChoice")])
        self.assertEqual(seen, [2, 1, -1, 5])
        self.assertEqual(sim.values[("Echo", "whichChoice")], 5)
        self.assertEqual([e[3] for e in sim.log if e[1] == "Pick" and e[2] == "whichChoice"], [2, 1, -1, 5])

    def test_hanim_targets_hold_the_last_value_that_reached_them(self):
        graph = world("probe-hanim")
        sim = bs.Simulation(graph)
        sim.start(0.0)
        sim.press("Touch", 0.1)
        sim.release("Touch", 0.2)
        sim.step(3.4)
        self.assertEqual(sim.not_simulated, [])
        self.assertEqual(sim.values[("hanim_root", "rotation")], (0.0, 0.0, 1.0, 0.0))     # the swing is over: back to rest
        self.assertEqual(sim.values[("hanim_spine", "translation")], (0.0, 0.5, 0.25))
        self.assertEqual(sim.values[("hanim_spine", "scale")], (1.5, 2.0, 1.5))
        self.assertEqual(sim.values[("hanim_spine", "center")], (0.5, 1.5, 0.0))
        self.assertEqual(sim.values[("hanim_tip", "translation")], (0.0, 0.5, 0.25))
        self.assertAlmostEqual(sim.values[("hanim_tip", "rotation")][3], 1.2, places=6)
        self.assertEqual(sim.values[("hanim_spine_seg", "centerOfMass")], (0.0, 2.0, 0.0))
        self.assertEqual(sim.values[("hanim_spine_seg", "mass")], 20.0)
        self.assertEqual(sim.values[("MirrorTranslation", "translation")], (0.0, 0.5, 0.25))     # a joint's echo reaches on

    def test_the_probe_covers_what_the_simulator_runs(self):
        # judged means: sends on a ROUTE in a recorded world (a node that only receives is never compared)
        judged = list(map(world, ("probe", "snake", "probe-spline", "probe-drag", "probe-proximity", "probe-timer", "probe-coord",
                                "probe-script", "probe-list-followers", "probe-world")))
        judged += [bg.Behaviour.from_x3d((d / f"{d.name}.x3d").read_text(encoding="utf-8")) for d in recorded_demos()]
        # the worlds recorded for outside resources (tools/behaviour_resources_judge.py, tests/test_behaviour_resources.py)
        judged += list(map(world, ("probe-load", "probe-loadlive", "probe-audio", "probe-movie")))
        used = {graph.nodes[route.from_id].node_type for graph in judged
                for route in graph.routes if graph.nodes[route.from_id].role == bg.BEHAVIOUR}
        # AudioClip and MovieTexture are scene nodes kept in place: targets in the graph, and they send on a ROUTE too
        used |= {graph.nodes[route.from_id].node_type for graph in judged
                 for route in graph.routes if graph.nodes[route.from_id].node_type in bg.IN_PLACE}
        unjudged = sorted(set(bs.SIMULATED) - used)
        # not judged against X_ITE: CollisionSensor is simulated from a contact stimulus and checked for timing against a
        # recording of X_ITE's physics (tests/test_behaviour_hosted.py), which is a consistency check and not a judgement:
        # X_ITE's own output is the stimulus. VisibilitySensor and TransformSensor are judged by probe-world
        # (tests/test_behaviour_world.py).
        self.assertEqual(unjudged, ["CollisionSensor"])


DEMOS = WORLDS / "demos"


def recorded_demos():
    """Demo folders with a contract and an X_ITE trace (docs/BEHAVIOUR_DEMOS.md); each is judged below."""
    return sorted(d for d in DEMOS.iterdir() if (d / "demo.json").is_file() and (d / "x_ite.json").is_file()) \
        if DEMOS.is_dir() else []


class DemoJudgeTests(unittest.TestCase):
    """Every demo in tests/behaviour/demos/ that has an X_ITE trace agrees with it, stream for stream, as its demo.json
    says; a node type a demo claims to judge for the first time must send on a ROUTE in that demo's world."""

    def test_there_is_a_demo(self):
        self.assertIn("hello-switch", [d.name for d in recorded_demos()])

    def test_every_recorded_demo_agrees_with_x_ite(self):
        for folder in recorded_demos():
            with self.subTest(demo=folder.name):
                contract = json.loads((folder / "demo.json").read_text(encoding="utf-8"))
                trace = json.loads((folder / "x_ite.json").read_text(encoding="utf-8"))
                self.assertEqual(trace["pageErrors"], [])
                result = judge.judge(folder / f"{folder.name}.x3d", trace)
                self.assertEqual([s["source"] for s in result["streams"] if not s["agree"]], [])
                self.assertEqual(len(result["streams"]), contract["streams"])
                self.assertTrue(all(s["x_ite_events"] > 0 for s in result["streams"]),
                                "a stream X_ITE never sent proves nothing")
                graph = bg.Behaviour.from_x3d((folder / f"{folder.name}.x3d").read_text(encoding="utf-8"))
                senders = {graph.nodes[r.from_id].node_type for r in graph.routes}
                self.assertEqual(sorted(set(contract.get("judges", [])) - senders), [])


if __name__ == "__main__":
    unittest.main()
