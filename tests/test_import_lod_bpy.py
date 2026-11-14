# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Importer: an X3D LOD shows only the level the first Viewpoint selects, as X_ITE 16.7.1 does.

Every level is still imported (so the file round-trips), but the levels not chosen are hidden in the viewport and the
render and tagged ``x3d_lod_hidden``. X_ITE's LOD.js getLevel: the distance between the viewer and the centre in the world
(``range`` is not scaled by the Transforms above), then the first ``range`` entry above it.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_import_lod_bpy
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
class ImportLodTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="x3d_lod_")
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
        self.assertNotIn("x3d_lod_hidden", ob.keys(), ob.name)

    def assertHidden(self, ob, level):
        self.assertTrue(ob.hide_render, ob.name)
        self.assertFalse(ob.visible_get(), ob.name)
        self.assertEqual(ob.get("x3d_lod_hidden"), level, ob.name)

    def test_near_viewer_sees_level_zero(self):
        objs = self._import("near.x3d", f"""
<Viewpoint position='0 0 3'/>
<LOD range='5 20'>{_shape('L0')}{_shape('L1')}{_shape('L2')}</LOD>
""")
        self.assertShown(objs["L0"]); self.assertHidden(objs["L1"], 1); self.assertHidden(objs["L2"], 2)

    def test_distance_picks_the_range_slot(self):
        objs = self._import("mid.x3d", f"""
<Viewpoint position='0 0 10'/>
<LOD range='5 20'>{_shape('L0')}{_shape('L1')}{_shape('L2')}</LOD>
""")
        self.assertHidden(objs["L0"], 0); self.assertShown(objs["L1"]); self.assertHidden(objs["L2"], 2)

    def test_far_viewer_and_a_short_range_list_use_the_last_level(self):
        objs = self._import("far.x3d", f"""
<Viewpoint position='0 0 100'/>
<LOD range='5 20'>{_shape('L0')}{_shape('L1')}{_shape('L2')}</LOD>
<LOD range='5'>{_shape('M0')}{_shape('M1')}{_shape('M2')}</LOD>
""")
        self.assertShown(objs["L2"])
        self.assertHidden(objs["L0"], 0); self.assertHidden(objs["L1"], 1)
        # one range entry, three children: X_ITE takes min(upperBound, last child) = 1
        self.assertShown(objs["M1"]); self.assertHidden(objs["M0"], 0)

    def test_the_viewpoint_after_the_lod_still_decides(self):
        objs = self._import("late.x3d", f"""
<LOD range='5'>{_shape('A')}{_shape('B')}</LOD>
<Viewpoint position='0 0 3'/>
""")
        self.assertShown(objs["A"]); self.assertHidden(objs["B"], 1)

    def test_range_is_not_scaled_by_the_transform_above(self):
        # the Showcase's lod-scaled: X_ITE measures 10 units to the centre and compares it with range 1000 as written
        objs = self._import("scaled.x3d", f"""
<Viewpoint position='0 0 10'/>
<Transform scale='0.001 0.001 0.001'><LOD range='1000'>{_shape('A')}{_shape('B')}</LOD></Transform>
""")
        self.assertShown(objs["A"]); self.assertHidden(objs["B"], 1)

    def test_center_and_transform_move_the_measuring_point(self):
        objs = self._import("centre.x3d", f"""
<Viewpoint position='0 0 10'/>
<Transform translation='0 0 8'><LOD range='5' center='0 0 -1'>{_shape('A')}{_shape('B')}</LOD></Transform>
""")
        # centre at z = 7, viewer at z = 10: distance 3 < 5
        self.assertShown(objs["A"]); self.assertHidden(objs["B"], 1)

    def test_no_range_shows_the_first_level(self):
        objs = self._import("norange.x3d", f"<LOD>{_shape('A')}{_shape('B')}{_shape('C')}</LOD>")
        self.assertShown(objs["A"]); self.assertHidden(objs["B"], 1); self.assertHidden(objs["C"], 2)

    def test_nested_groups_and_transforms_hide_with_their_level(self):
        objs = self._import("nested.x3d", f"""
<Viewpoint position='0 0 10'/>
<LOD range='5'>
  <Transform DEF='T0'>{_shape('A')}</Transform>
  <Transform DEF='T1'><Group>{_shape('B')}</Group></Transform>
</LOD>
""")
        self.assertHidden(objs["A"], 0); self.assertShown(objs["B"])

    def test_a_lod_outside_a_lod_is_untouched(self):
        objs = self._import("plain.x3d", f"""
<Viewpoint position='0 0 10'/>
<LOD range='5'>{_shape('A')}{_shape('B')}</LOD>
{_shape('Outside')}
""")
        self.assertShown(objs["Outside"])

    def test_the_export_does_not_draw_the_hidden_levels_on_top(self):
        import bpy
        self._import("rt.x3d", f"""
<Viewpoint position='0 0 10'/>
<LOD range='5'>{_shape('A')}{_shape('B')}</LOD>
""")
        out = os.path.join(self.tmpdir, "rt_out.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=out, x3d_version="X3D40", use_selection=False), {"FINISHED"})
        text = open(out, encoding="utf-8").read()
        self.assertEqual(text.count("<Shape"), 1, text)
        self.assertNotIn("DEF='A'", text)     # level 0 is the hidden one at distance 10 > range 5
        # unhiding a level brings it back into the export
        bpy.data.objects["A"].hide_render = False
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=out, x3d_version="X3D40", use_selection=False), {"FINISHED"})
        self.assertEqual(open(out, encoding="utf-8").read().count("<Shape"), 2)

    def test_the_x3d_33_export_does_not_draw_the_hidden_levels_either(self):
        # review round 1 (emitter F5): only the 4.0 writer skipped them
        import bpy
        self._import("rt33.x3d", f"""
<Viewpoint position='0 0 10'/>
<LOD range='5'>{_shape('A')}{_shape('B')}</LOD>
""")
        out = os.path.join(self.tmpdir, "rt33_out.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=out, x3d_version="X3D33", use_selection=False), {"FINISHED"})
        text = open(out, encoding="utf-8").read()
        self.assertEqual(text.count("<Shape"), 1, text)
        bpy.data.objects["A"].hide_render = False
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=out, x3d_version="X3D33", use_selection=False), {"FINISHED"})
        self.assertEqual(open(out, encoding="utf-8").read().count("<Shape"), 2)

    def test_geolod_root_node_content_stays_shown(self):
        # the child URLs are not imported, so a GeoLOD's rootNode is the only content: shown near and far
        for name, position in (("geo_far.x3d", "0 0 100"), ("geo_near.x3d", "0 0 0")):
            objs = self._import(name, f"""
<Viewpoint position='{position}'/>
<GeoLOD geoSystem='"GD" "WE"' center='0 0 0' range='10' child1Url='"a.x3d"' child2Url='"b.x3d"' child3Url='"c.x3d"' child4Url='"d.x3d"'>
  <Shape containerField='rootNode' DEF='Root'><Box size='1 1 1'/></Shape>
</GeoLOD>
""")
            self.assertShown(objs["Root"])


if __name__ == "__main__":
    unittest.main()
