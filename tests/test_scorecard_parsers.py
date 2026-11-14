# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Scorecard helpers that read tool output and files: render.mjs and Blender worker logs, X3D facts, the rig's viewpoint function,
the Castle command line, image metrics. No browser, no Blender."""
import json
import tempfile
import importlib.util
import unittest
from pathlib import Path

import scorecard_fixtures as fx  # noqa: F401
from scorecard import common
from scorecard.legs import blender_worker, castle_native, webrender

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "tools" / "fidelity_rig" / "probes" / "p1-point-physical.x3d"

RENDER_LOG = """BROWSER Chrome/153.0.8010.12
TIME xite p1 812
X_ITE 16.7.1
xite fail p2 Error: net::ERR_FILE_NOT_FOUND at something
babylon pageerror p3 TypeError: x is undefined
TIME babylon p3 1534
BABYLON p3 {"version":"9.32.0","lights":[["Sun","DirectionalLight",1,null]]}
babylon fail p4 Error: glb did not load
"""

WORKER_LOG = """noise line
BLENDER_META {"blender": "5.3.0", "addon_commit": "abc"}
BLENDER_LEG {"name": "s1", "ok": true, "frames": []}
Blender quit
BLENDER_LEG {"name": "s2", "ok": false, "error": "boom"}
BLENDER_LEG not json
"""


class RenderLogTests(unittest.TestCase):
    def test_parse_render_log(self):
        i = webrender.parse_render_log(RENDER_LOG)
        self.assertEqual((i["browser"], i["x_ite"], i["babylon"]), ("Chrome/153.0.8010.12", "16.7.1", "9.32.0"))
        self.assertEqual(i["times_ms"], {("xite", "p1"): 812, ("babylon", "p3"): 1534})
        self.assertIn(("xite", "p2"), i["fails"])
        self.assertIn("glb did not load", i["fails"][("babylon", "p4")])
        self.assertEqual(i["errors"][("babylon", "p3")], ["TypeError: x is undefined"])

    def test_empty_log(self):
        i = webrender.parse_render_log("")
        self.assertEqual((i["browser"], i["times_ms"], i["fails"]), (None, {}, {}))

    def test_parse_worker_output(self):
        meta, recs = blender_worker.parse_worker_output(WORKER_LOG)
        self.assertEqual(meta["blender"], "5.3.0")
        self.assertEqual(set(recs), {"s1", "s2"})
        self.assertFalse(recs["s2"]["ok"])


class SceneFactTests(unittest.TestCase):
    def write(self, text, name="t.x3d"):
        d = Path(self.td.name)
        (d / name).write_text(text)
        return str(d / name)

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.td.cleanup()

    def test_wellformed(self):
        good = self.write("<X3D version='4.0'><Scene><Shape><Box/></Shape></Scene></X3D>")
        self.assertEqual(common.x3d_wellformed(good)["verdict"], "pass")
        self.assertEqual(common.x3d_wellformed(self.write("<X3D><Scene></X3D>"))["verdict"], "fail")
        self.assertEqual(common.x3d_wellformed(self.write("<html/>"))["verdict"], "fail")
        self.assertEqual(common.x3d_wellformed(self.write("<X3D/>"))["verdict"], "fail")
        self.assertEqual(common.x3d_wellformed(self.write("#VRML V2.0", "t.wrl"))["verdict"], "not-checked")
        self.assertEqual(common.x3d_wellformed(str(Path(self.td.name) / "missing.x3d"))["verdict"], "fail")

    def test_has_geometry(self):
        self.assertTrue(common.x3d_has_geometry(self.write("<X3D><Scene><Shape><Sphere/></Shape></Scene></X3D>")))
        self.assertFalse(common.x3d_has_geometry(self.write("<X3D><Scene><Viewpoint/><PointLight/></Scene></X3D>")))
        self.assertTrue(common.x3d_has_geometry(self.write("<X3D><Scene><Inline url='a.x3d'/></Scene></X3D>")))
        self.assertTrue(common.x3d_has_geometry(self.write("<X3D><Scene><Shape><GaussianSplats/></Shape></Scene></X3D>")))
        self.assertIsNone(common.x3d_has_geometry(self.write("#VRML", "t.wrl")))

    def test_background_and_headlight(self):
        f = common.scene_facts(self.write("<X3D><Scene><Background skyColor='0.1 0.2 0.3'/><NavigationInfo headlight='false'/></Scene></X3D>"))
        self.assertEqual((f["clear"], f["headlight_on"]), ([0.1, 0.2, 0.3], False))
        f = common.scene_facts(self.write("<X3D><Scene/></X3D>"))
        self.assertEqual((f["clear"], f["headlight_on"]), ([0.0, 0.0, 0.0], True))

    @unittest.skipUnless(importlib.util.find_spec("numpy"), "viewpoint.py needs numpy (the CI unit job installs only ruff and x3d)")
    def test_rig_viewpoint_is_the_rigs_function(self):
        """first_viewpoint comes from tools/fidelity_rig/viewpoint.py itself (not a copy): the probe's Viewpoint is at 0 0 10 looking down -Z."""
        v = common.rig_viewpoint()(str(PROBE), str(ROOT / "source"))
        self.assertEqual(v["position"], [0.0, 0.0, 10.0])
        self.assertAlmostEqual(v["forward"][2], -1.0)
        self.assertIsNone(common.rig_viewpoint()(self.write("<X3D><Scene><Shape><Box/></Shape></Scene></X3D>"), None))

    def test_sha256_and_scene_loading(self):
        p = self.write("<X3D><Scene><Shape><Box/></Shape></Scene></X3D>")
        self.assertEqual(len(common.sha256_file(p)), 64)
        sj = Path(self.td.name) / "s.json"
        sj.write_text(json.dumps([dict(name="a", x3d="t.x3d")]))
        scenes = common.load_scenes(str(sj), self.td.name, self.td.name + "/out", ROOT / "source")
        self.assertEqual([s.name for s in scenes], ["a"])
        self.assertTrue(scenes[0].has_geometry)
        self.assertEqual(scenes[0].headlight_lux(), 1.0)
        hdr = scenes[0].record_header(self.td.name)
        self.assertEqual(hdr["x3d"]["path"], "t.x3d")
        sj.write_text(json.dumps([dict(name="a", x3d="t.x3d"), dict(name="a", x3d="t.x3d")]))
        with self.assertRaises(ValueError):
            common.load_scenes(str(sj), self.td.name, self.td.name + "/out")


class CastleCommandTests(unittest.TestCase):
    def test_command_line(self):
        class C:
            castle_render = "/opt/castle-render"

        class S:
            x3d, clear = "/s/a.x3d", [0.1, 0.2, 0.3]
        cmd = castle_native.command(C, S, "/o/a.png", "/o/v.json", 2.0)
        self.assertEqual(cmd[:3], ["xvfb-run", "-a", "/opt/castle-render"])
        self.assertEqual(cmd[cmd.index("--clear") + 1], "0.1,0.2,0.3")
        self.assertEqual(cmd[cmd.index("--headlight") + 1], "2.0")
        self.assertEqual(castle_native.command(C, S, "/o/a.png", "/o/v.json", None)[-1], "off")

    def test_unavailable_without_env(self):
        class C:
            castle_render = None
        self.assertEqual(castle_native.available(C)[0], False)
        self.assertIn("CASTLE_RENDER", castle_native.available(C)[1])


try:
    import numpy as np
    import flip_evaluator  # noqa: F401
    HAVE_STACK = True
except ImportError:
    HAVE_STACK = False


@unittest.skipUnless(HAVE_STACK, "numpy and flip-evaluator are needed")
class MetricsTests(unittest.TestCase):
    def test_identical_images_score_zero(self):
        from scorecard import metrics
        img = (np.random.RandomState(0).rand(64, 64, 3) * 255).astype(np.uint8)
        f = metrics.flip_pair(img, img.copy())
        self.assertEqual(f["mean"], 0.0)
        self.assertEqual(metrics.mean_abs_pair(img, img)["mean_abs"], 0.0)

    def test_brighter_image_scores_worse_and_mean_abs_is_exact(self):
        from scorecard import metrics
        ref = np.full((64, 64, 3), 100, np.uint8)
        a, b = np.full_like(ref, 110), np.full_like(ref, 140)
        self.assertLess(metrics.flip_pair(ref, a)["mean"], metrics.flip_pair(ref, b)["mean"])
        self.assertAlmostEqual(metrics.mean_abs_pair(ref, a)["mean_abs"], 10.0)

    def test_geometry_mask_uses_the_reference_corner_colour(self):
        from scorecard import metrics
        ref = np.zeros((16, 16, 3), np.uint8)
        test = ref.copy()
        ref[4:8, 4:8] = 200
        test[4:8, 4:8] = 180
        g = metrics.geometry_mask(ref, test)
        self.assertEqual(int(g.sum()), 16)
        f = metrics.flip_pair(ref, test)
        self.assertAlmostEqual(f["geometry_fraction"], 16 / 256)
        self.assertGreater(f["geometry_mean"], f["mean"])

    def test_corner_tie_break_order(self):
        from scorecard import metrics
        img = np.zeros((4, 4, 3), np.uint8)
        img[0, 0], img[0, 3], img[3, 0], img[3, 3] = (1, 1, 1), (2, 2, 2), (2, 2, 2), (1, 1, 1)
        self.assertEqual(metrics.corner_colour(img), (1, 1, 1))     # tie 2:2, top-left first

    def test_size_mismatch_is_refused(self):
        from scorecard import metrics
        with self.assertRaises(ValueError):
            metrics.flip_pair(np.zeros((8, 8, 3), np.uint8), np.zeros((9, 9, 3), np.uint8))

    def test_heat_map_shape(self):
        from scorecard import metrics
        ref = np.full((32, 32, 3), 100, np.uint8)
        f = metrics.flip_pair(ref, np.full_like(ref, 160), want_heat=True)
        self.assertEqual(f["heat"].shape, (32, 32, 3))
        self.assertEqual(f["heat"].dtype, np.uint8)


if __name__ == "__main__":
    unittest.main()
