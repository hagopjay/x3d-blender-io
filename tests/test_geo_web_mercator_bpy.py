# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Importer: the Geospatial component's "WM" (Web Mercator) geoSystem.

X3D 4.0 lists four spatial reference frames: GD, GC, UTM and WM (Web Mercator, x and y in metres from 0 N 0 E on
WGS 84, then the elevation). X_ITE 16.7.1 does not know WM and reads such a node as GD, so a grid at x 1113194.9 and
y 1118889.97 ended up at latitude 1.1e6 degrees. The expected values here come from PROJ 9.8.1 (EPSG:3857 to
EPSG:4978) and from the textbook sinh form of the inverse, not from the module under test.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_geo_web_mercator_bpy
"""

from __future__ import annotations

import math
import os
import sys
import tempfile
import unittest

import numpy as np

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

from test_roundtrip_bpy import _register_extension, SOURCE_DIR
from test_import_geoelevationgrid_bpy import WGS_A, Y_UP_TO_Z_UP, analytic, grid, scene

sys.path.insert(0, str(SOURCE_DIR))
import geospatial  # noqa: E402

TEN_TEN = (1113194.9079327357, 1118889.974857959)   # 10 E 10 N in EPSG:3857, metres


class WebMercatorMathTests(unittest.TestCase):
    def test_wm_is_its_own_system_on_wgs84_with_x_first(self):
        gs = geospatial.parse_geo_system(["WM"])
        self.assertEqual((gs.kind, gs.a, gs.standard_order), ("WM", WGS_A, False))
        self.assertEqual(geospatial.parse_geo_system(["WM", "IN"]).a, WGS_A)   # the spec fixes WM to WGS 84

    def test_proj_gives_the_same_geocentric_point(self):
        gs = geospatial.parse_geo_system(["WM"])
        got = np.array([float(v) for v in geospatial.to_geocentric(gs, *TEN_TEN, 500.0)])
        proj = np.array((6186921.989185415, 1090921.2742318744, 1100335.3718241947))   # EPSG:3857 to EPSG:4978
        self.assertLess(np.abs(got - proj).max(), 1e-3)

    def test_the_textbook_inverse(self):
        gs = geospatial.parse_geo_system(["WM"])
        for x, y, h in ((0.0, 0.0, 0.0), (-20037508.342789244, 0.0, 0.0), (2e6, -5e6, 250.0), (0.0, 7e6, 0.0)):
            lat, lon = math.degrees(math.atan(math.sinh(y / WGS_A))), math.degrees(x / WGS_A)
            got = np.array([float(v) for v in geospatial.to_geocentric(gs, x, y, h)])
            self.assertLess(np.abs(got - analytic(lat, lon, h)).max(), 1e-3, (x, y, h))


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class WebMercatorImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="x3d_geo_wm_")
        _register_extension(cls.tmpdir)

    def load(self, text):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        path = os.path.join(self.tmpdir, "wm.x3d")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=path), {"FINISHED"})
        return [o for o in bpy.context.scene.objects]

    def test_a_wm_grid_steps_east_and_north_in_metres(self):
        origin = "geoGridOrigin='%.9f %.9f 0'" % TEN_TEN
        ob = next(o for o in self.load(scene(grid("geoSystem='\"WM\"' %s xDimension='2' zDimension='2' "
                                                  "xSpacing='1000' zSpacing='1000'" % origin))) if o.type == "MESH")
        co = np.empty(12, dtype=np.float32)
        ob.data.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3).astype(np.float64)
        gs = geospatial.parse_geo_system(["WM"])
        for k, (dx, dy) in enumerate(((0, 0), (1000, 0), (0, 1000), (1000, 1000))):   # vertex z * 2 + x
            want = np.array([float(v) for v in geospatial.to_geocentric(gs, TEN_TEN[0] + dx, TEN_TEN[1] + dy, 0.0)])
            self.assertLess(np.abs(co[k] - want).max(), 0.3, k)
        self.assertLess(np.abs(co[0] - analytic(10, 10)).max(), 0.3)

    def test_a_wm_geo_viewpoint_is_placed_by_its_web_mercator_position(self):
        camera = next(o for o in self.load(scene("<GeoViewpoint geoSystem='\"WM\"' position='%.9f %.9f 500'/>"
                                                 % TEN_TEN)) if o.type == "CAMERA")
        expected = np.array(Y_UP_TO_Z_UP, dtype=float) @ analytic(10, 10, 500.0)
        self.assertLess(np.abs(np.array(camera.matrix_world.translation) - expected).max(), 1.0)


if __name__ == "__main__":
    unittest.main()
