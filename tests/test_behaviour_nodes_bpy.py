# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The behaviour graph as a Blender node tree (source/behaviour_nodes.py): authored by script, exported, imported, edited.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_behaviour_nodes_bpy
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

from test_roundtrip_bpy import _register_extension, SOURCE_DIR

sys.path.insert(0, str(SOURCE_DIR))
ROUTE_DEMO = Path(__file__).resolve().parent / "behaviour" / "route-demo.x3d"
NO_DIFFERENCE = {"nodes_lost": [], "nodes_added": [], "fields_changed": {}, "routes_lost": [], "routes_added": []}


def _routes(root):
    return {(r.get("fromNode"), r.get("fromField"), r.get("toNode"), r.get("toField")) for r in root.iter("ROUTE")}


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class BehaviourNodeTests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="x3d_behaviour_")
        _register_extension(self.tmpdir)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.scene = bpy.context.scene
        import importlib
        self.bn = importlib.import_module("io_scene_x3d.behaviour_nodes")
        self.bg = importlib.import_module("io_scene_x3d.behaviour_graph")
        # With the extension also installed (CI), a factory reset disables that copy, which takes the scene property
        # and possibly the node classes with it; put back whatever is missing.
        self.bn.ensure_registered()

    def _cube(self, name, x=0.0):
        bpy.ops.mesh.primitive_cube_add(location=(x, 0, 0))
        obj = bpy.context.active_object
        obj.name = name
        return obj

    def _door(self):
        door = self._cube("Door")
        b = self.bg.Behaviour()
        click = b.add("TouchSensor", "Click", parent="Door")
        timer = b.add("TimeSensor", "Timer", cycleInterval=2)
        slide = b.add("PositionInterpolator", "Slide", key=[0, 1], keyValue=[(0, 0, 0), (0, 2, 0)])
        target = self.bn.target(b, door)
        click.touchTime >> timer.startTime
        timer.fraction_changed >> slide.set_fraction
        slide.value_changed >> target.translation
        return b

    def _export(self, name="out.x3d", **options):
        path = os.path.join(self.tmpdir, name)
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=path, x3d_version="X3D40", **options), {"FINISHED"})
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        return text, ET.fromstring(text)

    # -- authored by script ------------------------------------------------------------------------------------------

    def test_a_scripted_door_becomes_a_node_tree(self):
        graph = self._door()
        tree = self.bn.apply(graph, self.scene)
        self.assertEqual(tree.bl_idname, "X3DBehaviourTree")
        self.assertIs(self.scene.x3d_behaviour_tree, tree)
        self.assertEqual(sorted(node.name for node in tree.nodes), ["Click", "Door", "Slide", "Timer"])
        self.assertEqual(len(tree.links), 3)
        self.assertEqual(tree.nodes["Click"].x3d_parent.name, "Door")
        self.assertEqual(tree.nodes["Slide"].x3d_fields["keyValue"].value, "0 0 0 0 2 0")
        self.assertEqual(self.bg.difference(graph, self.bn.read(self.scene)), NO_DIFFERENCE)

    def test_a_socket_has_the_type_of_its_field(self):
        tree = self.bn.apply(self._door(), self.scene)
        self.assertEqual(tree.nodes["Click"].outputs["touchTime"].x3d_type, "SFTime")
        self.assertEqual(tree.nodes["Timer"].inputs["startTime"].x3d_type, "SFTime")
        self.assertEqual(tree.nodes["Door"].inputs["translation"].x3d_type, "SFVec3f")
        self.assertNotIn("touchTime", tree.nodes["Click"].inputs)      # outputOnly: no input socket
        self.assertNotIn("set_fraction", tree.nodes["Slide"].outputs)  # inputOnly: no output socket

    def test_the_editor_drops_a_link_between_two_types(self):
        tree = self.bn.apply(self._door(), self.scene)
        tree.links.new(tree.nodes["Click"].outputs["isActive"], tree.nodes["Timer"].inputs["startTime"])
        self.assertEqual(len(tree.links), 3)
        tree.links.new(tree.nodes["Click"].outputs["isActive"], tree.nodes["Timer"].inputs["enabled"])
        self.assertEqual(len(tree.links), 4)

    def test_two_routes_may_end_at_one_field(self):
        graph = self._door()
        second = graph.add("TouchSensor", "Click2", parent="Door")
        second.touchTime >> graph.get("Timer").startTime
        tree = self.bn.apply(graph, self.scene)
        self.assertEqual(len(tree.links), 4)

    def test_the_door_is_exported_as_x3d(self):
        self.bn.apply(self._door(), self.scene)
        text, root = self._export()
        door = next(t for t in root.iter("Transform") if t.get("DEF") == "Door")
        self.assertEqual([child.get("DEF") for child in door if child.tag == "TouchSensor"], ["Click"])
        self.assertEqual(_routes(root), {("Click", "touchTime", "Timer", "startTime"),
                                         ("Timer", "fraction_changed", "Slide", "set_fraction"),
                                         ("Slide", "value_changed", "Door", "translation")})
        timer = next(root.iter("TimeSensor"))
        self.assertEqual((timer.get("DEF"), timer.get("cycleInterval")), ("Timer", "2"))

    def test_the_exported_files_are_valid_x3d_4(self):
        from validate import validate_xml_text
        self.bn.apply(self._door(), self.scene)
        text, _root = self._export()
        result = validate_xml_text(text)
        self.assertTrue(result.valid, result)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.scene = bpy.context.scene
        self._import_demo()
        text, _root = self._export("demo.x3d")
        result = validate_xml_text(text)
        self.assertTrue(result.valid, result)

    def test_no_tree_means_no_change(self):
        self._cube("Door")
        before, _ = self._export("a.x3d")
        self.scene.x3d_behaviour_tree = None
        after, _ = self._export("b.x3d")
        strip = lambda text: "\n".join(line for line in text.splitlines() if "<meta " not in line)  # noqa: E731
        self.assertEqual(strip(before), strip(after))
        self.assertNotIn("ROUTE", before)

    def test_a_route_to_an_object_that_is_not_exported_is_reported(self):
        graph = self._door()
        other = self._cube("Hidden", x=4)
        graph.get("Slide").value_changed >> self.bn.target(graph, other).translation
        self.bn.apply(graph, self.scene)
        bpy.ops.object.select_all(action="DESELECT")
        bpy.data.objects["Door"].select_set(True)
        text, root = self._export(use_selection=True)
        self.assertEqual(len(_routes(root)), 3)
        self.assertIn("1 ROUTE(s) left out", text)
        self.assertIn("3 written", text)

    def test_graph_names_keep_their_def_even_when_an_object_wants_it(self):
        graph = self._door()
        self._cube("Timer", x=3)
        self.bn.apply(graph, self.scene)
        _text, root = self._export()
        self.assertEqual(next(root.iter("TimeSensor")).get("DEF"), "Timer")
        self.assertIn("OB_Timer", {t.get("DEF") for t in root.iter("Transform")})

    def test_keyframes_of_a_driven_object_are_not_sampled_twice(self):
        graph = self._door()
        door = bpy.data.objects["Door"]
        door.keyframe_insert("location", frame=1)
        door.location.z = 2
        door.keyframe_insert("location", frame=24)
        self.bn.apply(graph, self.scene)
        text, root = self._export(use_animation=True)
        self.assertEqual([n.get("DEF") for n in root.iter("PositionInterpolator")], ["Slide"])
        self.assertIn("keyframes of Door are not sampled", text)

    def test_a_camera_a_light_and_a_material_can_be_ends(self):
        self._cube("Door")
        camera = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
        lamp = bpy.data.objects.new("Lamp", bpy.data.lights.new("Lamp", "POINT"))
        for obj in (camera, lamp):
            self.scene.collection.objects.link(obj)
        material = bpy.data.materials.new("Paint")
        bpy.data.objects["Door"].data.materials.append(material)
        b = self.bg.Behaviour()
        click = b.add("TouchSensor", "Click", parent="Door")
        toggle = b.add("BooleanToggle", "Toggle")
        timer = b.add("TimeSensor", "Timer", loop=True, cycleInterval=3)
        colour = b.add("ColorInterpolator", "Hue", key=[0, 1], keyValue=[(1, 0, 0), (0, 0, 1)])
        click.isActive >> toggle.set_boolean
        toggle.toggle >> self.bn.target(b, lamp).on
        click.isActive >> self.bn.target(b, camera).set_bind
        timer.fraction_changed >> colour.set_fraction
        colour.value_changed >> self.bn.target(b, material).baseColor
        self.assertEqual(b.check(), [])
        self.bn.apply(b, self.scene)
        text, root = self._export()
        routes = _routes(root)
        self.assertEqual(len(routes), 5, text)
        defs = {element.get("DEF"): element.tag for element in root.iter() if element.get("DEF")}
        for _a, _af, to_node, _tf in routes:
            self.assertIn(to_node, defs)
        self.assertEqual({defs[r[2]] for r in routes},
                         {"BooleanToggle", "PointLight", "Viewpoint", "ColorInterpolator", "PhysicalMaterial"})

    # -- imported ----------------------------------------------------------------------------------------------------

    def _import_demo(self):
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=str(ROUTE_DEMO), use_behaviour_graph=True), {"FINISHED"})
        return self.scene.x3d_behaviour_tree

    def test_import_is_off_by_default(self):
        bpy.ops.import_scene.x3d(filepath=str(ROUTE_DEMO))
        self.assertIsNone(getattr(self.scene, "x3d_behaviour_tree", None))
        self.assertEqual(bpy.data.objects["DoorButton"].get("x3d_trigger"), "click")

    def test_import_builds_the_graph_of_a_real_file(self):
        tree = self._import_demo()
        self.assertEqual(len(tree.links), 22)
        self.assertEqual(sum(1 for node in tree.nodes if node.x3d_role == "behaviour"), 17)
        self.assertEqual([node.name for node in tree.nodes if node.x3d_role == "carried"], ["TourRig"])
        self.assertEqual(tree.nodes["TS_DoorButton"].x3d_parent.name, "DoorButton")
        self.assertNotIn("x3d_trigger", bpy.data.objects["DoorButton"])

    def test_the_graph_takes_over_the_keyframes_the_import_baked(self):
        # route-demo: the importer bakes Door, Spinner and Beacon into <name>_x3d actions; the graph drives all three
        keep = self._cube("Keep")
        keep.animation_data_create()
        keep.animation_data.action = bpy.data.actions.new("Mine")   # made before the import: never touched
        bpy.ops.import_scene.x3d(filepath=str(ROUTE_DEMO), use_behaviour_graph=True)
        self.assertEqual([action.name for action in bpy.data.actions], ["Mine"])
        for name in ("Door", "Spinner", "Beacon"):
            self.assertIsNone(bpy.data.objects[name].animation_data.action)
        self.assertIn("removed the keyframes the importer baked for 'Door'",
                      self.scene.x3d_behaviour_tree["x3d_diagnostics"])

    def test_without_the_graph_the_baked_keyframes_stay(self):
        bpy.ops.import_scene.x3d(filepath=str(ROUTE_DEMO))
        self.assertEqual(sorted(action.name for action in bpy.data.actions), ["Beacon_x3d", "Door_x3d", "Spinner_x3d"])

    def test_a_sensor_binds_to_its_transform_not_to_a_child_that_inherited_the_def(self):
        # probe-proximity.x3d: GateBase and RoomBase hold unnamed Transforms with shapes; the importer gives those the
        # parent's DEF (and the name), the Transform itself becoming an empty "GateBase.001" or the like
        path = ROUTE_DEMO.parent / "probe-proximity.x3d"
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=str(path), use_behaviour_graph=True), {"FINISHED"})
        tree = self.scene.x3d_behaviour_tree
        for sensor in ("Gate", "Room"):
            parent = tree.nodes[sensor].x3d_parent
            self.assertEqual(parent.type, "EMPTY")
            self.assertTrue(parent.parent is None or parent.parent.get("x3d_def") != parent.get("x3d_def"))
            self.assertEqual(len(parent.children), 4)          # three shapes or more, and the lamp

    def test_import_says_where_the_graph_went(self):
        # Backlog 1: with no window (a script, blender -b) nothing can be shown; the line says how to see it
        tree = self._import_demo()
        self.assertIsNone(self.bn.show_tree(bpy.context, tree))
        line = self.bn.import_summary(tree, None)
        self.assertEqual(line, "X3D Behaviour: 17 nodes, 22 ROUTEs in node tree 'X3D Behaviour'. "
                               "To see them, switch any editor's type to X3D Behaviour.")
        self.assertTrue(self.bn.import_summary(tree, object()).endswith(", shown in the node editor."))

    def test_the_graph_goes_to_a_node_editor_never_to_another_editor(self):
        from types import SimpleNamespace as NS

        def area(kind, size, tree_type=""):
            return NS(type=kind, width=size, height=size, spaces=NS(active=NS(tree_type=tree_type)))
        viewport, shader, small_x3d = area("VIEW_3D", 900), area("NODE_EDITOR", 600), area("NODE_EDITOR", 200,
                                                                                            self.bn.TREE_IDNAME)
        self.assertIs(self.bn._editor_area_for(NS(areas=[viewport, shader, small_x3d])), small_x3d)
        self.assertIs(self.bn._editor_area_for(NS(areas=[viewport, shader])), shader)
        self.assertIsNone(self.bn._editor_area_for(NS(areas=[viewport])))

    def test_a_long_key_table_is_short_on_the_node(self):
        self.assertEqual(self.bn.rows_on_node(4, 6), [0, 1, 2, 3])
        self.assertEqual(self.bn.rows_on_node(48, 6), [0, 1, 2, 3, 4, 47])
        self.assertEqual(self.bn.rows_on_node(48, None), list(range(48)))

    def test_round_trip_keeps_every_node_field_and_route(self):
        self._import_demo()
        text, _root = self._export()
        before = self.bg.Behaviour.from_x3d(ROUTE_DEMO.read_text(encoding="utf-8"))
        after = self.bg.Behaviour.from_x3d(text)
        self.assertEqual(self.bg.difference(before, after), NO_DIFFERENCE)
        self.assertEqual(text.count("<ROUTE"), 22)

    def test_second_round_trip_is_a_fixed_point(self):
        self._import_demo()
        first, _ = self._export("first.x3d")
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.scene = bpy.context.scene
        bpy.ops.import_scene.x3d(filepath=os.path.join(self.tmpdir, "first.x3d"), use_behaviour_graph=True)
        second, _ = self._export("second.x3d")
        self.assertEqual(self.bg.difference(self.bg.Behaviour.from_x3d(first), self.bg.Behaviour.from_x3d(second)),
                         NO_DIFFERENCE)

    def test_the_three_wire_lab_worlds_round_trip(self):
        """door.x3d, counter.x3d and snake.x3d were written by the scripting methods (x3d.demo wire-lab/v1/build)."""
        for name, routes in (("door", 3), ("counter", 5), ("snake", 6)):
            with self.subTest(world=name):
                bpy.ops.wm.read_factory_settings(use_empty=True)
                self.scene = bpy.context.scene
                source = ROUTE_DEMO.with_name(f"{name}.x3d")
                bpy.ops.import_scene.x3d(filepath=str(source), use_behaviour_graph=True)
                tree = self.scene.x3d_behaviour_tree
                self.assertEqual(len(tree.links), routes)
                text, _root = self._export(f"{name}.x3d")
                before = self.bg.Behaviour.from_x3d(source.read_text(encoding="utf-8"))
                after = self.bg.Behaviour.from_x3d(text)
                self.assertEqual(self.bg.difference(before, after), NO_DIFFERENCE)

    def test_an_edit_in_blender_reaches_the_file_and_nothing_else_changes(self):
        tree = self._import_demo()
        tree.nodes["TT_Door"].x3d_fields["cycleInterval"].value = "5"
        link = next(l for l in tree.links if l.from_node.name == "TS_DoorButton")
        tree.links.remove(link)
        tree.links.new(tree.nodes["PS_Beacon"].outputs["enterTime"], tree.nodes["TT_Door"].inputs["startTime"])
        text, _root = self._export()
        before = self.bg.Behaviour.from_x3d(ROUTE_DEMO.read_text(encoding="utf-8"))
        after = self.bg.Behaviour.from_x3d(text)
        difference = self.bg.difference(before, after)
        self.assertEqual(difference["fields_changed"], {"TT_Door": {"cycleInterval": ("1.958333", "5")}})
        self.assertEqual(difference["routes_lost"], [("TS_DoorButton", "touchTime", "TT_Door", "startTime")])
        self.assertEqual(difference["routes_added"], [("PS_Beacon", "enterTime", "TT_Door", "startTime")])
        self.assertEqual((difference["nodes_lost"], difference["nodes_added"]), ([], []))


if __name__ == "__main__":
    unittest.main()
