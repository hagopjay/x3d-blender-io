# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The piano demo's Play changes, in Blender without a window: Blender key events as a browser would name them, a
KeySensor and a StringSensor driven through ``Player.key_event``, and Stop putting everything back
(source/behaviour_play.py; the demo is tests/behaviour/demos/piano). The modal operator needs a window: the eye test
(``python tools/behaviour_demo.py show piano``) types through Blender's event queue.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_behaviour_demo_piano_bpy
"""

from __future__ import annotations

import importlib
import sys
import tempfile
import types
import unittest
from pathlib import Path

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

from test_roundtrip_bpy import _register_extension, SOURCE_DIR

sys.path.insert(0, str(SOURCE_DIR))
PIANO = Path(__file__).resolve().parent / "behaviour" / "demos" / "piano" / "piano.x3d"


def key(kind, value="PRESS", unicode="", shift=False):
    """What Blender's modal handler is given for a key."""
    return types.SimpleNamespace(type=kind, value=value, unicode=unicode, shift=shift)


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class PianoPlayTests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="x3d_piano_play_")
        _register_extension(self.tmpdir)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.bn = importlib.import_module("io_scene_x3d.behaviour_nodes")
        self.bp = importlib.import_module("io_scene_x3d.behaviour_play")
        self.bn.ensure_registered()
        bpy.ops.import_scene.x3d(filepath=str(PIANO), use_behaviour_graph=True)
        self.scene = bpy.context.scene
        self.player = self.bp.Player(self.scene)
        self.player.start(0.0)
        self.t = 0.0

    def obj(self, def_name):
        """An object by its DEF (never by type)."""
        found = [o for o in self.scene.objects if o.get("x3d_def") == def_name]
        return (found or [self.scene.objects[def_name]])[0]

    def shown(self, def_name):
        o = self.obj(def_name)
        return not (o.hide_viewport or o.hide_get())

    def tap(self, event, held=0.05):
        """A key down, ``held`` seconds, up, then time moves on."""
        self.t += 0.1
        self.assertTrue(self.player.key_event(event, self.t))
        self.player.step(self.t + held)
        release = key(event.type, "RELEASE")
        self.assertTrue(self.player.key_event(release, self.t + held))
        self.t += held
        self.player.step(self.t)

    def click_sheet(self):
        self.t += 0.1
        self.assertTrue(self.player.press(self.obj("Sheet"), self.t))
        self.player.release(self.t + 0.05)
        self.t += 0.1
        self.player.step(self.t)

    def type_text(self, text):
        for char in text:
            self.tap(key(char.upper(), unicode=char, shift=char.isupper()))

    # -- Blender's keys, named as a browser names them ----------------------------------------------------------------

    def test_blender_keys_are_named_as_a_browser_names_them(self):
        named = self.bp.x3d_key
        self.assertEqual(named(key("A", unicode="a")), ("a", 65))
        self.assertEqual(named(key("A", unicode="A", shift=True)), ("A", 65))
        self.assertEqual(named(key("A", unicode="", shift=True)), ("A", 65))          # no text: from the key's name
        self.assertEqual(named(key("SEVEN", unicode="7")), ("7", 55))
        self.assertEqual(named(key("SPACE", unicode=" ")), (" ", 32))
        self.assertEqual(named(key("RET")), ("Enter", 13))
        self.assertEqual(named(key("BACK_SPACE")), ("Backspace", 8))
        self.assertEqual(named(key("LEFT_SHIFT")), ("Shift", 16))
        self.assertEqual(named(key("RIGHT_CTRL")), ("Control", 17))
        self.assertEqual(named(key("LEFT_ALT")), ("Alt", 18))
        self.assertEqual(named(key("UP_ARROW")), ("ArrowUp", 38))
        self.assertEqual(named(key("F2")), ("F2", 113))
        self.assertEqual(named(key("F12")), ("F12", 123))
        self.assertIsNone(named(key("OSKEY")))                                         # no name in X3D
        self.assertIsNone(named(key("LEFTMOUSE")))

    def test_only_keys_are_keyboard_events(self):
        self.assertTrue(self.bp.is_keyboard(key("A")))
        self.assertTrue(self.bp.is_keyboard(key("UP_ARROW", "RELEASE")))
        for kind in ("MOUSEMOVE", "LEFTMOUSE", "WHEELUPMOUSE", "TIMER", "NDOF_BUTTON_MENU", "INBETWEEN_MOUSEMOVE"):
            self.assertFalse(self.bp.is_keyboard(key(kind)), kind)
        self.assertFalse(self.bp.is_keyboard(key("A", "NOTHING")))

    def test_a_release_comes_up_as_the_key_that_went_down(self):
        self.t = 0.1
        self.assertTrue(self.player.key_event(key("A", unicode="A", shift=True), self.t))
        self.assertTrue(self.player.key_event(key("A", "RELEASE", shift=False), self.t + 0.05))   # Shift is up by now
        keys = [e for e in self.player.sim.log if e[1] == "Keys" and e[2] in ("keyPress", "keyRelease")]
        self.assertEqual([(field, value) for _t, _n, field, value in keys], [("keyPress", "A"), ("keyRelease", "A")])
        self.assertFalse(self.player.key_event(key("B", "RELEASE"), self.t + 0.1))                # never went down

    # -- the keyboard mode: hammer, lamp, pedals --------------------------------------------------------------------

    def test_any_key_strikes_the_hammer_and_flashes_the_lamp_then_it_rests(self):
        self.assertTrue(self.player.has_keys())
        hammer = self.obj("Hammer")
        rest = hammer.matrix_basis.translation.copy()
        self.tap(key("A", unicode="a"))
        lowest = 0.0
        for step in range(1, 10):                                  # the 0.25 s clock, in 0.03 s steps
            self.player.step(self.t + 0.03 * step)
            lowest = max(lowest, (hammer.matrix_basis.translation - rest).length)
        self.assertGreater(lowest, 0.05)
        self.player.step(self.t + 0.6)
        self.assertLess((hammer.matrix_basis.translation - rest).length, 1e-4)
        self.assertEqual(self.player.not_applied, [])

    def test_the_modifiers_light_their_pedal_while_held(self):
        pedals = {"LEFT_SHIFT": "SoftGlow", "LEFT_CTRL": "SustainGlow", "LEFT_ALT": "SostGlow"}
        self.assertFalse(any(self.shown(p) for p in pedals.values()))
        for kind, pedal in pedals.items():
            self.t += 0.1
            self.player.key_event(key(kind), self.t)
            self.assertEqual({p: self.shown(p) for p in pedals.values()}, {p: p == pedal for p in pedals.values()})
            self.player.key_event(key(kind, "RELEASE"), self.t + 0.05)
            self.assertFalse(any(self.shown(p) for p in pedals.values()))

    def test_an_arrow_and_an_f_key_send_their_code_down_the_integer_chain(self):
        self.tap(key("UP_ARROW"))
        self.assertEqual(self.player.sim.outputs[("ActionCode", "triggerValue")], 17)
        self.tap(key("F2"))
        self.assertEqual(self.player.sim.outputs[("ActionCode", "triggerValue")], 2)

    # -- the typing mode: only one key device sensor listens ---------------------------------------------------------

    def test_typing_waits_for_a_click_on_the_sheet_and_enter_gives_the_keyboard_back(self):
        sim = self.player.sim
        self.type_text("no")                                       # the KeySensor has the keyboard: nothing is typed
        self.assertNotIn(("Typed", "enteredText"), sim.outputs)
        self.assertEqual(self.player.typed(), {"Typed": {}})
        self.click_sheet()
        self.assertTrue(sim.machines["Typed"].listening)
        self.assertFalse(sim.machines["Keys"].listening)
        self.assertEqual([self.shown("KeysLight"), self.shown("TypeLight")], [False, True])
        self.type_text("Hi Pianos")
        self.assertEqual(sim.outputs[("Typed", "enteredText")], "Hi Pianos")
        self.tap(key("BACK_SPACE"))
        self.assertEqual(sim.outputs[("Typed", "enteredText")], "Hi Piano")
        self.assertEqual(self.player.typed_lines(), ["Typed: Hi Piano"])
        self.tap(key("RET"))
        self.assertEqual(sim.outputs[("Typed", "finalText")], "Hi Piano")
        self.assertTrue(sim.machines["Keys"].listening)
        self.assertEqual([self.shown("KeysLight"), self.shown("TypeLight")], [True, False])
        self.assertEqual(self.player.typed_lines(), ["Typed: Hi Piano   (entered: Hi Piano)"])
        before = len([e for e in sim.log if e[1] == "Keys" and e[2] == "isActive"])
        self.tap(key("Z", unicode="z"))                            # the keys work again
        self.assertGreater(len([e for e in sim.log if e[1] == "Keys" and e[2] == "isActive"]), before)

    def test_the_lever_forbids_backspace(self):
        sim = self.player.sim
        self.click_sheet()
        self.type_text("ab")
        self.assertTrue(self.player.press(self.obj("Lever"), self.t + 0.1))      # allowed -> forbidden
        self.player.release(self.t + 0.15)
        self.assertFalse(self.shown("AllowedLight"))
        self.tap(key("BACK_SPACE"))
        self.assertEqual(sim.outputs[("Typed", "enteredText")], "ab")
        self.assertTrue(self.player.press(self.obj("Lever"), self.t + 0.5))      # forbidden -> allowed
        self.player.release(self.t + 0.55)
        self.tap(key("BACK_SPACE"))
        self.assertEqual(sim.outputs[("Typed", "enteredText")], "a")

    def test_stop_puts_everything_back_after_typing(self):
        hammer = self.obj("Hammer")
        rest = hammer.matrix_basis.translation.copy()
        lit = [self.shown(p) for p in ("SoftGlow", "KeysLight", "TypeLight", "AllowedLight")]
        self.tap(key("LEFT_SHIFT"))
        self.click_sheet()
        self.type_text("go")
        self.tap(key("RET"))
        self.player.step(self.t + 0.1)
        self.player.stop()
        self.assertEqual((hammer.matrix_basis.translation - rest).length, 0.0)
        self.assertEqual([self.shown(p) for p in ("SoftGlow", "KeysLight", "TypeLight", "AllowedLight")], lit)
        self.assertEqual(self.player._down, {})

    def test_a_graph_without_key_sensors_leaves_the_keyboard_alone(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.bn.ensure_registered()
        bpy.ops.import_scene.x3d(filepath=str(PIANO.parents[2] / "door.x3d"), use_behaviour_graph=True)
        self.assertFalse(self.bp.Player(bpy.context.scene).has_keys())


if __name__ == "__main__":
    unittest.main()
