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

import json
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "source"))
sys.path.insert(0, str(ROOT / "tools"))

import behaviour_graph as bg          # noqa: E402
import behaviour_sim as bs            # noqa: E402
import behaviour_sim_judge as judge   # noqa: E402

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
        g.add("CoordinateInterpolator", "Mesh")
        g.add("TimeSensor", "Clock")
        self.assertEqual(bs.Simulation(g).not_simulated, ["CoordinateInterpolator Mesh"])

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


class XiteAgreementTests(unittest.TestCase):
    """The simulator against X_ITE 16.7.1's own event traces (headless Chromium, software GL, real mouse clicks)."""

    def agree(self, name, streams):
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

    def test_the_probe_covers_what_the_simulator_runs(self):
        # judged means: sends on a ROUTE in a recorded world (a node that only receives is never compared)
        used = {graph.nodes[route.from_id].node_type for graph in map(world, ("probe", "snake", "probe-spline", "probe-drag"))
                for route in graph.routes if graph.nodes[route.from_id].role == bg.BEHAVIOUR}
        unjudged = sorted(set(bs.SIMULATED) - used)
        # not judged against X_ITE: sensors the caller drives (they send what the caller says), and four followers
        # and one interpolator that share their code with a judged one
        self.assertEqual(unjudged, ["ColorChaser", "KeySensor", "PlaneSensor", "PositionChaser2D",
                                    "PositionInterpolator2D", "ProximitySensor", "StringSensor", "VisibilitySensor"])


if __name__ == "__main__":
    unittest.main()
