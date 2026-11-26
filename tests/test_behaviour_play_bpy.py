# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Version 2 of the behaviour editor, in Blender without a window: playing the graph on the scene's objects
(source/behaviour_play.py), the typed field widgets and key tables (source/behaviour_nodes.py), and visible="false"
surviving the trip. The mouse-driven operator needs a window and is not tested here.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_behaviour_play_bpy
"""

from __future__ import annotations

import importlib
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
WORLDS = Path(__file__).resolve().parent / "behaviour"


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class _Base(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="x3d_behaviour_play_")
        _register_extension(self.tmpdir)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.bn = importlib.import_module("io_scene_x3d.behaviour_nodes")
        self.bp = importlib.import_module("io_scene_x3d.behaviour_play")
        self.bn.ensure_registered()

    def load(self, name):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.bn.ensure_registered()
        bpy.ops.import_scene.x3d(filepath=str(WORLDS / f"{name}.x3d"), use_behaviour_graph=True)
        return bpy.context.scene

    def as_exported(self, obj):
        """The translation the exporter would write for this object now."""
        bpy.context.view_layer.update()
        matrix = self.bp.EXPORT_AXES @ obj.matrix_world if obj.parent is None \
            else obj.parent.matrix_world.inverted() @ obj.matrix_world
        return tuple(round(v, 4) for v in matrix.to_translation())


class PlayTests(_Base):

    def test_a_press_on_the_button_raises_the_door_and_stop_puts_it_back(self):
        scene = self.load("door")
        door, button = scene.objects["Door"], scene.objects["Button"]
        before = door.matrix_world.copy()
        player = self.bp.Player(scene)
        self.assertEqual([obj.name for obj in player.sensed_objects()], ["Button"])
        player.start(0.0)
        self.assertFalse(player.click(door, 0.5))                 # the door is not what the sensor senses
        player.step(0.9)
        self.assertEqual(self.as_exported(door), (0.0, 1.2, 0.0))
        self.assertTrue(player.click(button, 1.0, held=0.1))      # touchTime 1.1 starts the 3 s timer
        player.step(2.6)                                          # half way: the top
        self.assertEqual(self.as_exported(door), (0.0, 3.7, 0.0))
        self.assertAlmostEqual(door.location.z, 3.7, places=4)    # X3D's Y up is Blender's Z up
        player.step(1.1 + 0.6)                                    # a fifth of the way: half way up
        self.assertEqual(self.as_exported(door), (0.0, 2.45, 0.0))
        self.assertEqual(player.sim.not_simulated, [])
        self.assertEqual(player.not_applied, [])
        player.stop()
        bpy.context.view_layer.update()
        gap = max(abs(a - b) for row_a, row_b in zip(door.matrix_world, before) for a, b in zip(row_a, row_b))
        self.assertLess(gap, 1e-5)

    def test_the_counter_lights_its_lamps_in_binary(self):
        scene = self.load("counter")
        player = self.bp.Player(scene)
        button, = player.sensed_objects()
        lamps = [scene.objects[f"Bit{i}"] for i in range(2)]      # the starter world wires two of its four lamps
        self.assertEqual([lamp.visible_get() for lamp in lamps], [False, False])
        player.start(0.0)
        for presses in range(1, 6):
            player.click(button, float(presses))
            bpy.context.view_layer.update()
            number = sum(1 << bit for bit, lamp in enumerate(lamps) if lamp.visible_get())
            self.assertEqual(number, presses % 4)
        player.stop()
        bpy.context.view_layer.update()
        self.assertEqual([lamp.visible_get() for lamp in lamps], [False, False])

    def test_the_tail_follows_the_head_as_the_simulator_says(self):
        scene = self.load("snake")
        player = self.bp.Player(scene)
        player.start(0.0)
        t = 0.0
        while t < 3.0:
            t += 1 / 30
            player.step(t)
        for name in ("Head", "Seg1", "Seg2"):
            wanted = tuple(round(v, 4) for v in player.sim.values[(name, "translation")])
            self.assertEqual(self.as_exported(scene.objects[name]), wanted)
        head, seg1 = self.as_exported(scene.objects["Head"]), self.as_exported(scene.objects["Seg1"])
        self.assertGreater(sum((a - b) ** 2 for a, b in zip(head, seg1)) ** 0.5, 0.3)    # the bead lags the head

    def test_a_material_and_a_child_object_take_their_values(self):
        scene = bpy.context.scene
        mesh = bpy.data.meshes.new("M")
        parent = bpy.data.objects.new("Arm", None)
        child = bpy.data.objects.new("Hand", mesh)
        scene.collection.objects.link(parent)
        scene.collection.objects.link(child)
        parent.location = (5.0, 0.0, 0.0)
        child.parent = parent
        paint = bpy.data.materials.new("Paint")
        paint.use_nodes = True
        bg = importlib.import_module("io_scene_x3d.behaviour_graph")
        graph = bg.Behaviour()
        clock = graph.add("TimeSensor", "Clock", cycleInterval=2, loop=True)
        move = graph.add("PositionInterpolator", "Move", key=[0, 1], keyValue=[(0, 0, 0), (0, 0, 4)])
        tint = graph.add("ColorInterpolator", "Tint", key=[0, 1], keyValue=[(1, 0, 0), (1, 0, 0)])
        clock.fraction_changed >> move.set_fraction
        clock.fraction_changed >> tint.set_fraction
        move.value_changed >> self.bn.target(graph, child).translation
        tint.value_changed >> self.bn.target(graph, paint).baseColor
        self.bn.apply(graph, scene)
        player = self.bp.Player(scene)
        player.start(0.0)
        player.step(1.0)
        bpy.context.view_layer.update()
        # a child's Transform is in its parent's axes, which are Blender's: no turn from Y up to Z up
        self.assertEqual(tuple(round(v, 4) for v in child.matrix_local.to_translation()), (0.0, 0.0, 2.0))
        self.assertEqual(tuple(round(v, 4) for v in child.matrix_world.to_translation()), (5.0, 0.0, 2.0))
        shader = next(n for n in paint.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
        self.assertEqual(tuple(round(v, 3) for v in shader.inputs["Base Color"].default_value), (1.0, 0.0, 0.0, 1.0))
        player.stop()
        self.assertNotEqual(tuple(round(v, 3) for v in shader.inputs["Base Color"].default_value), (1.0, 0.0, 0.0, 1.0))

    def test_a_drag_on_a_plane_sensor_moves_what_it_is_wired_to(self):
        scene = bpy.context.scene
        mesh = bpy.data.meshes.new("M")
        handle = bpy.data.objects.new("Handle", mesh)
        ball = bpy.data.objects.new("Ball", mesh)
        scene.collection.objects.link(handle)
        scene.collection.objects.link(ball)
        bg = importlib.import_module("io_scene_x3d.behaviour_graph")
        graph = bg.Behaviour()
        grab = graph.add("PlaneSensor", "Grab", parent="Handle")
        grab.translation_changed >> self.bn.target(graph, ball).translation
        self.bn.apply(graph, scene)
        bpy.context.view_layer.update()
        player = self.bp.Player(scene)
        player.start(0.0)
        self.assertTrue(player.press(handle, 1.0, (0.0, 0.0, 0.0)))
        player.drag((2.0, 1.0, 10.0), (0.0, 0.0, -1.0), 1.1)       # a ray straight down onto the handle's XY plane
        self.assertEqual(tuple(round(v, 4) for v in player.sim.values[("Ball", "translation")]), (2.0, 1.0, 0.0))
        player.release(1.2)
        player.stop()

    def test_a_sphere_sensor_drag_turns_the_ball_and_stop_puts_it_back(self):
        # probe-drag.x3d: press on the Ball with a ray from the scene camera, drag sideways, stop
        from mathutils import Vector
        scene = self.load("probe-drag")
        ball = scene.objects["Ball"]
        camera = scene.camera or next(o for o in scene.objects if o.type == "CAMERA")
        eye = camera.matrix_world.translation.copy()
        back = (camera.matrix_world.to_3x3() @ Vector((0.0, 0.0, 1.0))).normalized()
        bpy.context.view_layer.update()
        aim = (ball.matrix_world.translation + Vector((0.1, 0.0, 0.15)) - eye).normalized()
        hit, location, _n, _i, obj, _m = scene.ray_cast(bpy.context.evaluated_depsgraph_get(), eye, aim)
        self.assertTrue(hit)
        before = ball.matrix_basis.copy()
        player = self.bp.Player(scene)
        player.start(0.0)
        self.assertTrue(player.press(obj.original, 0.5, location, ray=(eye, aim), eye=(eye, back)))
        sideways = (aim + Vector((0.03, 0.0, 0.0))).normalized()
        player.drag(eye, sideways, 0.6)
        player.step(0.6)
        turned = ball.matrix_basis.to_quaternion().rotation_difference(before.to_quaternion()).angle
        self.assertGreater(turned, 0.05)
        player.release(0.7)
        player.stop()
        gap = max(abs(a - b) for row_a, row_b in zip(ball.matrix_basis, before) for a, b in zip(row_a, row_b))
        self.assertLess(gap, 1e-6)

    def test_a_scripted_flight_carries_the_camera_through_the_proximity_sensors(self):
        # probe-proximity.x3d: a looping timer flies the Viewpoint; Play moves the camera and the ProximitySensors see
        # it (the gate lamp lights while the camera is in the gate); stop puts the camera back
        scene = self.load("probe-proximity")
        camera = next(o for o in scene.objects if o.type == "CAMERA" and o.get("x3d_def") == "Eye")
        lamp = scene.objects["GateLamp"]
        before = camera.matrix_world.copy()
        shown = lambda obj: not (obj.hide_viewport or obj.hide_get())
        self.assertFalse(shown(lamp))                             # visible="false" in the file
        player = self.bp.Player(scene)
        player.start(0.0)
        lit, frames = [], 0
        while frames < 8 * 30:                                    # one 8 s flight at 30 frames a second
            frames += 1
            now = frames / 30
            bpy.context.view_layer.update()
            player.view(camera.matrix_world.copy(), (0.0, 0.0, 0.0), now)
            player.step(now)
            lit.append(shown(lamp))
        self.assertNotEqual(camera.matrix_world, before)
        self.assertTrue(any(lit) and not lit[-1], "the lamp lights in the gate and goes out after it")
        self.assertEqual(player.not_applied, [])
        player.stop()
        bpy.context.view_layer.update()
        gap = max(abs(a - b) for row_a, row_b in zip(camera.matrix_world, before) for a, b in zip(row_a, row_b))
        self.assertLess(gap, 1e-6)

    def test_the_nodes_that_sent_an_event_light_up_and_go_back(self):
        scene = self.load("door")
        tree = scene.x3d_behaviour_tree
        before = {node.name: (node.use_custom_color, tuple(node.color)) for node in tree.nodes}
        player = self.bp.Player(scene)
        player.start(0.0)
        player.click(scene.objects["Button"], 1.0)
        player.step(1.2)
        self.assertTrue(tree.nodes["Timer"].use_custom_color)
        self.assertGreater(tree.nodes["Timer"].color[0], 0.5)
        player.stop()
        self.assertEqual({node.name: (node.use_custom_color, tuple(node.color)) for node in tree.nodes}, before)


    def test_a_running_timer_settles_to_a_readable_tint(self):
        # one event flashes; a node that keeps sending (the 3 s timer) drops to GLOW_BUSY after the first 0.35 s
        scene = self.load("door")
        tree = scene.x3d_behaviour_tree
        player = self.bp.Player(scene)
        player.start(0.0)
        player.click(scene.objects["Button"], 1.0)
        player.step(1.15)
        flash = tree.nodes["Timer"].color[0]
        for frame in range(1, 31):                                  # 30 frames at 60 Hz: still running at 1.65
            player.step(1.15 + frame / 60)
        busy = tree.nodes["Timer"].color[0]
        grey, orange = 0.19, self.bp.GLOW_COLOUR[0]
        self.assertAlmostEqual(flash, grey + (orange - grey) * self.bp.GLOW_FLASH, delta=0.05)
        self.assertAlmostEqual(busy, grey + (orange - grey) * self.bp.GLOW_BUSY, delta=0.05)
        self.assertFalse(tree.nodes["Click"].use_custom_color)    # sent once at 1.1, faded by 1.65
        player.stop()


class FieldEditorTests(_Base):

    def test_a_typed_widget_reads_and_writes_the_x3d_text(self):
        scene = self.load("door")
        timer = scene.x3d_behaviour_tree.nodes["Timer"]
        self.assertEqual((timer.f_cycleInterval, timer.f_loop, timer.f_enabled), (3.0, False, True))
        timer.f_cycleInterval, timer.f_loop = 6, True
        self.assertEqual({f.name: f.value for f in timer.x3d_fields}, {"cycleInterval": "6", "loop": "true"})
        timer.f_loop = False                                      # the standard's default is not written
        self.assertEqual({f.name: f.value for f in timer.x3d_fields}, {"cycleInterval": "6"})
        self.assertEqual(self.bn.read(scene).nodes["Timer"].fields, {"cycleInterval": "6"})

    def test_a_key_table_is_a_window_onto_key_and_key_value(self):
        scene = self.load("door")
        slide = scene.x3d_behaviour_tree.nodes["Slide"]
        rows = [(round(row.key, 3), tuple(round(v, 3) for v in row.vector)) for row in slide.x3d_rows]
        self.assertEqual(rows, [(0.0, (0.0, 1.2, 0.0)), (0.4, (0.0, 3.7, 0.0)), (0.6, (0.0, 3.7, 0.0)), (1.0, (0.0, 1.2, 0.0))])
        slide.x3d_rows[1].vector = (0.0, 5.0, 0.0)
        slide.x3d_rows[1].key = 0.3
        self.assertEqual(slide.x3d_fields["key"].value, "0 0.3 0.6 1")
        self.assertEqual(slide.x3d_fields["keyValue"].value, "0 1.2 0 0 5 0 0 3.7 0 0 1.2 0")
        self.bn.add_key(slide, 0)
        self.assertEqual(slide.x3d_fields["key"].value, "0 0.15 0.3 0.6 1")
        self.assertEqual(len(slide.x3d_rows), 5)
        self.bn.remove_key(slide, 1)
        self.assertEqual(slide.x3d_fields["key"].value, "0 0.3 0.6 1")
        self.assertEqual(len(slide.x3d_rows), 4)

    def test_z_up_turns_the_display_and_never_the_file(self):
        scene = self.load("door")
        tree = scene.x3d_behaviour_tree
        slide = tree.nodes["Slide"]
        text = slide.x3d_fields["keyValue"].value
        self.assertTrue(self.bn.drives_root_objects(slide))
        tree.x3d_blender_axes = True
        self.assertEqual(tuple(round(v, 3) for v in slide.x3d_rows[1].vector), (0.0, 0.0, 3.7))    # up is Z here
        self.assertEqual(slide.x3d_fields["keyValue"].value, text)
        slide.x3d_rows[1].vector = (0.0, 0.0, 5.0)                # typed in Blender's axes ...
        self.assertEqual(slide.x3d_fields["keyValue"].value, "0 1.2 0 0 5 0 0 3.7 0 0 1.2 0")      # ... stored in X3D's

    def test_a_rotation_is_an_axis_and_an_angle(self):
        tree = bpy.data.node_groups.new("T", self.bn.TREE_IDNAME)
        damper = tree.nodes.new(self.bn.BEHAVIOUR_CLASSES["OrientationDamper"].bl_idname)
        damper.f_initialValue_axis = (0.0, 1.0, 0.0)
        damper.f_initialValue_angle = 1.5
        self.assertEqual(damper.x3d_fields["initialValue"].value, "0 1 0 1.5")
        colour = tree.nodes.new(self.bn.BEHAVIOUR_CLASSES["ColorDamper"].bl_idname)
        colour.f_initialValue = (1.0, 0.5, 0.0)
        self.assertEqual(colour.x3d_fields["initialValue"].value, "1 0.5 0")

    def test_every_single_value_field_of_the_catalogue_has_a_widget(self):
        catalogue = importlib.import_module("io_scene_x3d.behaviour_catalogue")
        missing = []
        for name, (_group, rows) in catalogue.NODES.items():
            cls = self.bn.BEHAVIOUR_CLASSES[name]
            for field_name, x3d_type, access, _default in rows:
                if access in ("inputOutput", "initializeOnly") and x3d_type.startswith("SF") and x3d_type != "SFNode":
                    known = cls.bl_rna.properties.keys()
                    if f"f_{field_name}" not in known and f"f_{field_name}_axis" not in known:
                        missing.append(f"{name}.{field_name} ({x3d_type})")
        self.assertEqual(missing, [])

    def test_editing_leaves_the_round_trip_exact(self):
        scene = self.load("door")
        graph_before = self.bn.read(scene)
        timer = scene.x3d_behaviour_tree.nodes["Timer"]
        timer.f_cycleInterval = 3                                 # the value it already had
        bg = importlib.import_module("io_scene_x3d.behaviour_graph")
        difference = bg.difference(graph_before, self.bn.read(scene))
        self.assertEqual({k: v for k, v in difference.items() if v}, {})


class VisibleTests(_Base):

    def trip(self, name):
        scene = self.load(name)
        target = os.path.join(self.tmpdir, f"{name}.x3d")
        bpy.ops.export_scene.x3d(filepath=target)
        return scene, ET.parse(target).getroot()

    @staticmethod
    def hidden(root):
        """Names of the Transforms written invisible. An object no ROUTE names is written as OB_<name>."""
        return sorted(t.get("DEF").removeprefix("OB_") for t in root.iter("Transform") if t.get("visible") == "false")

    def test_hidden_lamps_stay_hidden_through_blender(self):
        source = ET.parse(WORLDS / "counter.x3d").getroot()
        wanted = sorted(t.get("DEF") for t in source.iter("Transform") if t.get("visible") == "false")
        self.assertEqual(wanted, ["Bit0", "Bit1", "Bit2", "Bit3"])
        scene, root = self.trip("counter")
        self.assertEqual([scene.objects[name].visible_get() for name in wanted], [False] * 4)
        self.assertEqual(self.hidden(root), wanted)

    def test_unhiding_in_blender_is_the_users_choice(self):
        scene = self.load("counter")
        lamp = scene.objects["Bit0"]
        lamp.hide_render = False
        lamp.hide_set(False)
        target = os.path.join(self.tmpdir, "shown.x3d")
        bpy.ops.export_scene.x3d(filepath=target)
        self.assertEqual(self.hidden(ET.parse(target).getroot()), ["Bit1", "Bit2", "Bit3"])

    def test_a_visible_scene_gains_no_hidden_object(self):
        scene, root = self.trip("door")
        self.assertEqual([obj.name for obj in scene.objects if obj.get("x3d_visible_false")], [])
        self.assertEqual([t for t in root.iter() if t.get("visible") == "false"], [])


if __name__ == "__main__":
    unittest.main()
