# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""ROUTE interaction scaffolding written from custom properties (source/interaction.py).

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_export_interaction_bpy
"""

from __future__ import annotations

import os
import tempfile
import unittest
import xml.etree.ElementTree as ET

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

from test_roundtrip_bpy import _register_extension, SOURCE_DIR
import sys
sys.path.insert(0, str(SOURCE_DIR))


def _routes(root):
    return {(r.get("fromNode"), r.get("fromField"), r.get("toNode"), r.get("toField")) for r in root.iter("ROUTE")}


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class ExportInteractionTests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="x3d_interaction_")
        _register_extension(self.tmpdir)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.scene = bpy.context.scene
        self.scene.frame_start, self.scene.frame_end = 1, 25

    def _cube(self, name, x=0.0, animated=False):
        bpy.ops.mesh.primitive_cube_add(location=(x, 0, 0))
        obj = bpy.context.active_object
        obj.name = name
        if animated:
            obj.location.z = 0.0
            obj.keyframe_insert("location", frame=1)
            obj.location.z = 2.0
            obj.keyframe_insert("location", frame=25)
        return obj

    def _camera(self, name, location, **props):
        cam = bpy.data.objects.new(name, bpy.data.cameras.new(name))
        self.scene.collection.objects.link(cam)
        cam.location = location
        cam.rotation_euler = (1.2, 0, 0.5)
        for key, value in props.items():
            cam[key] = value
        return cam

    def _export(self, **options):
        path = os.path.join(self.tmpdir, "out_%d.x3d" % len(os.listdir(self.tmpdir)))
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=path, x3d_version="X3D40", use_selection=False,
                                                  use_animation=True, **options), {"FINISHED"})
        return ET.parse(path).getroot()

    def test_click_to_animate_replaces_the_looping_scene_timer(self):
        door = self._cube("Door", animated=True)
        door["x3d_trigger"] = "click"
        root = self._export()
        transform = next(t for t in root.iter("Transform") if t.get("DEF") == "OB_Door")
        sensor = transform.find("TouchSensor")
        self.assertIsNotNone(sensor)
        timers = {t.get("DEF"): t.get("loop") for t in root.iter("TimeSensor")}
        self.assertEqual(timers, {"TT_Door": "false"})                       # no SceneTimer: nothing runs free
        routes = _routes(root)
        self.assertIn((sensor.get("DEF"), "touchTime", "TT_Door", "set_startTime"), routes)
        self.assertIn(("TT_Door", "fraction_changed", "PI_Door", "set_fraction"), routes)
        self.assertIn(("PI_Door", "value_changed", "OB_Door", "set_translation"), routes)

    def test_a_button_can_play_another_objects_animation(self):
        self._cube("Lift", animated=True)
        button = self._cube("Button", x=3)
        button["x3d_trigger"], button["x3d_target"] = "click", "Lift"
        root = self._export()
        routes = _routes(root)
        self.assertIn(("TS_Button", "touchTime", "TT_Lift", "set_startTime"), routes)
        self.assertIsNotNone(next(t for t in root.iter("Transform") if t.get("DEF") == "OB_Button").find("TouchSensor"))

    def test_an_untargeted_animation_keeps_the_free_running_timer(self):
        self._cube("Spinner", animated=True)
        door = self._cube("Door", x=3, animated=True)
        door["x3d_trigger"] = "click"
        root = self._export()
        timers = {t.get("DEF"): t.get("loop") for t in root.iter("TimeSensor")}
        self.assertEqual(timers, {"SceneTimer": "true", "TT_Door": "false"})

    def test_proximity_sensor_box_and_route(self):
        pad = self._cube("Pad", animated=True)
        pad["x3d_trigger"], pad["x3d_radius"] = "proximity", 2.5
        root = self._export()
        sensor = root.find(".//ProximitySensor")
        self.assertEqual(sensor.get("size").split(), ["5", "5", "5"])
        self.assertIn((sensor.get("DEF"), "enterTime", "TT_Pad", "set_startTime"), _routes(root))

    def test_click_to_viewpoint_binds_only_on_press(self):
        self._camera("CamA", (0, -5, 2))
        button = self._cube("Button")
        button["x3d_trigger"], button["x3d_action"], button["x3d_target"] = "click", "viewpoint", "CamA"
        routes = _routes(self._export())
        self.assertIn(("TS_Button", "isActive", "BF_Button", "set_boolean"), routes)
        self.assertIn(("BF_Button", "inputTrue", "CA_CamA", "set_bind"), routes)

    def test_viewpoint_tour_flies_through_the_cameras_in_order(self):
        self._camera("Second", (4, -4, 2), x3d_tour_order=2, x3d_tour_dwell=1)
        self._camera("First", (0, -6, 2), x3d_tour_order=1)
        self.scene["x3d_tour_travel"] = 2
        go = self._cube("Go")
        go["x3d_trigger"], go["x3d_action"] = "click", "tour"
        root = self._export()
        timer = next(t for t in root.iter("TimeSensor") if t.get("DEF") == "TourTimer")
        self.assertEqual(timer.get("loop"), "false")
        self.assertAlmostEqual(float(timer.get("cycleInterval")), 2 + 2 + 1)
        pi = next(p for p in root.iter("PositionInterpolator") if p.get("DEF") == "PI_TourRig")
        values = [float(v) for v in pi.get("keyValue").split()]
        self.assertEqual(len(values), 12)                                   # two entries per stop
        self.assertEqual(values[:3], values[3:6])                           # dwell: arrive == leave
        self.assertAlmostEqual(values[0], 0.0)                              # First at x=0
        self.assertAlmostEqual(values[6], 4.0)                              # Second at x=4
        routes = _routes(root)
        self.assertIn(("TS_Go", "touchTime", "TourTimer", "set_startTime"), routes)
        self.assertIn(("TourTimer", "isActive", "TourView", "set_bind"), routes)

    def test_autostart_tour_loops_from_load(self):
        self._camera("A", (0, -6, 2), x3d_tour_order=1)
        self._camera("B", (4, -4, 2), x3d_tour_order=2)
        self.scene["x3d_tour_autostart"] = True
        root = self._export()
        self.assertEqual(next(t for t in root.iter("TimeSensor") if t.get("DEF") == "TourTimer").get("loop"), "true")

    def test_an_unreachable_target_is_dropped_with_a_diagnostic(self):
        cube = self._cube("Lonely")
        cube["x3d_trigger"] = "click"          # animate itself, but it has no animation
        root = self._export()
        self.assertIsNone(root.find(".//TouchSensor"))
        info = " ".join(m.get("content", "") for m in root.iter("meta"))
        self.assertIn("has no animation to play", info)

    def test_panel_presets_write_properties_the_exporter_reads(self):
        door = self._cube("Door", animated=True)
        bpy.context.view_layer.objects.active = door
        self.assertEqual(bpy.ops.object.x3d_interaction_preset(preset="CLICK_ANIMATE"), {"FINISHED"})
        self.assertEqual((door["x3d_trigger"], door["x3d_action"]), ("click", "animate"))
        self.assertIsNotNone(self._export().find(".//TouchSensor"))
        self.assertEqual(bpy.ops.object.x3d_interaction_preset(preset="CLEAR"), {"FINISHED"})
        self.assertNotIn("x3d_trigger", door)
        self.assertTrue(hasattr(bpy.types, "OBJECT_PT_x3d_interaction"))

    def test_output_validates(self):
        try:
            import x3d  # noqa: F401
        except ImportError:
            self.skipTest("x3d package not installed")
        self._camera("A", (0, -6, 2), x3d_tour_order=1)
        self._camera("B", (4, -4, 2), x3d_tour_order=2)
        door = self._cube("Door", animated=True)
        door["x3d_trigger"] = "click"
        pad = self._cube("Pad", x=3)
        pad["x3d_trigger"], pad["x3d_action"], pad["x3d_target"] = "proximity", "viewpoint", "A"
        go = self._cube("Go", x=6)
        go["x3d_trigger"], go["x3d_action"] = "click", "tour"
        path = os.path.join(self.tmpdir, "v.x3d")
        bpy.ops.export_scene.x3d(filepath=path, x3d_version="X3D40", use_selection=False, use_animation=True)
        from validate import validate_with_x3d_py
        result = validate_with_x3d_py(path)
        self.assertTrue(result.valid, result.errors)
        self.assertEqual(result.warnings, [], "the Web3D x3d.py loader did not know a node or field we wrote")


if __name__ == "__main__":
    unittest.main()
