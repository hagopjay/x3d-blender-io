# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A scene imported from X3D with interpolators keeps its animation in the X3D 4.0/4.1 export (Animation AUTO).

``use_animation`` stays off by default, so a scene built in Blender exports as before; the importer marks a scene whose
import made animation (``x3d_imported_animation``) and the export operator then turns the option on unless it was set by
hand.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_export_imported_animation_bpy
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

ANIMATED = """<?xml version='1.0' encoding='UTF-8'?>
<X3D profile='Immersive' version='4.0'><Scene>
<Viewpoint position='0 0 10'/>
<TimeSensor DEF='Clock' cycleInterval='2' loop='true'/>
<PositionInterpolator DEF='Move' key='0 0.5 1' keyValue='0 0 0 1 0 0 2 0 0'/>
<Transform DEF='Ball'><Shape><Box/></Shape></Transform>
<ROUTE fromNode='Clock' fromField='fraction_changed' toNode='Move' toField='set_fraction'/>
<ROUTE fromNode='Move' fromField='value_changed' toNode='Ball' toField='set_translation'/>
</Scene></X3D>
"""
STILL = ANIMATED.split("<TimeSensor")[0] + "<Transform DEF='Ball'><Shape><Box/></Shape></Transform></Scene></X3D>\n"


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class ImportedAnimationExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="x3d_anim_auto_")
        _register_extension(cls.tmpdir)

    def _import(self, name, text):
        import bpy
        bpy.ops.wm.read_factory_settings(use_empty=True)
        path = os.path.join(self.tmpdir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=path), {"FINISHED"})

    def _export(self, name, **kwargs):
        import bpy
        out = os.path.join(self.tmpdir, name)
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=out, x3d_version="X3D40", use_selection=False, **kwargs),
                         {"FINISHED"})
        with open(out, encoding="utf-8") as f:
            return f.read()

    def test_imported_animation_is_kept_by_default(self):
        import bpy
        self._import("a.x3d", ANIMATED)
        self.assertTrue(bpy.context.scene.get("x3d_imported_animation"))
        text = self._export("a_out.x3d")
        self.assertIn("<TimeSensor", text)
        self.assertIn("<PositionInterpolator", text)
        self.assertIn("<ROUTE", text)

    def test_animation_set_off_by_hand_is_respected(self):
        self._import("b.x3d", ANIMATED)
        text = self._export("b_out.x3d", use_animation=False)
        self.assertNotIn("<TimeSensor", text)

    def test_a_still_import_has_no_marker_and_exports_no_animation(self):
        import bpy
        self._import("c.x3d", STILL)
        self.assertNotIn("x3d_imported_animation", bpy.context.scene.keys())
        self.assertNotIn("<TimeSensor", self._export("c_out.x3d"))

    def test_a_scene_built_in_blender_is_unchanged(self):
        import bpy
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.mesh.primitive_cube_add()
        ob = bpy.context.object
        ob.keyframe_insert("location", frame=1)
        ob.location.x = 3
        ob.keyframe_insert("location", frame=24)
        self.assertNotIn("<TimeSensor", self._export("d_out.x3d"))
        self.assertIn("<TimeSensor", self._export("d_out2.x3d", use_animation=True))

    def test_the_option_is_not_remembered_between_exports(self):
        # review round 1 (importer F4): invoke turns Animation on for a scene imported with animation; a remembered value
        # would come back ticked on the next export of any scene (the dialog cannot be driven in a background Blender,
        # so this checks the flag Blender reads when it stores and restores an operator's last-used properties)
        import bpy
        prop = bpy.ops.export_scene.x3d.get_rna_type().properties["use_animation"]
        self.assertTrue(prop.is_skip_save)
        self.assertFalse(prop.default)


if __name__ == "__main__":
    unittest.main()
