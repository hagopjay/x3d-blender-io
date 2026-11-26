# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Hosted nodes in Blender (source/behaviour_hosted.py, the handler hook and the rigid body read in behaviour_play.py).

The security rule under test: a Python handler runs only from a text datablock the person enabled for that Script in this
session, as it was when they enabled it; nothing a file carries (an imported .x3d, a .blend's properties and datablocks, a
linked library) can turn it on. Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_behaviour_hosted_bpy
"""

from __future__ import annotations

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

HANDLER = """\
def handle(field, value, time, state):
    if field == "touched":
        return [("place", (0.0, 4.0, 0.0))]
    return []
"""

# what a hostile text would do if anything ran it: leave a mark where this test can see it
HOSTILE = """\
import builtins
builtins.X3D_HANDLER_RAN = True
def handle(field, value, time, state):
    return [("place", (0.0, 9.0, 0.0))]
"""


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class _Base(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="x3d_behaviour_hosted_")
        _register_extension(self.tmpdir)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.bn = importlib.import_module("io_scene_x3d.behaviour_nodes")
        self.bp = importlib.import_module("io_scene_x3d.behaviour_play")
        self.bh = importlib.import_module("io_scene_x3d.behaviour_hosted")
        self.bn.ensure_registered()
        self.bp.ensure_axes_properties()
        self.bh.REGISTRY.clear()
        import builtins
        if hasattr(builtins, "X3D_HANDLER_RAN"):
            del builtins.X3D_HANDLER_RAN
        self.addCleanup(self.bh.REGISTRY.clear)

    def load(self, name):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.bn.ensure_registered()
        bpy.ops.import_scene.x3d(filepath=str(WORLDS / f"{name}.x3d"), use_behaviour_graph=True)
        return bpy.context.scene

    @staticmethod
    def ran():
        import builtins
        return getattr(builtins, "X3D_HANDLER_RAN", False)


class HandlerGateTests(_Base):

    def test_a_script_with_nothing_enabled_is_wired_and_says_hosted_not_run(self):
        scene = self.load("wired-script")
        player = self.bp.Player(scene)
        self.assertEqual(sorted(player.sim.hosted_not_run()), ["Script Brain", "Script Remote"])
        self.assertEqual(player.hosting, [])
        player.start(0.0)
        player.sim.send("Brain", "touched", 1.0, 1.0)
        self.assertGreater(player.sim.noted["hosted-not-run"], 0)

    def test_everything_a_file_can_carry_does_not_enable_a_handler(self):
        scene = self.load("wired-script")
        text = bpy.data.texts.new("Brain")                      # a text named like the Script, in the file
        text.write(HOSTILE)
        for owner in (scene, text, scene.x3d_behaviour_tree, scene.objects["Lamp"], bpy.context.window_manager):
            for key in ("x3d_handler_enabled", "x3d_handler", "x3d_enabled", "enabled", "x3d_handler_text", "Brain"):
                owner[key] = True if key != "x3d_handler_text" else "Brain"
        for node in scene.x3d_behaviour_tree.nodes:
            node["x3d_handler_enabled"] = True
            node["x3d_handler_text"] = "Brain"
        player = self.bp.Player(scene)
        player.start(0.0)
        player.sim.send("Brain", "touched", 1.0, 1.0)
        self.assertFalse(self.ran())
        self.assertEqual(player.hosting, [])
        self.assertIn("Script Brain", player.sim.hosted_not_run())

    def test_an_imported_x3d_that_holds_python_or_a_handler_name_runs_nothing(self):
        path = Path(self.tmpdir) / "hostile.x3d"
        path.write_text(
            '<?xml version="1.0"?><X3D profile="Full" version="4.0"><Scene>'
            '<Transform DEF="Lamp"><Shape><Sphere/></Shape></Transform>'
            '<Transform DEF="Pad"><Shape><Box/></Shape><TouchSensor DEF="Touch"/></Transform>'
            '<Script DEF="Brain" url=\'"python:import builtins; builtins.X3D_HANDLER_RAN = True"\'>'
            '<field name="touched" type="SFTime" accessType="inputOnly"/><field name="place" type="SFVec3f" accessType="outputOnly"/>'
            "<![CDATA[python:\nimport builtins\nbuiltins.X3D_HANDLER_RAN = True\n]]></Script>"
            '<ROUTE fromNode="Touch" fromField="touchTime" toNode="Brain" toField="touched"/>'
            '<ROUTE fromNode="Brain" fromField="place" toNode="Lamp" toField="set_translation"/></Scene></X3D>', encoding="utf-8")
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.bn.ensure_registered()
        bpy.ops.import_scene.x3d(filepath=str(path), use_behaviour_graph=True)
        scene = bpy.context.scene
        player = self.bp.Player(scene)
        player.start(0.0)
        player.click(scene.objects["Pad"], 1.0)
        player.step(2.0)
        self.assertFalse(self.ran())
        self.assertEqual(len(self.bh.REGISTRY), 0)

    def test_enabling_is_an_act_in_this_session_and_then_the_handler_runs(self):
        scene = self.load("wired-script")
        text = bpy.data.texts.new("brain.py")
        text.write(HANDLER)
        result = bpy.ops.x3d.behaviour_enable_handler("EXEC_DEFAULT", script="Brain", text="brain.py")
        self.assertEqual(result, {"FINISHED"})
        self.assertEqual(self.bh.REGISTRY.binding(scene.name, "Brain")[0], "brain.py")
        player = self.bp.Player(scene)
        self.assertEqual(player.hosting, ["Script Brain: handler 'brain.py' runs"])
        self.assertEqual(player.sim.hosted_not_run(), ["Script Remote"])
        player.start(0.0)
        self.assertTrue(player.click(scene.objects["Pad"], 1.0))
        lamp = scene.objects["Lamp"]
        bpy.context.view_layer.update()
        self.assertAlmostEqual(lamp.location.z, 4.0, places=4)          # X3D's y 4 is Blender's z 4: the handler's output moved it
        player.stop()

    def test_the_enablement_is_not_in_the_file(self):
        scene = self.load("wired-script")
        text = bpy.data.texts.new("brain.py")
        text.write(HANDLER)
        bpy.ops.x3d.behaviour_enable_handler("EXEC_DEFAULT", script="Brain", text="brain.py")
        saved = Path(self.tmpdir) / "saved.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(saved))
        keys = set()
        for owner in [scene, text, scene.x3d_behaviour_tree, bpy.context.window_manager, *scene.objects, *scene.x3d_behaviour_tree.nodes]:
            keys |= {str(k) for k in owner.keys()}
        self.assertFalse([k for k in keys if "handler" in k.lower() or "enabled" in k.lower()], keys)
        self.assertTrue(self.bh.REGISTRY.binding(scene.name, "Brain"))
        # loading a file (this one) forgets every enablement: the hook the add-on registers on load_post
        self.bp._forget_handlers()
        self.assertEqual(len(self.bh.REGISTRY), 0)
        bpy.ops.wm.open_mainfile(filepath=str(saved))
        self.assertEqual(len(self.bh.REGISTRY), 0)
        player = self.bp.Player(bpy.context.scene)
        self.assertEqual(player.hosting, [])

    def test_the_hook_is_registered_on_load(self):
        self.bp.register()
        self.assertIn(self.bp._forget_handlers, bpy.app.handlers.load_post)

    def test_a_text_changed_after_enabling_is_not_run_until_enabled_again(self):
        scene = self.load("wired-script")
        text = bpy.data.texts.new("brain.py")
        text.write(HANDLER)
        bpy.ops.x3d.behaviour_enable_handler("EXEC_DEFAULT", script="Brain", text="brain.py")
        text.clear()
        text.write(HOSTILE)                                 # swapped for something else after the person looked
        player = self.bp.Player(scene)
        self.assertFalse(self.ran())
        self.assertTrue(any("changed since it was enabled" in line for line in player.hosting), player.hosting)
        self.assertIn("Script Brain", player.sim.hosted_not_run())
        bpy.ops.x3d.behaviour_enable_handler("EXEC_DEFAULT", script="Brain", text="brain.py")    # the person looked again
        player = self.bp.Player(scene)
        self.assertTrue(self.ran())                         # the text defines itself when the Player loads it
        self.assertEqual(player.hosting, ["Script Brain: handler 'brain.py' runs"])

    def test_a_text_replaced_by_another_of_the_same_name_is_not_the_one_enabled(self):
        scene = self.load("wired-script")
        text = bpy.data.texts.new("brain.py")
        text.write(HANDLER)
        bpy.ops.x3d.behaviour_enable_handler("EXEC_DEFAULT", script="Brain", text="brain.py")
        bpy.data.texts.remove(text)
        other = bpy.data.texts.new("brain.py")
        other.write(HOSTILE)
        player = self.bp.Player(scene)
        self.assertFalse(self.ran())
        self.assertTrue(player.hosting and "not run" in player.hosting[0])

    def test_a_text_linked_from_a_library_is_refused(self):
        library = Path(self.tmpdir) / "library.blend"
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.data.texts.new("brain.py").write(HOSTILE)
        bpy.ops.wm.save_as_mainfile(filepath=str(library))
        scene = self.load("wired-script")
        with bpy.data.libraries.load(str(library), link=True) as (source, target):
            target.texts = ["brain.py"]
        linked = bpy.data.texts["brain.py"]
        self.assertIsNotNone(linked.library)
        with self.assertRaisesRegex(RuntimeError, "linked from a library"):      # an ERROR report is a RuntimeError to a script
            bpy.ops.x3d.behaviour_enable_handler("EXEC_DEFAULT", script="Brain", text="brain.py")
        self.assertEqual(len(self.bh.REGISTRY), 0)
        self.bh.REGISTRY.enable(scene.name, "Brain", "brain.py", linked.as_string())        # even enabled by other means
        player = self.bp.Player(scene)
        self.assertFalse(self.ran())
        self.assertTrue(any("linked from a library" in line for line in player.hosting), player.hosting)

    def test_a_handler_that_raises_does_not_stop_the_player(self):
        scene = self.load("wired-script")
        text = bpy.data.texts.new("brain.py")
        text.write("def handle(field, value, time, state):\n    raise RuntimeError('boom')\n")
        bpy.ops.x3d.behaviour_enable_handler("EXEC_DEFAULT", script="Brain", text="brain.py")
        player = self.bp.Player(scene)
        player.start(0.0)
        player.click(scene.objects["Pad"], 1.0)
        player.step(2.0)
        self.assertTrue(player.sim.faults)

    def test_the_operator_needs_a_text_and_refuses_while_playing(self):
        self.load("wired-script")
        with self.assertRaisesRegex(RuntimeError, "Choose a text"):
            bpy.ops.x3d.behaviour_enable_handler("EXEC_DEFAULT", script="Brain", text="nothing")
        self.assertEqual(len(self.bh.REGISTRY), 0)
        bpy.data.texts.new("t.py").write(HANDLER)
        self.bp._running["player"] = object()
        try:
            self.assertFalse(bpy.ops.x3d.behaviour_enable_handler.poll())
        finally:
            self.bp._running["player"] = None


class CollisionReadTests(_Base):

    def scene_with_cubes(self, rigid=True):
        scene = self.load("wired-collision")
        bpy.ops.mesh.primitive_cube_add(location=(0, 0, 0))
        a = bpy.context.active_object
        a.name = "A"
        bpy.ops.mesh.primitive_cube_add(location=(5, 0, 0))
        b = bpy.context.active_object
        b.name = "B"
        if rigid:
            bpy.ops.rigidbody.world_add()
            for obj in (a, b):
                bpy.ops.object.select_all(action="DESELECT")
                obj.select_set(True)
                bpy.context.view_layer.objects.active = obj
                bpy.ops.rigidbody.object_add()
        return scene, a, b

    def test_two_rigid_bodies_that_meet_make_the_sensor_active(self):
        scene, a, b = self.scene_with_cubes()
        player = self.bp.Player(scene)
        self.assertTrue(any("reads Blender's rigid body world" in line for line in player.hosting), player.hosting)
        player.start(0.0)
        self.assertIs(player.sim.outputs.get(("Contact", "isActive"), False), False)
        self.assertEqual([n for n in player.sim.hosted_not_run() if n.startswith("Collision")], [])
        b.location = (1.5, 0, 0)                          # the boxes (2 across) now touch
        bpy.context.view_layer.update()
        player.step(0.1)
        self.assertIs(player.sim.outputs[("Contact", "isActive")], True)
        self.assertTrue(player.sim.outputs[("Contact", "contacts")])
        b.location = (5, 0, 0)
        bpy.context.view_layer.update()
        player.step(0.2)
        self.assertIs(player.sim.outputs[("Contact", "isActive")], False)
        player.stop()

    def test_without_a_rigid_body_world_the_sensor_is_wired_and_not_run(self):
        scene, a, b = self.scene_with_cubes(rigid=False)
        player = self.bp.Player(scene)
        self.assertTrue(any("no rigid body world; hosted, not run" in line for line in player.hosting), player.hosting)
        self.assertIn("CollisionSensor Contact", player.sim.hosted_not_run())
        player.start(0.0)
        player.step(0.1)
        self.assertNotIn(("Contact", "isActive"), player.sim.outputs)

    def test_a_contact_the_player_found_is_recorded_as_a_call(self):
        scene, a, b = self.scene_with_cubes()
        b.location = (1.5, 0, 0)
        bpy.context.view_layer.update()
        player = self.bp.Player(scene, activity=True, record=True)
        player.start(0.0)
        player.step(0.1)
        calls = [c for c in player.activity.stimulus if c["call"] == "contact"]
        self.assertTrue(calls and calls[-1]["args"]["active"] is True)


if __name__ == "__main__":
    unittest.main()
