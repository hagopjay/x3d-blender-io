# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Importer: an X3D Switch shows only the child its whichChoice names.

Every child is still imported (so the file round-trips), but the ones not chosen
are hidden in the viewport and the render and tagged ``x3d_switch_hidden``.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_import_switch_bpy
"""

from __future__ import annotations

import os
import tempfile
import unittest

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

from test_roundtrip_bpy import _register_extension

HEADER = ("<?xml version='1.0' encoding='UTF-8'?>\n"
          "<X3D profile='Immersive' version='4.0'><Scene>\n")
FOOTER = "</Scene></X3D>\n"


def _shape(name: str) -> str:
    return f"<Shape DEF='{name}'><Box size='1 1 1'/></Shape>"


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class ImportSwitchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="x3d_switch_")
        _register_extension(cls.tmpdir)

    def _import(self, name: str, body: str):
        import bpy
        bpy.ops.wm.read_factory_settings(use_empty=True)
        path = os.path.join(self.tmpdir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(HEADER + body + FOOTER)
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=path), {"FINISHED"})
        return {o.name: o for o in bpy.context.scene.objects}

    def assertShown(self, ob):
        self.assertFalse(ob.hide_render, ob.name)
        self.assertTrue(ob.visible_get(), ob.name)
        self.assertNotIn("x3d_switch_hidden", ob.keys(), ob.name)

    def assertHidden(self, ob):
        self.assertTrue(ob.hide_render, ob.name)
        self.assertFalse(ob.visible_get(), ob.name)
        self.assertTrue(ob.get("x3d_switch_hidden"), ob.name)

    def test_which_choice_shows_one_child(self):
        objs = self._import("pick.x3d", f"""
<Switch whichChoice='1'>{_shape('A')}{_shape('B')}{_shape('C')}</Switch>
{_shape('Outside')}
""")
        self.assertHidden(objs["A"]); self.assertShown(objs["B"]); self.assertHidden(objs["C"])
        self.assertShown(objs["Outside"])

    def test_no_choice_hides_every_child(self):
        objs = self._import("none.x3d", f"""
<Switch>{_shape('D0')}{_shape('D1')}</Switch>
<Switch whichChoice='5'>{_shape('E0')}</Switch>
""")
        for n in ("D0", "D1", "E0"):
            self.assertHidden(objs[n])

    def test_nested_switches_and_groups(self):
        objs = self._import("nested.x3d", f"""
<Switch whichChoice='0'>
  <Group><Switch whichChoice='1'>{_shape('P')}<Transform translation='2 0 0'>{_shape('Q')}</Transform></Switch></Group>
  {_shape('R')}
</Switch>
""")
        self.assertHidden(objs["P"]); self.assertShown(objs["Q"]); self.assertHidden(objs["R"])

    def test_metadata_and_route_are_not_children(self):
        objs = self._import("meta.x3d", f"""
<Switch whichChoice='0'>
  <MetadataString containerField='metadata' name='note' value='"first child follows"'/>
  {_shape('M0')}{_shape('M1')}
</Switch>
""")
        self.assertShown(objs["M0"]); self.assertHidden(objs["M1"])

    def test_light_and_viewpoint_on_a_hidden_branch(self):
        objs = self._import("lights.x3d", """
<Switch whichChoice='0'>
  <Group/>
  <Group><PointLight DEF='Lamp' location='0 2 0'/><Viewpoint DEF='Look' position='0 0 5'/></Group>
</Switch>
""")
        lamps = [o for o in objs.values() if o.type == "LIGHT"]
        cams = [o for o in objs.values() if o.type == "CAMERA"]
        self.assertEqual((len(lamps), len(cams)), (1, 1))
        self.assertHidden(lamps[0]); self.assertHidden(cams[0])

    def test_use_of_a_switch_and_of_a_hidden_shape(self):
        # Each instance gets its own object; a hidden child stays hidden in every instance of its Switch, and a
        # Shape USE'd outside any Switch is shown even though its DEF sits on a hidden branch.
        objs = self._import("use.x3d", f"""
<Switch DEF='S' whichChoice='0'>{_shape('U0')}{_shape('U1')}</Switch>
<Transform translation='3 0 0'><Switch USE='S'/></Transform>
<Transform translation='6 0 0'><Shape USE='U1'/></Transform>
""")
        meshes = [o for o in objs.values() if o.type == "MESH"]
        self.assertEqual(len(meshes), 5)
        shown = sorted(round(o.matrix_world.translation.x) for o in meshes if not o.hide_render)
        hidden = sorted(round(o.matrix_world.translation.x) for o in meshes if o.hide_render)
        self.assertEqual(shown, [0, 3, 6])     # U0 twice, and the U1 outside the Switch
        self.assertEqual(hidden, [0, 3])       # U1 in both instances of the Switch


if __name__ == "__main__":
    unittest.main()
