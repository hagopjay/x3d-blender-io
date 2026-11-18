# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Controls for the round-3 outside review (18 Nov 2026): each reproduction is kept as a test.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_round3_bpy
"""

from __future__ import annotations

import hashlib
import json
import os
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

BASE = """<X3D version="4.0" profile="Immersive"><Scene>
<Transform DEF="Door"><Shape><Appearance><Material/></Appearance><Box/></Shape></Transform>
<Transform DEF="Handle"><TouchSensor DEF="Touch"/><Shape><Sphere/></Shape></Transform>
<TimeSensor DEF="TT" cycleInterval="2" loop="false" startTime="1e+30"/>
<PositionInterpolator DEF="Slide" key="0 1" keyValue="0 0 0 2 0 0"/>
<ROUTE fromNode="Touch" fromField="touchTime" toNode="TT" toField="set_startTime"/>
<ROUTE fromNode="TT" fromField="fraction_changed" toNode="Slide" toField="set_fraction"/>
<ROUTE fromNode="Slide" fromField="value_changed" toNode="Door" toField="set_translation"/>
</Scene></X3D>"""
SECOND = """<Transform DEF="Second"><Shape><Box/></Shape></Transform>
<TimeSensor DEF="TT2" cycleInterval="2" loop="false" startTime="1e+30"/>
<PositionInterpolator DEF="Slide2" key="0 1" keyValue="0 0 0 0 3 0"/>
<ROUTE fromNode="Touch" fromField="touchTime" toNode="TT2" toField="set_startTime"/>
<ROUTE fromNode="TT2" fromField="fraction_changed" toNode="Slide2" toField="set_fraction"/>
<ROUTE fromNode="Slide2" fromField="value_changed" toNode="Second" toField="set_translation"/>"""
CASES = {
    "disabled_touch": BASE.replace('<TouchSensor DEF="Touch"/>', '<TouchSensor DEF="Touch" enabled="false"/>'),
    "fanout_two_timers": BASE.replace("</Scene>", SECOND + "</Scene>"),
    "offset_rectangular_proximity": BASE.replace(
        '<TouchSensor DEF="Touch"/>', '<ProximitySensor DEF="Touch" center="3 1 0" size="8 4 2"/>'
    ).replace('fromField="touchTime"', 'fromField="enterTime"'),
}


def sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class Round3Tests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="x3d_round3_")
        _register_extension(self.tmpdir)
        sys.path.insert(0, str(SOURCE_DIR))
        sys.path.insert(0, str(SOURCE_DIR.parent / "tools"))
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def _export(self, path, **kw):
        return bpy.ops.export_scene.x3d(filepath=str(path), x3d_version="X3D40", use_selection=False, **kw)

    # 1: two meshes whose names differ only in punctuation must not share a sidecar
    def test_splat_sidecar_names_do_not_alias(self):
        from splat_fixture import build_splat_fixture
        first = build_splat_fixture(count=8)["helix"]
        first.name, first.data.name = "First", "A B"
        first.data["x3d_splat_glb"] = True
        second = bpy.data.objects.new("Second", first.data.copy())
        second.data.name = "A_B"
        bpy.context.scene.collection.objects.link(second)
        second.data.vertices[0].co.x += 5
        second.data.update()
        out = Path(self.tmpdir) / "alias"
        out.mkdir()
        self.assertEqual(self._export(out / "scene.x3d"), {"FINISHED"})
        urls = [i.get("url").strip("'\"") for i in ET.parse(out / "scene.x3d").getroot().iter("Inline")]
        self.assertEqual(len(urls), 2)
        self.assertEqual(len(set(urls)), 2, f"two different splat sets share {urls}")
        self.assertEqual(len({sha(out / u) for u in urls}), 2)

    def test_same_splat_data_may_share_a_sidecar_but_every_url_resolves(self):
        from splat_fixture import build_splat_fixture
        obj = build_splat_fixture(count=8)["helix"]
        obj.data["x3d_splat_glb"] = True
        out = Path(self.tmpdir) / "one"
        out.mkdir()
        self.assertEqual(self._export(out / "scene.x3d"), {"FINISHED"})
        for inline in ET.parse(out / "scene.x3d").getroot().iter("Inline"):
            self.assertTrue((out / inline.get("url").strip("'\"")).is_file())

    # 3: a failed export must not change a sidecar the previous document already references
    def _transaction(self, compressed):
        from splat_fixture import build_splat_fixture
        folder = Path(self.tmpdir) / ("gzip" if compressed else "plain")
        folder.mkdir()
        obj = build_splat_fixture(count=8)["helix"]
        obj.data.name = "ASplats"
        obj.data["x3d_splat_glb"] = True
        doc = folder / ("scene.x3dz" if compressed else "scene.x3d")
        asset = folder / "ASplats.splats.glb"
        self.assertEqual(self._export(doc, use_compress=compressed), {"FINISHED"})
        before_doc, before_asset = sha(doc), sha(asset)
        obj.data.vertices[0].co.x += 5
        obj.data.update()
        second = bpy.data.objects.new("Second", obj.data.copy())
        second.data.name = "ZSplats"
        bpy.context.scene.collection.objects.link(second)
        (folder / "ZSplats.splats.glb").mkdir()                  # a directory where the new sidecar must go
        with self.assertRaises(Exception):
            self._export(doc, use_compress=compressed)
        self.assertEqual(sha(doc), before_doc)
        self.assertEqual(sha(asset), before_asset, "the referenced sidecar was replaced by a failed export")
        self.assertEqual([p.name for p in folder.iterdir() if p.name.startswith(".x3d-")], [])

    def test_failed_export_keeps_previous_sidecar_plain(self):
        self._transaction(False)

    def test_failed_export_keeps_previous_sidecar_gzip(self):
        self._transaction(True)

    # 4: strict import must not silently change what a sensor does
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

    def test_strict_import_refuses_each_unpreserved_sensor_change(self):
        for name, text in CASES.items():
            with self.subTest(name):
                with self.assertRaises(Exception):
                    self._import(text, name, strict=True)

    def test_loss_records_name_the_changed_field(self):
        expect = {"disabled_touch": "enabled", "fanout_two_timers": "Touch.touchTime -> TT2",
                  "offset_rectangular_proximity": "center"}
        for name, needle in expect.items():
            with self.subTest(name):
                self._import(CASES[name], name, strict=False)
                losses = json.loads(bpy.context.scene["x3d_import_losses"])
                self.assertTrue(any(needle in f"{r['node']} {r['detail']}" for r in losses), losses)

    def test_a_plain_touch_and_a_cubic_centered_proximity_stay_lossless(self):
        self._import(BASE, "base", strict=True)
        self.assertNotIn("x3d_import_losses", bpy.context.scene)
        cube = BASE.replace('<TouchSensor DEF="Touch"/>', '<ProximitySensor DEF="Touch" size="6 6 6"/>').replace(
            'fromField="touchTime"', 'fromField="enterTime"')
        self._import(cube, "cube", strict=True)
        self.assertNotIn("x3d_import_losses", bpy.context.scene)

    # 5: tour stops that share a position but not an orientation are different stops
    def test_same_position_tour_stops_survive_a_round_trip(self):
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
        before = Path(self.tmpdir) / "tour-before.x3d"
        self.assertEqual(self._export(before, use_animation=True), {"FINISHED"})
        bpy.ops.wm.read_factory_settings(use_empty=True)
        os.environ["X3D_IMPORT_STRICT"] = "1"
        try:
            self.assertEqual(bpy.ops.import_scene.x3d(filepath=str(before)), {"FINISHED"})
        finally:
            os.environ.pop("X3D_IMPORT_STRICT", None)
        after = Path(self.tmpdir) / "tour-after.x3d"
        self.assertEqual(self._export(after, use_animation=True), {"FINISHED"})

        def tour(path):
            root = ET.parse(path).getroot()
            timer = next(t for t in root.iter("TimeSensor") if t.get("DEF") == "TourTimer")
            keys = next(p for p in root.iter("PositionInterpolator") if "Tour" in p.get("DEF", "")).get("key")
            return float(timer.get("cycleInterval")), keys
        self.assertEqual(tour(after), tour(before))


if __name__ == "__main__":
    unittest.main()
