# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The behaviour graph core (source/behaviour_graph.py) in plain Python: no Blender needed.

    cd tests && python -m unittest test_behaviour_graph
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "source"))

import behaviour_graph as bg  # noqa: E402
from behaviour_catalogue import NODES, TARGETS, X3DUOM_SHA256  # noqa: E402

FIXTURES = ROOT / "tests" / "behaviour"
ROUTE_DEMO = (FIXTURES / "route-demo.x3d").read_text(encoding="utf-8")

SCENE = """<?xml version="1.0" encoding="UTF-8"?>
<X3D profile="Interchange" version="4.0"><Scene>
  <Transform DEF="Door"><Shape><Box/></Shape></Transform>
  <Transform DEF="Lamp"><PointLight DEF="Bulb"/></Transform>
</Scene></X3D>
"""


def door():
    b = bg.Behaviour()
    click = b.add("TouchSensor", "Click", parent="Door")
    timer = b.add("TimeSensor", "Timer", cycleInterval=2)
    slide = b.add("PositionInterpolator", "Slide", key=[0, 1], keyValue=[(0, 0, 0), (0, 2, 0)])
    target = b.target("Transform", "Door")
    click.touchTime >> timer.startTime
    timer.fraction_changed >> slide.set_fraction
    slide.value_changed >> target.translation
    return b


class CatalogueTests(unittest.TestCase):

    def test_catalogue_is_generated_from_the_object_model(self):
        self.assertEqual(len(X3DUOM_SHA256), 64)
        self.assertEqual(len(NODES), 45)
        self.assertEqual(sum(len(rows) for _group, rows in NODES.values()), 303)
        self.assertEqual(len(TARGETS), 34)       # 32, then HAnimSegment and HAnimSite

    def test_events_are_in_the_catalogue(self):
        fields = {row[0]: row for row in NODES["TouchSensor"][1]}
        self.assertEqual(fields["touchTime"][1:3], ("SFTime", "outputOnly"))
        self.assertEqual(fields["isActive"][1:3], ("SFBool", "outputOnly"))

    def test_route_cases(self):
        cases = json.loads((FIXTURES / "route-cases.json").read_text(encoding="utf-8"))["cases"]
        self.assertGreaterEqual(len(cases), 50)
        for from_type, from_field, to_type, to_field, expected in cases:
            with self.subTest(route=f"{from_type}.{from_field} -> {to_type}.{to_field}"):
                self.assertEqual(bg.route_verdict(from_type, from_field, to_type, to_field), expected)

    def test_generator_check_passes_when_the_object_model_is_present(self):
        model = ROOT.parent / "x3d_mcp" / "src" / "validation" / "schemas" / "X3dUnifiedObjectModel-4.0.xml"
        if not model.exists():
            self.skipTest("X3DUOM not on this machine")
        done = subprocess.run([sys.executable, str(ROOT / "tools" / "behaviour_catalogue_gen.py"), str(model), "--check"],
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)


class ScriptingTests(unittest.TestCase):

    def test_door_reads_as_three_routes(self):
        self.assertEqual(door().explain().splitlines(), [
            "TouchSensor Click.touchTime --SFTime--> TimeSensor Timer.startTime",
            "TimeSensor Timer.fraction_changed --SFFloat--> PositionInterpolator Slide.set_fraction",
            "PositionInterpolator Slide.value_changed --SFVec3f--> Transform Door.translation"])
        self.assertEqual(door().check(), [])

    def test_python_values_become_x3d_text(self):
        b = bg.Behaviour()
        node = b.add("TimeSensor", "T", loop=True, cycleInterval=2.5).node
        self.assertEqual(node.fields, {"loop": "true", "cycleInterval": "2.5"})
        self.assertEqual(bg.to_lexical([(0, 0, 0), (0, 2, 0.5)]), "0 0 0 0 2 0.5")
        self.assertEqual(bg.to_lexical(["a", 'b "c"'], "MFString"), '"a" "b \\"c\\""')
        self.assertEqual(bg.to_lexical(-0.0), "0")

    def test_a_route_between_two_types_is_refused(self):
        b = door()
        with self.assertRaises(bg.BehaviourError) as caught:
            b.get("Click").isActive >> b.get("Timer").startTime
        self.assertEqual(caught.exception.code, "type-mismatch")
        self.assertIn("SFBool", str(caught.exception))
        self.assertIn("SFTime", str(caught.exception))
        self.assertEqual(len(b.routes), 3)

    def test_a_route_against_the_flow_is_refused(self):
        b = door()
        with self.assertRaises(bg.BehaviourError) as caught:
            b.get("Timer").startTime >> b.get("Click").touchTime
        self.assertEqual(caught.exception.code, "wrong-direction")

    def test_mistakes_name_the_fix(self):
        b = bg.Behaviour()
        with self.assertRaises(bg.BehaviourError) as caught:
            b.add("TimeSensr")
        self.assertIn("TimeSensor", str(caught.exception))
        timer = b.add("TimeSensor")
        self.assertEqual(timer.id, "TimeSensor1")
        with self.assertRaises(bg.BehaviourError) as caught:
            timer.set(isActive=True)
        self.assertEqual(caught.exception.code, "event-has-no-value")
        with self.assertRaises(bg.BehaviourError) as caught:
            timer.cycleIntervl
        self.assertIn("cycleInterval", str(caught.exception))
        with self.assertRaises(bg.BehaviourError) as caught:
            b.add("TimeSensor", "TimeSensor1")
        self.assertEqual(caught.exception.code, "duplicate-def")

    def test_fan_in_and_fan_out_are_legal(self):
        b = door()
        second = b.add("TouchSensor", "Click2", parent="Door")
        second.touchTime >> b.get("Timer").startTime
        b.get("Slide").value_changed >> b.get("Door").scale
        self.assertEqual(b.check(), [])
        self.assertEqual(len(b.routes), 5)

    def test_the_same_route_twice_is_one_route(self):
        b = door()
        b.get("Click").touchTime >> b.get("Timer").startTime
        self.assertEqual(len(b.routes), 3)

    def test_remove_takes_the_routes_with_it(self):
        b = door()
        b.remove("Timer")
        self.assertEqual(len(b.routes), 1)
        self.assertTrue(b.disconnect(b.get("Slide").value_changed, b.get("Door").translation))
        self.assertEqual(b.routes, [])

    def test_json_round_trip(self):
        b = door()
        again = bg.from_json(json.loads(json.dumps(bg.to_json(b))))
        self.assertEqual(bg.signature(again), bg.signature(b))
        with self.assertRaises(bg.BehaviourError):
            bg.from_json({"schema": "other"})


HANIM_SCENE = """<?xml version="1.0" encoding="UTF-8"?>
<X3D profile="Immersive" version="4.0"><head><component name="HAnim" level="1"/></head><Scene>
  <HAnimHumanoid DEF="Body" name="Body">
    <HAnimJoint DEF="hanim_root" name="root" center="0 1 0" containerField="skeleton">
      <HAnimSegment DEF="Seg" name="seg"/>
      <HAnimSite DEF="Tip" name="tip" translation="0 1 0"/>
    </HAnimJoint>
  </HAnimHumanoid>
</Scene></X3D>
"""


class HAnimTargetTests(unittest.TestCase):

    def graph(self):
        b = bg.Behaviour()
        timer = b.add("TimeSensor", "Timer", cycleInterval=2)
        turn = b.add("OrientationInterpolator", "Turn", key=[0, 1], keyValue=[(0, 0, 1, 0), (0, 0, 1, 1)])
        slide = b.add("PositionInterpolator", "Slide", key=[0, 1], keyValue=[(0, 0, 0), (0, 1, 0)])
        weigh = b.add("ScalarInterpolator", "Weigh", key=[0, 1], keyValue=[1, 2])
        joint, site, segment = b.target("HAnimJoint", "hanim_root"), b.target("HAnimSite", "Tip"), b.target("HAnimSegment", "Seg")
        timer.fraction_changed >> turn.set_fraction
        timer.fraction_changed >> slide.set_fraction
        timer.fraction_changed >> weigh.set_fraction
        turn.value_changed >> joint.rotation
        slide.value_changed >> joint.translation
        slide.value_changed >> joint.scale
        slide.value_changed >> joint.center
        turn.value_changed >> site.rotation
        slide.value_changed >> site.translation
        weigh.value_changed >> segment.mass
        return b

    def test_the_three_types_are_targets_with_the_fields_of_the_object_model(self):
        for name in ("HAnimJoint", "HAnimSegment", "HAnimSite"):
            self.assertIn(name, TARGETS)
        joint = {row[0]: row for row in TARGETS["HAnimJoint"]}
        for field, kind in (("rotation", "SFRotation"), ("translation", "SFVec3f"), ("scale", "SFVec3f"), ("center", "SFVec3f")):
            self.assertEqual(joint[field][1:3], (kind, "inputOutput"))
        self.assertEqual({row[0]: row[1] for row in TARGETS["HAnimSegment"]}["mass"], "SFFloat")
        self.assertEqual({row[0]: row[1] for row in TARGETS["HAnimSite"]}["translation"], "SFVec3f")
        self.assertEqual([bg.BINDING_OF[t] for t in ("HAnimJoint", "HAnimSite", "HAnimSegment")], ["joint", "site", "site"])

    def test_a_segment_has_no_rotation_in_the_object_model_so_a_route_to_it_is_refused(self):
        # X3DUOM 4.0 gives HAnimSegment centerOfMass, mass, momentsOfInertia, coord ...: no rotation or translation.
        b = bg.Behaviour()
        turn = b.add("OrientationInterpolator", "Turn")
        segment = b.target("HAnimSegment", "Seg")
        with self.assertRaises(bg.BehaviourError) as caught:
            turn.value_changed >> segment.rotation
        self.assertEqual(caught.exception.code, "unknown-field")

    def test_the_type_is_checked_like_a_transform_s(self):
        b = bg.Behaviour()
        slide = b.add("PositionInterpolator", "Slide")
        joint = b.target("HAnimJoint", "J")
        with self.assertRaises(bg.BehaviourError) as caught:
            slide.value_changed >> joint.rotation
        self.assertEqual(caught.exception.code, "type-mismatch")

    def test_routes_to_them_read_from_a_file_and_write_back_with_no_difference(self):
        b = self.graph()
        self.assertEqual(b.check(), [])
        text = b.weave(HANIM_SCENE)
        again = bg.Behaviour.from_x3d(text)
        self.assertEqual(again.nodes["hanim_root"].node_type, "HAnimJoint")
        self.assertEqual(again.nodes["hanim_root"].binding, ("joint", "hanim_root"))
        self.assertEqual(again.nodes["Tip"].binding, ("site", "Tip"))
        self.assertEqual(bg.difference(b, again),
                         {"nodes_lost": [], "nodes_added": [], "fields_changed": {}, "routes_lost": [], "routes_added": []})
        self.assertEqual(bg.difference(again, bg.Behaviour.from_x3d(again.weave(bg.strip(text)))),
                         {"nodes_lost": [], "nodes_added": [], "fields_changed": {}, "routes_lost": [], "routes_added": []})
        self.assertEqual(len(again.routes), 10)

    def test_bind_keeps_a_joint_the_resolver_does_not_know_by_name(self):
        parsed = bg.parse_x3d(self.graph().weave(HANIM_SCENE))
        self.assertEqual(parsed.nodes["hanim_root"].binding, None)
        self.assertEqual(parsed._candidates["hanim_root"]["hanim_name"], "root")      # what the importer names the bone
        bg.bind(parsed, lambda name, node_type: (bg.BINDING_OF[node_type], name) if node_type in bg.BINDING_OF else None)
        self.assertEqual(parsed.nodes["hanim_root"].binding, ("joint", "hanim_root"))
        self.assertEqual(len([n for n in parsed.nodes.values() if n.role == bg.CARRIED]), 0)
        self.assertEqual(len(parsed.routes), 10)

    def test_json_keeps_the_binding(self):
        again = bg.from_json(bg.to_json(self.graph()))
        self.assertEqual(again.nodes["Seg"].binding, ("site", "Seg"))
        self.assertEqual(bg.difference(self.graph(), again)["routes_lost"], [])


SWITCH_SCENE = """<?xml version="1.0" encoding="UTF-8"?>
<X3D profile="Immersive" version="4.0"><Scene>
  <Switch DEF="Pick" whichChoice="0"><Shape><Box/></Shape><Shape><Sphere/></Shape></Switch>
</Scene></X3D>
"""


class SwitchTargetTests(unittest.TestCase):

    def graph(self):
        b = bg.Behaviour()
        steps = b.add("IntegerSequencer", "Steps", key=[0, 0.5], keyValue=[1, 0])
        b.add("TimeSensor", "Timer", cycleInterval=2).fraction_changed >> steps.set_fraction
        steps.value_changed >> b.target("Switch", "Pick").whichChoice
        return b

    def test_whichChoice_is_an_int32_target_bound_as_a_switch(self):
        row = {r[0]: r for r in TARGETS["Switch"]}["whichChoice"]
        self.assertEqual(row[1:3], ("SFInt32", "inputOutput"))
        self.assertEqual(bg.BINDING_OF["Switch"], "switch")
        self.assertEqual(self.graph().nodes["Pick"].binding, ("switch", "Pick"))

    def test_a_float_is_not_a_choice(self):
        b = bg.Behaviour()
        weigh = b.add("ScalarInterpolator", "Weigh")
        with self.assertRaises(bg.BehaviourError) as caught:
            weigh.value_changed >> b.target("Switch", "Pick").whichChoice
        self.assertEqual(caught.exception.code, "type-mismatch")

    def test_the_route_reads_from_a_file_and_writes_back_with_no_difference(self):
        b = self.graph()
        again = bg.Behaviour.from_x3d(b.weave(SWITCH_SCENE))
        self.assertEqual(again.nodes["Pick"].binding, ("switch", "Pick"))
        self.assertEqual(bg.difference(b, again),
                         {"nodes_lost": [], "nodes_added": [], "fields_changed": {}, "routes_lost": [], "routes_added": []})
        self.assertEqual(len(again.routes), 2)


class DocumentTests(unittest.TestCase):

    def test_weave_puts_the_sensor_in_its_parent_and_the_rest_at_the_end(self):
        text = door().weave(SCENE)
        self.assertIn('<Transform DEF="Door">', text)
        root = bg.ET.fromstring(text)
        scene = root.find("Scene")
        door_transform = scene.find("Transform")
        self.assertEqual([child.tag for child in door_transform], ["Shape", "TouchSensor"])
        self.assertEqual([child.tag for child in scene][-5:],
                         ["TimeSensor", "PositionInterpolator", "ROUTE", "ROUTE", "ROUTE"])

    def test_weave_then_read_gives_the_same_graph(self):
        b = door()
        again = bg.Behaviour.from_x3d(b.weave(SCENE))
        self.assertEqual(bg.difference(b, again),
                         {"nodes_lost": [], "nodes_added": [], "fields_changed": {}, "routes_lost": [], "routes_added": []})

    def test_weave_refuses_a_missing_target_and_a_broken_graph(self):
        b = door()
        b.target("Transform", "Window")
        with self.assertRaises(bg.BehaviourError) as caught:
            b.weave(SCENE)
        self.assertEqual(caught.exception.code, "unknown-def")
        b = door()
        b.route("Click", "isActive", "Timer", "startTime", check=False)
        with self.assertRaises(bg.BehaviourError) as caught:
            b.weave(SCENE)
        self.assertEqual(caught.exception.code, "type-mismatch")

    def test_strip_and_weave_restore_a_real_file(self):
        graph = bg.Behaviour.from_x3d(ROUTE_DEMO)
        self.assertEqual(ROUTE_DEMO.count("<ROUTE"), 22)
        self.assertEqual(len(graph.routes), 22)
        self.assertEqual(sum(1 for n in graph.nodes.values() if n.role == bg.BEHAVIOUR), 17)
        bare = bg.strip(ROUTE_DEMO)
        self.assertEqual(bare.count("<ROUTE"), 0)
        self.assertNotIn("TimeSensor", bare)
        again = bg.Behaviour.from_x3d(graph.weave(bare))
        difference = bg.difference(graph, again)
        self.assertEqual({key: len(value) for key, value in difference.items()},
                         {"nodes_lost": 0, "nodes_added": 0, "fields_changed": 0, "routes_lost": 0, "routes_added": 0})

    def test_every_route_of_the_real_file_is_legal(self):
        graph = bg.Behaviour.from_x3d(ROUTE_DEMO)
        self.assertEqual(graph.check(), [])

    def test_a_route_to_a_missing_def_is_reported_not_guessed(self):
        text = SCENE.replace("</Scene>", '<TimeSensor DEF="T"/><ROUTE fromNode="T" fromField="isActive" toNode="Ghost" '
                                         'toField="on"/></Scene>')
        graph = bg.parse_x3d(text)
        self.assertEqual(graph.routes, [])
        self.assertIn("Ghost", graph.diagnostics[0])

    def test_an_unresolved_top_level_node_is_carried_whole(self):
        graph = bg.parse_x3d(ROUTE_DEMO)
        known = {"OB_Door", "OB_Beacon", "OB_Spinner", "CA_Overview"}
        bg.bind(graph, lambda name, node_type: (bg.BINDING_OF.get(node_type, "def"), name) if name in known else None)
        carried = [node for node in graph.nodes.values() if node.role == bg.CARRIED]
        self.assertEqual([node.id for node in carried], ["TourRig"])
        self.assertIn("TourView", carried[0].inner)
        into_rig = sorted({route.to_field for route in graph.routes if route.to_id == "TourRig"})
        self.assertEqual(into_rig, ["TourView.set_bind", "set_rotation", "set_translation"])
        self.assertEqual(len(graph.routes), 22)
        emission = bg.emit(graph)
        self.assertEqual((emission.written_routes, emission.dropped_routes), (22, 0))
        self.assertTrue(any("<Transform" in text and "TourView" in text for text in emission.root))

    def test_an_unexported_target_drops_its_routes_and_says_so(self):
        b = door()
        emission = bg.emit(b, def_of_target=lambda node: None)
        self.assertEqual((emission.written_routes, emission.dropped_routes), (2, 1))
        self.assertTrue(any("Door" in message for message in emission.diagnostics))

    def test_layout_runs_left_to_right(self):
        positions = bg.layout(door())
        self.assertLess(positions["Click"][0], positions["Timer"][0])
        self.assertLess(positions["Timer"][0], positions["Slide"][0])
        self.assertLess(positions["Slide"][0], positions["Door"][0])

    def test_layout_survives_a_cycle(self):
        b = bg.Behaviour()
        a = b.add("TimeSensor", "A")
        c = b.add("TimeSensor", "B")
        a.cycleTime >> c.startTime
        c.cycleTime >> a.startTime
        self.assertEqual(set(bg.layout(b)), {"A", "B"})

    def test_unstack_pushes_a_tall_node_s_neighbour_down(self):
        # rows 200 apart, but the top node is 500 tall: the one below must move, the other column must not
        boxes = [("Tall", 0, 0, 500), ("Below", 0, -200, 100), ("Last", 0, -400, 100), ("Other", 320, -200, 100)]
        moved = bg.unstack_columns(boxes, gap=40)
        self.assertEqual(moved, {"Below": -540, "Last": -680})

    def test_unstack_leaves_a_spaced_column_alone(self):
        boxes = [("A", 0, 0, 100), ("B", 0, -200, 100), ("C", 0, -400, 100)]
        self.assertEqual(bg.unstack_columns(boxes, gap=40), {})


if __name__ == "__main__":
    unittest.main()
