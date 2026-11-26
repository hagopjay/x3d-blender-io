# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Activity (source/behaviour_activity.py) with the Player in Blender, no window: the totals equal what the simulation
logged for the same calls, Activity off or on changes no simulated value, the overlay handler is added and removed in
balance, and the Scene properties come back after being deleted. Drawing itself needs a window and is not run here
(see tools/behaviour_eyetest.py --activity)::

    cd tests && python -m unittest test_behaviour_activity_bpy
"""

from __future__ import annotations

import hashlib
import importlib
import sys
import tempfile
import unittest
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
class ActivityInBlender(unittest.TestCase):

    def setUp(self):
        _register_extension(tempfile.mkdtemp(prefix="x3d_behaviour_activity_"))
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.bn = importlib.import_module("io_scene_x3d.behaviour_nodes")
        self.bp = importlib.import_module("io_scene_x3d.behaviour_play")
        self.ba = importlib.import_module("io_scene_x3d.behaviour_activity")
        self.bn.ensure_registered()
        self.bp.ensure_axes_properties()

    def load(self, name):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.bn.ensure_registered()
        bpy.ops.import_scene.x3d(filepath=str(WORLDS / f"{name}.x3d"), use_behaviour_graph=True)
        return bpy.context.scene

    def run_world(self, scene, activity):
        """The same calls every time: start, click what is sensed, type, step 3 s. Returns (player, values digest)."""
        player = self.bp.Player(scene, activity=activity)
        player.start(0.0)
        now = 0.0
        for obj in player.sensed_objects():
            now += 0.2
            player.click(obj, now, held=0.1)
        if player.has_keys():
            for key, which in (("ArrowLeft", 37), ("ArrowUp", 38), ("a", 65)):
                now += 0.2
                player.key("keydown", key, which, now)
                player.key("keyup", key, which, now + 0.05)
        for k in range(1, 91):
            player.step(now + k / 30)
        digest = hashlib.sha256(repr(sorted((k, repr(v)) for k, v in player.sim.values.items())).encode()
                                + repr(list(player.sim.log)).encode()).hexdigest()
        return player, digest

    def test_totals_equal_the_simulation_log_on_three_worlds(self):
        for world in ("door", "counter", "snake"):
            with self.subTest(world=world):
                scene = self.load(world)
                player, _ = self.run_world(scene, True)
                activity = player.activity
                self.assertGreater(player.sim.log.appended, 0)
                self.assertEqual(activity.events, player.sim.log.appended)
                report = activity.report()
                self.assertEqual(sum(n["out"] for n in report["nodes"]), activity.events)
                self.assertEqual(sum(r["events"] for r in report["routes"]), activity.deliveries)
                # independent of the model: every value the simulation holds for a target arrived over a counted ROUTE
                for (to_id, to_field) in player.sim.values:
                    self.assertTrue(any(r["to"] == to_id and r["to_field"] == to_field and r["events"] for r in report["routes"]))
                player.stop()

    def test_off_and_on_simulate_the_same(self):
        for world in ("door", "counter", "snake"):
            with self.subTest(world=world):
                scene = self.load(world)
                off, digest_off = self.run_world(scene, False)
                values_off = dict(off.sim.values)
                off.stop()
                scene = self.load(world)
                on, digest_on = self.run_world(scene, True)
                self.assertIsNone(off.activity)
                self.assertEqual(values_off, dict(on.sim.values))
                self.assertEqual(digest_off, digest_on)
                on.stop()

    def test_the_perf_digest_still_matches(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
        import behaviour_bench as bench
        import behaviour_sim as bs
        sim = bs.Simulation(bench.build("fan", 20), log_size=10_000_000)
        self.ba.Activity.from_simulation(sim)                # attached: the log is a counting log
        changes = bench.run_sim(sim, "fan", 20, 120)
        h = hashlib.sha256()
        for line in sim.log:
            h.update(repr(line).encode())
        h.update(b"|")
        for line in changes:
            h.update(repr(line).encode())
        self.assertEqual(h.hexdigest(), bench.digest("fan", 20, 120))

    def test_overlay_handler_is_balanced(self):
        scene = self.load("door")
        player = self.bp.Player(scene, activity=True)
        self.assertFalse(self.ba.handler_active())
        try:
            started = self.ba.start_overlay(player)
        except Exception as error:      # pragma: no cover
            self.skipTest(f"SpaceNodeEditor.draw_handler_add is not usable here: {error}")
        if not started:
            self.skipTest(f"draw_handler_add refused in this build: {self.ba._state['failed']}")
        self.assertTrue(self.ba.handler_active())
        self.ba.start_overlay(player)                         # again: replaces, never stacks
        self.ba.stop_overlay()
        self.assertFalse(self.ba.handler_active())
        self.ba.stop_overlay()                                # idempotent
        self.assertFalse(self.ba.handler_active())
        player_off = self.bp.Player(scene)
        self.assertFalse(self.ba.start_overlay(player_off))   # no Activity, no handler
        self.assertFalse(self.ba.handler_active())

    def test_the_overlay_stops_on_file_load_and_unregister(self):
        scene = self.load("door")
        player = self.bp.Player(scene, activity=True)
        if not self.ba.start_overlay(player):
            self.skipTest("draw_handler_add refused in this build")
        self.ba._on_load()
        self.assertFalse(self.ba.handler_active())
        self.assertIsNone(self.ba.last_activity())
        self.ba.start_overlay(player)
        loaded = len(bpy.app.handlers.load_post)
        self.ba.unregister()
        self.assertFalse(self.ba.handler_active())
        self.ba.register()
        self.assertEqual(len(bpy.app.handlers.load_post), loaded)      # balanced: one handler, not two, not none

    def test_ensure_properties_after_they_are_deleted(self):
        for name, _l, _t, _d in self.ba.PROPERTIES:
            if hasattr(bpy.types.Scene, name):
                delattr(bpy.types.Scene, name)
        self.assertFalse(hasattr(bpy.types.Scene, "x3d_activity_show"))
        self.ba.ensure_properties()
        self.ba.ensure_properties()                           # safe to repeat
        scene = bpy.context.scene
        self.assertTrue(scene.x3d_activity_show and scene.x3d_activity_stream and scene.x3d_activity_badges)
        self.assertFalse(scene.x3d_activity_record)

    def test_a_full_recording_from_the_player_replays(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
        import behaviour_sim as bs
        for world in ("door", "counter"):
            with self.subTest(world=world):
                scene = self.load(world)
                self.ba.ensure_properties()                   # a factory reset with another copy of the add-on drops them
                scene.x3d_activity_record = True
                player, _ = self.run_world(scene, True)
                activity = player.activity
                self.assertIsNotNone(activity.trace)
                self.assertEqual(len(activity.trace), activity.deliveries)
                calls = {c["call"] for c in activity.stimulus}
                self.assertTrue({"start", "step", "press", "release"} <= calls, calls)
                fresh = bs.Simulation(player.graph, log_size=10_000_000)
                again = self.ba.Activity.from_simulation(fresh, record=True)
                self.ba.replay(fresh, __import__("json").loads(activity.to_json())["stimulus"], again)
                self.assertEqual(again.trace, __import__("json").loads(activity.to_json())["trace"])
                player.stop()
                scene.x3d_activity_record = False
                off, _ = self.run_world(self.load(world), True)
                self.assertIsNone(off.activity.trace)
                off.stop()

    def test_a_sensor_at_the_scene_root_senses_every_object(self):
        path = Path(tempfile.mkdtemp(prefix="x3d_root_sensor_")) / "root.x3d"
        path.write_text("""<X3D profile="Immersive" version="4.0"><Scene>
  <TouchSensor DEF="Poke" />
  <Transform DEF="A"><Shape><Appearance><Material/></Appearance><Box/></Shape></Transform>
  <Transform DEF="B" translation="2 0 0"><Shape><Appearance><Material/></Appearance><Box/></Shape></Transform>
  <TimeSensor DEF="Clock" cycleInterval="1" />
  <ROUTE fromNode="Poke" fromField="touchTime" toNode="Clock" toField="startTime" />
</Scene></X3D>""", encoding="utf-8")
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.bn.ensure_registered()
        bpy.ops.import_scene.x3d(filepath=str(path), use_behaviour_graph=True)
        scene = bpy.context.scene
        player = self.bp.Player(scene, activity=True)
        self.assertIsNone(player.graph.nodes["Poke"].parent)
        objects = [o for o in scene.objects if o.type == "MESH"]
        self.assertGreaterEqual(len(objects), 2)
        for obj in objects:
            self.assertEqual(player.sensors_for(obj), ["Poke"])
        player.start(0.0)
        self.assertTrue(player.click(objects[0], 0.5, held=0.1))
        player.step(0.7)
        self.assertGreater(player.activity.deliveries, 0)
        player.stop()

    def test_the_copy_text_and_report(self):
        scene = self.load("counter")
        player, _ = self.run_world(scene, True)
        self.ba._state["last"] = player.activity
        text = self.ba.copy_text()
        self.assertIn(str(player.activity.events), text)
        self.assertIn("ROUTE", text)
        player.stop()


if __name__ == "__main__":
    unittest.main()
