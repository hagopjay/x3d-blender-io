# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The twelve event nodes P0 wired (docs/BEHAVIOUR_EVENT_NODES.md), in plain Python: no Blender, no browser.

Nine are behaviour nodes of the graph (the Geo nodes, the pick sensors, CollisionSensor, Script); three are scene
nodes the graph leaves where the scene has them (Collision, AudioClip, MovieTexture). One world per family under
tests/behaviour/ (wired-geo, wired-pick, wired-media, wired-script, wired-collision) is read, written back
(``weave(strip(document), graph)``) and compared canonically. Nothing here simulates the nodes: they are wired. ::

    python -m unittest tests.test_behaviour_wired
"""

from __future__ import annotations

import collections
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "source"))

import behaviour_catalogue as cat   # noqa: E402
import behaviour_graph as bg        # noqa: E402
import behaviour_sim as bs          # noqa: E402

WORLDS = ROOT / "tests" / "behaviour"
FAMILIES = {
    "wired-geo": {"GeoPositionInterpolator", "GeoProximitySensor", "GeoTouchSensor"},
    "wired-pick": {"LinePickSensor", "PointPickSensor", "PrimitivePickSensor", "VolumePickSensor"},
    "wired-media": {"AudioClip", "MovieTexture"},
    "wired-script": {"Script"},
    "wired-collision": {"Collision", "CollisionSensor"},
}
NINE = {"GeoPositionInterpolator", "GeoProximitySensor", "GeoTouchSensor", "LinePickSensor", "PointPickSensor",
        "PrimitivePickSensor", "VolumePickSensor", "CollisionSensor", "Script"}
IN_PLACE = {"Collision", "AudioClip", "MovieTexture"}


def text_of(name):
    return (WORLDS / f"{name}.x3d").read_text(encoding="utf-8")


def canonical(element):
    """One element, with its children, as canonical XML (attributes sorted, empty elements written out, text that is only
    white space removed): equal text means equal element."""
    copy = ET.fromstring(ET.tostring(element))
    copy.tail = None
    return ET.canonicalize(ET.tostring(copy, encoding="unicode"), strip_text=True)


def census(text):
    """What a document holds, by kind: tags, DEFs and USEs counted. A node lost, copied or lifted into another place
    changes a count."""
    root = ET.fromstring(text)
    return (collections.Counter(e.tag for e in root.iter()), collections.Counter(e.get("DEF") for e in root.iter() if e.get("DEF")),
            collections.Counter(e.get("USE") for e in root.iter() if e.get("USE")))


def by_def(text):
    return {e.get("DEF"): e for e in ET.fromstring(text).iter() if e.get("DEF")}


def routes_of(text):
    return collections.Counter((r.get("fromNode"), r.get("fromField"), r.get("toNode"), r.get("toField"))
                               for r in ET.fromstring(text).iter("ROUTE"))


def trip(name):
    """(graph, the document written back from it): behaviour taken out of the file and woven in again from the graph."""
    text = text_of(name)
    graph = bg.Behaviour.from_x3d(text)
    return graph, bg.weave(bg.strip(text), graph)


class CatalogueTests(unittest.TestCase):

    def test_the_nine_are_behaviour_nodes_with_their_fields(self):
        for name in NINE:
            with self.subTest(node=name):
                self.assertIn(name, cat.NODES)
        rows = {row[0]: row[1:3] for row in cat.NODES["LinePickSensor"][1]}
        self.assertEqual(rows["pickedPoint"], ("MFVec3f", "outputOnly"))
        self.assertEqual(rows["pickedGeometry"], ("MFNode", "outputOnly"))
        self.assertEqual(rows["pickTarget"], ("MFNode", "inputOutput"))
        self.assertEqual({row[0]: row[1] for row in cat.NODES["GeoPositionInterpolator"][1]}["geovalue_changed"], "SFVec3d")
        self.assertEqual({row[0]: row[1:3] for row in cat.NODES["CollisionSensor"][1]}["contacts"], ("MFNode", "outputOnly"))

    def test_a_scripts_field_children_are_not_catalogue_fields(self):
        self.assertNotIn("field", {row[0] for row in cat.NODES["Script"][1]})
        self.assertEqual({row[0]: row[1] for row in cat.NODES["Script"][1]}["url"], "MFString")

    def test_the_three_scene_nodes_stay_targets_and_are_named_in_place(self):
        self.assertEqual(set(cat.IN_PLACE), IN_PLACE)
        for name in IN_PLACE:
            with self.subTest(node=name):
                self.assertNotIn(name, cat.NODES)                # not lifted out of the scene
                self.assertIn(name, cat.TARGETS)
                self.assertEqual(bg.BINDING_OF[name], "scene")
        self.assertEqual({row[0]: row[1:3] for row in cat.TARGETS["Collision"]}["collideTime"], ("SFTime", "outputOnly"))
        self.assertEqual({row[0]: row[1:3] for row in cat.TARGETS["MovieTexture"]}["duration_changed"], ("SFTime", "outputOnly"))
        self.assertEqual({row[0]: row[1:3] for row in cat.TARGETS["AudioClip"]}["isActive"], ("SFBool", "outputOnly"))

    def test_none_of_the_twelve_is_simulated_yet(self):
        # the hosted two (Script, CollisionSensor) now are: Simulation.host and Simulation.contact (tests/test_behaviour_hosted.py)
        self.assertFalse(((NINE | IN_PLACE) - {"Script", "CollisionSensor"}) & set(bs.SIMULATED))

    def test_every_node_that_is_placed_in_the_scene_is_listed_as_placed(self):
        self.assertLessEqual({"GeoProximitySensor", "GeoTouchSensor", "LinePickSensor", "PointPickSensor",
                              "PrimitivePickSensor", "VolumePickSensor"}, bg.PLACED_TYPES)
        self.assertFalse({"Script", "CollisionSensor", "GeoPositionInterpolator"} & bg.PLACED_TYPES)


class WorldTests(unittest.TestCase):

    def test_each_world_is_read_whole(self):
        for name, nodes in FAMILIES.items():
            with self.subTest(world=name):
                graph = bg.Behaviour.from_x3d(text_of(name))
                self.assertEqual(graph.diagnostics, [])
                self.assertEqual(bg.validate(graph), [])
                kinds = {node.node_type: node.role for node in graph.nodes.values()}
                for node in nodes:
                    self.assertEqual(kinds[node], bg.TARGET if node in IN_PLACE else bg.BEHAVIOUR, node)
                self.assertEqual(len(graph.routes), len(routes_of(text_of(name))))

    def test_every_node_and_every_route_is_written_back(self):
        for name in FAMILIES:
            with self.subTest(world=name):
                graph, out = trip(name)
                before = text_of(name)
                # every ROUTE, once each
                self.assertEqual(routes_of(out), routes_of(before))
                # every node element, with its children and attributes, equal canonically (white-space-only text aside)
                original, written = by_def(before), by_def(out)
                self.assertEqual(set(original), set(written))
                for def_name, element in original.items():
                    self.assertEqual(canonical(written[def_name]), canonical(element), def_name)
                # nothing lost, nothing duplicated: the same tags, DEFs and USEs, in the same numbers
                self.assertEqual(census(out), census(before))
                # and read again, the graph has no difference
                self.assertEqual({k: v for k, v in bg.difference(graph, bg.Behaviour.from_x3d(out)).items() if v}, {})

    def test_the_scene_around_the_behaviour_is_untouched(self):
        for name in FAMILIES:
            with self.subTest(world=name):
                _graph, out = trip(name)
                self.assertEqual(canonical(ET.fromstring(bg.strip(out))), canonical(ET.fromstring(bg.strip(text_of(name)))))

    def test_a_collision_keeps_its_children_and_its_proxy(self):
        graph, out = trip("wired-collision")
        wall = by_def(out)["Wall"]
        self.assertEqual([child.get("DEF") or child.tag for child in wall], ["Slab", "Pillar", "Shape"])
        self.assertEqual(wall.find("Shape").get("containerField"), "proxy")
        self.assertEqual(sum(1 for e in ET.fromstring(out).iter("Collision")), 1)
        self.assertEqual(graph.nodes["Wall"].binding, ("scene", "Wall"))
        keys = graph.route_keys()
        self.assertIn(("Wall", "collideTime", "HitClock", "startTime"), keys)
        self.assertIn(("Wall", "isActive", "Toggle", "set_boolean"), keys)

    def test_a_collision_sensor_keeps_its_collider_and_its_contacts_route(self):
        graph, out = trip("wired-collision")
        sensor = by_def(out)["Contact"]
        collider = sensor.find("CollisionCollection")
        self.assertEqual((collider.get("DEF"), collider.get("containerField"), collider.get("bounce")), ("World", "collider", "0.5"))
        self.assertIn(("Contact", "contacts", "Log", "hits"), graph.route_keys())

    def test_media_nodes_stay_in_their_parents(self):
        _graph, out = trip("wired-media")
        root = ET.fromstring(out)
        parents = {child.get("DEF"): parent.tag for parent in root.iter() for child in parent if child.get("DEF")}
        self.assertEqual(parents["Tone"], "Sound")
        self.assertEqual(parents["Film"], "Appearance")

    def test_pick_sensors_keep_their_references_and_their_places(self):
        graph, out = trip("wired-pick")
        root = ET.fromstring(out)
        gun = by_def(out)["Gun"]
        self.assertEqual([child.get("DEF") for child in gun], ["Ray", "Dot", "Prim", "Vol"])
        dot = by_def(out)["Dot"]
        self.assertEqual([(c.tag, c.get("USE"), c.get("containerField")) for c in dot][1:],
                         [("Shape", "BallShape", "pickTarget"), ("Shape", "CrateShape", "pickTarget")])
        self.assertEqual(collections.Counter(e.get("USE") for e in root.iter() if e.get("USE"))["World"], 3)
        self.assertEqual(graph.nodes["Ray"].parent, "Gun")

    def test_geo_nodes_keep_their_origin_and_sit_where_they_sat(self):
        graph, out = trip("wired-geo")
        root = ET.fromstring(out)
        self.assertEqual(sum(1 for e in root.iter("GeoOrigin") if e.get("DEF")), 1)
        self.assertEqual(sum(1 for e in root.iter("GeoOrigin") if e.get("USE") == "Origin"), 3)
        self.assertEqual((graph.nodes["Ground"].parent, graph.nodes["Near"].parent, graph.nodes["Route"].parent),
                         ("Terrain", "Terrain", None))
        self.assertEqual(by_def(out)["Route"].get("keyValue"), "48.8 2.3 0 48.9 2.4 100")


class ScriptTests(unittest.TestCase):

    SOURCE_MARK = "ecmascript:\nfunction touched(value, time) {"

    def test_declared_fields_become_typed_ports_in_the_right_directions(self):
        graph = bg.Behaviour.from_x3d(text_of("wired-script"))
        brain = graph.nodes["Brain"]
        self.assertEqual({row[0]: row[1:] for row in brain.declared}, {
            "touched": ("SFTime", "inputOnly"), "fraction": ("SFFloat", "inputOnly"), "place": ("SFVec3f", "outputOnly"),
            "on": ("SFBool", "inputOutput"), "steps": ("SFInt32", "initializeOnly"), "names": ("MFString", "outputOnly"),
            "where": ("SFVec3d", "inputOnly"), "things": ("MFNode", "inputOnly"), "thing": ("SFNode", "initializeOnly")})
        resolve = lambda field, way: bg.resolve_field("Script", field, way, brain.declared)    # noqa: E731
        self.assertEqual(resolve("place", "out"), ("place", "SFVec3f"))
        self.assertEqual(resolve("set_on", "in"), ("on", "SFBool"))           # inputOutput: both ways and both spellings
        self.assertEqual(resolve("on_changed", "out"), ("on", "SFBool"))
        for field, way, code in (("place", "in", "wrong-direction"), ("touched", "out", "wrong-direction"),
                                 ("steps", "in", "wrong-direction"), ("steps", "out", "wrong-direction"),
                                 ("nothing", "in", "unknown-field")):
            with self.subTest(field=field, way=way), self.assertRaises(bg.BehaviourError) as caught:
                resolve(field, way)
            self.assertEqual(caught.exception.code, code)
        # the node's own fields are still there, and a declared field never hides one
        self.assertEqual(bg.resolve_field("Script", "url", "in", brain.declared), ("url", "MFString"))

    def test_a_route_between_declared_ports_is_checked_by_type(self):
        graph = bg.Behaviour.from_x3d(text_of("wired-script"))
        self.assertEqual(bg.validate(graph), [])
        graph.route("Brain", "place", "Lamp", "set_translation")
        with self.assertRaises(bg.BehaviourError) as caught:
            graph.route("Brain", "where", "Lamp", "set_translation")        # "where" is a destination: not a source
        self.assertEqual(caught.exception.code, "wrong-direction")
        with self.assertRaises(bg.BehaviourError) as caught:
            graph.route("Brain", "names", "Lamp", "set_translation")        # an MFString into a Vec3f
        self.assertEqual(caught.exception.code, "type-mismatch")
        with self.assertRaises(bg.BehaviourError) as caught:
            graph.route("Remote", "colour", "Lamp", "set_translation")      # SFColor into SFVec3f
        self.assertEqual(caught.exception.code, "type-mismatch")

    def test_the_source_survives_to_the_character(self):
        text = text_of("wired-script")
        source = "".join(by_def(text)["Brain"].itertext())
        self.assertTrue(source.startswith(self.SOURCE_MARK))
        self.assertIn("x]]> y", source)                  # the ]]> inside it is text, not the end of the CDATA section
        graph, out = trip("wired-script")
        self.assertEqual("".join(by_def(out)["Brain"].itertext()), source)
        # written for Blender's exporter (not through an XML library) the source is in CDATA, every character as it was
        emission = bg.emit(graph)
        written = "".join(emission.root)
        self.assertIn("<![CDATA[" + source[:source.index("]]>")], written)
        self.assertEqual("".join(ET.fromstring(f"<R>{written}</R>").find("Script[@DEF='Brain']").itertext()), source)

    def test_a_url_survives_as_it_was(self):
        graph, out = trip("wired-script")
        self.assertEqual(by_def(out)["Remote"].get("url"), '"remote.js" "https://example.org/remote.js"')
        self.assertEqual(graph.nodes["Remote"].fields["url"], '"remote.js" "https://example.org/remote.js"')
        self.assertEqual("".join(by_def(out)["Remote"].itertext()).strip(), "")

    def test_field_values_survive_in_the_declarations(self):
        _graph, out = trip("wired-script")
        fields = {f.get("name"): f.attrib for f in by_def(out)["Brain"].findall("field")}
        self.assertEqual(fields["on"]["value"], "true")
        self.assertEqual(fields["steps"]["value"], "3")
        self.assertEqual(list(fields), ["touched", "fraction", "place", "on", "steps", "names", "where", "things", "thing"])

    def test_a_script_made_by_script_declares_its_fields(self):
        b = bg.Behaviour()
        script = b.add("Script", "S", declared=[("go", "SFBool", "inputOnly"), ("out", "SFVec3f", "outputOnly"),
                                                 ("things", "MFNode", "inputOnly")],
                       content="<![CDATA[ecmascript: function go(v) { if (v < 1 && v > 0) {} }]]>", url='"a.js"')
        timer = b.add("TouchSensor", "T")
        lamp = b.target("Transform", "Lamp")
        timer.isActive >> script.go
        script.out >> lamp.translation
        with self.assertRaises(bg.BehaviourError):
            script.nothing                                              # a field the Script does not declare
        document = '<X3D><Scene><Transform DEF="Lamp"/></Scene></X3D>'
        out = bg.weave(document, b)
        back = bg.Behaviour.from_x3d(out)
        self.assertEqual({k: v for k, v in bg.difference(b, back).items() if v}, {})
        self.assertEqual(back.nodes["S"].declared, (("go", "SFBool", "inputOnly"), ("out", "SFVec3f", "outputOnly"),
                                                    ("things", "MFNode", "inputOnly")))
        self.assertIn("function go(v) { if (v < 1 && v > 0) {} }", "".join(by_def(out)["S"].itertext()))

    def test_only_a_script_declares_fields_of_node_types(self):
        with self.assertRaises(bg.BehaviourError):
            bg.Behaviour().target("ComposedShader", "Sh", declared=[("x", "SFNode", "inputOnly")])
        with self.assertRaises(bg.BehaviourError):
            bg.Behaviour().add("TimeSensor", "T", declared=[("x", "SFBool", "inputOnly")])
        with self.assertRaises(bg.BehaviourError):
            bg.Behaviour().add("Script", "S", declared=[("url", "SFBool", "inputOnly")])      # a name the node has
        with self.assertRaises(bg.BehaviourError):
            bg.Behaviour().add("Script", "S", declared=[("x", "SFFoo", "inputOnly")])


class NodeValuedFieldTests(unittest.TestCase):

    def test_a_node_valued_field_is_content_not_a_value(self):
        b = bg.Behaviour()
        with self.assertRaises(bg.BehaviourError) as caught:
            b.add("LinePickSensor", "P", pickTarget="x")
        self.assertEqual(caught.exception.code, "node-field")
        sensor = b.add("LinePickSensor", "P2", content='<Group USE="G" containerField="pickTarget"/>')
        self.assertEqual(sensor.node.content, '<Group USE="G" containerField="pickTarget"/>')
        with self.assertRaises(bg.BehaviourError) as caught:
            b.add("TimeSensor", "T", content="<x/>")
        self.assertEqual(caught.exception.code, "no-content")

    def test_a_node_valued_field_written_as_an_attribute_is_a_problem(self):
        graph = bg.Behaviour.from_x3d(text_of("wired-pick"))
        graph.nodes["Ray"].fields["pickTarget"] = "x"
        self.assertEqual([p["code"] for p in bg.validate(graph)], ["node-field"])

    def test_node_valued_fields_can_be_routed(self):
        b = bg.Behaviour()
        ray = b.add("LinePickSensor", "Ray")
        script = b.add("Script", "S", declared=[("picked", "MFNode", "inputOnly"), ("one", "SFNode", "inputOnly")])
        ray.pickedGeometry >> script.picked
        with self.assertRaises(bg.BehaviourError) as caught:
            ray.pickedGeometry >> script.one                              # MFNode into SFNode
        self.assertEqual(caught.exception.code, "type-mismatch")

    def test_content_and_declarations_survive_json(self):
        graph = bg.Behaviour.from_x3d(text_of("wired-script"))
        back = bg.from_json(bg.to_json(graph))
        self.assertEqual(back.nodes["Brain"].content, graph.nodes["Brain"].content)
        self.assertEqual(back.nodes["Brain"].declared, graph.nodes["Brain"].declared)
        self.assertEqual({k: v for k, v in bg.difference(graph, back).items() if v}, {})

    def test_a_change_to_the_content_is_a_difference(self):
        a = bg.Behaviour.from_x3d(text_of("wired-pick"))
        b = bg.Behaviour.from_x3d(text_of("wired-pick"))
        b.nodes["Ray"].content = b.nodes["Ray"].content.replace("World", "Elsewhere")
        self.assertIn("Ray", bg.difference(a, b)["fields_changed"])

    def test_a_reference_to_a_def_that_is_not_there_is_refused(self):
        graph = bg.Behaviour.from_x3d(text_of("wired-pick"))
        with self.assertRaises(bg.BehaviourError) as caught:
            bg.weave('<X3D><Scene><Transform DEF="Gun"/></Scene></X3D>', graph)
        self.assertEqual(caught.exception.code, "unknown-def")

    def test_the_exporter_never_writes_a_use_of_nothing(self):
        graph = bg.Behaviour.from_x3d(text_of("wired-pick"))
        emission = bg.emit(graph)                    # the exporter cannot know which DEFs its file will hold
        written = "".join(emission.root) + "".join("".join(v) for v in emission.children.values())
        self.assertNotIn('USE="World"', written)
        self.assertIn("RayGeometry", written)        # what the node defines itself is kept
        self.assertTrue(any("'World'" in line and "left out" in line for line in emission.diagnostics), emission.diagnostics)
        known = bg.emit(graph, known_defs={"World", "BallShape", "CrateShape"})      # and with the DEFs known, all of it
        self.assertNotIn("left out", " ".join(known.diagnostics))
        self.assertIn('USE="World"', "".join(known.root))

    def test_the_exporter_keeps_the_names_a_nodes_content_defines(self):
        graph = bg.Behaviour.from_x3d(text_of("wired-pick"))
        self.assertEqual(graph.nodes["Ray"].inner, ("RayGeometry",))
        self.assertEqual(graph.nodes["Tally"].inner, ())


class UnchangedTests(unittest.TestCase):

    def test_an_older_node_still_does_not_hold_its_children(self):
        doc = '<X3D><Scene><TouchSensor DEF="T"><MetadataString name="n" value="v"/></TouchSensor></Scene></X3D>'
        graph = bg.Behaviour.from_x3d(doc)
        self.assertEqual(graph.nodes["T"].content, "")
        self.assertTrue(any("child nodes" in line for line in graph.diagnostics))


if __name__ == "__main__":
    unittest.main()
