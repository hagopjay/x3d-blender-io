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
        self.bp.ensure_axes_properties()    # the factory reset above can remove them, as it does the tree property

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


class HAnimPlayTests(_Base):
    """HAnimJoint, HAnimSite and HAnimSegment as targets (tests/behaviour/probe-hanim.x3d): the importer makes a bone for each
    joint and no object for a site or a segment."""

    def import_world(self, graph=True):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.bn.ensure_registered()
        bpy.ops.import_scene.x3d(filepath=str(WORLDS / "probe-hanim.x3d"), use_behaviour_graph=graph)
        return bpy.context.scene

    def poses(self, scene):
        armature = scene.objects["Body"]
        return {pb.name: (pb.rotation_mode, tuple(round(v, 5) for v in pb.location),
                          tuple(round(v, 5) for v in pb.rotation_quaternion), tuple(round(v, 5) for v in pb.scale))
                for pb in armature.pose.bones}

    def test_the_importer_binds_a_joint_to_the_bone_it_named_after_the_joint(self):
        scene = self.import_world()
        graph = self.bn.read(scene)
        self.assertEqual(graph.nodes["hanim_root"].binding, ("joint", "root"))       # name="root", not the DEF
        self.assertEqual(graph.nodes["hanim_spine"].binding, ("joint", "spine"))
        self.assertEqual(graph.nodes["hanim_tip"].binding, ("site", "hanim_tip"))
        self.assertEqual(graph.nodes["hanim_spine_seg"].binding, ("site", "hanim_spine_seg"))
        self.assertEqual(len(graph.routes), 24)                        # and no ROUTE was lost to carrying a Humanoid whole
        self.assertEqual([n.id for n in graph.nodes.values() if n.role == "carried"], [])

    def test_a_joint_turns_its_bone_as_the_importer_turns_it_from_keys_and_stop_puts_it_back(self):
        scene = self.import_world()
        rest = self.poses(scene)
        player = self.bp.Player(scene)
        player.start(0.0)
        player.click(scene.objects["Pad"], 0.0, held=0.0)
        player.step(1.5)                       # half way through the 3 s cycle: the swing's middle key, 1 radian
        self.assertAlmostEqual(player.sim.values[("hanim_root", "rotation")][3], 1.0, places=9)
        applied = self.poses(scene)
        self.assertNotEqual(applied["root"], rest["root"])
        self.assertNotEqual(applied["spine"], rest["spine"])                  # translation, scale and center
        # the importer keys the same joint from the same interpolator (no graph); at a key the two agree (between keys it
        # blends quaternion components, the Player turns by the angle)
        baked = self.import_world(graph=False)
        baked.frame_set(baked.frame_start + round(1.5 * baked.render.fps / baked.render.fps_base))
        self.assertEqual(tuple(round(v, 3) for v in self.poses(baked)["root"][2]), tuple(round(v, 3) for v in applied["root"][2]))
        scene = self.import_world()
        player = self.bp.Player(scene)
        player.start(0.0)
        player.click(scene.objects["Pad"], 0.0, held=0.0)
        player.step(1.2)
        player.stop()
        self.assertEqual(self.poses(scene), rest)

    def test_what_is_not_shown_is_listed_with_why(self):
        scene = self.import_world()
        player = self.bp.Player(scene)
        player.start(0.0)
        player.click(scene.objects["Pad"], 0.0, held=0.0)
        player.step(1.0)
        self.assertEqual(player.not_applied, [
            "HAnimSite.translation (no object 'hanim_tip')", "HAnimSite.rotation (no object 'hanim_tip')",
            "HAnimSegment.centerOfMass (a segment has no placement)", "HAnimSegment.mass (a segment has no placement)",
            "Transform.center"])
        player.stop()

    def test_a_site_is_moved_where_some_object_carries_its_def(self):
        scene = self.import_world()
        marker = bpy.data.objects.new("Marker", None)
        scene.collection.objects.link(marker)
        marker["x3d_def"] = "hanim_tip"
        player = self.bp.Player(scene)
        player.start(0.0)
        player.click(scene.objects["Pad"], 0.0, held=0.0)
        player.step(3.5)
        self.assertEqual(self.as_exported(marker), (0.0, 0.5, 0.25))            # Slide's last value, in the file's axes
        self.assertNotIn("HAnimSite.translation", " ".join(player.not_applied))
        player.stop()
        self.assertEqual(tuple(marker.location), (0.0, 0.0, 0.0))

    def test_a_joint_with_no_bone_or_with_two_is_listed_not_guessed(self):
        scene = self.import_world()
        graph = self.bn.read(scene)
        graph.nodes["hanim_root"].binding = ("joint", "no_such_bone")
        player = self.bp.Player(scene, graph)
        player.start(0.0)
        player.click(scene.objects["Pad"], 0.0, held=0.0)
        player.step(1.0)
        self.assertIn("HAnimJoint.rotation (no bone 'no_such_bone')", player.not_applied)
        player.stop()
        twin = bpy.data.objects.new("Twin", bpy.data.armatures.new("Twin"))
        scene.collection.objects.link(twin)
        bpy.context.view_layer.objects.active = twin
        bpy.ops.object.mode_set(mode="EDIT")
        bone = twin.data.edit_bones.new("spine")
        bone.head, bone.tail = (0, 0, 0), (0, 0.1, 0)
        bpy.ops.object.mode_set(mode="OBJECT")
        before = self.poses(scene)
        player = self.bp.Player(scene, self.bn.read(scene))
        player.start(0.0)
        player.click(scene.objects["Pad"], 0.0, held=0.0)
        player.step(1.0)
        self.assertIn("HAnimJoint.translation (2 armatures have a bone 'spine')", player.not_applied)
        player.stop()
        self.assertEqual(self.poses(scene), before)

    def test_the_binding_survives_the_node_tree(self):
        scene = self.import_world()
        tree = scene.x3d_behaviour_tree
        labels = sorted(n.label for n in tree.nodes if n.x3d_role == "target")
        self.assertIn("HAnimJoint  root", labels)
        self.assertIn("HAnimSite  hanim_tip", labels)
        again = self.bn.read(scene)
        self.assertEqual(again.nodes["hanim_spine"].binding, ("joint", "spine"))
        self.bn.apply(again, scene)
        self.assertEqual(self.bn.read(scene).nodes["hanim_spine"].binding, ("joint", "spine"))


class SwitchPlayTests(_Base):
    """Switch.whichChoice as a target (tests/behaviour/probe-switch.x3d): the importer tags each object made under a DEF'd
    Switch with its branch."""

    def import_world(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.bn.ensure_registered()
        bpy.ops.import_scene.x3d(filepath=str(WORLDS / "probe-switch.x3d"), use_behaviour_graph=True)
        return bpy.context.scene

    def shown(self, scene):
        bpy.context.view_layer.update()
        return sorted(name for name in ("Red", "Green", "Blue") if scene.objects[name].visible_get() and not scene.objects[name].hide_render)

    def test_the_importer_tags_each_branch_object_with_its_switch_branch_and_choice(self):
        scene = self.import_world()
        self.assertEqual({n: scene.objects[n].get("x3d_switch") for n in ("Red", "Green", "Blue")},
                         {"Red": "Pick:0:0", "Green": "Pick:1:0", "Blue": "Pick:2:0"})
        self.assertEqual(scene.objects["Pad"].get("x3d_switch"), None)
        graph = self.bn.read(scene)
        self.assertEqual(graph.nodes["Pick"].binding, ("switch", "Pick"))
        self.assertEqual(graph.nodes["Echo"].binding, ("switch", "Echo"))   # the Echo's one Shape is tagged too ("Echo:0:-1")
        self.assertEqual(self.bp.SWITCH_PROPERTY, importlib.import_module("io_scene_x3d.import_x3d").SWITCH_BRANCH_PROPERTY)

    def test_a_choice_shows_one_branch_and_stop_puts_the_scene_back(self):
        scene = self.import_world()
        self.assertEqual(self.shown(scene), ["Red"])                       # whichChoice="0" in the file
        player = self.bp.Player(scene)
        player.start(0.0)
        player.click(scene.objects["Pad"], 0.0, held=0.0)
        player.step(0.2)                                                   # Steps sends 2 at fraction 0
        self.assertEqual(self.shown(scene), ["Blue"])
        player.step(1.0)                                                   # 1
        self.assertEqual(self.shown(scene), ["Green"])
        player.step(2.0)                                                   # -1: none
        self.assertEqual(self.shown(scene), [])
        player.step(2.8)                                                   # 5: past the last child, none
        self.assertEqual(self.shown(scene), [])
        self.assertNotIn("Switch.whichChoice", " ".join(player.not_applied))
        player.stop()
        self.assertEqual(self.shown(scene), ["Red"])

    def test_a_switch_with_no_object_under_it_is_listed_not_guessed(self):
        scene = self.import_world()
        bg = importlib.import_module("io_scene_x3d.behaviour_graph")
        graph = bg.Behaviour()
        steps = graph.add("IntegerSequencer", "Steps", key=[0, 1], keyValue=[1, 0])
        graph.add("TimeSensor", "Timer", cycleInterval=2, loop=True).fraction_changed >> steps.set_fraction
        steps.value_changed >> graph.target("Switch", "Nowhere").whichChoice
        player = self.bp.Player(scene, graph)
        player.start(0.0)
        player.step(0.5)
        self.assertEqual(player.not_applied, ["Switch.whichChoice (no object under Switch 'Nowhere')"])
        self.assertEqual(self.shown(scene), ["Red"])
        player.stop()


class ShaderPlayTests(_Base):
    """A ComposedShader's own fields as targets (tests/behaviour/probe-shader.x3d): kept in the graph and the node tree,
    simulated, and not applied in Blender."""

    def import_world(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.bn.ensure_registered()
        bpy.ops.import_scene.x3d(filepath=str(WORLDS / "probe-shader.x3d"), use_behaviour_graph=True)
        return bpy.context.scene

    def test_the_importer_keeps_the_shader_and_its_declared_fields_and_every_route(self):
        scene = self.import_world()
        graph = self.bn.read(scene)
        glow = graph.nodes["Glow"]
        self.assertEqual((glow.role, glow.binding), ("target", ("shader", "Glow")))
        self.assertEqual([row[:2] for row in glow.declared],
                         [("uTime", "SFFloat"), ("uTint", "SFColor"), ("uSteps", "SFInt32"), ("uFlag", "SFBool"),
                          ("uOffset", "SFVec3f"), ("uScale", "SFVec2f")])
        self.assertEqual(len(graph.routes), 18)
        self.assertEqual(graph.check(), [])
        self.assertEqual([n.id for n in graph.nodes.values() if n.role == "carried"], [])

    def test_the_node_tree_has_a_socket_for_each_declared_field_and_survives_apply_and_read(self):
        scene = self.import_world()
        node = next(n for n in scene.x3d_behaviour_tree.nodes if n.name == "Glow")
        self.assertEqual(node.label, "ComposedShader  Glow")
        self.assertIn("uTime", node.inputs)
        self.assertIn("uTime", node.outputs)                  # inputOutput: both
        self.assertIn("uScale", node.inputs)
        self.assertNotIn("uScale", node.outputs)              # inputOnly
        self.assertEqual(node.inputs["uOffset"].bl_idname, "X3DSocketSFVec3f")
        graph = self.bn.read(scene)
        self.bn.apply(graph, scene)
        again = self.bn.read(scene)
        self.assertEqual(again.nodes["Glow"].declared, graph.nodes["Glow"].declared)
        self.assertEqual(len(again.routes), 18)
        self.assertEqual(self.bg_module().difference(graph, again)["routes_lost"], [])

    def bg_module(self):
        return importlib.import_module("io_scene_x3d.behaviour_graph")

    def test_play_runs_the_fields_and_says_it_does_not_show_them(self):
        scene = self.import_world()
        player = self.bp.Player(scene)
        player.start(0.0)
        player.click(scene.objects["Pad"], 0.0, held=0.0)
        player.step(1.5)
        self.assertEqual(player.sim.values[("Glow", "uTime")], 3.75)                  # half of 7.5
        self.assertEqual(player.not_applied, [f"ComposedShader.{field} (a shader's fields are not set in Blender)"
                                              for field in ("uTime", "uTint", "uSteps", "uFlag", "uOffset", "uScale")])
        self.assertEqual(player.sim.not_simulated, [])
        player.stop()


class MediaNodesTests(_Base):

    WORLD = ('<?xml version="1.0" encoding="UTF-8"?><X3D profile="Full" version="4.0"><head/><Scene>\n'
             '<Transform DEF="Box"><Shape><Box/></Shape></Transform>\n'
             '<Sound><AudioClip DEF="Tone" url=\'"t.wav"\' loop="true"/></Sound>\n'
             '<Shape><Appearance><MovieTexture DEF="Film" url=\'"f.webm"\' loop="true"/></Appearance></Shape>\n'
             '<LoadSensor DEF="Loading"><ImageTexture containerField="children" url=\'"a.png"\'/></LoadSensor>\n'
             '<BooleanToggle DEF="Sink"/>\n'
             '<ROUTE fromNode="Tone" fromField="isActive" toNode="Sink" toField="set_boolean"/>\n'
             '<ROUTE fromNode="Film" fromField="isActive" toNode="Sink" toField="set_boolean"/>\n'
             '<ROUTE fromNode="Loading" fromField="isLoaded" toNode="Sink" toField="set_boolean"/>\n'
             '</Scene></X3D>')

    def test_play_runs_the_media_clocks_and_lists_what_it_does_not_apply(self):
        bg = importlib.import_module("io_scene_x3d.behaviour_graph")
        scene = self.import_world() if hasattr(self, "import_world") else bpy.context.scene
        graph = bg.Behaviour.from_x3d(self.WORLD)
        player = self.bp.Player(scene, graph)
        player.start(0.0)
        player.step(0.5)
        self.assertEqual(sorted(player.not_applied), [
            "AudioClip.sound (the Player plays no sound; its clock and events run)",
            "LoadSensor.loading (nothing is fetched; every URL counts as loaded at once)",
            "MovieTexture.picture (the Player shows no video; its clock and events run)"])
        self.assertEqual(player.sim.outputs[("Tone", "isActive")], True)           # the clock runs though nothing sounds
        self.assertEqual(player.sim.outputs[("Loading", "isLoaded")], True)
        self.assertEqual(player.sim.noted["assumed-loaded"], 3)
        player.stop()


class GeoNodesTests(_Base):

    ORIGIN = '<GeoOrigin geoSystem=\'"GD" "WE"\' geoCoords="48.7 2.2 0" containerField="geoOrigin"/>'
    WORLD = ('<?xml version="1.0" encoding="UTF-8"?><X3D profile="Full" version="4.0"><head/><Scene>\n'
             '<GeoOrigin DEF="Home" geoSystem=\'"GD" "WE"\' geoCoords="48.7 2.2 0"/>\n'
             '<GeoTouchSensor DEF="Pick" geoSystem=\'"GD" "WE"\'>' + ORIGIN + '</GeoTouchSensor>\n'
             '<GeoTouchSensor DEF="PickUse" geoSystem=\'"GD" "WE"\'><GeoOrigin USE="Home" containerField="geoOrigin"/></GeoTouchSensor>\n'
             '<GeoProximitySensor DEF="Near" geoSystem=\'"GD" "WE"\' size="-1 -1 -1">' + ORIGIN + '</GeoProximitySensor>\n'
             '</Scene></X3D>')

    def test_play_feeds_the_geo_sensors_and_lists_what_it_cannot_give(self):
        bg = importlib.import_module("io_scene_x3d.behaviour_graph")
        scene = bpy.context.scene
        thing = bpy.data.objects.new("Thing", None)
        scene.collection.objects.link(thing)
        player = self.bp.Player(scene, bg.Behaviour.from_x3d(self.WORLD))
        self.assertEqual(player.proximity_sensors(), ["Near"])
        self.assertEqual(sorted(player.not_applied), [
            "GeoTouchSensor Pick: hover gives no hit point, so hitGeoCoord_changed comes only with a press",
            "GeoTouchSensor PickUse: hover gives no hit point, so hitGeoCoord_changed comes only with a press"])
        player.start(0.0)
        player.view(thing.matrix_world.copy(), (0.0, 0.0, 0.0), 0.1)
        self.assertEqual(player.sim.outputs[("Near", "isActive")], True)
        self.assertIn(("Near", "geoCoord_changed"), player.sim.outputs)
        self.assertTrue(player.press(thing, 0.2, location=(1.0, 2.0, 3.0)))
        self.assertEqual(player.sim.outputs[("Pick", "isActive")], True)
        self.assertIn(("Pick", "hitGeoCoord_changed"), player.sim.outputs)
        # a GeoOrigin named by USE is a node Play does not read from the scene: refused by name, nothing sent from it
        self.assertNotIn(("PickUse", "hitGeoCoord_changed"), player.sim.outputs)
        self.assertGreaterEqual(player.sim.noted.get("geo-origin-unresolved", 0), 1)
        player.release(0.3)
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


class PlayAxesTests(_Base):
    """The player moves objects as a file exported with the same axes would (the Play axes on the scene)."""

    PAIRS = (("-Z", "Y", (0.0, 0.0, 2.0)),     # the export dialog's default: X3D +Y is Blender +Z
             ("Y", "Z", (0.0, 2.0, 0.0)),      # Blender's own axes (axis_conversion is the identity): X3D +Y is Blender +Y
             ("X", "Z", (-2.0, 0.0, 0.0)))     # Blender +Y forward turned to +X: X3D +Y is Blender -X

    def lift_scene(self, *, child=False):
        """A root object "Lift" (and optionally a child "Hand" under a parent "Arm" at X 5) driven by a looping timer:
        X3D value (0, 2, 0) at 1 s for the root, (0, 0, 2) at 1 s for the child."""
        scene = bpy.context.scene
        lift = bpy.data.objects.new("Lift", bpy.data.meshes.new("LiftMesh"))
        scene.collection.objects.link(lift)
        bg = importlib.import_module("io_scene_x3d.behaviour_graph")
        graph = bg.Behaviour()
        clock = graph.add("TimeSensor", "Clock", cycleInterval=2, loop=True)
        up = graph.add("PositionInterpolator", "Up", key=[0, 1], keyValue=[(0, 0, 0), (0, 4, 0)])
        clock.fraction_changed >> up.set_fraction
        up.value_changed >> self.bn.target(graph, lift).translation
        hand = None
        if child:
            arm = bpy.data.objects.new("Arm", None)
            hand = bpy.data.objects.new("Hand", bpy.data.meshes.new("HandMesh"))
            scene.collection.objects.link(arm)
            scene.collection.objects.link(hand)
            arm.location = (5.0, 0.0, 0.0)
            hand.parent = arm
            along = graph.add("PositionInterpolator", "Along", key=[0, 1], keyValue=[(0, 0, 0), (0, 0, 4)])
            clock.fraction_changed >> along.set_fraction
            along.value_changed >> self.bn.target(graph, hand).translation
        self.bn.apply(graph, scene)
        return scene, lift, hand

    def play_axes(self, scene, forward, up):
        scene.x3d_play_forward, scene.x3d_play_up = forward, up
        matrix, problem = self.bp.scene_axes(bpy.context, scene)
        self.assertIsNone(problem)
        return matrix

    def test_the_axis_choices_are_the_export_dialogs(self):
        for name in ("axis_forward", "axis_up"):
            export = bpy.ops.export_scene.x3d.get_rna_type().properties[name]
            ours = bpy.types.Scene.bl_rna.properties["x3d_play_" + name[5:]]
            self.assertEqual([(i.identifier, i.name) for i in ours.enum_items],
                             [(i.identifier, i.name) for i in export.enum_items])
            self.assertEqual(ours.default, export.default)

    def test_a_root_object_moves_along_the_axis_the_exporter_maps_x3d_y_from(self):
        for forward, up, literal in self.PAIRS:
            with self.subTest(forward=forward, up=up):
                bpy.ops.wm.read_factory_settings(use_empty=True)
                self.bn.ensure_registered()
                scene, lift, _ = self.lift_scene()
                matrix = self.play_axes(scene, forward, up)
                player = self.bp.Player(scene, global_matrix=matrix)
                player.start(0.0)
                player.step(1.0)                                    # fraction 0.5: X3D translation (0, 2, 0)
                bpy.context.view_layer.update()
                from bpy_extras.io_utils import axis_conversion
                from mathutils import Vector
                derived = axis_conversion(to_forward=forward, to_up=up).inverted() @ Vector((0.0, 2.0, 0.0))
                self.assertEqual(tuple(round(v, 4) for v in lift.location), tuple(round(v, 4) for v in derived))
                # the literal vector, worked out by hand from the exporter's rule (X3D = axis_conversion @ Blender):
                self.assertEqual(tuple(round(v, 4) for v in lift.location), literal)
                player.stop()
                self.assertEqual(tuple(lift.location), (0.0, 0.0, 0.0))

    def test_a_child_object_ignores_the_axes(self):
        for forward, up, _ in self.PAIRS:
            with self.subTest(forward=forward, up=up):
                bpy.ops.wm.read_factory_settings(use_empty=True)
                self.bn.ensure_registered()
                scene, lift, hand = self.lift_scene(child=True)
                player = self.bp.Player(scene, global_matrix=self.play_axes(scene, forward, up))
                player.start(0.0)
                player.step(1.0)
                bpy.context.view_layer.update()
                # the child's Transform is in its parent's space, which is Blender's: (0, 0, 4) at fraction 0.5 is Z 2
                self.assertEqual(tuple(round(v, 4) for v in hand.matrix_local.to_translation()), (0.0, 0.0, 2.0))
                self.assertEqual(tuple(round(v, 4) for v in hand.matrix_world.to_translation()), (5.0, 0.0, 2.0))
                player.stop()
                self.assertEqual(tuple(hand.location), (0.0, 0.0, 0.0))

    def test_the_exporter_writes_what_the_player_was_fed(self):
        for forward, up, _ in self.PAIRS:
            with self.subTest(forward=forward, up=up):
                bpy.ops.wm.read_factory_settings(use_empty=True)
                self.bn.ensure_registered()
                scene, lift, _ = self.lift_scene()
                player = self.bp.Player(scene, global_matrix=self.play_axes(scene, forward, up))
                player.start(0.0)
                player.step(1.0)
                target = next(n.id for n in player.graph.nodes.values() if n.role == "target")
                fed = tuple(round(v, 4) for v in player.sim.values[(target, "translation")])
                self.assertEqual(fed, (0.0, 2.0, 0.0))
                bpy.context.view_layer.update()
                path = os.path.join(self.tmpdir, f"axes_{forward}_{up}.x3d")
                bpy.ops.export_scene.x3d(filepath=path, axis_forward=forward, axis_up=up)
                root = ET.parse(path).getroot()
                interpolator = next(e for e in root.iter() if e.tag.split("}")[-1] == "PositionInterpolator"
                                    and e.get("DEF") == "Up")
                self.assertEqual([float(v) for v in interpolator.get("keyValue").split()], [0, 0, 0, 0, 4, 0])
                transform = next(e for e in root.iter() if e.tag.split("}")[-1] == "Transform"
                                 and e.get("DEF", "").startswith("Lift"))
                written = tuple(round(float(v), 4) for v in transform.get("translation", "0 0 0").split())
                self.assertEqual(written, fed)          # the file puts the object where the player put it
                player.stop()
