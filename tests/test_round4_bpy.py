# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Controls for the round-4 outside review (18 Nov 2026): timer fields, event-field identity, scaled proximity boxes.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_round4_bpy
"""

from __future__ import annotations

import json
import os
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

DOC = """<X3D version="4.0" profile="Immersive"><Scene>
<Viewpoint DEF="CA_Home" description="Home"/>
<Transform DEF="Door"><Shape><Appearance><Material/></Appearance><Box/></Shape></Transform>
<Transform DEF="Handle" SCALE_ATTR>{SENSOR}<Shape><Sphere/></Shape></Transform>
<TimeSensor DEF="TT" cycleInterval="2" TIMER_ATTRS/>
<PositionInterpolator DEF="Slide" key="0 1" keyValue="0 0 0 2 0 0"/>
{ROUTES}
<ROUTE fromNode="TT" fromField="fraction_changed" toNode="Slide" toField="set_fraction"/>
<ROUTE fromNode="Slide" fromField="value_changed" toNode="Door" toField="set_translation"/>
</Scene></X3D>"""
TOUCH = '<TouchSensor DEF="Touch" description="animate Door"/>'
START = '<ROUTE fromNode="Touch" fromField="touchTime" toNode="TT" toField="set_startTime"/>'


def doc(*, sensor=TOUCH, routes=START, timer='loop="false" startTime="1e+30"', scale=""):
    return (DOC.replace("{SENSOR}", sensor).replace("{ROUTES}", routes).replace("TIMER_ATTRS", timer)
            .replace("SCALE_ATTR", scale))


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class Round4Tests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="x3d_round4_")
        _register_extension(self.tmpdir)
        sys.path.insert(0, str(SOURCE_DIR))

    def _import(self, text, name, strict):
        path = Path(self.tmpdir) / f"{name}.x3d"
        path.write_text(text, encoding="utf-8")
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

    def test_the_baseline_chain_is_lossless(self):
        self._import(doc(), "base", strict=True)
        self.assertEqual(self._losses(), [])

    # (a) the timer inside a recognised chain keeps its own fields
    def test_timer_loop_true_is_not_silently_normalised(self):
        self._import(doc(timer='loop="true" startTime="1e+30"'), "loop", strict=False)
        losses = self._losses()
        self.assertTrue(any(r["kind"] == "timer" and "loop=true" in r["detail"] for r in losses), losses)
        with self.assertRaises(Exception):
            self._import(doc(timer='loop="true" startTime="1e+30"'), "loop2", strict=True)

    def test_timer_enabled_false_is_not_silently_normalised(self):
        with self.assertRaises(Exception):
            self._import(doc(timer='loop="false" startTime="1e+30" enabled="false"'), "dis", strict=True)
        self._import(doc(timer='loop="false" startTime="1e+30" enabled="false"'), "dis2", strict=False)
        self.assertTrue(any("enabled" in f"{r['node']} {r['detail']}" for r in self._losses()), self._losses())

    def test_a_timer_that_starts_at_load_is_a_loss(self):
        with self.assertRaises(Exception):
            self._import(doc(timer='loop="false"'), "load", strict=True)

    # (b) event-field identity: hover is not click
    def test_hover_edge_is_not_imported_as_a_click_trigger(self):
        hover = doc(routes=START.replace("touchTime", "isOver"))
        with self.assertRaises(Exception):
            self._import(hover, "hover", strict=True)
        self._import(hover, "hover2", strict=False)
        self.assertTrue(any("isOver" in r["node"] for r in self._losses()), self._losses())
        self.assertNotIn("x3d_trigger", bpy.data.objects["Handle"])

    def test_hover_to_viewpoint_is_not_a_click_to_viewpoint(self):
        sensor = '<TouchSensor DEF="Touch" description="viewpoint Home"/><BooleanFilter DEF="BF"/>'
        routes = ('<ROUTE fromNode="Touch" fromField="isOver" toNode="BF" toField="set_boolean"/>'
                  '<ROUTE fromNode="BF" fromField="inputTrue" toNode="CA_Home" toField="set_bind"/>')
        with self.assertRaises(Exception):
            self._import(doc(sensor=sensor, routes=routes, timer='loop="false" startTime="1e+30"'), "hv", strict=True)

    def test_exact_click_to_viewpoint_stays_lossless(self):
        sensor = '<TouchSensor DEF="Touch" description="viewpoint Home"/><BooleanFilter DEF="BF"/>'
        routes = ('<ROUTE fromNode="Touch" fromField="isActive" toNode="BF" toField="set_boolean"/>'
                  '<ROUTE fromNode="BF" fromField="inputTrue" toNode="CA_Home" toField="set_bind"/>')
        self._import(doc(sensor=sensor, routes=routes), "cv", strict=False)
        self.assertEqual([r for r in self._losses() if r["kind"] in ("node", "route") and "BF" in r["node"] + r["detail"]], [])

    # (c) the exporter's own anisotropic proximity box: size = 2 x radius / scale per axis
    def test_anisotropic_proximity_box_round_trips(self):
        sensor = '<ProximitySensor DEF="Touch" description="animate Door" center="0 0 0" size="3 6 12"/>'
        text = doc(sensor=sensor, routes=START.replace("touchTime", "enterTime"), scale='scale="2 1 0.5"')
        self._import(text, "aniso", strict=True)
        self.assertEqual(self._losses(), [])
        handle = bpy.data.objects["Handle"]
        self.assertEqual(handle["x3d_trigger"], "proximity")
        self.assertAlmostEqual(handle["x3d_radius"], 3.0, places=5)

    def test_a_box_that_is_not_a_world_cube_is_still_refused(self):
        sensor = '<ProximitySensor DEF="Touch" description="animate Door" center="0 0 0" size="3 6 6"/>'
        text = doc(sensor=sensor, routes=START.replace("touchTime", "enterTime"), scale='scale="2 1 0.5"')
        with self.assertRaises(Exception):
            self._import(text, "notcube", strict=True)


if __name__ == "__main__":
    unittest.main()
