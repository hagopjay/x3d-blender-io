# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Presets to graph (source/behaviour_presets.py): the click / proximity custom-property presets become nodes of the
behaviour tree without changing what is exported.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_behaviour_presets_bpy
"""

from __future__ import annotations

import importlib
import os
import sys
import tempfile
import unittest

try:
    import bpy  # noqa: F401
    from mathutils import Matrix
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

from test_roundtrip_bpy import _register_extension, SOURCE_DIR

sys.path.insert(0, str(SOURCE_DIR))

PRESET_KEYS = ("x3d_trigger", "x3d_action", "x3d_target", "x3d_radius")


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class PresetsToGraphTests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="x3d_presets_")
        _register_extension(self.tmpdir)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.bn = importlib.import_module("io_scene_x3d.behaviour_nodes")
        self.bp = importlib.import_module("io_scene_x3d.behaviour_play")
        self.bg = importlib.import_module("io_scene_x3d.behaviour_graph")
        self.presets = importlib.import_module("io_scene_x3d.behaviour_presets")
        self.bn.ensure_registered()
        self.scene = bpy.context.scene
        self.scene.frame_start, self.scene.frame_end = 1, 25

    # ----- the scene -----

    def _cube(self, name, location=(0, 0, 0), scale=(1, 1, 1)):
        bpy.ops.mesh.primitive_cube_add(location=location)
        obj = bpy.context.active_object
        obj.name = name
        obj.scale = scale
        return obj

    def _camera(self, name, location):
        cam = bpy.data.objects.new(name, bpy.data.cameras.new(name))
        self.scene.collection.objects.link(cam)
        cam.location = location
        cam.rotation_euler = (1.2, 0, 0.5)
        return cam

    def _world(self, tour=False):
        """A Door that slides and turns, a Button that plays it on a click, a Pad (scaled, so the sensor box must divide
        the scale back out) that binds the second camera when the viewer comes within 4 m, and an Eye that binds the
        first camera on a click."""
        door = self._cube("Door", (0, 0, 0))
        door.keyframe_insert("location", frame=1)
        door.keyframe_insert("rotation_euler", frame=1)
        door.location.z, door.rotation_euler.z = 2.0, 1.0
        door.keyframe_insert("location", frame=25)
        door.keyframe_insert("rotation_euler", frame=25)
        button = self._cube("Button", (4, 0, 0))
        button.update_tag()
        button["x3d_trigger"], button["x3d_action"], button["x3d_target"] = "click", "animate", "Door"
        self._camera("Cam1", (0, -8, 3))
        self._camera("Cam2", (6, -4, 2))
        pad = self._cube("Pad", (-4, 0, 0), scale=(2, 1, 1))
        pad["x3d_trigger"], pad["x3d_action"], pad["x3d_target"], pad["x3d_radius"] = \
            "proximity", "viewpoint", "Cam2", 4.0
        eye = self._cube("Eye", (0, -4, 0))
        eye["x3d_trigger"], eye["x3d_action"], eye["x3d_target"] = "click", "viewpoint", "Cam1"
        if tour:
            gate = self._cube("Gate", (0, 6, 0))
            gate["x3d_trigger"], gate["x3d_action"] = "click", "tour"
            self.scene.objects["Cam1"]["x3d_tour_order"] = 1
            self.scene.objects["Cam2"]["x3d_tour_order"] = 2
            self.scene.objects["Cam2"]["x3d_tour_dwell"] = 1.5
            self.scene["x3d_tour_loop"] = True
        return self.scene

    def _export(self, label):
        path = os.path.join(self.tmpdir, f"{label}.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=path, x3d_version="X3D40", use_animation=True,
                                                  use_selection=False), {"FINISHED"})
        with open(path, "rb") as handle:
            return handle.read()

    # ----- structure comparison -----

    def _canonical(self, document):
        """A parsed export as a structure with no DEF names in it, and how it was matched.

        The exporter names a scene node OB_<object> or CA_<camera> when only the scene writes it, and by its graph id
        (the object's own name) when the graph holds it; the preset's own nodes are TS_/PS_/TT_/PI_/OI_/SI_/BF_ either
        way. So: a node stands for (its type, its set fields, the object it sits in) and a scene target stands for
        (its type, the object name with one leading OB_ or CA_, or a trailing _viewpoint, taken off). A ROUTE is the pair of those and the two
        canonical field names. Only the nodes the presets made are compared (the scene's own Transforms, shapes and the
        free-running timers are not behaviour). Two nodes with the same description would make the match ambiguous: the
        scene has none, and the helper fails if it meets one."""
        bg = self.bg
        graph = bg.parse_x3d(document)

        def strip(name):
            for prefix in ("OB_", "CA_"):
                if name and name.startswith(prefix):
                    return name[len(prefix):]
            if name and name.endswith("_viewpoint"):       # the graph's id for a camera is "<name>_viewpoint"
                return name[:-len("_viewpoint")]
            return name

        keys = {}
        for node in graph.nodes.values():
            if node.role == bg.BEHAVIOUR:
                keys[node.id] = (node.node_type, tuple(sorted(node.fields.items())), strip(node.parent))
            elif node.role == bg.TARGET:
                keys[node.id] = ("target", node.node_type, strip(node.id))
        self.assertEqual(len(set(keys.values())), len(keys), "two nodes with one description: match is ambiguous")
        routes = []
        for route in graph.routes:
            ends = []
            for node_id, field_name, direction in ((route.from_id, route.from_field, "out"),
                                                   (route.to_id, route.to_field, "in")):
                node = graph.nodes[node_id]
                ends.append((keys[node_id], bg.resolve_field(node.node_type, field_name, direction)[0]))
            routes.append(tuple(ends))
        # drop the scene's own free-running timer and what it drives: the presets' timers never loop
        return sorted(keys.values(), key=repr), sorted(routes, key=repr)

    def _behaviour_of_presets(self, document):
        nodes, routes = self._canonical(document)
        return nodes, routes

    # ----- a: the acceptance test -----

    def test_a_export_before_and_after_the_conversion_holds_the_same_behaviour(self):
        scene = self._world()
        before = self._export("before")
        converted, notes = self.presets.presets_to_graph(scene)
        self.assertEqual(converted, 3, notes)
        after = self._export("after")
        nodes_before, routes_before = self._behaviour_of_presets(before)
        nodes_after, routes_after = self._behaviour_of_presets(after)
        types = sorted(key[0] for key in nodes_before if key[0] != "target")
        # one PositionInterpolator for the Door's position; 2.9.0 also wrote a scale one (SI_Door) for float32 noise
        # in the scale of a turning Door, which the sampler now reads as still (chaos round 4, 2.9.1)
        self.assertEqual(types, sorted(["BooleanFilter", "OrientationInterpolator", "PositionInterpolator",
                                        "ProximitySensor", "TimeSensor", "TouchSensor", "TouchSensor"]))
        self.assertEqual(nodes_before, nodes_after)
        self.assertEqual(routes_before, routes_after)
        self.assertEqual(len(routes_after), 8)   # 10 with the noise scale interpolator's two ROUTEs (2.9.0)
        # the converted file must not write the behaviour twice
        self.assertEqual(after.count(b"<TouchSensor"), 2)
        self.assertEqual(after.count(b"<ProximitySensor"), 1)
        self.assertEqual(after.count(b"<TimeSensor"), 1)

    # ----- b: the properties go, and a second run adds nothing -----

    def _graph_size(self):
        tree = self.scene.x3d_behaviour_tree
        return len(tree.nodes), len(tree.links)

    def test_b_the_preset_properties_are_gone_and_a_second_conversion_adds_nothing(self):
        scene = self._world()
        converted, notes = self.presets.presets_to_graph(scene)
        self.assertEqual(converted, 3, notes)
        for name in ("Button", "Pad", "Eye"):
            self.assertEqual([key for key in PRESET_KEYS if key in scene.objects[name]], [], name)
        size = self._graph_size()
        self.assertGreater(size[1], 0)
        converted, notes = self.presets.presets_to_graph(scene)
        self.assertEqual(converted, 0, notes)
        self.assertEqual(self._graph_size(), size)
        self.assertFalse(self.presets.has_convertible_presets(scene))
        self.assertEqual(self._export("twice").count(b"<ROUTE "), self._export("again").count(b"<ROUTE "))

    def test_b_the_operator_does_the_same_and_is_offered_only_while_there_is_something_to_convert(self):
        scene = self._world()
        self.assertTrue(bpy.ops.x3d.behaviour_from_presets.poll())
        self.assertEqual(bpy.ops.x3d.behaviour_from_presets(), {"FINISHED"})
        self.assertFalse(bpy.ops.x3d.behaviour_from_presets.poll())
        self.assertGreater(self._graph_size()[1], 0)
        self.assertIsNotNone(scene.x3d_behaviour_tree)

    def test_b_a_scene_with_nothing_to_convert_gets_no_tree(self):
        self._cube("Plain")
        self.assertEqual(self.presets.presets_to_graph(self.scene), (0, []))
        self.assertIsNone(self.scene.x3d_behaviour_tree)

    def test_b_a_preset_the_exporter_would_drop_is_left_and_named(self):
        self._cube("Mute")["x3d_trigger"] = "click"            # animate on itself, which has no animation
        ghost = self._cube("Ghost")
        ghost["x3d_trigger"], ghost["x3d_action"], ghost["x3d_target"] = "click", "viewpoint", "Nobody"
        converted, notes = self.presets.presets_to_graph(self.scene)
        self.assertEqual(converted, 0)
        self.assertIn("Mute", " ".join(notes))
        self.assertIn("Ghost", " ".join(notes))
        self.assertEqual(self.scene.objects["Mute"]["x3d_trigger"], "click")
        self.assertIsNone(self.scene.x3d_behaviour_tree)

    def test_b_a_preset_added_later_joins_the_tree_beside_what_is_there(self):
        scene = self._world()
        self.presets.presets_to_graph(scene)
        size = self._graph_size()
        later = self._cube("Later", (0, 8, 0))
        later["x3d_trigger"], later["x3d_action"], later["x3d_target"] = "click", "viewpoint", "Cam2"
        converted, notes = self.presets.presets_to_graph(scene)
        self.assertEqual(converted, 1, notes)
        after = self._graph_size()
        self.assertGreater(after[0], size[0])
        self.assertGreater(after[1], size[1])
        names = [node.name for node in scene.x3d_behaviour_tree.nodes]
        self.assertEqual(len(names), len(set(names)))

    # ----- c: the tour is left alone -----

    def test_c_a_tour_preset_is_left_untouched_and_named(self):
        scene = self._world(tour=True)
        tour_before = {name: dict(scene.objects[name].items()) for name in ("Gate", "Cam1", "Cam2")}
        scene_before = {key: scene[key] for key in ("x3d_tour_loop",)}
        converted, notes = self.presets.presets_to_graph(scene)
        self.assertEqual(converted, 3, notes)
        text = "\n".join(notes)
        for name in ("Gate", "Cam1", "Cam2"):
            self.assertIn(repr(name), text)
        self.assertIn("tour", text)
        self.assertEqual(scene.objects["Gate"]["x3d_trigger"], "click")
        self.assertEqual(scene.objects["Gate"]["x3d_action"], "tour")
        for name, props in tour_before.items():
            self.assertEqual({k: v for k, v in scene.objects[name].items() if k.startswith("x3d_tour")},
                             {k: v for k, v in props.items() if k.startswith("x3d_tour")})
        self.assertEqual({key: scene[key] for key in scene_before}, scene_before)
        # the tour is still written by the exporter: its rig, its timer, and the Gate's sensor routed to it
        document = self._export("tour").decode("utf-8")
        self.assertIn('DEF="TourTimer"', document)
        self.assertIn('DEF="TourRig"', document)
        self.assertIn('toNode="TourTimer" toField="set_startTime"', document)

    # ----- d: the converted presets play -----

    def _clock(self, player, start, seconds):
        player.step(start + seconds)
        bpy.context.view_layer.update()

    def test_d_the_converted_click_plays_the_door_as_the_preset_meant(self):
        scene = self._world()
        self.presets.presets_to_graph(scene)
        door, button = scene.objects["Door"], scene.objects["Button"]
        bpy.context.view_layer.update()
        rest = door.matrix_world.copy()
        player = self.bp.Player(scene)
        self.assertEqual([obj.name for obj in player.sensed_objects()].count("Button"), 1)
        player.start(0.0)
        player.step(0.5)
        self.assertAlmostEqual(door.location.z, 0.0, places=4)          # nothing runs until the click
        self.assertTrue(player.click(button, 1.0, held=0.1))
        self.assertEqual(player.sim.not_simulated, [])
        cycle = (scene.frame_end - scene.frame_start + 1) / scene.render.fps    # what the exporter writes as the cycle
        player.step(1.1 + cycle / 2)
        halfway = door.location.z
        self.assertGreater(halfway, 0.5)
        self.assertLess(halfway, 1.5)
        player.step(1.1 + cycle + 0.5)                                  # past the end: the animation's last pose
        self.assertAlmostEqual(door.location.z, 2.0, places=3)
        self.assertAlmostEqual(door.rotation_euler.z, 1.0, places=3)
        player.stop()
        bpy.context.view_layer.update()
        gap = max(abs(a - b) for row_a, row_b in zip(door.matrix_world, rest) for a, b in zip(row_a, row_b))
        self.assertLess(gap, 1e-5)

    def test_d_the_converted_click_binds_the_camera(self):
        scene = self._world()
        self.presets.presets_to_graph(scene)
        scene.camera = scene.objects["Cam2"]
        player = self.bp.Player(scene)
        player.start(0.0)
        self.assertTrue(player.click(scene.objects["Eye"], 1.0, held=0.1))
        self.assertEqual(scene.camera.name, "Cam1")
        player.step(2.0)
        self.assertEqual(scene.camera.name, "Cam1")                     # the release did not unbind it
        player.stop()

    def test_d_the_converted_proximity_binds_the_camera_when_the_viewer_comes_within_the_radius(self):
        scene = self._world()
        self.presets.presets_to_graph(scene)
        scene.camera = scene.objects["Cam1"]
        player = self.bp.Player(scene)
        player.start(0.0)
        far, near = Matrix.Translation((-12, 0, 0)), Matrix.Translation((-6, 0, 0))   # the Pad is at -4, radius 4
        player.view(far, (0, 0, 0), 0.5)
        self.assertEqual(scene.camera.name, "Cam1")
        player.view(near, (0, 0, 0), 1.0)
        self.assertEqual(scene.camera.name, "Cam2")
        player.stop()


if __name__ == "__main__":
    unittest.main()
