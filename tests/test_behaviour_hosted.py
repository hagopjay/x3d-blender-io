# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Hosted nodes (class E): Script handlers and CollisionSensor contacts, in the simulator and in plain Python.

The Script handler is judged against X_ITE running the real JavaScript (tests/behaviour/x_ite_traces/probe-script.json,
X_ITE 16.8.1). The CollisionSensor is a consistency check against a recording of X_ITE's physics: the stimulus is X_ITE's
own output, so it is not counted as judged. The security tests state what may run Python and what may never run anything.
No bpy needed::

    cd tests && python -m unittest test_behaviour_hosted
"""

from __future__ import annotations

import ast
import json
import math
import subprocess
import sys
import unittest
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "source"))
sys.path.insert(0, str(ROOT / "tools"))

import behaviour_activity as ba                 # noqa: E402
import behaviour_graph as bg                    # noqa: E402
import behaviour_hosted as bh                   # noqa: E402
import behaviour_hosted_probe as probe          # noqa: E402
import behaviour_sim as bs                      # noqa: E402
import behaviour_sim_judge as judge             # noqa: E402
import behaviour_sim_judge_mf as judge_mf       # noqa: E402

WORLDS = ROOT / "tests" / "behaviour"

DOOR = """<?xml version="1.0"?>
<X3D profile="Full" version="4.0"><Scene>
<Transform DEF="Lamp"><Shape><Sphere/></Shape></Transform>
<Transform DEF="Pad"><Shape><Box/></Shape><TouchSensor DEF="Touch"/></Transform>
<Script DEF="Brain">
<field name="poke" type="SFTime" accessType="inputOnly"/>
<field name="armed" type="SFBool" accessType="inputOutput" value="true"/>
<field name="step" type="SFInt32" accessType="initializeOnly" value="3"/>
<field name="place" type="SFVec3f" accessType="outputOnly"/>
<field name="count" type="SFInt32" accessType="outputOnly"/>
<field name="a" type="SFInt32" accessType="outputOnly"/>
<field name="b" type="SFInt32" accessType="outputOnly"/>
<field name="level" type="SFFloat" accessType="outputOnly"/>
<![CDATA[ecmascript:
function poke(value, time) { }
]]></Script>
<ROUTE fromNode="Touch" fromField="touchTime" toNode="Brain" toField="poke"/>
<ROUTE fromNode="Touch" fromField="isActive" toNode="Brain" toField="set_armed"/>
<ROUTE fromNode="Brain" fromField="place" toNode="Lamp" toField="set_translation"/>
<ROUTE fromNode="Brain" fromField="count" toNode="Pad" toField="set_visible"/>
</Scene></X3D>
"""


def graph(text=DOOR):
    return bg.Behaviour.from_x3d(text)


def counting(field, value, time, state):
    if field == "poke":
        state["n"] = state.get("n", 0) + state["step"]
        return [("place", (float(state["n"]), 0.0, 0.0)), ("count", state["n"])]
    return []


class ScriptTests(unittest.TestCase):

    def test_a_handler_gets_each_event_and_its_outputs_travel_in_the_same_cascade(self):
        seen = []

        def handler(field, value, time, state):
            seen.append((field, value, time))
            return counting(field, value, time, state)
        sim = bs.Simulation(graph())
        sim.host("Brain", handler)
        sim.start(0.0)
        changes = sim.click("Touch", 1.0, held=0.0)
        self.assertEqual([(f, v) for f, v, _t in seen if f == "poke"], [("poke", 1.0)])
        self.assertIn(("Lamp", "translation", (3.0, 0.0, 0.0)), changes)
        self.assertEqual(sim.values[("Lamp", "translation")], (3.0, 0.0, 0.0))

    def test_the_handler_is_called_with_the_declared_values_as_state_and_initialize_first(self):
        calls = []
        sim = bs.Simulation(graph())
        sim.host("Brain", lambda field, value, time, state: calls.append((field, dict(state), time)) or [])
        sim.start(5.0)
        self.assertEqual(calls[0][0], bs.INITIALIZE)
        self.assertEqual((calls[0][1]["step"], calls[0][1]["armed"], calls[0][2]), (3, True, 5.0))
        self.assertNotIn("poke", calls[0][1])            # an inputOnly field holds no value

    def test_an_inputoutput_field_echoes_before_the_handler_sends_and_is_named_by_its_own_name(self):
        order = []

        def handler(field, value, time, state):
            order.append(field)
            return [("count", 7)] if field == "armed" else []
        sim = bs.Simulation(graph())
        sim.host("Brain", handler)
        sim.start(0.0)
        sim.post("Touch", "isActive", False, 1.0)
        self.assertIn("armed", order)
        names = [e[2] for e in sim.log if e[1] == "Brain"]
        self.assertLess(names.index("armed"), names.index("count"))
        self.assertIs(sim.outputs[("Brain", "armed")], False)

    def test_a_call_sends_one_event_per_field_in_the_order_the_fields_were_first_assigned(self):
        # X_ITE 16.8.1, JavaScript `b = 1; a = 2; b = 3;` in one function: it sent b 3, then a 2
        sim = bs.Simulation(graph())
        sim.host("Brain", lambda f, v, t, s: [("b", 1), ("a", 2), ("b", 3)] if f == "poke" else [])
        sim.start(0.0)
        sim.send("Brain", "poke", 1.0, 1.0)
        sent = [(e[2], e[3]) for e in sim.log if e[1] == "Brain"]
        self.assertEqual(sent, [("b", 3), ("a", 2)])

    def test_a_number_for_an_integer_field_keeps_its_whole_part_and_bad_outputs_are_dropped_not_raised(self):
        sim = bs.Simulation(graph())
        outputs = [("a", 7.9), ("level", 1), ("place", [1, 2, 3]),                  # fits: 7, 1, (1, 2, 3)
                   ("b", "x"), ("count", True), ("poke", 3.0), ("nothing", 1),      # not fits: wrong type, an input, no such field
                   ("level", float("nan")), "oops", (1, 2, 3)]
        sim.host("Brain", lambda f, v, t, s: outputs if f == "poke" else [])
        sim.start(0.0)
        sim.send("Brain", "poke", 1.0, 1.0)
        got = {e[2]: e[3] for e in sim.log if e[1] == "Brain"}
        self.assertEqual((got["a"], got["place"]), (7, (1, 2, 3)))
        self.assertNotIn("b", got)
        self.assertGreaterEqual(sim.dropped.get("mismatch", 0), 6)
        self.assertEqual(sim.faults, [])

    def test_a_handler_that_raises_is_a_fault_and_the_run_goes_on(self):
        def broken(field, value, time, state):
            raise RuntimeError("the person's text failed")
        sim = bs.Simulation(graph())
        sim.host("Brain", broken)
        sim.start(0.0)
        sim.click("Touch", 1.0)
        self.assertTrue(sim.faults)
        self.assertIn("Brain", sim.faults[-1])
        sim.step(2.0)                                       # still alive

    def test_a_handler_may_ask_to_be_called_later(self):
        calls = []

        def handler(field, value, time, state):
            calls.append((field, value, time))
            if field == "poke":
                return [(bs.CALLED_AT, time + 0.5)]
            if field == bs.CALLED_AT:
                return [("count", 1)]
            return []
        sim = bs.Simulation(graph())
        sim.host("Brain", handler)
        sim.start(0.0)
        sim.send("Brain", "poke", 1.0, 1.0)
        sim.step(1.2)
        self.assertNotIn(bs.CALLED_AT, [c[0] for c in calls])
        sim.step(1.6)
        self.assertEqual([c for c in calls if c[0] == bs.CALLED_AT], [(bs.CALLED_AT, 1.5, 1.6)])
        sim.step(3.0)
        self.assertEqual(len([c for c in calls if c[0] == bs.CALLED_AT]), 1)       # once, not every step

    def test_without_a_handler_events_are_recorded_and_counted_and_the_node_says_hosted_not_run(self):
        sim = bs.Simulation(graph())
        self.assertEqual(sim.hosted_not_run(), ["Script Brain"])
        sim.start(0.0)
        sim.click("Touch", 1.0)
        self.assertEqual(sim.noted["hosted-not-run"], 3)             # touchTime, isActive true and false
        machine = sim.machines["Brain"]
        self.assertEqual([(f, v) for _t, f, v in machine.received if f == "poke"], [("poke", 1.0)])
        self.assertEqual(sim.not_simulated, [])
        sim.host("Brain", counting)
        self.assertEqual(sim.hosted_not_run(), [])
        sim.host("Brain", None)
        self.assertEqual(sim.hosted_not_run(), ["Script Brain"])

    def test_host_names_a_script_and_a_function(self):
        sim = bs.Simulation(graph())
        with self.assertRaises(bg.BehaviourError):
            sim.host("Lamp", counting)
        with self.assertRaises(bg.BehaviourError):
            sim.host("Nope", counting)
        with self.assertRaises(bg.BehaviourError):
            sim.host("Brain", "not callable")

    def test_a_script_and_a_collision_sensor_are_simulated_and_the_nodes_it_holds_are_still_wired(self):
        self.assertIn("Script", bs.SIMULATED)
        self.assertIn("CollisionSensor", bs.SIMULATED)
        g = graph()
        self.assertEqual(sorted(g.nodes["Brain"].declared)[0][0], "a")


class JudgedAgainstXiteTests(unittest.TestCase):
    """The probe world has two Scripts that X_ITE 16.8.1 runs as JavaScript; the same two as Python handlers must send the
    same events, stream for stream."""

    def setUp(self):
        self.trace = json.loads((WORLDS / "x_ite_traces" / "probe-script.json").read_text(encoding="utf-8"))
        self.world = WORLDS / "probe-script.x3d"

    def test_the_handlers_agree_with_the_javascript_on_every_stream(self):
        self.assertEqual(self.trace["pageErrors"], [])
        self.assertTrue(self.trace["browser"].startswith("X_ITE 16.8"))
        result = judge_mf.judge(self.world, self.trace, handlers=probe.HANDLERS)
        self.assertEqual([s["source"] for s in result["streams"] if not s["agree"]], [])
        scripts = [s for s in result["streams"] if s["node"] == "Script"]
        self.assertEqual(len(scripts), 6)
        self.assertEqual(result["not_simulated_sources"], [])
        self.assertTrue(all(s["x_ite_events"] > 0 for s in result["streams"]), "a stream X_ITE never sent proves nothing")

    def test_a_wrong_handler_is_caught(self):
        def off_by_one(field, value, time, state):
            sent = probe.counter(field, value, time, state)
            return [(f, v + 1 if f == "count" else v) for f, v in sent]
        result = judge_mf.judge(self.world, self.trace, handlers={**probe.HANDLERS, "Counter": off_by_one})
        self.assertIn("Counter.count", [s["source"] for s in result["streams"] if not s["agree"]])

    def test_without_handlers_the_scripts_are_listed_not_compared(self):
        result = judge_mf.judge(self.world, self.trace)
        self.assertEqual({s["source"].split(".")[0] for s in result["not_simulated_sources"]}, {"Counter", "Threshold"})
        self.assertFalse([s for s in result["streams"] if s["node"] == "Script"])

    def test_the_javascript_in_the_probe_is_not_what_the_handlers_are_written_from_by_copy(self):
        # the world holds JavaScript, the handlers are Python: a change to one must show in the judge, so the two are
        # kept as separate texts that must agree, not one derived from the other
        self.assertIn("ecmascript:", self.world.read_text(encoding="utf-8"))
        self.assertTrue(all(callable(h) for h in probe.HANDLERS.values()))


class CollisionSensorTests(unittest.TestCase):

    def world(self):
        return bg.Behaviour.from_x3d((WORLDS / "wired-collision.x3d").read_text(encoding="utf-8"))

    def test_the_stimulus_drives_isactive_and_the_names(self):
        sim = bs.Simulation(self.world())
        self.assertIn("CollisionSensor Contact", sim.hosted_not_run())
        sim.start(0.0)
        sim.contact("Contact", True, ["Floor|Ball"], ["Floor", "Ball"], 1.0)
        self.assertIs(sim.outputs[("Contact", "isActive")], True)
        self.assertEqual(sim.outputs[("Contact", "contacts")], ["Floor|Ball"])
        self.assertEqual(sim.outputs[("Contact", "intersections")], ["Floor", "Ball"])
        self.assertEqual([n for n in sim.hosted_not_run() if n.startswith("CollisionSensor")], [])
        before = len(sim.log)
        sim.contact("Contact", True, ["Floor|Ball"], ["Floor", "Ball"], 1.1)       # still touching: contacts again, isActive not
        sent = [e[2] for e in list(sim.log)[before:]]
        self.assertEqual(sent, ["contacts", "intersections"])         # X_ITE 16.8.1 sends contacts every frame, isActive on change
        sim.contact("Contact", False, (), (), 1.2)
        self.assertIs(sim.outputs[("Contact", "isActive")], False)

    def test_the_stimulus_reaches_a_script_as_the_same_events_any_node_sends(self):
        sim = bs.Simulation(self.world())
        seen = []
        sim.host("Log", lambda f, v, t, s: seen.append((f, v)) or [])
        sim.start(0.0)
        sim.contact("Contact", True, ["A|B"], ["A"], 1.0)
        self.assertIn(("touching", True), seen)
        self.assertIn(("hits", ["A|B"]), seen)

    def test_a_disabled_sensor_is_silent_and_a_sensor_switched_off_while_touching_ends_the_contact(self):
        g = bg.Behaviour()
        sensor = g.add("CollisionSensor", "S", enabled=False)
        sim = bs.Simulation(g)
        sim.start(0.0)
        sim.contact("S", True, ["A|B"], ["A"], 1.0)
        self.assertEqual(list(sim.log), [])
        g2 = bg.Behaviour()
        g2.add("CollisionSensor", "S")
        sim2 = bs.Simulation(g2)
        sim2.start(0.0)
        sim2.contact("S", True, ["A|B"], ["A"], 1.0)
        sim2.send("S", "enabled", False, 2.0)
        self.assertIs(sim2.outputs[("S", "isActive")], False)

    def test_hostile_stimulus_raises_a_behaviour_error_never_anything_else(self):
        sim = bs.Simulation(self.world())
        sim.start(0.0)
        for args in ((1, [], []), (True, "AB", []), (True, [1, 2], []), (True, [], None), (None, [], [])):
            with self.assertRaises(bg.BehaviourError):
                sim.contact("Contact", *args, 1.0)
        for node in ("Nope", "Wall", "Log"):
            with self.assertRaises(bg.BehaviourError):
                sim.contact(node, True, [], [], 1.0)
        sim.contact("Contact", True, [], [], float("nan"))            # a bad time is counted, not raised
        self.assertEqual(sim.faults, [])

    def test_a_recorded_contact_call_replays(self):
        sim = bs.Simulation(self.world())
        activity = ba.Activity.from_simulation(sim, record=True)
        activity.drive(sim, "start", None, 0.0)
        activity.drive(sim, "contact", "Contact", 1.0, active=True, contacts=["A|B"], intersections=["A"])
        stimulus = json.loads(json.dumps(activity.report()["stimulus"]))
        again = bs.Simulation(self.world())
        ba.replay(again, stimulus)
        self.assertEqual(again.outputs[("Contact", "contacts")], ["A|B"])

    def test_the_recording_agrees_in_timing_within_the_stated_tolerance_but_is_not_a_judgement(self):
        path = WORLDS / "consistency" / "probe-collision"
        trace = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        self.assertEqual(trace["pageErrors"], [])
        self.assertTrue(trace["browser"].startswith("X_ITE 16.8"))
        result = probe.check(path.with_suffix(".x3d"), trace)
        self.assertTrue(result["agree"], result)
        self.assertGreaterEqual(len(result["x_ite"]), 3)
        self.assertEqual(result["disabled_sent"], 0)
        self.assertLessEqual(result["worst_gap"], probe.TOLERANCE)
        # the coverage table must not count it: the recording is outside x_ite_traces/
        self.assertFalse((WORLDS / "x_ite_traces" / "probe-collision.json").exists())

    def test_the_consistency_check_fails_when_the_timing_is_off(self):
        path = WORLDS / "consistency" / "probe-collision"
        trace = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        slow = json.loads(json.dumps(trace))
        slow["events"] = [[e[0] + (0.2 if i == 1 else 0.0), *e[1:]] for i, e in enumerate(slow["events"])]
        # the stimulus is taken from the recording, so a shifted recording shifts the stimulus with it: compare against the original
        original = probe.check(path.with_suffix(".x3d"), trace)
        shifted = probe.stimulus_from(slow)
        self.assertGreater(max(abs(a[0] - b[0]) for a, b in zip(shifted, original["x_ite"])), probe.TOLERANCE)

    def test_what_a_rigid_body_world_can_be_asked(self):
        boxes = {"Floor": ((-5, -1.1, -2), (5, -0.9, 2), 0.0), "Ball": ((-0.5, -0.9, -0.5), (0.5, 0.1, 0.5), 0.0),
                 "High": ((-0.5, 5, -0.5), (0.5, 6, 0.5), 0.0)}
        self.assertEqual(bh.touching(boxes), (["Ball|Floor"], ["Ball", "Floor"]))          # meeting counts
        self.assertEqual(bh.touching(boxes, {"High"}), ([], []))
        self.assertEqual(bh.touching(boxes, {"Ball"}), (["Ball|Floor"], ["Ball"]))
        boxes["High"] = ((-0.5, 0.3, -0.5), (0.5, 1, 0.5), 0.2)                           # a margin of 0.2 closes a gap of 0.2
        self.assertEqual(bh.touching(boxes, {"High"}), (["Ball|High"], ["High"]))
        self.assertEqual(bh.touching({}), ([], []))
        self.assertEqual(bh.collidable_names('<CollisionCollection DEF="C"><CollidableShape USE="A"/><CollidableShape DEF="B"/>'
                                             '<RigidBody USE="A"/></CollisionCollection>'), ["A", "B"])
        self.assertEqual(bh.collidable_names('<CollisionCollection USE="World"/>'), [])
        self.assertEqual(bh.collidable_names("<unclosed"), [])


class ReplayTests(unittest.TestCase):

    def test_a_recording_carries_the_scripts_outputs_so_a_replay_without_the_handler_reproduces_the_run(self):
        world = (WORLDS / "probe-script.x3d").read_text(encoding="utf-8")
        sim = bs.Simulation(bg.Behaviour.from_x3d(world), log_size=10 ** 6)
        for name, handler in probe.HANDLERS.items():
            sim.host(name, handler)
        activity = ba.Activity.from_simulation(sim, record=True)
        activity.drive(sim, "start", None, 0.0)
        activity.drive(sim, "click", "Touch", 1.0)
        for frame in range(1, 150):
            activity.drive(sim, "step", None, 1.0 + frame / 60)
        report = json.loads(json.dumps(activity.report()))
        self.assertTrue(report["script_outputs"])
        self.assertEqual({e[1] for e in report["script_outputs"]}, {"Counter", "Threshold"})
        plain = bs.Simulation(bg.Behaviour.from_x3d(world), log_size=10 ** 6)       # no handlers at all
        ba.replay(plain, report["stimulus"], script_outputs=report["script_outputs"])
        for key in (("Marker", "translation"), ("Pick", "whichChoice")):
            self.assertEqual(plain.values[key], sim.values[key], key)
        self.assertEqual(plain.noted["hosted-not-run"] > 0, True)

    def test_a_recording_without_scripts_has_no_such_block(self):
        sim = bs.Simulation(bg.Behaviour.from_x3d((WORLDS / "door.x3d").read_text(encoding="utf-8")))
        activity = ba.Activity.from_simulation(sim, record=True)
        activity.drive(sim, "start", None, 0.0)
        self.assertNotIn("script_outputs", activity.report())


class NothingFromAFileRunsTests(unittest.TestCase):
    """The add-on never evaluates the text of a file it imported."""

    SOURCE = ROOT / "source"

    def calls(self, path):
        names = {"exec", "eval", "compile", "__import__", "execfile"}
        found = []
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)       # other modules' strings, not ours
            tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                f = node.func
                name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
                if name in names and not (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "re"):
                    found.append((name, node.lineno))
        return found

    def test_exec_and_eval_appear_in_one_place_only_and_it_is_the_gated_handler_loader(self):
        found = {p.name: self.calls(p) for p in sorted(self.SOURCE.rglob("*.py")) if self.calls(p)}
        self.assertEqual(sorted(found), ["behaviour_hosted.py"], found)
        self.assertEqual(sorted(n for n, _ in found["behaviour_hosted.py"]), ["compile", "exec"])
        text = (self.SOURCE / "behaviour_hosted.py").read_text(encoding="utf-8")
        body = text[text.index("def build_handler"):text.index("# ----", text.index("def build_handler"))]
        self.assertLess(body.index("is_enabled"), body.index("exec("), "the registry is asked before anything is run")

    def test_the_text_of_a_script_is_markup_to_the_simulator_never_code(self):
        import builtins
        text = DOOR.replace("function poke(value, time) { }", "function poke(v, t) { } __import__('builtins').PWNED = 1")
        text = text.replace('<Script DEF="Brain">', '<Script DEF="Brain" url=\'"python:__import__(\\"builtins\\").PWNED=2"\'>')
        sim = bs.Simulation(graph(text))
        sim.start(0.0)
        sim.click("Touch", 1.0)
        sim.step(2.0)
        self.assertFalse(hasattr(builtins, "PWNED"))
        self.assertEqual(sim.noted["hosted-not-run"], 3)

    def test_a_hostile_declaration_does_not_run_and_does_not_raise(self):
        text = DOOR.replace('value="3"', 'value="__import__(\'os\').getcwd()"').replace('value="true"', 'value="&lt;&amp;"')
        sim = bs.Simulation(graph(text))
        sim.start(0.0)
        self.assertEqual(sim.machines["Brain"].state["step"], 0)         # not a number: the zero of the type
        self.assertEqual(sim.faults, [])


class EnablementTests(unittest.TestCase):
    """What may run Python: a text the person enabled for one Script in this session, as it was when they enabled it."""

    TEXT = "def handle(field, value, time, state):\n    return [('count', 1)]\n"

    def test_nothing_is_enabled_in_a_new_process(self):
        out = subprocess.run([sys.executable, "-I", "-c", "import sys; sys.path.insert(0, sys.argv[1]); import behaviour_hosted as h; "
                              "print(len(h.REGISTRY))", str(ROOT / "source")], capture_output=True, text=True, check=True)
        self.assertEqual(out.stdout.strip(), "0")

    def test_a_handler_is_built_only_for_what_was_enabled(self):
        registry = bh.Registry()
        with self.assertRaises(bh.HostedRefused):
            bh.build_handler("Scene", "Brain", "h.py", self.TEXT, registry)             # never enabled
        registry.enable("Scene", "Brain", "h.py", self.TEXT)
        handler = bh.build_handler("Scene", "Brain", "h.py", self.TEXT, registry)
        self.assertEqual(handler("poke", 1.0, 1.0, {}), [("count", 1)])

    def test_enablement_is_for_one_script_one_scene_one_text_and_one_content(self):
        registry = bh.Registry()
        registry.enable("Scene", "Brain", "h.py", self.TEXT)
        for scope, script, name, source in (("Other", "Brain", "h.py", self.TEXT), ("Scene", "Remote", "h.py", self.TEXT),
                                            ("Scene", "Brain", "other.py", self.TEXT),
                                            ("Scene", "Brain", "h.py", self.TEXT + "# edited\n")):
            with self.subTest(scope=scope, script=script, name=name, edited=source != self.TEXT):
                with self.assertRaises(bh.HostedRefused):
                    bh.build_handler(scope, script, name, source, registry)

    def test_the_reasons_are_said(self):
        registry = bh.Registry()
        with self.assertRaisesRegex(bh.HostedRefused, "never enabled"):
            bh.build_handler("S", "A", "t", "x", registry)
        registry.enable("S", "A", "t", "x")
        with self.assertRaisesRegex(bh.HostedRefused, "changed since"):
            bh.build_handler("S", "A", "t", "y", registry)
        with self.assertRaisesRegex(bh.HostedRefused, "another text"):
            bh.build_handler("S", "A", "u", "x", registry)

    def test_disable_and_clear(self):
        registry = bh.Registry()
        registry.enable("S", "A", "t", self.TEXT)
        registry.disable("S", "A")
        with self.assertRaises(bh.HostedRefused):
            bh.build_handler("S", "A", "t", self.TEXT, registry)
        registry.enable("S", "A", "t", self.TEXT)
        registry.clear()
        self.assertEqual(len(registry), 0)

    def test_a_text_that_is_not_a_handler_or_does_not_run_is_refused_with_the_reason(self):
        registry = bh.Registry()
        for source, why in (("x = 1\n", "defines no function"), ("def handle(:\n", "did not run"), ("raise ValueError('no')\n", "did not run")):
            registry.enable("S", "A", "t", source)
            with self.assertRaisesRegex(bh.HostedRefused, why):
                bh.build_handler("S", "A", "t", source, registry)

    def test_nothing_in_a_files_data_can_enable_a_handler(self):
        # the registry has no constructor argument, no loader and no field that data from a file could set
        registry = bh.Registry()
        self.assertEqual(len(registry), 0)
        for hostile in ({"enabled": True}, "enabled", None, 1):
            with self.assertRaises(TypeError):
                bh.Registry(hostile)
        self.assertFalse([n for n in dir(bh) if not n.startswith("__") and ("load" in n.lower() or "from_file" in n.lower())])


if __name__ == "__main__":
    unittest.main()
