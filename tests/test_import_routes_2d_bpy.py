# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Importer regressions: ROUTE animation with several objects under one animated
Transform, and the Geometry2D Rectangle2D and Disk2D nodes.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_import_routes_2d_bpy
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


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class ImportRoutesAnd2DTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="x3d_routes2d_")
        _register_extension(cls.tmpdir)

    def _import(self, name: str, body: str):
        import bpy
        bpy.ops.wm.read_factory_settings(use_empty=True)
        path = os.path.join(self.tmpdir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(HEADER + body + FOOTER)
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=path), {"FINISHED"})
        return {o.name: o for o in bpy.context.scene.objects}

    def test_route_animates_every_object_under_one_transform(self):
        # Two shapes under the animated Transform: the second used to raise
        # UnboundLocalError (the TimeSensor's loop flag was deleted per object).
        # A second animated Transform after it must still be keyed, and the scene's
        # end frame must reach the 20 s clock (both are skipped if the import stops).
        import bpy
        objs = self._import("two_under_one.x3d", """
<TimeSensor DEF='Clock' cycleInterval='20' loop='true'/>
<OrientationInterpolator DEF='Turn' key='0 0.5 1' keyValue='0 1 0 0, 0 1 0 3.14159, 0 1 0 6.28318'/>
<PositionInterpolator DEF='Slide' key='0 1' keyValue='0 0 -3, 0 2 -3'/>
<Transform DEF='Spinner'>
  <Shape DEF='First'><Box size='1 1 1'/></Shape>
  <Transform translation='2 0 0'><Shape DEF='Second'><Sphere radius='0.5'/></Shape></Transform>
</Transform>
<Transform DEF='Mover'><Shape DEF='Third'><Cone/></Shape></Transform>
<ROUTE fromNode='Clock' fromField='fraction_changed' toNode='Turn' toField='set_fraction'/>
<ROUTE fromNode='Turn' fromField='value_changed' toNode='Spinner' toField='set_rotation'/>
<ROUTE fromNode='Clock' fromField='fraction_changed' toNode='Slide' toField='set_fraction'/>
<ROUTE fromNode='Slide' fromField='value_changed' toNode='Mover' toField='set_translation'/>
""")
        meshes = [o for o in objs.values() if o.type == "MESH"]
        self.assertEqual(len(meshes), 3)
        for o in meshes:
            self.assertIsNotNone(o.animation_data, o.name)
            self.assertIsNotNone(o.animation_data.action, o.name)
        self.assertGreaterEqual(bpy.context.scene.frame_end, 20 * 24)

    def test_rectangle2d(self):
        objs = self._import("rect.x3d", "<Shape DEF='Card'><Rectangle2D size='2 1'/></Shape>\n")
        meshes = [o for o in objs.values() if o.type == "MESH"]
        self.assertEqual(len(meshes), 1)
        me = meshes[0].data
        self.assertEqual((len(me.vertices), len(me.polygons)), (4, 1))
        xs = sorted({round(v.co.x, 5) for v in me.vertices}); ys = sorted({round(v.co.y, 5) for v in me.vertices})
        self.assertEqual((xs, ys), ([-1.0, 1.0], [-0.5, 0.5]))
        self.assertTrue(all(abs(v.co.z) < 1e-9 for v in me.vertices))
        self.assertEqual(len(me.uv_layers), 1)

    def test_disk2d_disc_and_annulus(self):
        objs = self._import("disks.x3d", """
<Shape DEF='Disc'><Disk2D outerRadius='1.5'/></Shape>
<Transform translation='4 0 0'><Shape DEF='Ring'><Disk2D innerRadius='0.5' outerRadius='1'/></Shape></Transform>
""")
        meshes = sorted((o for o in objs.values() if o.type == "MESH"), key=lambda o: len(o.data.polygons))
        self.assertEqual(len(meshes), 2)
        disc, ring = meshes
        self.assertEqual(len(disc.data.polygons), 1)
        self.assertAlmostEqual(max(v.co.length for v in disc.data.vertices), 1.5, places=5)
        n = len(ring.data.polygons)
        self.assertGreaterEqual(n, 8)
        radii = sorted({round(v.co.length, 5) for v in ring.data.vertices})
        self.assertEqual(radii, [0.5, 1.0])


if __name__ == "__main__":
    unittest.main()
