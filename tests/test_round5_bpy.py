# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Controls for the round-5 outside review (18 Nov 2026): BooleanFilter output edge, disabled tour timer.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_round5_bpy
"""

from __future__ import annotations

import json
import os
import re
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

VIEW = """<X3D version="4.0" profile="Immersive"><Scene>
<Viewpoint DEF="CA_Home" description="Home"/>
<Transform DEF="Handle"><TouchSensor DEF="Touch" description="viewpoint Home"/><Shape><Sphere/></Shape></Transform>
<BooleanFilter DEF="BF"/>
<ROUTE fromNode="Touch" fromField="isActive" toNode="BF" toField="set_boolean"/>
<ROUTE fromNode="BF" fromField="OUTFIELD" toNode="CA_Home" toField="set_bind"/>
</Scene></X3D>"""


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class Round5Tests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="x3d_round5_")
        _register_extension(self.tmpdir)
        sys.path.insert(0, str(SOURCE_DIR))
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def _export(self, path, **kw):
        return bpy.ops.export_scene.x3d(filepath=str(path), x3d_version="X3D40", use_selection=False, **kw)

    def _import(self, path, strict):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        if strict:
            os.environ["X3D_IMPORT_STRICT"] = "1"
        try:
            return bpy.ops.import_scene.x3d(filepath=str(path))
        finally:
            os.environ.pop("X3D_IMPORT_STRICT", None)

    def _losses(self):
        raw = bpy.context.scene.get("x3d_import_losses")
        return json.loads(raw) if raw else []

    # 6: only the true edge of a BooleanFilter is the exporter's press-to-bind pattern
    def test_input_true_click_to_viewpoint_stays_lossless(self):
        path = Path(self.tmpdir) / "true.x3d"
        path.write_text(VIEW.replace("OUTFIELD", "inputTrue"), encoding="utf-8")
        self._import(path, strict=True)
        self.assertEqual(self._losses(), [])
        self.assertEqual(bpy.data.objects["Handle"]["x3d_action"], "viewpoint")

    def test_other_boolean_filter_edges_are_not_imported_as_input_true(self):
        for field in ("inputNegate", "inputFalse"):
            path = Path(self.tmpdir) / f"{field}.x3d"
            path.write_text(VIEW.replace("OUTFIELD", field), encoding="utf-8")
            with self.assertRaises(Exception, msg=field):
                self._import(path, strict=True)
            self._import(path, strict=False)
            self.assertTrue(any(field in r["node"] for r in self._losses()), (field, self._losses()))
            self.assertNotIn("x3d_trigger", bpy.data.objects["Handle"])

    # 7: a tour timer that is disabled (or carries other fields) is not the properties' tour
    def _tour_file(self):
        from mathutils import Vector
        scene = bpy.context.scene
        scene.frame_start, scene.frame_end = 1, 25
        scene["x3d_tour_travel"] = 2
        for index, (name, target) in enumerate([("A", (0, 0, 0)), ("B", (5, 0, 0))], start=1):
            cam = bpy.data.objects.new(name, bpy.data.cameras.new(name))
            scene.collection.objects.link(cam)
            cam.location = (0, -5, 2)
            cam.rotation_euler = (Vector(target) - cam.location).to_track_quat("-Z", "Y").to_euler()
            cam["x3d_tour_order"], cam["x3d_tour_dwell"] = index, index
        bpy.ops.mesh.primitive_cube_add()
        button = bpy.context.object
        button.name = "TourButton"
        button["x3d_trigger"], button["x3d_action"] = "click", "tour"
        path = Path(self.tmpdir) / "tour.x3d"
        self.assertEqual(self._export(path, use_animation=True), {"FINISHED"})
        return path

    def test_own_exported_tour_is_lossless(self):
        self._import(self._tour_file(), strict=True)
        self.assertEqual(self._losses(), [])

    def test_disabled_tour_timer_is_a_loss(self):
        path = self._tour_file()
        text = path.read_text(encoding="utf-8")
        edited, count = re.subn(r'(<TimeSensor DEF="TourTimer")', r'\1 enabled="false"', text)
        self.assertEqual(count, 1)
        path.write_text(edited, encoding="utf-8")
        with self.assertRaises(Exception):
            self._import(path, strict=True)
        self._import(path, strict=False)
        self.assertTrue(any("enabled" in f"{r['node']} {r['detail']}" for r in self._losses()), self._losses())


if __name__ == "__main__":
    unittest.main()
