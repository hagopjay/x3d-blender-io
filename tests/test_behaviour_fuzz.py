# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Random and hostile graphs against the graph, the simulator and the Blender node tree (tools/behaviour_fuzz.py).

The first class runs 150 normal and 150 hostile graphs with fixed seeds, in plain Python. The second holds one named test
for each thing the fuzzer found, each with the smallest graph that shows it. The third (Blender) takes 20 graphs through
the node tree and the Player::

    cd tests && python -m unittest test_behaviour_fuzz
"""

from __future__ import annotations

import math
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "source"))
sys.path.insert(0, str(ROOT / "tools"))

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

import behaviour_fuzz as fuzz   # noqa: E402
import behaviour_graph as bg    # noqa: E402
import behaviour_sim as bs      # noqa: E402

DOCUMENT = '<?xml version="1.0"?><X3D profile="Interchange" version="4.0"><Scene><Transform DEF="Door"/></Scene></X3D>'


def _failures(receipt):
    return [(f["index"], f["findings"][:2]) for f in receipt["failures"]]


class FuzzRuns(unittest.TestCase):
    """The five properties of the fuzzer, on fixed seeds (the full runs are 2000 graphs each: see docs/BEHAVIOUR_GRAPH.md)."""

    def test_150_normal_graphs(self):
        began = time.perf_counter()
        receipt = fuzz.fuzz(150, 11, False, minimise_failures=False)
        self.assertEqual(_failures(receipt), [])
        self.assertEqual(receipt["faults"], 0, "a legal graph must not make a node raise")
        self.assertEqual(receipt["dropped"], {}, "a legal graph must not lose a value")
        self.assertEqual(receipt["node_types_used"], fuzz.NODE_TYPES)
        self.assertEqual(receipt["target_types_used"], fuzz.TARGET_TYPES)
        self.assertGreater(receipt["target_events"], 100, "the graphs must reach the targets, or nothing is checked")
        self.assertLess(time.perf_counter() - began, 10)

    def test_150_hostile_graphs(self):
        began = time.perf_counter()
        receipt = fuzz.fuzz(150, 11, True, minimise_failures=False)
        self.assertEqual(_failures(receipt), [])
        for kind in ("non-finite", "mismatch", "bad-field", "bad-time"):
            self.assertGreater(receipt["dropped"].get(kind, 0), 0, f"hostile graphs should exercise {kind}")
        self.assertLess(time.perf_counter() - began, 10)

    def test_same_seed_same_graphs(self):
        for hostile in (False, True):
            a, calls_a = fuzz.case(5, 3, hostile)
            b, calls_b = fuzz.case(5, 3, hostile)
            self.assertEqual(bg.to_json(a), bg.to_json(b))
            self.assertEqual(repr(calls_a), repr(calls_b))

    def test_the_checks_have_teeth(self):
        """Take a safeguard out and the fuzzer must say so: a fuzzer that cannot fail proves nothing."""
        original = bs._finite
        bs._finite = lambda value: True
        try:
            receipt = fuzz.fuzz(60, 1, True, minimise_failures=False)
        finally:
            bs._finite = original
        self.assertGreater(receipt["properties"]["c-values"]["failed"], 0)
        original = bs._fits
        bs._fits = lambda value, kind: True
        try:
            receipt = fuzz.fuzz(60, 1, True, minimise_failures=False)
        finally:
            bs._fits = original
        self.assertGreater(receipt["properties"]["c-values"]["failed"], 0)

    def test_a_failing_graph_is_minimised(self):
        original = bs._finite
        bs._finite = lambda value: True
        try:
            index = next(i for i in range(100) if fuzz.check(*fuzz.case(1, i, True), True)[0])
            graph, calls = fuzz.case(1, index, True)
            small_graph, small_calls = fuzz.minimise(graph, calls, True, "c-values")
        finally:
            bs._finite = original
        self.assertLess(len(small_graph.nodes) + len(small_calls), len(graph.nodes) + len(calls))


def _sim(graph, start=0.0):
    sim = bs.Simulation(graph)
    if start is not None:
        sim.start(start)
    return sim


class Regressions(unittest.TestCase):
    """What the fuzzer found, one test each. Hostile graphs, hostile seed 1 of 2000 unless said otherwise."""

    def test_field_text_that_is_not_a_number_is_the_default(self):
        """Simulation(...) raised ValueError on cycleInterval="abc" (703 of 2000 hostile graphs)."""
        b = bg.Behaviour()
        b.add("TimeSensor", "T", cycleInterval="abc", loop="yes")
        sim = _sim(b)
        self.assertEqual(sim.machines["T"].f["cycleInterval"], 1.0)
        self.assertEqual(sim.dropped["bad-field"], 1)

    def test_nan_and_infinity_in_a_field_are_the_default(self):
        """Simulation(...) raised OverflowError or ValueError on an Int32 or Time field holding inf or nan."""
        b = bg.Behaviour()
        b.add("TimeSensor", "T", cycleInterval="nan", startTime="inf", stopTime="-inf")
        b.add("ScalarDamper", "D", order="inf", tau="nan")
        b.add("ScalarInterpolator", "I", key="0 nan 1", keyValue="0 1 2")
        sim = _sim(b)
        self.assertEqual(sim.machines["T"].f["cycleInterval"], 1.0)
        self.assertEqual(sim.machines["T"].f["startTime"], 0.0)
        self.assertEqual(sim.machines["I"].f["key"], [])
        sim.step(1.0)

    def test_a_huge_damper_order_does_not_allocate_it(self):
        """order = 1e9 made a list of a billion values (the process was killed for memory); X3D allows 0 to 5."""
        b = bg.Behaviour()
        b.add("PositionDamper", "D", order=10 ** 9)
        sim = _sim(b)
        self.assertLessEqual(len(sim.machines["D"].buffer), 65)

    def test_a_vector_into_a_float_field_is_a_clear_error(self):
        """send() of a tuple to set_fraction raised TypeError inside the node (about 100 of 2000 hostile graphs)."""
        b = bg.Behaviour()
        b.add("ScalarInterpolator", "I", key=[0, 1], keyValue=[0, 1])
        sim = _sim(b)
        for value in ((1.0, 2.0), "x", None, [1.0], True, math.nan, math.inf):
            with self.assertRaises(bg.BehaviourError) as caught:
                sim.send("I", "set_fraction", value, 1.0)
            self.assertEqual(caught.exception.code, "bad-value")

    def test_a_number_beyond_the_double_range_never_reaches_a_target(self):
        """Interpolating -1e308 to 1e308 gave infinity at a PointLight's intensity."""
        b = bg.Behaviour()
        b.add("ScalarInterpolator", "I", key=[0, 1], keyValue=[-1e308, 1e308])
        b.target("PointLight", "L")
        b.route("I", "value_changed", "L", "intensity")
        sim = _sim(b)
        self.assertEqual(sim.send("I", "set_fraction", 0.5, 1.0), [])
        self.assertEqual(sim.values, {})
        self.assertEqual(sim.dropped["non-finite"], 1)

    def test_a_value_of_the_wrong_shape_is_not_delivered(self):
        """A ROUTE the editor would not allow (float to translation) delivered a float to a Transform's translation."""
        b = bg.Behaviour()
        b.add("ScalarInterpolator", "I", key=[0, 1], keyValue=[0, 1])
        b.target("Transform", "T")
        b.route("I", "value_changed", "T", "translation", check=False)
        sim = _sim(b)
        self.assertEqual(sim.send("I", "set_fraction", 0.5, 1.0), [])
        self.assertEqual(sim.dropped["mismatch"], 1)
        self.assertEqual(bg.validate(b)[0]["code"], "type-mismatch")

    def test_a_vector_into_a_string_list_is_not_delivered(self):
        b = bg.Behaviour()
        b.add("PositionInterpolator", "I", key=[0, 1], keyValue=[(0, 0, 0), (1, 1, 1)])
        b.target("Text", "Label")
        b.route("I", "value_changed", "Label", "string", check=False)
        sim = _sim(b)
        self.assertEqual(sim.send("I", "set_fraction", 0.5, 1.0), [])

    def test_a_spline_with_three_equal_keys_is_built(self):
        """Three equal keys are legal X3D; the tangent of the middle one divided by zero and the node was never built."""
        b = bg.Behaviour()
        b.add("SplineScalarInterpolator", "S", key=[0, 0.5, 0.5, 0.5, 1], keyValue=[0, 1, 2, 3, 4])
        sim = _sim(b)
        self.assertIn("S", sim.machines)
        sim.send("S", "set_fraction", 0.7, 1.0)
        self.assertTrue(math.isfinite(sim.outputs[("S", "value_changed")]))

    def test_time_that_is_not_a_number_is_ignored(self):
        """step(inf) raised OverflowError and step(nan) put NaN into a running timer's fraction."""
        b = bg.Behaviour()
        b.add("TimeSensor", "T", cycleInterval=2, loop=True)
        sim = _sim(b)
        sim.step(1.0)
        for bad in (math.nan, math.inf, -math.inf, None, "1"):
            sim.step(bad)
        self.assertEqual(sim.outputs[("T", "fraction_changed")], 0.5)
        self.assertEqual(sim.dropped["bad-time"], 5)
        sim.step(1.5)
        self.assertEqual(sim.outputs[("T", "fraction_changed")], 0.75)

    def test_a_pointer_with_a_nan_ray_is_ignored(self):
        """press() with a NaN in the ray raised ValueError (NaN to integer) in the CylinderSensor, then release() raised
        AttributeError because the press had not finished."""
        b = bg.Behaviour()
        b.add("CylinderSensor", "C")
        sim = _sim(b)
        nan = math.nan
        self.assertEqual(sim.press("C", 0.0, (0, 0, 1), ((0, 0, 5), (nan, 0, -1)), ((0, 0, 5), (0, 0, 1))), [])
        self.assertEqual(sim.release("C", 1.0), [])
        self.assertEqual(sim.dropped["non-finite"], 1)
        self.assertEqual(sim.faults, [])

    def test_a_node_that_raises_is_left_out_not_fatal(self):
        """Magnitudes beyond about 1e154 overflow a distance: the damper is isolated and counted, the rest runs."""
        b = bg.Behaviour()
        b.add("PositionDamper", "D", initialValue="1e200 0 0", initialDestination="-1e200 0 0")
        b.add("TimeSensor", "T", cycleInterval=1, loop=True)
        sim = bs.Simulation(b)
        sim.start(0.0)
        sim.step(0.5)
        self.assertTrue(sim.faults)
        self.assertEqual(sim.outputs[("T", "fraction_changed")], 0.5)

    def test_a_cycle_of_routes_stops_at_one_event_per_route(self):
        """The loop rule (4.4.8.3): a self-loop and a two-node cycle each carry one event per timestamp."""
        b = bg.Behaviour()
        b.add("ScalarInterpolator", "A", key=[0, 1], keyValue=[0, 2])
        b.add("ScalarInterpolator", "B", key=[0, 1], keyValue=[0, 0.5])
        b.target("PointLight", "L")
        b.route("A", "value_changed", "A", "set_fraction")
        b.route("A", "value_changed", "B", "set_fraction")
        b.route("B", "value_changed", "A", "set_fraction")
        b.route("A", "value_changed", "L", "intensity")
        sim = _sim(b)
        done = sim.send("A", "set_fraction", 0.5, 1.0)
        self.assertLessEqual(len(done), 2)
        self.assertLess(len(sim.log), 20)

    def test_a_sensor_asked_before_start_does_not_fail(self):
        b = bg.Behaviour()
        b.add("TimeSensor", "T", cycleInterval=2)
        b.add("TouchSensor", "Touch")
        sim = _sim(b, start=None)
        sim.send("T", "startTime", 0.0)
        sim.click("Touch", 1.0)
        sim.hover("Touch", True, 2.0)
        self.assertEqual(sim.faults, [])

    def test_text_xml_cannot_hold_is_refused_by_weave_and_removed_by_the_exporter(self):
        """weave() raised xml ParseError for a field holding a control character (hostile seed 1, graph 1)."""
        b = bg.Behaviour()
        b.add("TimeSensor", "T", description="a\x01b")
        with self.assertRaises(bg.BehaviourError) as caught:
            b.weave(DOCUMENT)
        self.assertEqual(caught.exception.code, "bad-value")
        self.assertEqual(bg.validate(b)[0]["code"], "bad-value")
        text = bg.node_xml(b.nodes["T"])
        self.assertNotIn("\x01", text)
        bg.ET.fromstring(text)

    def test_a_def_may_not_end_in_a_newline(self):
        """'$' matched before a final newline, so 'T\\n' was a legal DEF and was written into ROUTE attributes."""
        b = bg.Behaviour()
        with self.assertRaises(bg.BehaviourError) as caught:
            b.add("TimeSensor", "T\n")
        self.assertEqual(caught.exception.code, "bad-def")

    def test_text_that_is_not_a_value_reads_as_the_empty_value(self):
        """parse_value (the editor reads every field through it) raised ValueError on 'abc' and '1e'."""
        self.assertEqual(bs.parse_value("abc", "SFFloat"), 0.0)
        self.assertEqual(bs.parse_value("1 2 x", "MFFloat"), [])
        self.assertEqual(bs.parse_value("0x10", "SFVec3f"), (0.0, 0.0, 0.0))
        self.assertEqual(bs.parse_value("1e", "SFInt32"), 0)
        with self.assertRaises(ValueError):
            bs.parse_value("abc", "SFFloat", strict=True)

    def test_unknown_nodes_and_fields_in_calls_are_clear_errors(self):
        b = bg.Behaviour()
        b.add("TimeSensor", "T")
        sim = _sim(b)
        for call in (lambda: sim.send("Nope", "startTime", 1.0), lambda: sim.send("T", "nothing", 1.0),
                     lambda: sim.press("T", 1.0), lambda: sim.viewer("T", (0, 0, 0), (0, 0, 1, 0), 1.0)):
            with self.assertRaises(bg.BehaviourError):
                call()


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class BlenderPass(unittest.TestCase):
    """20 graphs through apply and read (no difference) and through the Player (nothing raised, everything restored)."""

    def test_normal_graphs(self):
        receipt = fuzz.bpy_pass(20, 21)
        self.assertEqual([(f["index"], f["findings"]) for f in receipt["failures"]], [])
        self.assertEqual(receipt["properties"]["apply-read-no-difference"]["checked"], 20)

    def test_hostile_graphs_play_without_raising_and_are_restored(self):
        receipt = fuzz.bpy_pass(20, 21, hostile=True)
        self.assertEqual([(f["index"], f["findings"]) for f in receipt["failures"]], [])

    def test_play_gives_back_the_euler_angles_the_user_typed(self):
        """Player.stop() restored an object through its matrix, so a rotation typed as (0.011, -2.2, 2.97) came back as
        an equal rotation with other angles, and a location came back a few ulps off (Blender fuzz seed 1, graphs 2, 18)."""
        _bn, bp, _bg = fuzz.blender_modules()
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.object.empty_add()
        obj = bpy.context.object
        obj.location = (0.1, 0.2, 0.3)
        obj.rotation_euler = (0.011334174312651157, -2.244690418243408, 2.9686994552612305)
        obj.scale = (1.1, 0.9, 1.3)
        before = (tuple(obj.location), tuple(obj.rotation_euler), tuple(obj.scale))
        state = bp._TransformState(obj, bp.EXPORT_AXES)
        state.location = state.location.copy()
        state.location.x += 1
        state.write()
        self.assertNotEqual(tuple(obj.location), before[0])
        state.restore()
        self.assertEqual((tuple(obj.location), tuple(obj.rotation_euler), tuple(obj.scale)), before)


if __name__ == "__main__":
    unittest.main()
